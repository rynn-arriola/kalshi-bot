"""Bounded LOCAL agreement checks. Not atomic venue/history/stream proof."""
from dataclasses import dataclass
from decimal import Decimal
import json

from .orders import OrderUpdate
from .values import InvalidData


@dataclass(frozen=True)
class AccountAudit:
    writer_epoch: str
    writer_revision: int
    positions_match: bool
    unresolved_intents: int
    foreign_order_ids: tuple[str, ...]
    missing_order_ids: tuple[str, ...]
    mismatched_order_ids: tuple[str, ...]
    awaiting_fill_ids: tuple[str, ...]
    unbound_client_ids: tuple[str, ...]
    pending_fills: int
    blockers: tuple[str, ...]

    @property
    def consistent(self):
        return not self.blockers


def audit_snapshot(ledger, snapshot, *, epoch, revision, capacity):
    """Called on the sole writer inside the reconciliation transaction.

    Full orders include terminal evidence: flat net inventory cannot hide an
    owned order whose positive fill count has not been accounted for.
    """
    rows = ledger.connection.execute("SELECT payload FROM order_evidence LIMIT 4097").fetchall()
    intents = ledger.connection.execute("SELECT client_id,payload,state FROM intents WHERE state IN "
        "('RESERVED','SENDING','UNKNOWN','ACKNOWLEDGED') LIMIT 4097").fetchall()
    lots = ledger.connection.execute("SELECT ticker,direction,quantity FROM lots LIMIT ?", (capacity+1,)).fetchall()
    if len(rows) > 4096 or len(intents) > 4096 or len(lots) > capacity:
        raise InvalidData("account audit exceeds bounded ledger scope")
    positions = {r[0]: Decimal(r[2])*r[1] for r in lots}
    venue_positions = {p.ticker: p.quantity for p in snapshot.positions if p.quantity}
    blockers, waiting, missing, mismatched = set(), [], [], []
    if positions != venue_positions:
        blockers.add("position_ledger_mismatch")
    orders = {o.order_id: o for o in (OrderUpdate.decode(r[0]) for r in rows)}
    visible = {o.order_id: o for o in snapshot.orders}
    foreign = sorted(set(visible)-set(orders))
    if foreign:
        blockers.add("foreign_resting_orders")
    market_shards = {}
    for key, order in orders.items():
        if order.subaccount != snapshot.subaccount:
            blockers.add("account_scope_conflict")
        market_shards.setdefault(order.ticker, set()).add(order.exchange_index)
        if ledger.filled_quantity(key) != order.filled:
            waiting.append(key)
        row = visible.get(key)
        if not order.terminal and row is None:
            missing.append(key)
        elif row is not None and (order.terminal or
                (order.client_id, order.ticker, order.exchange_index, order.side, order.yes_price, order.remaining) !=
                (row.client_id, row.ticker, row.exchange_index, row.book_side, row.yes_price, row.remaining)):
            mismatched.append(key)
    for position in snapshot.positions:
        if position.quantity and market_shards.get(position.ticker) != {position.exchange_index}:
            blockers.add("position_order_scope_unproven")
    bound = {o.client_id for o in orders.values()}
    unbound = []
    for row in intents:
        payload = json.loads(row["payload"])
        if payload.get("subaccount") != snapshot.subaccount:
            blockers.add("account_scope_conflict")
        if row["client_id"] not in bound:
            unbound.append(row["client_id"])
    pending = ledger.connection.execute("SELECT COUNT(*) FROM pending_fills").fetchone()[0]
    for value, reason in ((missing, "owned_working_order_missing"), (mismatched, "owned_order_terms_mismatch"),
                          (waiting, "owned_order_fill_gap"), (unbound, "unbound_order_intents"),
                          (pending, "pending_fills")):
        if value:
            blockers.add(reason)
    return AccountAudit(epoch, revision, positions == venue_positions, len(intents), tuple(foreign),
        tuple(sorted(missing)), tuple(sorted(mismatched)), tuple(sorted(waiting)),
        tuple(sorted(unbound)), pending, tuple(sorted(blockers)))
