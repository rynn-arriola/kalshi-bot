"""Single-event-loop account evidence owner, not an entry authorizer.

REST enumeration plus local agreement cannot prove lossless private-stream
continuity or complete fill history. Keep that distinction explicit in reports.
"""
import asyncio
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
import time

from .adapters import parse_fill
from .orders import parse_order
from .position_basis import VenueCost
from .recovery import RecoveryReport, fetch_archived_orders, fetch_history
from .rest import ReadFailure, RestReads
from .quota import QuotaUnavailable
from .values import InvalidData, count, decimal, identity, integer, price, utc
from .writer import LedgerWriter
from .verification import AccountAudit


@dataclass(frozen=True)
class PositionRow:
    ticker: str
    exchange_index: int
    quantity: Decimal
    exposure: Decimal


@dataclass(frozen=True)
class RestingOrder:
    order_id: str
    client_id: str
    ticker: str
    exchange_index: int
    book_side: str
    yes_price: Decimal
    remaining: Decimal


@dataclass(frozen=True)
class Snapshot:
    positions: tuple[PositionRow, ...]
    orders: tuple[RestingOrder, ...]
    available_balance: Decimal
    balance_updated_ts: int
    subaccount: int


@dataclass(frozen=True)
class PositionObservation:
    ticker: str
    quantity: Decimal
    cost: Decimal
    received_at: datetime


@dataclass(frozen=True)
class UnscopedPositionUpdate:
    """Invalidation only: no account/lot/cost authority can be inferred."""
    ticker: str
    received_at: datetime


def normalize_snapshot(orders, positions, balance, *, subaccount, capacity=128) -> Snapshot:
    """Only called with cursor-exhausted, unfiltered-by-market REST responses."""
    integer(subaccount, 0, 63)
    integer(capacity, 1, 1024)
    if len(orders) > 4096 or len(positions) > capacity:
        raise InvalidData("account snapshot exceeds bounded scope")
    normalized_orders, normalized_positions = {}, {}
    try:
        for row in orders:
            key = identity(row["order_id"])
            if key in normalized_orders or row["status"] != "resting":
                raise InvalidData("duplicate or non-resting order in resting enumeration")
            if row.get("subaccount_number") is not None:
                if integer(row["subaccount_number"], 0, 63) != subaccount:
                    raise InvalidData("order belongs to a different subaccount")
            side = row["book_side"]
            if side not in {"bid", "ask"}:
                raise InvalidData("canonical order direction required")
            client_id = row.get("client_order_id", "")
            if client_id != "":
                identity(client_id)
            normalized_orders[key] = RestingOrder(key, client_id, identity(row["ticker"]),
                integer(row["exchange_index"], 0, 2**31-1), side, price(row["yes_price_dollars"]),
                count(row["remaining_count_fp"]))
        for row in positions:
            ticker = identity(row["ticker"])
            if ticker in normalized_positions:
                raise InvalidData("duplicate position ticker; not a coherent enumeration")
            qty, exposure = decimal(row["position_fp"]), decimal(row["market_exposure_dollars"])
            count(abs(qty), zero=True)
            if exposure < 0:
                raise InvalidData("negative position exposure")
            normalized_positions[ticker] = PositionRow(ticker,
                integer(row["exchange_index"], 0, 2**31-1), qty, exposure)
        cash = decimal(balance["balance_dollars"])
        if cash < 0:
            raise InvalidData("negative available balance")
        return Snapshot(tuple(normalized_positions[k] for k in sorted(normalized_positions)),
                        tuple(normalized_orders[k] for k in sorted(normalized_orders)), cash,
                        integer(balance["updated_ts"], 0, 2**63-1), subaccount)
    except (KeyError, TypeError) as exc:
        raise InvalidData("incomplete account snapshot") from exc


@dataclass(frozen=True)
class ReconcileToken:
    generation: int
    revision: int
    started_at: datetime
    started_monotonic: float


@dataclass(frozen=True)
class ReconciliationReport:
    snapshot: Snapshot
    observed_at: datetime
    positions_match: bool
    unresolved_intents: int
    blockers: tuple[str, ...]
    ready_for_entry: bool = False
    audit: AccountAudit | None = None


@dataclass(frozen=True)
class ArchiveRecoveryReport:
    seen: int
    owned: int
    foreign: int
    awaiting_fill_order_ids: tuple[str, ...]
    excluded_other_accounts: int
    blockers: tuple[str, ...] = ("archive_not_atomic_account_proof", "execution_history_not_proven")
    ready_for_entry: bool = False


class AccountCoordinator:
    def __init__(self, writer: LedgerWriter, *, subaccount: int, capacity=128, clock=time.monotonic):
        self.writer = writer
        self.subaccount = integer(subaccount, 0, 63)
        self.capacity = integer(capacity, 1, 1024)
        self.clock = clock
        self.generation = 0
        self.revision = 0
        self.connected = False
        self.report = None
        self.latest_fill = None
        self.order_states = {}
        self.position_updates = {}
        self.history_report = None
        self.archive_report = None
        self._token = None
        self._processing = False
        self._loop = None
        self._opening_task = None
        self._accounting_fence = None
        self._report_monotonic = None

    def _check_owner(self):
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        if loop is not self._loop:
            raise InvalidData("account owner cannot cross event loops")

    def _invalidate(self):
        self.revoke_accounting()
        self.revision += 1
        self.report = None
        self._token = None
        self.history_report = None
        self.archive_report = None

    def revoke_accounting(self):
        if self._accounting_fence is not None:
            self._accounting_fence.revoked.set()


    def connect_generation(self) -> int:
        self._check_owner()
        if self._processing:
            raise InvalidData("cannot reconnect while applying an account event")
        self.generation += 1
        self.connected = True
        self.order_states.clear()
        self.position_updates.clear()
        self._invalidate()
        return self.generation

    def disconnect(self):
        self._check_owner()
        self.connected = False
        self._invalidate()

    async def on_event(self, event: dict, *, generation: int, received_at: datetime):
        self._check_owner()
        if generation != self.generation:
            return None  # Old reader cannot mutate a new connection epoch.
        if not self.connected or self._processing:
            self.disconnect()
            raise InvalidData("account consumer unavailable or concurrent")
        self._processing = True
        self._invalidate()  # Before the first await, including malformed events.
        try:
            now = utc(received_at)
            kind = event["type"]
            if kind not in {"fill", "user_order", "market_position", "order_group_updates"}:
                raise InvalidData("not a supported private account event")
            if kind == "fill":
                # Missing optional scope can only be resolved through a durably
                # bound venue order, not a primary-account assumption.
                owned_scope = await self.writer.fill_scope(event["msg"]["order_id"])
                if owned_scope is None:
                    raise InvalidData("fill ownership unresolved; recover order/history before accounting")
                scope = event["msg"].get("subaccount")
                if scope is None:
                    scope = owned_scope
                if integer(scope, 0, 63) != self.subaccount or scope != owned_scope:
                    raise InvalidData("out-of-scope fill requires account routing")
                result = await self.writer.fill(parse_fill(event), now)
                if not self.connected or generation != self.generation:
                    raise InvalidData("account epoch lost during durable fill")
                self.latest_fill = result
                if result.order is not None:
                    self._store_order(result.order)
                return result
            if kind == "user_order":
                update = parse_order(event["msg"])
                if update.subaccount != self.subaccount:
                    raise InvalidData("order update outside owner account scope")
                result = await self.writer.order(update, now)
                if not self.connected or generation != self.generation:
                    raise InvalidData("account epoch lost during order persistence")
                self._store_order(result)
                return result
            if kind == "market_position":
                msg = event["msg"]
                ticker = identity(msg["market_ticker"])
                quantity, cost = decimal(msg["position_fp"]), decimal(msg["position_cost_dollars"])
                count(abs(quantity), zero=True)
                if cost < 0:
                    raise InvalidData("negative position cost")
                if "subaccount" not in msg:
                    # Published stream example has no account scope. Preserve
                    # the reader for fills but install no quantity/cost basis.
                    return UnscopedPositionUpdate(ticker, now)
                if integer(msg["subaccount"], 0, 63) != self.subaccount:
                    raise InvalidData("position update account scope unknown/conflicting")
                if ticker not in self.position_updates and len(self.position_updates) >= self.capacity:
                    raise InvalidData("position update capacity exceeded")
                self.position_updates[ticker] = PositionObservation(ticker, quantity, cost, now)
                await self.writer.stream_cost(ticker, quantity, cost, subaccount=self.subaccount, now=now)
                if not self.connected or generation != self.generation:
                    raise InvalidData("account epoch lost during venue cost persistence")
                # Informational projection only: no sequence/timestamp barrier is
                # documented for these updates, and settlement may alter position.
                return self.position_updates[ticker]
            return None
        except (KeyError, TypeError) as exc:
            self.disconnect()
            raise InvalidData("incomplete private account event") from exc
        except BaseException:
            self.disconnect()
            raise
        finally:
            self._processing = False

    def _store_order(self, receipt):
        key = receipt.order.order_id
        if key not in self.order_states and len(self.order_states) >= 4096:
            raise InvalidData("account order projection capacity exceeded")
        self.order_states[key] = receipt

    async def recover_order(self, reads: RestReads, order_id: str, *, now):
        """Read one known order after a gap/ambiguity; 404 never means canceled."""
        token = self.begin_reconciliation(now())
        try:
            known = await self.writer.order_evidence(identity(order_id))
            if not self._current(token):
                return None
            scope = known.subaccount if known is not None else None
            try:
                result = await reads.read("order", reason="reconcile", order_id=order_id)
            except ReadFailure as exc:
                # Only an actual HTTP 404 triggers archive fallback. A timeout,
                # auth error or malformed response is not evidence of archival.
                if exc.status != 404 or known is None:
                    raise
                if not self._current(token):
                    return None
                evidence = await fetch_archived_orders(reads, subaccount=self.subaccount, ticker=known.ticker)
                update = next((o for o in evidence.orders if o.order_id == order_id), None)
                if update is None:
                    raise InvalidData("order absent from archive; ownership/reservation remains unresolved")
            else:
                update = parse_order(result.payload["order"], scope=scope)
            if not self._current(token):
                return None
            if update.order_id != order_id or update.subaccount != self.subaccount:
                raise InvalidData("single-order recovery scope mismatch")
            receipt = await self.writer.order(update, now())
            if not self._current(token):
                return None
            self._store_order(receipt)
            self._token = None
            return receipt
        except BaseException:
            if token is self._token:
                self._invalidate()
            raise

    async def recover_pending_order(self, reads, pending, *, now):
        """Resolve a persisted unbound fill, not an inferred primary-account order."""
        token = self.begin_reconciliation(now())
        fill = pending.fill
        try:
            if pending.owner != self.subaccount:
                raise InvalidData("pending inbox owner mismatch")
            try:
                result = await reads.read("order", reason="reconcile", order_id=fill.order_id)
            except ReadFailure as exc:
                if exc.status != 404:
                    raise
                if not self._current(token):
                    return None
                archive = await fetch_archived_orders(reads, subaccount=self.subaccount, ticker=fill.ticker)
                order = next((o for o in archive.orders if o.order_id == fill.order_id), None)
                if order is None:
                    return None  # Retain inbox/reservation; absence is not terminal proof.
            else:
                order = parse_order(result.payload["order"], scope=pending.scope)
            if (order.order_id, order.ticker, order.side, order.subaccount) != (
                    fill.order_id, fill.ticker, fill.book_side, self.subaccount):
                raise InvalidData("pending fill/order scope conflicts")
            if pending.exchange_index is not None and pending.exchange_index != order.exchange_index:
                raise InvalidData("pending fill shard conflicts")
            if not self._current(token):
                return None
            receipt = await self.writer.order(order, now())
            if not self._current(token):
                return None
            self._store_order(receipt)
            return receipt
        finally:
            if token is self._token:
                self._token = None

    async def apply_pending_fill(self, key, *, generation, now):
        self._check_owner()
        if generation != self.generation or not self.connected:
            return None
        if self._processing:
            raise InvalidData("concurrent private consumer")
        self._processing = True
        self._invalidate()
        try:
            receipt = await self.writer.apply_pending(key, owner=self.subaccount, now=now)
            if generation != self.generation or not self.connected:
                return None  # Durable positive evidence remains; no stale report.
            if receipt is not None:
                self.latest_fill = receipt
                if receipt.order is not None:
                    self._store_order(receipt.order)
            return receipt
        finally:
            self._processing = False

    async def recover_archived_orders(self, reads: RestReads, *, now, ticker=None):
        """Bind only exact durable intents; archived absence never cancels."""
        token = self.begin_reconciliation(now())
        try:
            evidence = await fetch_archived_orders(reads, subaccount=self.subaccount, ticker=ticker)
            owned, foreign, waiting = 0, 0, []
            for offset in range(0, len(evidence.orders), 32):
                if not self._current(token):
                    return None
                receipts = await self.writer.order_batch(evidence.orders[offset:offset+32], now())
                if not self._current(token):
                    return None
                for receipt in receipts:
                    if receipt.owned:
                        owned += 1
                        self._store_order(receipt)
                        if receipt.awaiting_fills:
                            waiting.append(receipt.order.order_id)
                    else:
                        foreign += 1
            if not self._current(token):
                return None
            report = ArchiveRecoveryReport(len(evidence.orders), owned, foreign, tuple(waiting),
                                            evidence.excluded_other_accounts)
            self.archive_report = report
            self._token = None
            return report
        except BaseException:
            if token is self._token:
                self._invalidate()
            raise

    async def recover_history(self, reads: RestReads, *, start, end, now):
        """D-025: stage/validate, resolve bounded missing bindings, import once.

        Positive executions can repair the ledger; never infer complete history
        or entry readiness from cursor exhaustion or matching net positions.
        """
        token = self.begin_reconciliation(now())
        try:
            evidence = await fetch_history(reads, start=start, end=end, subaccount=self.subaccount)
            if not self._current(token):
                return None
            staged = await self.writer.audit_history(evidence, now(), read_started_at=token.started_at,
                                                     generation=token.generation, source_revision=token.revision)
            if not self._current(token):
                return None
            known = {r.order.order_id for r in await self.writer.orders()}
            if not self._current(token):
                return None
            attempted, archives = set(), {}
            targets = set()
            for record in evidence.records:
                if record.fill.order_id not in known and len(targets) < 32:
                    targets.add(record.fill.order_id)
            # Bound exact order lookups and reuse one archive fetch per ticker.
            for record in evidence.records:
                order_id = record.fill.order_id
                if order_id not in targets or order_id in attempted:
                    continue
                attempted.add(order_id)
                if not self._current(token):
                    return None
                receipt = await self._bind_history_order(reads, record, token, now, archives, targets)
                if not self._current(token):
                    return None
                if receipt is not None and receipt.owned:
                    self._store_order(receipt)
                    known.add(order_id)
            imported, duplicates, missing = 0, 0, []
            # Fetcher sorts by execution time/identity; committed older receipts
            # are never reordered. New chunks get receipt AFTER all awaited reads.
            for offset in range(0, len(evidence.records), 32):
                if not self._current(token):
                    return None
                result = await self.writer.recover_fills(evidence.records[offset:offset+32],
                                                       subaccount=self.subaccount, now=now())
                if not self._current(token):
                    return None
                missing.extend(result.unbound_fill_keys)
                for receipt in result.receipts:
                    imported += int(receipt.inserted)
                    duplicates += int(not receipt.inserted)
                    self.latest_fill = receipt
                    if receipt.order is not None:
                        self._store_order(receipt.order)
            blockers = ["history_pages_not_atomic_account_proof", "starting_basis_and_coverage_not_proven",
                        "settlement_and_correction_reconciliation_not_complete", "live_activation_not_authorized"]
            if missing:
                blockers.append("unbound_fills_not_imported")
            if staged.enumeration.omitted_rows:
                blockers.append('previously_observed_fills_omitted')
            report = RecoveryReport(len(evidence.records), duplicates, imported, tuple(missing), tuple(blockers),
                start_us=evidence.start_us, end_us=evidence.end_us, cutoff_us=evidence.cutoff_us,
                subaccount=evidence.subaccount, generation=token.generation, revision=token.revision,
                enumeration=staged.enumeration)
            self.history_report = report
            self._token = None
            return report
        except BaseException:
            if token is self._token:
                self._invalidate()
            raise

    async def _bind_history_order(self, reads, record, token, now, archives, targets):
        """Only actual matching durable intent terms can establish ownership."""
        fill = record.fill
        try:
            result = await reads.read("order", reason="reconcile", order_id=fill.order_id)
        except ReadFailure as exc:
            if exc.status != 404:
                return None  # No binding; no import. Ordinary missing proof can retry.
            if not self._current(token):
                return None
            if fill.ticker not in archives:
                archive = await fetch_archived_orders(
                    reads, subaccount=self.subaccount, ticker=fill.ticker)
                # Retain only this run's <=32 requested identities, not many
                # complete 4096-row archives simultaneously.
                archives[fill.ticker] = {o.order_id: o for o in archive.orders if o.order_id in targets}
            order = archives[fill.ticker].get(fill.order_id)
            if order is None:
                return None
        except QuotaUnavailable:
            raise
        except InvalidData:
            return None  # Failed read is not cancellation or ownership evidence.
        else:
            order = parse_order(result.payload["order"], scope=record.subaccount)
        if not self._current(token):
            return None
        if (order.order_id, order.ticker, order.side, order.subaccount, order.exchange_index) != (
                fill.order_id, fill.ticker, fill.book_side, record.subaccount, record.exchange_index):
            raise InvalidData("history fill and recovered order identity conflict")
        return await self.writer.order(order, now())

    def begin_reconciliation(self, now: datetime) -> ReconcileToken:
        self._check_owner()
        self.revoke_accounting()
        if not self.connected or self._processing or self.writer.failed:
            raise InvalidData("account cannot start reconciliation")
        self.report = None
        self.history_report = None
        self.archive_report = None
        self._token = ReconcileToken(self.generation, self.revision, utc(now), self.clock())
        return self._token

    def _current(self, token):
        return (isinstance(token, ReconcileToken) and token is self._token and self.connected and not self._processing
                and token.generation == self.generation and token.revision == self.revision
                and not self.writer.failed and 0 <= self.clock()-token.started_monotonic <= 5)

    async def finish_reconciliation(self, token: ReconcileToken, snapshot: Snapshot,
                                    now: datetime) -> ReconciliationReport | None:
        self._check_owner()
        if not self._current(token):
            return None
        now = utc(now)
        if not token.started_at <= now <= token.started_at+timedelta(seconds=5):
            self._invalidate()
            raise InvalidData("snapshot age/clock invalid; no account proof")
        if snapshot.subaccount != self.subaccount:
            self._invalidate()
            raise InvalidData("snapshot scope differs from account owner")
        try:
            audit = await self.writer.reconcile_snapshot(snapshot, now=now)
        except BaseException:
            self._invalidate()
            raise
        if (not self._current(token) or
                (audit.writer_epoch, audit.writer_revision) != (self.writer.epoch, self.writer.revision)):
            return None  # A fill/reconnect may have overtaken the disk read.
        blockers = ["execution_history_not_proven", "private_stream_continuity_not_proven",
                    "cash_snapshot_not_atomic", "starting_basis_not_proven",
                    "settlement_and_correction_reconciliation_not_complete", "live_activation_not_authorized"]
        blockers.extend(audit.blockers)
        self.report = ReconciliationReport(snapshot, now, audit.positions_match, audit.unresolved_intents,
                                           tuple(blockers), audit=audit)
        self._report_monotonic = token.started_monotonic
        self._token = None  # Cannot reuse a snapshot token.
        return self.report

    def current_report(self, now):
        report = self.report
        if (report is None or report.audit is None or not self.connected or self._processing
                or self.writer.failed or (report.audit.writer_epoch, report.audit.writer_revision) !=
                (self.writer.epoch, self.writer.revision)
                or not timedelta(0) <= utc(now)-report.observed_at <= timedelta(seconds=5)):
            return None
        return report

    async def exit_basis(self, ticker: str, *, now: datetime):
        """Informational exit basis, never an entry/mutation authorization."""
        self._check_owner()
        ticker, now = identity(ticker), utc(now)
        report, generation, revision = self.current_report(now), self.generation, self.revision
        if (report is None or not self.connected or self._processing or self.writer.failed
                or not timedelta(0) <= now-report.observed_at <= timedelta(seconds=5)):
            return None
        position = next((p for p in report.snapshot.positions if p.ticker == ticker), None)
        if position is None:
            return None
        # Foreign resting orders in this market invalidate bot-only ownership.
        for order in report.snapshot.orders:
            if order.ticker == ticker:
                owned = self.order_states.get(order.order_id)
                if owned is None or not owned.owned:
                    return None
        result = await self.writer.exit_basis(VenueCost(ticker, self.subaccount, position.exchange_index,
            position.quantity, position.exposure, "rest"), now)
        if (self.current_report(now) is not report or not self.connected or self._processing
                or self.generation != generation or self.revision != revision or self.writer.failed):
            return None
        return result

    async def reconcile(self, reads: RestReads, *, now) -> ReconciliationReport | None:
        """One explicit bounded bootstrap/recovery read, never a polling loop."""
        token = self.begin_reconciliation(now())
        try:
            orders, positions, balance = await asyncio.gather(
                reads.collect("orders", reason="reconcile", status="resting", subaccount=self.subaccount,
                              max_rows=4096),
                reads.collect("positions", reason="reconcile", count_filter="position",
                              subaccount=self.subaccount, max_rows=self.capacity),
                reads.read("balance", reason="reconcile", subaccount=self.subaccount))
            snapshot = normalize_snapshot(orders.rows, positions.rows, balance.payload,
                                          subaccount=self.subaccount, capacity=self.capacity)
            if not self._current(token):
                return None
            # Bounded batches yield between writes so account events can revoke
            # this generation. Never delete absent durable orders on bootstrap.
            for offset in range(0, len(orders.rows), 32):
                if not self._current(token):
                    return None
                updates = tuple(parse_order(row, scope=self.subaccount) for row in orders.rows[offset:offset+32])
                receipts = await self.writer.order_batch(updates, now())
                if not self._current(token):
                    return None
                for receipt in receipts:
                    self._store_order(receipt)
            persisted = await self.writer.orders()
            if not self._current(token):
                return None
            for receipt in persisted:
                self._store_order(receipt)
            return await self.finish_reconciliation(token, snapshot, now())
        except BaseException:
            if token is self._token:
                self._invalidate()
            raise

    async def inspect_opening_account(self, reads: RestReads, *, proposed_boundary,
                                      continuity, now, persist=False, release=False):
        """Bounded inspection; optional durable restrictions, never live authority."""
        self._check_owner()
        if self._opening_task is not None:
            raise InvalidData('opening inspection already active')
        if release:
            self.writer.claim_accounting_owner(self)
        if persist:
            self.revoke_accounting()
        from threading import Event
        cancelled = Event()
        task = asyncio.create_task(self._inspect_opening_account(reads,
            proposed_boundary=proposed_boundary, continuity=continuity, now=now, persist=persist,
            release=release, cancelled=cancelled),
            name='kalshi-opening-inspection')
        self._opening_task = task
        def completed(result):
            if self._opening_task is result:
                self._opening_task = None
            if not result.cancelled():
                result.exception()  # Observe failure even if the caller cancelled.
        task.add_done_callback(completed)
        # A cancelled consumer cannot release the single inspection slot while
        # bounded reads or the pure normalization thread still own work.
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled.set()
            if release:
                self.revoke_accounting()
            raise

    async def reconcile_accounting(self, reads: RestReads, *, proposed_boundary, continuity, now, release=False):
        """Explicit account-owner integration; no background polling is created."""
        return await self.inspect_opening_account(reads, proposed_boundary=proposed_boundary,
            continuity=continuity, now=now, persist=True, release=release)

    async def _inspect_opening_account(self, reads, *, proposed_boundary, continuity, now, persist=False,
                                      release=False, cancelled=None):
        try:
            return await self._collect_opening_account(reads, proposed_boundary=proposed_boundary,
                continuity=continuity, now=now, persist=persist, release=release, cancelled=cancelled)
        except BaseException:
            self.revoke_accounting()
            if persist and not self.writer.failed:
                await self.writer.accounting_source_failed()
            raise

    async def _collect_opening_account(self, reads, *, proposed_boundary, continuity, now, persist,
                                     release=False, cancelled=None):
        from .opening_account import build_opening_evidence_async
        observed = utc(now())
        boundary = utc(proposed_boundary)
        report = self.current_report(observed)
        if report is None or boundary > observed:
            raise InvalidData('current account report and past boundary required')
        if continuity is None or continuity.generation != self.generation:
            raise InvalidData('current continuity assessment required for opening inspection')
        generation, revision = self.generation, self.revision
        writer_epoch, writer_revision = self.writer.epoch, self.writer.revision
        # Endpoint filters are second-granularity and documented as "after";
        # overlap one second, then apply the exact boundary locally.
        minimum = max(0, int(boundary.timestamp())-1)
        results = await asyncio.gather(
            reads.read('balance', reason='cash', subaccount=self.subaccount),
            reads.collect('settlements', reason='cash', subaccount=self.subaccount,
                          min_ts=minimum, max_rows=10000),
            reads.collect('subaccount_transfers', reason='cash', max_rows=10000),
            reads.collect('intra_exchange_transfers', reason='cash', max_rows=10000),
            reads.collect('deposits', reason='cash', max_rows=10000),
            reads.collect('withdrawals', reason='cash', max_rows=10000),
            return_exceptions=True)
        # Join every bounded enumeration before surfacing an error, so a failed
        # source does not leave sibling pagination running behind the caller.
        for result in results:
            if isinstance(result, BaseException):
                raise result
        current = utc(now())
        source_changed = (self.current_report(current) is not report or generation != self.generation
                or revision != self.revision or writer_epoch != self.writer.epoch
                or writer_revision != self.writer.revision)
        if source_changed and not persist:
            return None
        balance, settlements, subaccount_transfers, intra_transfers, deposits, withdrawals = results
        evidence = await build_opening_evidence_async(
            report=report, continuity=continuity,
            proposed_boundary=boundary, subaccount=self.subaccount,
            writer_epoch=writer_epoch, writer_revision=writer_revision,
            cash_document=balance.payload, settlements=settlements,
            subaccount_transfers=subaccount_transfers,
            intra_exchange_transfers=intra_transfers, deposits=deposits,
            withdrawals=withdrawals, observed_at=current)
        if persist:
            source_current = (not source_changed and not (cancelled and cancelled.is_set())
                and (not release or (self._report_monotonic is not None
                                     and 0 <= self.clock()-self._report_monotonic <= 5))
                and self.current_report(utc(now())) is report
                and (generation, revision, writer_epoch, writer_revision) ==
                    (self.generation, self.revision, self.writer.epoch, self.writer.revision))
            if release and source_current:
                from .account_release import SourceFence
                fence = SourceFence(generation=generation, revision=revision,
                    observed_at=report.observed_at, clock=self.clock, now=now,
                    started=self._report_monotonic, revoked=cancelled)
                self._accounting_fence = fence
                receipt = await self.writer.release_accounting(self, evidence, report,
                    continuity, fence, now=utc(now()))
                if not receipt.released:
                    fence.revoked.set()
                elif (self.report is report and generation == self.generation
                        and revision == self.revision and fence.current()
                        and receipt.audit is not None and receipt.audit.consistent
                        and (receipt.audit.writer_epoch, receipt.audit.writer_revision) ==
                            (self.writer.epoch, self.writer.revision)):
                    # Release changes only the accounting/risk evidence, but it
                    # advances the writer revision. Carry the audit computed in
                    # that same transaction; never relabel an older audit after
                    # an unrelated write or refresh the source's original age.
                    self.report = replace(report, audit=receipt.audit)
                else:
                    fence.revoked.set()
            else:
                receipt = await self.writer.capture_accounting(evidence, report, source_current=source_current)
                if release:
                    from .account_release import ReleaseResult
                    receipt = ReleaseResult(False, ('accounting_source_stale',))
            if ((generation, revision) != (self.generation, self.revision)
                    or (release and receipt.released and
                        (not fence.current() or self.writer._accounting_lease is None))):
                self.revoke_accounting()
                await self.writer.accounting_source_failed()
                if release:
                    from .account_release import ReleaseResult
                    return ReleaseResult(False, ('accounting_source_stale',))
            return receipt
        if (self.current_report(utc(now())) is not report or generation != self.generation
                or revision != self.revision or writer_epoch != self.writer.epoch
                or writer_revision != self.writer.revision):
            return None
        return evidence
