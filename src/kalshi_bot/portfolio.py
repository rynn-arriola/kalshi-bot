"""Single-writer exposure and OFFLINE reservation checks. No venue commands."""
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, localcontext
import json

from .execution import validate_request
from .orders import OrderReceipt, OrderUpdate
from .risk import WindowRisk, admit_entry
from .values import InvalidData, count, decimal, identity, integer, price, utc


@dataclass(frozen=True)
class MarketInventory:
    ticker: str
    position: Decimal
    orders: tuple[OrderReceipt, ...]
    blockers: tuple[str, ...]
    first_seen_at: datetime | None = None
    writer_epoch: str = ""
    writer_revision: int = -1
    yes_basis: Decimal | None = None
    exit_journal: object = None


@dataclass(frozen=True)
class PortfolioView:
    epoch: str
    revision: int
    subaccount: int
    observed_at: datetime
    positions: tuple[tuple[str, Decimal], ...]
    exposure: tuple[tuple[str, Decimal], ...]
    working_risk: Decimal
    entry_count: int
    blockers: tuple[str, ...]

    @property
    def total(self):
        with localcontext() as ctx:
            ctx.prec = 40
            return sum((value for _, value in self.exposure), Decimal(0))


@dataclass(frozen=True)
class ReservationResult:
    reserved: bool
    blockers: tuple[str, ...]
    client_id: str
    live_authorized: bool = False


def active_rows(ledger, ticker=None):
    clause = "" if ticker is None else " AND json_extract(i.payload,'$.ticker')=?"
    params = () if ticker is None else (identity(ticker),)
    rows = ledger.connection.execute(
        "SELECT i.client_id,i.payload,i.state,o.payload AS order_payload FROM intents i "
        "LEFT JOIN order_evidence o ON o.client_id=i.client_id "
        "WHERE i.state IN ('RESERVED','SENDING','UNKNOWN','ACKNOWLEDGED')"+clause+" LIMIT 4097", params).fetchall()
    if len(rows) > 4096:
        raise InvalidData("active risk evidence exceeds capacity")
    return rows


def market_inventory(ledger, ticker, subaccount):
    identity(ticker)
    integer(subaccount, 0, 63)
    receipts, blockers = [], set()
    for row in active_rows(ledger, ticker):
        payload = json.loads(row["payload"])
        if payload.get("subaccount") != subaccount:
            blockers.add("account_scope_conflict")
            continue
        if row["order_payload"] is None:
            blockers.add("unbound_intent")
            continue
        order = OrderUpdate.decode(row["order_payload"])
        if order.subaccount != subaccount:
            blockers.add("account_scope_conflict")
            continue
        awaiting = ledger.filled_quantity(order.order_id) != order.filled
        receipts.append(OrderReceipt(order, True, False, awaiting, row["state"],
                                     payload.get("reduce_only") is True))
    if ledger.connection.execute("SELECT 1 FROM pending_fills WHERE json_extract(payload,'$.ticker')=? LIMIT 1",
                                 (ticker,)).fetchone():
        blockers.add("pending_fills")
    clock = ledger.connection.execute("SELECT first_seen_at FROM position_clocks WHERE ticker=?", (ticker,)).fetchone()
    first = datetime.fromisoformat(clock[0]) if clock else None
    lot = ledger.connection.execute("SELECT yes_price FROM lots WHERE ticker=?", (ticker,)).fetchone()
    from .exits import ExitJournal
    attempts, started, unresolved, cancels, cancel_started = 0, None, False, [], None
    rows = ledger.connection.execute("SELECT m.*,i.state AS intent_state FROM mutation_attempts m "
        "LEFT JOIN intents i ON i.client_id=json_extract(m.request,'$.client_order_id') "
        "WHERE coalesce(json_extract(m.request,'$.ticker'),json_extract(m.request,'$.market_ticker'))=? "
        "AND (m.created_at>=? OR m.kind='cancel') ORDER BY m.created_at LIMIT 4097",
        (ticker, first.isoformat() if first else '')).fetchall()
    if len(rows) > 4096: raise InvalidData("exit journal capacity exceeded")
    working = {r.order.order_id for r in receipts if not r.order.terminal or r.awaiting_fills}
    for row in rows:
        request = json.loads(row['request'])
        if request.get('subaccount') != subaccount:
            blockers.add('exit_journal_scope_conflict')
        stamp = datetime.fromisoformat(row['created_at'])
        if row['kind'] == 'create' and request.get('time_in_force') == 'immediate_or_cancel':
            attempts += 1
            started = started or stamp
            unresolved |= row['intent_state'] != 'TERMINAL'
        if row['kind'] == 'cancel' and request.get('order_id') in working:
            cancels.append(request['order_id'])
            cancel_started = cancel_started or stamp
    journal = ExitJournal(attempts, started, unresolved, tuple(cancels), cancel_started)
    return MarketInventory(ticker, ledger.position(ticker), tuple(receipts), tuple(sorted(blockers)),
                           first, yes_basis=Decimal(lot[0]) if lot else None, exit_journal=journal)


def portfolio_view(ledger, *, subaccount, epoch, revision, now, capacity):
    integer(subaccount, 0, 63)
    positions, exposure, blockers = {}, {}, set()
    with localcontext() as ctx:
        ctx.prec = 40
        lots = ledger.connection.execute("SELECT ticker,direction,quantity,yes_price FROM lots LIMIT ?",
                                         (capacity+1,)).fetchall()
        if len(lots) > capacity:
            raise InvalidData("risk inventory scope exceeds capacity")
        for row in lots:
            qty, basis = Decimal(row[2]), Decimal(row[3])
            positions[row[0]] = qty*row[1]
            exposure[row[0]] = qty*(basis if row[1] == 1 else 1-basis)
        # This ledger is single-account. Do not net another account's inventory.
        if ledger.connection.execute("SELECT 1 FROM order_evidence WHERE "
            "json_extract(payload,'$.subaccount')<>? LIMIT 1", (subaccount,)).fetchone():
            blockers.add("account_scope_conflict")
        venues = ledger.connection.execute("SELECT * FROM venue_costs LIMIT 4097").fetchall()
        if len(venues) > 4096:
            raise InvalidData("venue observation capacity exceeded")
        for row in venues:
            if row["subaccount"] != subaccount:
                blockers.add("account_scope_conflict")
                continue
            qty, cost = Decimal(row["quantity"]), Decimal(row["cost"])
            if qty != positions.get(row["ticker"], Decimal(0)):
                blockers.add("venue_inventory_mismatch")
            # Never lower risk on a conflicting/stale cost observation.
            if qty or cost or row["ticker"] in exposure:
                exposure[row["ticker"]] = max(exposure.get(row["ticker"], Decimal(0)), cost)
        working, entries = Decimal(0), 0
        for row in active_rows(ledger):
            payload = json.loads(row["payload"])
            ticker = identity(payload["ticker"])
            if integer(payload["subaccount"], 0, 63) != subaccount:
                blockers.add("account_scope_conflict")
            integer(payload["exchange_index"], 0, 2**31-1)
            side, p, quantity = payload["side"], price(payload["price"]), count(payload["count"])
            if side not in {"bid", "ask"}:
                raise InvalidData("invalid intent direction")
            if row["order_payload"] is not None:
                order = OrderUpdate.decode(row["order_payload"])
                accounted = ledger.filled_quantity(order.order_id)
                if accounted > order.initial:
                    raise InvalidData("accounted executions exceed order size")
                quantity = max(order.remaining, order.initial-accounted)
                if accounted != order.filled or order.terminal:
                    blockers.add("terminal_or_fill_proof_pending")
            elif row["state"] != "RESERVED":
                blockers.add("ambiguous_send")
            risk = quantity*(p if side == "bid" else 1-p)
            working += risk
            exposure[ticker] = exposure.get(ticker, Decimal(0))+risk
            # Reducers are exempt only from the count, not the dollar sum.
            entries += int(payload.get("reduce_only") is not True)
        if ledger.connection.execute("SELECT 1 FROM pending_fills LIMIT 1").fetchone():
            blockers.add("pending_fills")
        if len(exposure) > capacity:
            raise InvalidData("risk market scope exceeds capacity")
    return PortfolioView(epoch, revision, subaccount, utc(now), tuple(sorted(positions.items())),
                         tuple(sorted(exposure.items())), working, entries, tuple(sorted(blockers)))


def reserve_entry(ledger, *, request, view, epoch, revision, config, now,
                  free_cash, account_known, offline_fixture, capacity):
    """Compare current ownership/risk and reserve in one owner transaction.

    This API has no live-authorized branch. The positive path is explicitly an
    offline fixture; a future production gate must prove account/book/cash scope.
    """
    validate_request("create", request)
    if request["reduce_only"]:
        raise InvalidData("entry reservation cannot authorize a reducer")
    cash = decimal(free_cash)
    if cash < 0 or type(account_known) is not bool or type(offline_fixture) is not bool:
        raise InvalidData("invalid account evidence")
    client = request["client_order_id"]
    now = utc(now)
    if not isinstance(view, PortfolioView):
        raise InvalidData("writer-issued portfolio view required")
    blockers = []
    if not offline_fixture:
        blockers.append("live_authorization_missing")
    if (view.epoch, view.revision, view.subaccount) != (epoch, revision, request["subaccount"]):
        blockers.append("stale_writer_evidence")
    if not timedelta(0) <= now-view.observed_at <= timedelta(seconds=5):
        blockers.append("stale_account_evidence")
    with ledger.transaction():
        # Recompute in the transaction; caller-provided exposure numbers are never trusted.
        current = portfolio_view(ledger, subaccount=request["subaccount"], epoch=epoch,
                                 revision=revision, now=now, capacity=capacity)
        blockers.extend(current.blockers)
        if ledger.connection.execute("SELECT 1 FROM intents WHERE client_id=?", (client,)).fetchone():
            blockers.append("client_identity_already_reserved")
        if ledger.connection.execute("SELECT COUNT(*) FROM intents").fetchone()[0] >= 4096:
            blockers.append("intent_retention_capacity")
        p, q = price(request["price"]), count(request["count"])
        candidate = q*(p if request["side"] == "bid" else 1-p)
        window = WindowRisk(ledger).observe(now)
        blockers.extend(admit_entry(config, window=window, ticker=request["ticker"],
            current_position=dict(current.positions).get(request["ticker"], Decimal(0)),
            resting_entries=current.entry_count, candidate_loss=candidate,
            exposure=dict(current.exposure),
            # Conservative fixture cash bound; does not infer which venue holds
            # were reflected in a non-atomic balance snapshot.
            free_capital=max(Decimal(0), cash-current.working_risk), account_known=account_known, now=now))
        if request["ticker"] not in dict(current.exposure) and len(current.exposure) >= capacity:
            blockers.append("risk_market_capacity")
        if not blockers:
            ledger.reserve_intent(client, request, now)
    return ReservationResult(not blockers, tuple(dict.fromkeys(blockers)), client)
