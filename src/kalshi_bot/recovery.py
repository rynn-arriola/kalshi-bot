"""Bounded execution-history evidence. Never silently rewrites trading P&L.

D-024 selects receipt-time attribution; D-025 allows automatic owned-fill
backfill. Staging alone is not replay or complete account proof.
"""
import asyncio
from dataclasses import dataclass
from datetime import datetime

from .ledger import Fill
from .history_coverage import EnumerationReceipt
from .orders import OrderUpdate, parse_order, timestamp_us
from .values import InvalidData, identity, integer, utc


@dataclass(frozen=True)
class ArchivedOrders:
    """Cursor-exhausted archive evidence, NOT an atomic account snapshot."""
    cutoff_us: int
    subaccount: int
    orders: tuple[OrderUpdate, ...]
    pages: int
    excluded_other_accounts: int

    def __post_init__(self):
        integer(self.cutoff_us, 0, 2**63-1)
        integer(self.subaccount, 0, 63)
        integer(self.pages, 1, 100)
        integer(self.excluded_other_accounts, 0, 4096)
        if type(self.orders) is not tuple or len(self.orders) > 4096:
            raise InvalidData("bounded immutable archived orders required")
        seen = set()
        for order in self.orders:
            if (not isinstance(order, OrderUpdate) or not order.terminal
                    or order.subaccount != self.subaccount or order.order_id in seen):
                raise InvalidData("conflicting archived order scope/status/identity")
            seen.add(order.order_id)


async def fetch_archived_orders(reads, *, subaccount: int, ticker: str | None = None,
                                max_rows=4096, max_bytes=8388608) -> ArchivedOrders:
    """One explicit gap/history request. No guessed archive subaccount filter.

    Do not split on order creation time: archival uses terminal-update time.
    Read all bounded archive pages (optionally one ticker), compare cutoff before
    and after, require explicit per-row account scope. Absence proves nothing.
    """
    integer(subaccount, 0, 63)
    integer(max_rows, 1, 4096)
    integer(max_bytes, 1, 16777216)
    params = {} if ticker is None else {"ticker": identity(ticker)}
    first = await reads.read("cutoff", reason="history")
    try:
        cutoff = timestamp_us(first.payload["orders_updated_ts"])
    except (KeyError, TypeError) as exc:
        raise InvalidData("missing order-history cutoff") from exc
    result = await reads.collect("historical_orders", reason="history", max_rows=max_rows,
                                 byte_limit=max_bytes, **params)
    if len(result.rows) > max_rows or result.wire_bytes > max_bytes:
        raise InvalidData("archived-order resource budget exceeded")
    orders, excluded = {}, 0
    for index, row in enumerate(result.rows):
        if index and index % 32 == 0:
            await asyncio.sleep(0)
        # There is no archive subaccount query; omission is unknown, not primary.
        scope = integer(row.get("subaccount_number"), 0, 63)
        if scope != subaccount:
            excluded += 1
            continue
        order = parse_order(row)
        if not order.terminal or (ticker is not None and order.ticker != ticker):
            raise InvalidData("archived-order status/ticker mismatch")
        prior = orders.get(order.order_id)
        if prior is not None and prior != order:
            raise InvalidData("conflicting duplicate archived order")
        orders[order.order_id] = order
    last = await reads.read("cutoff", reason="history")
    try:
        if timestamp_us(last.payload["orders_updated_ts"]) != cutoff:
            raise InvalidData("order-history cutoff moved; discard enumeration")
    except (KeyError, TypeError) as exc:
        raise InvalidData("missing final order-history cutoff") from exc
    return ArchivedOrders(cutoff, subaccount, tuple(orders[k] for k in sorted(orders)),
                          result.pages, excluded)


@dataclass(frozen=True)
class HistoricalFill:
    fill: Fill
    executed_us: int
    subaccount: int
    exchange_index: int

    def __post_init__(self):
        if not isinstance(self.fill, Fill):
            raise InvalidData("validated history fill required")
        integer(self.executed_us, 0, 2**63-1)
        if self.fill.executed_us is not None and self.fill.executed_us != self.executed_us:
            raise InvalidData("historical fill execution timestamp disagrees")
        integer(self.subaccount, 0, 63)
        integer(self.exchange_index, 0, 2**31-1)


def parse_history_fill(row, *, scope=None) -> HistoricalFill:
    try:
        if row["fill_id"] != row["trade_id"] or row["ticker"] != row["market_ticker"]:
            raise InvalidData("conflicting canonical fill aliases")
        subaccount = row.get("subaccount_number")
        if subaccount is None:
            if scope is None:
                raise InvalidData("historical fill has no proven account scope")
            subaccount = scope
        integer(subaccount, 0, 63)
        if scope is not None and subaccount != scope:
            raise InvalidData("fill account differs from filtered request")
        executed = timestamp_us(row["created_time"])
        if row.get("ts") is not None and integer(row["ts"], 0, 2**63-1) != executed//1000000:
            raise InvalidData("conflicting fill execution timestamps")
        fill = Fill(row["trade_id"], row["order_id"], row["ticker"], row["book_side"],
                    row["count_fp"], row["yes_price_dollars"], row["fee_cost"], executed)
        return HistoricalFill(fill, executed, subaccount, integer(row["exchange_index"], 0, 2**31-1))
    except (KeyError, TypeError) as exc:
        raise InvalidData("incomplete historical fill") from exc


@dataclass(frozen=True)
class HistoryEvidence:
    start_us: int
    end_us: int
    cutoff_us: int
    subaccount: int
    records: tuple[HistoricalFill, ...]
    pages: int
    excluded_other_accounts: int

    def __post_init__(self):
        integer(self.start_us, 0, 2**63-1)
        integer(self.end_us, self.start_us+1, 2**63-1)
        integer(self.cutoff_us, 0, 2**63-1)
        integer(self.subaccount, 0, 63)
        integer(self.pages, 1, 200)
        integer(self.excluded_other_accounts, 0, 10000)
        if type(self.records) is not tuple or len(self.records) > 10000:
            raise InvalidData("history records must be a bounded immutable tuple")
        seen = set()
        for record in self.records:
            if (not isinstance(record, HistoricalFill) or record.subaccount != self.subaccount
                    or not self.start_us <= record.executed_us < self.end_us or record.fill.key in seen):
                raise InvalidData("invalid/duplicate history record scope")
            seen.add(record.fill.key)


async def fetch_history(reads, *, start: datetime, end: datetime, subaccount: int,
                        max_rows=10000, max_bytes=8388608) -> HistoryEvidence:
    start_us, end_us = timestamp_us(utc(start).isoformat()), timestamp_us(utc(end).isoformat())
    integer(subaccount, 0, 63)
    integer(max_rows, 1, 10000)
    integer(max_bytes, 1, 16777216)
    if start_us >= end_us:
        raise InvalidData("history interval must be nonempty")
    first = await reads.read("cutoff", reason="history")
    try:
        cutoff = timestamp_us(first.payload["trades_created_ts"])
    except (KeyError, TypeError) as exc:
        raise InvalidData("missing trade-history cutoff") from exc
    # Deliberate one-second overlap protects against second-based filter edges.
    lower = max(0, start_us//1000000-1)
    upper = (end_us+999999)//1000000+1
    requests = []
    if start_us < cutoff:
        requests.append(("historical_fills", dict(min_ts=lower, max_ts=min(upper, (cutoff+999999)//1000000+1))))
    if end_us >= cutoff:
        requests.append(("fills", dict(min_ts=max(lower, cutoff//1000000-1), max_ts=upper, subaccount=subaccount)))
    records, pages, size, raw_count, excluded = {}, 0, 0, 0, 0
    for name, params in requests:
        result = await reads.collect(name, reason="history", max_rows=max_rows, byte_limit=max_bytes, **params)
        pages += result.pages
        size += result.wire_bytes
        raw_count += len(result.rows)
        if size > max_bytes or raw_count > max_rows:
            raise InvalidData("combined history resource budget exceeded")
        for row in result.rows:
            if name == "historical_fills":
                # Historical endpoint has no documented subaccount query.
                account = row.get("subaccount_number")
                integer(account, 0, 63)
                if account != subaccount:
                    excluded += 1
                    continue
            record = parse_history_fill(row, scope=subaccount if name == "fills" else None)
            if not start_us <= record.executed_us < end_us:
                continue
            prior = records.get(record.fill.key)
            if prior is not None and prior != record:
                raise InvalidData("overlapping history contains conflicting fill economics/scope")
            records[record.fill.key] = record
    last = await reads.read("cutoff", reason="history")
    try:
        if timestamp_us(last.payload["trades_created_ts"]) != cutoff:
            raise InvalidData("history boundary moved; discard enumeration and reconcile")
    except (KeyError, TypeError) as exc:
        raise InvalidData("missing final history cutoff") from exc
    return HistoryEvidence(start_us, end_us, cutoff, subaccount,
                           tuple(sorted(records.values(), key=lambda r: (r.executed_us, r.fill.key))), pages, excluded)


@dataclass(frozen=True)
class HistoryAudit:
    seen: int
    already_recorded: int
    missing_fill_keys: tuple[str, ...]
    blockers: tuple[str, ...]
    enumeration: EnumerationReceipt | None = None


@dataclass(frozen=True)
class RecoveryReport:
    seen: int
    already_recorded: int
    imported: int
    missing_fill_keys: tuple[str, ...]
    blockers: tuple[str, ...]
    ready_for_entry: bool = False
    start_us: int | None = None
    end_us: int | None = None
    cutoff_us: int | None = None
    subaccount: int | None = None
    generation: int | None = None
    revision: int | None = None
    enumeration: EnumerationReceipt | None = None


def stage_history(ledger, evidence: HistoryEvidence, now: datetime) -> HistoryAudit:
    """Atomic evidence staging; no risk-window changes or imported zero-cost lots."""
    stamp = utc(now).isoformat()
    missing, recorded = [], 0
    with ledger.transaction():
        stored = ledger.connection.execute("SELECT COUNT(*) FROM recovery_fills").fetchone()[0]
        for record in evidence.records:
            fill = record.fill
            identity(fill.order_id)
            values = (fill.payload, record.executed_us, record.subaccount, record.exchange_index)
            previous = ledger.connection.execute(
                "SELECT payload,executed_us,subaccount,exchange_index FROM recovery_fills WHERE id=?", (fill.key,)).fetchone()
            if previous is not None and tuple(previous) != values:
                raise InvalidData("recovered fill correction requires explicit replay policy")
            actual = ledger.connection.execute(
                "SELECT payload,executed_us,execution_precision_us FROM fills WHERE id=?", (fill.key,)).fetchone()
            if actual is not None and actual[0] != fill.payload:
                raise InvalidData("venue fill conflicts with durable trading ledger")
            if actual is not None and actual[1] is not None and actual[1]//actual[2] != record.executed_us//actual[2]:
                raise InvalidData("venue fill execution time conflicts with durable trading ledger")
            if actual is None:
                missing.append(fill.key)
            else:
                recorded += 1
            if previous is None:
                stored += 1
                if stored > 10000:
                    raise InvalidData("recovery evidence capacity reached; explicit archival required")
                ledger.connection.execute("INSERT INTO recovery_fills VALUES (?,?,?,?,?,?)", (fill.key, *values, stamp))
    blockers = ["history_pages_not_atomic_account_proof", "settlements_and_corrections_not_replayed",
                "ledger_execution_time_coverage_not_proven"]
    if missing:
        blockers.append("missing_fills_not_yet_imported")
    return HistoryAudit(len(evidence.records), recorded, tuple(missing), tuple(blockers))
