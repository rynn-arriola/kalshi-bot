"""Durable owned-order evidence and pure inventory actions; never sends orders."""
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
import json

from .values import InvalidData, count, identity, integer, price, utc


def timestamp_us(value: str) -> int:
    try:
        parsed = utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
        elapsed = parsed-datetime(1970, 1, 1, tzinfo=timezone.utc)
        return integer((elapsed.days*86400+elapsed.seconds)*1000000+elapsed.microseconds, 0, 2**63-1)
    except (ValueError, AttributeError, OverflowError) as exc:
        raise InvalidData("invalid execution/update timestamp") from exc


@dataclass(frozen=True)
class OrderUpdate:
    order_id: str
    client_id: str
    ticker: str
    side: str
    yes_price: Decimal
    initial: Decimal
    filled: Decimal
    remaining: Decimal
    status: str
    subaccount: int
    exchange_index: int
    version_us: int | None

    def __post_init__(self):
        for name in ("order_id", "ticker"):
            identity(getattr(self, name))
        if self.client_id != "":
            identity(self.client_id)
        if self.side not in {"bid", "ask"} or self.status not in {"resting", "canceled", "executed"}:
            raise InvalidData("unsupported order side/status")
        object.__setattr__(self, "yes_price", price(self.yes_price))
        for name in ("initial", "filled", "remaining"):
            object.__setattr__(self, name, count(getattr(self, name), zero=name != "initial"))
        integer(self.subaccount, 0, 63)
        integer(self.exchange_index, 0, 2**31-1)
        if self.version_us is not None:
            integer(self.version_us, 0, 2**63-1)
        if self.filled+self.remaining > self.initial:
            raise InvalidData("order quantities exceed initial size")
        if self.status == "resting" and self.remaining == 0:
            raise InvalidData("resting order has no remaining quantity")
        if self.status == "executed" and self.remaining != 0:
            raise InvalidData("executed order still has remaining quantity")

    @property
    def terminal(self):
        return self.status in {"canceled", "executed"}

    def encode(self):
        return json.dumps(asdict(self), default=str, sort_keys=True, separators=(",", ":"))

    @classmethod
    def decode(cls, payload):
        return cls(**json.loads(payload))


def parse_order(row: dict, *, scope: int | None = None) -> OrderUpdate:
    """Scope may come from an explicit filtered REST request, never guessed WS."""
    try:
        subaccount = row.get("subaccount_number")
        if subaccount is None:
            if scope is None:
                raise InvalidData("order account scope is unknown")
            subaccount = scope
        if scope is not None and subaccount != scope:
            raise InvalidData("order account scope conflicts")
        version = row.get("last_updated_ts_ms")
        if version is not None:
            version = integer(version, 0, (2**63-1)//1000)*1000
        elif row.get("last_update_time") is not None:
            version = timestamp_us(row["last_update_time"])
        return OrderUpdate(row["order_id"], row.get("client_order_id", ""), row["ticker"],
                           row["book_side"], row["yes_price_dollars"], row["initial_count_fp"],
                           row["fill_count_fp"], row["remaining_count_fp"], row["status"],
                           subaccount, row["exchange_index"], version)
    except (KeyError, TypeError) as exc:
        raise InvalidData("incomplete canonical order") from exc


@dataclass(frozen=True)
class OrderReceipt:
    order: OrderUpdate
    owned: bool
    applied: bool
    awaiting_fills: bool
    intent_state: str | None
    reducing: bool = False


def settle_order(ledger, order_id: str) -> OrderReceipt | None:
    row = ledger.connection.execute("SELECT payload FROM order_evidence WHERE order_id=?", (order_id,)).fetchone()
    if row is None:
        return None
    update = OrderUpdate.decode(row[0])
    intent = ledger.connection.execute("SELECT state,payload FROM intents WHERE client_id=?", (update.client_id,)).fetchone()
    if intent is None:
        raise InvalidData("owned order lost its durable intent")
    quantity = ledger.filled_quantity(order_id)
    waiting = quantity != update.filled
    state = intent[0]
    if state == "TERMINAL" and waiting:
        raise InvalidData("late execution conflicts with terminal order proof")
    if update.terminal and not waiting and state == "ACKNOWLEDGED":
        ledger.transition_intent(update.client_id, "TERMINAL")
        state = "TERMINAL"
    if update.terminal and not waiting and state == 'TERMINAL':
        from .command_capacity import (episode_for_client, maybe_retire_episode,
                                       release_client_credits)
        episode = episode_for_client(ledger, update.client_id)
        release_client_credits(ledger, update.client_id)
        maybe_retire_episode(ledger, episode)
    return OrderReceipt(update, True, True, waiting, state,
                        json.loads(intent[1]).get("reduce_only") is True)


def record_order(ledger, update: OrderUpdate, now: datetime, *, capacity=4096) -> OrderReceipt:
    integer(capacity, 1, 4096)
    with ledger.transaction():
        intent = ledger.connection.execute("SELECT state,payload FROM intents WHERE client_id=?", (update.client_id,)).fetchone()
        if intent is None:
            return OrderReceipt(update, False, False, True, None)
        payload = json.loads(intent[1])
        if payload.get("client_order_id", update.client_id) != update.client_id:
            raise InvalidData("intent payload client identity conflicts with reservation")
        try:
            if (payload["ticker"], payload["side"], price(payload["price"]), count(payload["count"]),
                    integer(payload["subaccount"], 0, 63), integer(payload["exchange_index"], 0, 2**31-1)) != (
                    update.ticker, update.side, update.yes_price, update.initial, update.subaccount, update.exchange_index):
                raise InvalidData("venue order does not match durable intent terms")
        except KeyError as exc:
            raise InvalidData("intent missing explicit market/account terms") from exc
        if intent[0] not in {"SENDING", "UNKNOWN", "ACKNOWLEDGED", "TERMINAL"}:
            raise InvalidData("venue order conflicts with unsent/rejected intent")
        binding = ledger.connection.execute("SELECT order_id FROM order_evidence WHERE client_id=?", (update.client_id,)).fetchone()
        if binding and binding[0] != update.order_id:
            raise InvalidData("one client identity matched multiple venue orders")
        previous = ledger.connection.execute("SELECT payload FROM order_evidence WHERE order_id=?", (update.order_id,)).fetchone()
        if previous:
            old = OrderUpdate.decode(previous[0])
            if old.client_id != update.client_id:
                raise InvalidData("order identity rebound to another intent")
            if update == old:
                return replace(settle_order(ledger, update.order_id), applied=False)
            if old.version_us is None or update.version_us is None:
                raise InvalidData("changed order lacks comparable version evidence")
            if update.version_us < old.version_us:
                return replace(settle_order(ledger, update.order_id), applied=False)
            if update.version_us == old.version_us:
                raise InvalidData("conflicting order states at the same version")
            if update.filled < old.filled or (old.terminal and not update.terminal):
                raise InvalidData("order progress/terminal state regressed")
        else:
            from .command_capacity import bind_order_evidence
            bind_order_evidence(ledger, update.client_id)
        if previous is None and ledger.connection.execute(
                "SELECT COUNT(*) FROM order_evidence").fetchone()[0] >= capacity:
            raise InvalidData("durable order evidence capacity reached")
        ledger.connection.execute("INSERT INTO order_evidence VALUES (?,?,?,?) ON CONFLICT(order_id) DO UPDATE SET payload=excluded.payload,observed_at=excluded.observed_at",
                                   (update.order_id, update.client_id, update.encode(), utc(now).isoformat()))
        if intent[0] in {"SENDING", "UNKNOWN"}:
            ledger.transition_intent(update.client_id, "ACKNOWLEDGED")
        return settle_order(ledger, update.order_id)


@dataclass(frozen=True)
class InventoryPlan:
    cancel_ids: tuple[str, ...]
    keep_id: str | None
    reduce_side: str | None
    reduce_quantity: Decimal
    blockers: tuple[str, ...]


def inventory_plan(position: Decimal, orders: tuple[OrderReceipt, ...], *, ticker: str,
                   touch: Decimal | None, complete_scope: bool) -> InventoryPlan:
    """Source-verified passive reducer mechanics only; no IOC/deadline policy."""
    from .values import decimal
    identity(ticker)
    if len(orders) > 4096 or any(not isinstance(r, OrderReceipt) for r in orders):
        raise InvalidData("bounded validated order receipts required")
    position = decimal(position)
    qty = count(abs(position), zero=True)
    relevant = [r for r in orders if r.order.ticker == ticker]
    if len({r.order.order_id for r in relevant}) != len(relevant):
        raise InvalidData("duplicate order in inventory plan")
    blockers = []
    if complete_scope is not True:
        blockers.append("incomplete_order_scope")
    if any(not r.owned or r.awaiting_fills for r in relevant):
        blockers.append("unowned_order_or_unaccounted_fills")
    working = [r for r in relevant if r.owned and not r.order.terminal]
    if qty == 0:
        return InventoryPlan(tuple(sorted(r.order.order_id for r in working if r.reducing)),
                             None, None, Decimal(0), tuple(blockers))
    side = "ask" if position > 0 else "bid"
    p = price(touch) if touch is not None else None
    if p is None:
        # Preserve existing reducing work when its book side is unavailable.
        # This mirrors the reference's no-touch branch, not a forced IOC choice.
        cancels = tuple(sorted(r.order.order_id for r in working
                               if r.order.side != side or not r.reducing))
        return InventoryPlan(cancels, None, None, Decimal(0), tuple(blockers+["no_passive_touch"]))
    matching = sorted((r for r in working if r.reducing and r.order.side == side
                       and r.order.remaining == qty and r.order.yes_price == p), key=lambda r: r.order.order_id)
    keep = matching[0].order.order_id if matching else None
    cancels = tuple(sorted(r.order.order_id for r in working if r.order.order_id != keep))
    if cancels:
        blockers.append("await_terminal_cancellation_and_fill_proof")
    return InventoryPlan(cancels, keep, side if not blockers and keep is None else None,
                         qty if not blockers and keep is None else Decimal(0), tuple(blockers))
