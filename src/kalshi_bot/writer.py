"""Bounded, one-thread SQLite owner. Accepted commands survive caller cancellation.

No trading/network actions. A failed command poisons this owner; restart and
reconcile instead of allowing later risk decisions to overtake a failed write.
"""
import asyncio
from concurrent.futures import Future
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
import json
from pathlib import Path
from queue import Full, Queue
from threading import Lock, Thread
from uuid import uuid4

from .command_capacity import (CapacityPolicy, DEFAULT_POLICY, status,
                               validate_capacity)
from .command_types import (CancelEvidence, PreparationResult, PreparedBatch, PreparedMutation,
                            ReductionEvidence)
from .ledger import Fill, Ledger
from .inbox import pending, stage
from .orders import OrderUpdate, record_order, settle_order
from .position_basis import VenueCost, exit_basis, observe_cost, observe_costs
from .recovery import HistoricalFill, HistoryAudit, HistoryEvidence, stage_history
from .risk import WindowRisk, WindowState
from .observability import NO_LOG
from .values import InvalidData, count, identity, integer, price, utc


@dataclass(frozen=True)
class FillReceipt:
    inserted: bool
    position: Decimal
    window: WindowState
    order: object | None = None


@dataclass(frozen=True)
class Inventory:
    positions: tuple[tuple[str, Decimal], ...]
    unresolved_intents: int


@dataclass(frozen=True)
class RecoveredChunk:
    receipts: tuple[FillReceipt, ...]
    unbound_fill_keys: tuple[str, ...]


class LedgerWriter:
    def __init__(self, path: Path | str, *, capacity: int = 256, market_capacity: int = 128,
                 diagnostics=NO_LOG, command_policy=DEFAULT_POLICY, live_session=None):
        self.live_session = live_session
        if live_session is not None:
            from .live_session import LiveSession
            if type(live_session) is not LiveSession:
                raise InvalidData('typed live session required')
            live_session.bind(self)
        self.diagnostics = diagnostics
        self.path = path
        self.epoch = uuid4().hex
        self._revision = 0
        self.market_capacity = integer(market_capacity, 1, 1024)
        if not isinstance(command_policy, CapacityPolicy):
            raise InvalidData('typed command capacity policy required')
        self.command_policy = command_policy
        self._queue = Queue(maxsize=integer(capacity, 1, 8192))
        self._lock = Lock()
        self._closing = False
        self._failed = False
        self._started = False
        self._ready = Future()
        self._close_task = None
        self._executor_owner = None
        self._dispatcher_owner = None
        self._management_owner = None
        self._accounting_owner = None
        self._accounting_lease = None
        self._accounting_prepared = None
        self._accounting_enabled = live_session is not None
        self._max_backlog_observed = 0
        self._thread = Thread(target=self._run, name="kalshi-ledger", daemon=False)

    @property
    def revision(self):
        return self._revision

    @property
    def failed(self):
        with self._lock:
            return self._failed

    @property
    def backlog(self):
        return self._queue.qsize()

    @property
    def max_backlog_observed(self):
        with self._lock:
            return self._max_backlog_observed

    def claim_executor(self, owner):
        with self._lock:
            if self._executor_owner is not None and self._executor_owner is not owner:
                raise InvalidData('one mutation executor permitted per writer lifetime')
            self._executor_owner = owner

    def claim_dispatcher(self, owner):
        with self._lock:
            if self._dispatcher_owner is not None and self._dispatcher_owner is not owner:
                raise InvalidData('one mutation dispatcher permitted per writer lifetime')
            self._dispatcher_owner = owner

    def claim_management_owner(self, owner):
        from .management import InventoryManager
        if not isinstance(owner, InventoryManager):
            raise InvalidData('typed inventory manager required')
        with self._lock:
            if self._management_owner is not None and self._management_owner is not owner:
                raise InvalidData('one inventory manager permitted per writer lifetime')
            self._management_owner = owner

    async def start(self):
        with self._lock:
            if self._started or self._closing:
                raise InvalidData("writer cannot be started twice or after close")
            self._started = True
            self._thread.start()
        try:
            await self._wait(self._ready)
        except BaseException:
            await self.close()
            raise
        return self

    @staticmethod
    async def _wait(future):
        wrapped = asyncio.wrap_future(future)
        # Consume exceptions even if the original caller stops awaiting.
        wrapped.add_done_callback(lambda f: None if f.cancelled() else f.exception())
        return await asyncio.shield(wrapped)

    def _submit(self, command, *args):
        future = Future()
        with self._lock:
            if not self._started or self._closing or self._failed:
                raise InvalidData("ledger owner unavailable; reconciliation required")
            try:
                self._queue.put_nowait((command, args, future))
                self._max_backlog_observed = max(
                    self._max_backlog_observed, self._queue.qsize())
            except Full as exc:
                self._failed = True
                self.diagnostics.emit('writer_overflow', error=exc, backlog=self.backlog)
                raise InvalidData("ledger backlog exceeded; proof lost") from exc
        return future

    async def fill(self, fill: Fill, received_at: datetime) -> FillReceipt:
        if not isinstance(fill, Fill):
            raise InvalidData("validated Fill required")
        return await self._wait(self._submit("fill", fill, utc(received_at)))

    async def stage_fill(self, fill: Fill, *, owner: int, scope=None, exchange_index=None, now):
        return await self._wait(self._submit("stage_fill", fill, owner, scope, exchange_index, utc(now)))

    async def pending_fills(self, owner: int, order_id=None):
        return await self._wait(self._submit("pending_fills", integer(owner, 0, 63), order_id))

    async def apply_pending(self, key: str, *, owner: int, now):
        if not isinstance(key, str) or len(key) > 1024:
            raise InvalidData("invalid pending identity")
        return await self._wait(self._submit("apply_pending", key, integer(owner, 0, 63), utc(now)))

    async def observe(self, now: datetime) -> WindowState:
        return await self._wait(self._submit("observe", utc(now)))

    async def capture_accounting(self, evidence, report, *, source_current=True):
        """Accepted evidence writes survive caller cancellation; never grant entry."""
        from .opening_account import OpeningAccountEvidence
        if not isinstance(evidence, OpeningAccountEvidence):
            raise InvalidData('typed opening evidence required')
        return await self._wait(self._submit('capture_accounting', evidence, report, source_current))

    async def accounting_source_failed(self):
        return await self._wait(self._submit('accounting_source_failed'))

    async def accounting_status(self):
        return await self._wait(self._submit('accounting_status'))

    def claim_accounting_owner(self, owner):
        from .account import AccountCoordinator
        if not isinstance(owner, AccountCoordinator) or owner.writer is not self:
            raise InvalidData('account coordinator required')
        if self._accounting_owner is not None and self._accounting_owner is not owner:
            raise InvalidData('one accounting owner per writer lifetime')
        self._accounting_owner = owner

    async def approve_opening(self, *, checkpoint_digest, reference, now,
                              captured_digest=None):
        return await self._wait(self._submit('approve_opening', checkpoint_digest,
                                             identity(reference), utc(now),
                                             checkpoint_digest if captured_digest is None
                                             else identity(captured_digest)))

    async def release_accounting(self, owner, evidence, report, continuity, fence, *, now):
        if (owner is not self._accounting_owner or fence is not owner._accounting_fence
                or not fence.current()):
            raise InvalidData('current account-owner release fence required')
        return await self._wait(self._submit('release_accounting', evidence, report,
                                             continuity, fence, utc(now)))

    def entry_accounting_current(self, receipt):
        receipts = receipt.receipts if isinstance(receipt, PreparedBatch) else (receipt,)
        if any(not isinstance(row, PreparedMutation) for row in receipts):
            return False
        if all(row.kind != 'create' or row.reduction
               for row in receipts):
            return True
        if not self._accounting_enabled:
            return True  # Isolated legacy fixtures; never a live path.
        lease = self._accounting_lease
        return (lease is not None and lease.writer_epoch == self.epoch
            and not self.failed and not self._closing
            and self.revision in (receipt.writer_revision, receipt.writer_revision+1)
            and self._accounting_prepared == receipt
            and all(json.loads(row.proof_json).get('accounting_release') == lease.release_digest
                    for row in receipts)
            and lease.fence.current())

    async def record_accounting_review(self, *, reference, checkpoint_digest, now):
        return await self._wait(self._submit('accounting_review', identity(reference),
                                             checkpoint_digest, utc(now)))

    async def market_inventory(self, ticker, *, subaccount):
        return await self._wait(self._submit("market_inventory", identity(ticker), integer(subaccount, 0, 63)))

    async def portfolio(self, *, subaccount, now):
        return await self._wait(self._submit("portfolio", integer(subaccount, 0, 63), utc(now)))

    async def reserve_entry(self, request, *, attempt_id, view, config, now, free_cash,
                            account_known=False, offline_fixture=False, fee_per_contract_bound=None):
        frozen = json.dumps(request, allow_nan=False, separators=(",", ":"))
        if len(frozen.encode()) > 16384:
            raise InvalidData("entry request exceeds byte budget")
        return await self._wait(self._submit("reserve_entry", identity(attempt_id), frozen, view, config, utc(now),
                                            free_cash, account_known, offline_fixture, fee_per_contract_bound))

    async def reserve_entry_pair(self, requests, *, batch_id, view, config, now,
                                 free_cash, account_known=False,
                                 offline_fixture=False,
                                 fee_per_contract_bound=None):
        if type(requests) is not tuple:
            raise InvalidData('immutable entry pair required')
        frozen = json.dumps(requests, allow_nan=False, separators=(',', ':'))
        if len(frozen.encode()) > 32768:
            raise InvalidData('entry pair exceeds byte budget')
        return await self._wait(self._submit('reserve_entry_pair', identity(batch_id),
            frozen, view, config, utc(now), free_cash, account_known,
            offline_fixture, fee_per_contract_bound))

    async def cancel_evidence(self, order_id):
        return await self._wait(self._submit('cancel_evidence', identity(order_id)))

    async def next_entry_cancel_evidence(self, ticker, *, subaccount):
        """Return one exact uncancelled entry order from durable local evidence.

        This is a safety-only source for an already-paused live session.  It
        deliberately does not require a current public book or account report:
        cancelling an exact owned order can only reduce resting exposure.  Any
        prior submitted/uncertain cancel remains non-repeatable.
        """
        return await self._wait(self._submit('next_entry_cancel_evidence',
            identity(ticker), integer(subaccount, 0, 63)))

    async def reduction_evidence(self, request, *, now):
        frozen = json.dumps(request, allow_nan=False, sort_keys=True, separators=(',', ':'))
        if len(frozen.encode()) > 16384:
            raise InvalidData('reduction request exceeds byte budget')
        owner = self._management_owner
        plan = owner.current(request.get('ticker')) if owner is not None else None
        if plan is None:
            return None
        return await self._wait(self._submit('reduction_evidence', frozen, plan, utc(now)))

    async def prepare_cancel(self, attempt_id, request, *, evidence, now):
        if not isinstance(evidence, CancelEvidence):
            raise InvalidData('typed cancel evidence required')
        encoded = json.dumps(request, allow_nan=False, separators=(',', ':'))
        if len(encoded.encode()) > 16384:
            raise InvalidData('cancel request exceeds byte budget')
        frozen = json.loads(encoded)
        return await self._wait(self._submit('prepare_cancel', identity(attempt_id), frozen,
                                             evidence, utc(now)))

    async def prepare_reduction(self, attempt_id, request, *, evidence, now):
        if not isinstance(evidence, ReductionEvidence):
            raise InvalidData('typed reduction evidence required')
        encoded = json.dumps(request, allow_nan=False, separators=(',', ':'))
        if len(encoded.encode()) > 16384:
            raise InvalidData('reduction request exceeds byte budget')
        frozen = json.loads(encoded)
        owner = self._management_owner
        plan = owner.current(request.get('ticker')) if owner is not None else None
        management_current = (plan is not None and
                              self._decision_matches_plan(evidence, plan, frozen))
        result = await self._wait(self._submit('prepare_reduction', identity(attempt_id), frozen,
                                               evidence, management_current, utc(now)))
        if result.receipt is not None:
            current = owner.current_after_prepare(
                request.get('ticker'), prior_revision=evidence.writer_revision,
                prepared_revision=result.receipt.writer_revision) if owner is not None else None
            if current is None or not self._decision_matches_plan(evidence, current, frozen):
                await self.abort_prepared(result.receipt)
                return PreparationResult(
                    None, ('reduction_management_decision_changed',),
                    await self.command_capacity(), result.client_id)
        return result

    @staticmethod
    def _decision_matches_plan(evidence, plan, request):
        try:
            decision = json.loads(evidence.decision_json)
            journal = plan.inventory.exit_journal
            return (plan.ticker == request['ticker']
                and plan.exit is not None and plan.terms is not None
                and plan.inventory.writer_epoch == evidence.writer_epoch
                and plan.inventory.writer_revision == evidence.writer_revision
                and decision['observed_at'] == plan.observed_at.isoformat()
                and decision['account_generation'] == plan.generation
                and decision['account_revision'] == plan.account_revision
                and decision['book_generation'] == plan.book_generation
                and decision['book_revision'] == plan.book_revision
                and decision['terms_observed_at'] == plan.terms.observed_at.isoformat()
                and decision['terms_valid_until'] == plan.terms.valid_until.isoformat()
                and decision['fee_per_contract_bound'] == (
                    str(plan.terms.taker_fee_per_contract_bound)
                    if plan.terms.taker_fee_per_contract_bound is not None else None)
                and decision['mode'] == plan.exit.mode
                and decision['limit_price'] == str(plan.exit.limit_price)
                and count(decision['quantity']) == count(
                    plan.exit.quantity if plan.exit.mode == 'ioc'
                    else plan.exit.passive.reduce_quantity)
                and decision['attempts'] == journal.attempts
                and decision['started_at'] == (journal.started_at.isoformat()
                                                if journal.started_at else None))
        except (AttributeError, KeyError, TypeError, ValueError):
            return False

    async def begin_send(self, receipt):
        if not isinstance(receipt, PreparedMutation):
            raise InvalidData('typed prepared mutation required')
        return await self._wait(self._submit('begin_send', receipt))

    async def begin_batch_send(self, batch):
        if not isinstance(batch, PreparedBatch):
            raise InvalidData('typed prepared batch required')
        return await self._wait(self._submit('begin_batch_send', batch))

    async def abort_prepared(self, receipt):
        if not isinstance(receipt, PreparedMutation):
            raise InvalidData('typed prepared mutation required')
        return await self._wait(self._submit('abort_prepared', receipt))

    async def abort_batch(self, batch):
        if not isinstance(batch, PreparedBatch):
            raise InvalidData('typed prepared batch required')
        return await self._wait(self._submit('abort_batch', batch))

    async def abort_sending_before_submission(self, receipt, owner):
        if not isinstance(receipt, PreparedMutation):
            raise InvalidData('typed prepared mutation required')
        with self._lock:
            if self._executor_owner is not owner:
                raise InvalidData('only the active mutation executor may prove no submission')
        return await self._wait(
            self._submit('abort_sending_before_submission', receipt))

    async def abort_sending_batch_before_submission(self, batch, owner):
        if not isinstance(batch, PreparedBatch):
            raise InvalidData('typed prepared batch required')
        with self._lock:
            if self._executor_owner is not owner:
                raise InvalidData('only the active mutation executor may prove no submission')
        return await self._wait(
            self._submit('abort_sending_batch_before_submission', batch))

    async def record_outcome(self, operation, receipt, document, now):
        if operation not in {'unknown', 'ack', 'rejected'} or not isinstance(receipt, PreparedMutation):
            raise InvalidData('invalid typed mutation outcome')
        frozen = json.loads(json.dumps(document, allow_nan=False))
        return await self._wait(self._submit('mutation_outcome', operation, receipt,
                                             frozen, utc(now)))

    async def record_batch_outcome(self, batch, document, now):
        if not isinstance(batch, PreparedBatch) or document is not None and not isinstance(document, dict):
            raise InvalidData('invalid typed batch outcome')
        frozen = (None if document is None else
                  json.loads(json.dumps(document, allow_nan=False)))
        return await self._wait(self._submit('batch_outcome', batch, frozen, utc(now)))

    async def command_capacity(self):
        return await self._wait(self._submit('command_capacity'))

    async def inventory(self) -> Inventory:
        return await self._wait(self._submit("inventory"))

    async def reconcile_snapshot(self, snapshot, *, now):
        from .account import Snapshot
        if (not isinstance(snapshot, Snapshot) or type(snapshot.orders) is not tuple
                or type(snapshot.positions) is not tuple or len(snapshot.orders) > 4096
                or len(snapshot.positions) > self.market_capacity):
            raise InvalidData("bounded immutable account snapshot required")
        return await self._wait(self._submit("reconcile_snapshot", snapshot, utc(now)))

    async def order(self, update: OrderUpdate, now: datetime):
        if not isinstance(update, OrderUpdate):
            raise InvalidData("validated order update required")
        return await self._wait(self._submit("order", update, utc(now)))

    async def orders(self):
        return await self._wait(self._submit("orders"))

    async def order_batch(self, updates: tuple[OrderUpdate, ...], now: datetime):
        if type(updates) is not tuple or not 1 <= len(updates) <= 32 or any(not isinstance(u, OrderUpdate) for u in updates):
            raise InvalidData("order evidence batch must contain 1 to 32 validated updates")
        return await self._wait(self._submit("order_batch", updates, utc(now)))

    async def fill_scope(self, order_id: str):
        return await self._wait(self._submit("fill_scope", identity(order_id)))

    async def order_evidence(self, order_id: str) -> OrderUpdate | None:
        return await self._wait(self._submit("order_evidence", identity(order_id)))

    async def recover_fills(self, records: tuple[HistoricalFill, ...], *, subaccount: int, now: datetime):
        if (type(records) is not tuple or not 1 <= len(records) <= 32
                or any(not isinstance(r, HistoricalFill) for r in records)):
            raise InvalidData("replay batch requires 1 to 32 immutable historical fills")
        return await self._wait(self._submit("recover_fills", records, integer(subaccount, 0, 63), utc(now)))

    async def venue_snapshot(self, observations: tuple[VenueCost, ...], *, subaccount: int, now: datetime):
        integer(subaccount, 0, 63)
        if (type(observations) is not tuple or len(observations) > self.market_capacity
                or any(not isinstance(o, VenueCost) or o.subaccount != subaccount for o in observations)
                or len({o.ticker for o in observations}) != len(observations)):
            raise InvalidData("bounded account-scoped venue cost snapshot required")
        return await self._wait(self._submit("venue_snapshot", observations, subaccount, utc(now)))

    async def stream_cost(self, ticker, quantity, cost, *, subaccount, now):
        from .values import decimal
        return await self._wait(self._submit("stream_cost", identity(ticker), decimal(quantity), decimal(cost),
                                            integer(subaccount, 0, 63), utc(now)))

    async def exit_basis(self, observation: VenueCost, now: datetime):
        if not isinstance(observation, VenueCost):
            raise InvalidData("validated venue cost required")
        return await self._wait(self._submit("exit_basis", observation, utc(now)))

    async def history_coverage(self, *, subaccount, start, end):
        from .orders import timestamp_us
        scope = integer(subaccount, 0, 63)
        start_us, end_us = timestamp_us(utc(start).isoformat()), timestamp_us(utc(end).isoformat())
        integer(end_us, start_us+1, 2**63-1)
        return await self._wait(self._submit('history_coverage', scope, start_us, end_us))

    async def open_private_epoch(self, epoch):
        from .continuity import PrivateEpoch
        if not isinstance(epoch, PrivateEpoch) or epoch.writer_epoch != self.epoch:
            raise InvalidData('current writer private epoch required')
        return await self._wait(self._submit('private_epoch_open', epoch))

    async def close_private_epoch(self, epoch_id, *, closed_at, ingress_count,
                                  durable_fill_count, terminal_reason, clean_local_delivery):
        return await self._wait(self._submit('private_epoch_close', identity(epoch_id), self.epoch,
            utc(closed_at), integer(ingress_count, 0, 2**63-1),
            integer(durable_fill_count, 0, 2**63-1), terminal_reason, bool(clean_local_delivery)))

    async def private_epoch_gap_count(self, *, subaccount, exclude_epoch_id=None):
        if exclude_epoch_id is not None:
            identity(exclude_epoch_id)
        return await self._wait(self._submit('private_epoch_gaps',
            integer(subaccount, 0, 63), exclude_epoch_id))

    async def inspect_private_epochs(self, *, subaccount, limit=128):
        return await self._wait(self._submit('private_epoch_inspect',
            integer(subaccount, 0, 63), integer(limit, 1, 128)))

    async def audit_history(self, evidence: HistoryEvidence, now: datetime, *, read_started_at=None,
                            generation=None, source_revision=None):
        if not isinstance(evidence, HistoryEvidence) or len(evidence.records) > 10000:
            raise InvalidData("bounded history evidence required")
        # Evidence is not trading accounting: commit bounded chunks and yield
        # between them so fill/order commands can interleave. A partial run
        # never returns a completed audit and never changes lots/risk windows.
        now = utc(now)
        read_started_at = now if read_started_at is None else utc(read_started_at)
        if read_started_at > now or (generation is None) != (source_revision is None):
            raise InvalidData('invalid history clock/source provenance')
        if generation is not None:
            integer(generation, 1, 2**63-1)
            integer(source_revision, 0, 2**63-1)
        recorded, missing, blockers = 0, [], []
        for offset in range(0, max(1, len(evidence.records)), 256):
            chunk = replace(evidence, records=evidence.records[offset:offset+256])
            result = await self._wait(self._submit("history", chunk, now))
            recorded += result.already_recorded
            missing.extend(result.missing_fill_keys)
            for blocker in result.blockers:
                if blocker not in blockers:
                    blockers.append(blocker)
        receipt = await self._wait(self._submit('history_complete', evidence, uuid4().hex,
            read_started_at, now, generation, source_revision))
        if receipt.omitted_rows:
            blockers.append('previously_observed_fills_omitted')
            self.diagnostics.emit('history_omission', blocker_count=1)
        self.diagnostics.emit('history_enumerated', blocker_count=len(blockers))
        return HistoryAudit(len(evidence.records), recorded, tuple(missing), tuple(blockers), receipt)

    async def reserve_intent(self, client_id: str, payload: dict, now: datetime):
        identity(client_id)
        if not isinstance(payload, dict):
            raise InvalidData("intent payload must be an object")
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        if len(encoded.encode("utf-8")) > 16384:
            raise InvalidData("intent payload exceeds byte budget")
        # Freeze caller-owned mutable data before submitting to another thread.
        return await self._wait(self._submit("reserve", client_id, encoded, utc(now)))

    async def transition_intent(self, client_id: str, target: str):
        identity(client_id)
        if target not in {"SENDING", "ABORTED", "UNKNOWN", "ACKNOWLEDGED", "REJECTED", "TERMINAL"}:
            raise InvalidData("unsupported intent state")
        return await self._wait(self._submit("transition", client_id, target))

    async def mutations(self):
        return await self._wait(self._submit("mutations"))

    def _execute(self, ledger, command, args):
        if command == 'approve_opening':
            from .account_release import approve_opening
            result = approve_opening(ledger, *args)
            self._accounting_enabled = self.live_session is not None or bool(ledger.connection.execute(
                'SELECT 1 FROM accounting_baseline WHERE id=1').fetchone())
            self._accounting_lease = None
            return result
        if command == 'release_accounting':
            from .accounting import capture
            from .account_release import release
            evidence, report, continuity, fence, now = args
            self._accounting_lease = None
            with ledger.transaction():
                capture(ledger, evidence, report, source_current=fence.current(),
                    writer_epoch=self.epoch, writer_revision=self._revision,
                    post_revision=self._revision+1, capacity=self.market_capacity)
                result, lease = release(ledger, evidence, report, continuity, fence,
                    epoch=self.epoch, revision=self._revision, now=now, capacity=self.market_capacity)
                if result.released:
                    from .verification import audit_snapshot
                    audit = audit_snapshot(ledger, report.snapshot, epoch=self.epoch,
                        revision=self._revision+1, capacity=self.market_capacity)
                    result = replace(result, audit=audit)
            self._accounting_lease = lease
            return result
        if command == 'capture_accounting':
            self._accounting_lease = None
            from .accounting import capture
            return capture(ledger, args[0], args[1], source_current=args[2], writer_epoch=self.epoch,
                           writer_revision=self._revision, post_revision=self._revision+1,
                           capacity=self.market_capacity)
        if command == 'accounting_status':
            from .accounting import inspect
            return inspect(ledger)
        if command == 'accounting_source_failed':
            self._accounting_lease = None
            from .accounting import record_failure, inspect
            record_failure(ledger, command)
            return inspect(ledger)
        if command == 'accounting_review':
            from .accounting import record_review
            return record_review(ledger, reference=args[0], checkpoint_digest=args[1], now=args[2])
        if command == 'private_epoch_open':
            from .private_epoch_store import open_epoch
            return open_epoch(ledger, args[0])
        if command == 'private_epoch_close':
            from .private_epoch_store import close_epoch
            epoch_id, writer_epoch, closed_at, ingress, fills, reason, clean = args
            return close_epoch(ledger, epoch_id, writer_epoch=writer_epoch, closed_at=closed_at,
                ingress_count=ingress, durable_fill_count=fills, terminal_reason=reason,
                clean_local_delivery=clean)
        if command == 'private_epoch_gaps':
            from .private_epoch_store import gap_count
            return gap_count(ledger, subaccount=args[0], exclude_epoch_id=args[1])
        if command == 'private_epoch_inspect':
            from .private_epoch_store import inspect_epochs
            return inspect_epochs(ledger, subaccount=args[0], limit=args[1])
        if command == 'history_complete':
            from .history_coverage import complete_enumeration
            evidence, receipt_id, started, observed, generation, revision = args
            return complete_enumeration(ledger, evidence, receipt_id=receipt_id, writer_epoch=self.epoch,
                read_started_at=started, observed_at=observed, generation=generation, source_revision=revision)
        if command == 'history_coverage':
            from .history_coverage import enumeration_coverage
            scope, start_us, end_us = args
            return enumeration_coverage(ledger, subaccount=scope, start_us=start_us, end_us=end_us)
        if command == "reconcile_snapshot":
            from .verification import audit_snapshot
            snapshot, now = args
            with ledger.transaction():
                self._execute(ledger, "venue_snapshot", (tuple(VenueCost(p.ticker, snapshot.subaccount,
                    p.exchange_index, p.quantity, p.exposure, "rest") for p in snapshot.positions),
                    snapshot.subaccount, now))
                return audit_snapshot(ledger, snapshot, epoch=self.epoch, revision=self._revision,
                                      capacity=self.market_capacity)
        if command == "market_inventory":
            from .portfolio import market_inventory
            return replace(market_inventory(ledger, *args), writer_epoch=self.epoch,
                           writer_revision=self._revision)
        if command == "portfolio":
            from .portfolio import portfolio_view
            scope, now = args
            return portfolio_view(ledger, subaccount=scope, epoch=self.epoch,
                                  revision=self._revision, now=now, capacity=self.market_capacity)
        if command == "reserve_entry":
            from .portfolio import reserve_entry
            from .live_session import permits
            attempt_id, encoded, view, config, now, cash, known, fixture, fee_bound = args
            result = reserve_entry(ledger, request=json.loads(encoded), attempt_id=attempt_id,
                view=view, epoch=self.epoch, revision=self._revision,
                post_revision=self._revision+1, config=config, now=now, free_cash=cash,
                account_known=known, offline_fixture=fixture, capacity=self.market_capacity,
                command_policy=self.command_policy, accounting_lease=self._accounting_lease,
                fee_per_contract_bound=fee_bound,
                live_authorized=permits(self.live_session, self)
                    and not self.live_session.entries_paused)
            if result.receipt is not None and self._accounting_enabled:
                self._accounting_prepared = result.receipt
            return result
        if command == 'reserve_entry_pair':
            from .portfolio import reserve_entry_pair
            from .live_session import permits
            batch_id, encoded, view, config, now, cash, known, fixture, fee_bound = args
            result = reserve_entry_pair(ledger, requests=tuple(json.loads(encoded)),
                batch_id=batch_id, view=view, epoch=self.epoch,
                revision=self._revision, post_revision=self._revision+1,
                config=config, now=now, free_cash=cash, account_known=known,
                offline_fixture=fixture, capacity=self.market_capacity,
                command_policy=self.command_policy,
                accounting_lease=self._accounting_lease,
                fee_per_contract_bound=fee_bound,
                live_authorized=permits(self.live_session, self)
                    and not self.live_session.entries_paused)
            if result.batch is not None and self._accounting_enabled:
                self._accounting_prepared = result.batch
            return result
        if command == 'cancel_evidence':
            order_id = args[0]
            row = ledger.connection.execute('SELECT payload FROM order_evidence WHERE order_id=?',
                                            (order_id,)).fetchone()
            if row is None:
                return None
            update = OrderUpdate.decode(row[0])
            if update.terminal:
                return None
            return CancelEvidence(self.epoch, self._revision, update.order_id, update.ticker,
                                  update.subaccount, update.exchange_index)
        if command == 'next_entry_cancel_evidence':
            ticker, subaccount = args
            rows = ledger.connection.execute(
                'SELECT payload FROM order_evidence ORDER BY order_id').fetchall()
            for row in rows:
                update = OrderUpdate.decode(row[0])
                if (update.ticker != ticker or update.subaccount != subaccount
                        or update.terminal):
                    continue
                receipt = settle_order(ledger, update.order_id)
                if receipt is None or not receipt.owned or receipt.reducing:
                    continue
                prior = ledger.connection.execute(
                    "SELECT phase FROM mutation_attempts WHERE kind='cancel' "
                    "AND json_extract(request,'$.order_id')=? ORDER BY rowid",
                    (update.order_id,)).fetchall()
                if prior and not (len(prior) == 1 and prior[0][0] == 'NOT_SENT'):
                    continue
                return CancelEvidence(self.epoch, self._revision, update.order_id,
                    update.ticker, update.subaccount, update.exchange_index)
            return None
        if command == 'reduction_evidence':
            from .execution import encoded_request, reduction_authority, validate_request
            from .management import ManagedPlan
            request, plan, now = json.loads(args[0]), args[1], args[2]
            validate_request('create', request)
            passive = (request['time_in_force'] == 'good_till_canceled'
                       and request['post_only'] is True
                       and request['reduce_only'] is False)
            ioc = (request['time_in_force'] == 'immediate_or_cancel'
                   and request['post_only'] is False
                   and request['reduce_only'] is True)
            if not (passive or ioc) or not isinstance(plan, ManagedPlan):
                raise InvalidData('reduction evidence requires managed exit request')
            inventory, exit_plan, terms = plan.inventory, plan.exit, plan.terms
            if (plan.ticker != request['ticker'] or exit_plan is None or terms is None
                    or inventory.ticker != request['ticker']
                    or (inventory.writer_epoch, inventory.writer_revision) !=
                       (self.epoch, self._revision)
                    or plan.observed_at > now or now-plan.observed_at > timedelta(seconds=5)
                    or not terms.observed_at <= now < terms.valid_until
                    or inventory.blockers
                    or (exit_plan.blockers and not exit_plan.passive_allowed)):
                return None
            quantity = count(request['count'])
            limit_price = price(request['price'])
            passive = request['time_in_force'] == 'good_till_canceled'
            action_matches = (
                exit_plan.passive_allowed
                and exit_plan.passive.keep_id is None
                and not exit_plan.passive.cancel_ids
                and exit_plan.passive.reduce_side == request['side']
                and exit_plan.passive.reduce_quantity == quantity
                and exit_plan.limit_price == limit_price
            ) if passive else (
                exit_plan.mode == 'ioc'
                and exit_plan.quantity == quantity
                and exit_plan.limit_price == limit_price
            )
            if not action_matches:
                return None
            episode, position, route, authority_blockers = reduction_authority(ledger, request)
            if (episode is None or not position or route is None
                    or set(authority_blockers)-{'reduction_route_changed'}):
                return None
            journal = inventory.exit_journal
            decision = encoded_request({
                'type': 'managed_exit', 'ticker': plan.ticker,
                'observed_at': plan.observed_at.isoformat(),
                'account_generation': plan.generation,
                'account_revision': plan.account_revision,
                'book_generation': plan.book_generation,
                'book_revision': plan.book_revision,
                'writer_epoch': inventory.writer_epoch,
                'writer_revision': inventory.writer_revision,
                'terms_observed_at': terms.observed_at.isoformat(),
                'terms_valid_until': terms.valid_until.isoformat(),
                'fee_per_contract_bound': (str(terms.taker_fee_per_contract_bound)
                    if terms.taker_fee_per_contract_bound is not None else None),
                'mode': exit_plan.mode,
                'limit_price': str(exit_plan.limit_price),
                'quantity': str(quantity),
                'attempts': journal.attempts,
                'started_at': journal.started_at.isoformat() if journal.started_at else None})
            return ReductionEvidence(self.epoch, self._revision, episode,
                request['ticker'], request['subaccount'], route, position,
                encoded_request(request), decision)
        if command == 'prepare_cancel':
            from .execution import prepare_cancel
            attempt_id, request, evidence, now = args
            with ledger.transaction():
                return prepare_cancel(ledger, attempt_id=attempt_id, request=request,
                    evidence=evidence, writer_epoch=self.epoch, writer_revision=self._revision,
                    post_revision=self._revision+1, now=now, policy=self.command_policy)
        if command == 'prepare_reduction':
            from .execution import prepare_reduction
            attempt_id, request, evidence, management_current, now = args
            with ledger.transaction():
                return prepare_reduction(ledger, attempt_id=attempt_id, request=request,
                    evidence=evidence, writer_epoch=self.epoch, writer_revision=self._revision,
                    post_revision=self._revision+1, now=now,
                    management_current=management_current, policy=self.command_policy)
        if command == 'begin_send':
            from .execution import begin_send
            with ledger.transaction():
                return begin_send(ledger, args[0], writer_epoch=self.epoch,
                    writer_revision=self._revision, post_revision=self._revision+1,
                    accounting_current=self.entry_accounting_current(args[0]))
        if command == 'begin_batch_send':
            from .execution import begin_batch_send
            with ledger.transaction():
                return begin_batch_send(ledger, args[0], writer_epoch=self.epoch,
                    writer_revision=self._revision, post_revision=self._revision+1,
                    accounting_current=self.entry_accounting_current(args[0]))
        if command == 'abort_prepared':
            from .execution import abort_prepared
            with ledger.transaction():
                return abort_prepared(ledger, args[0], writer_epoch=self.epoch,
                    writer_revision=self._revision, post_revision=self._revision+1)
        if command == 'abort_batch':
            from .execution import abort_batch
            with ledger.transaction():
                return abort_batch(ledger, args[0], writer_epoch=self.epoch,
                    writer_revision=self._revision, post_revision=self._revision+1)
        if command == 'abort_sending_before_submission':
            from .execution import abort_sending_before_submission
            with ledger.transaction():
                return abort_sending_before_submission(ledger, args[0],
                    writer_epoch=self.epoch, writer_revision=self._revision,
                    post_revision=self._revision+1)
        if command == 'abort_sending_batch_before_submission':
            from .execution import abort_sending_batch_before_submission
            with ledger.transaction():
                return abort_sending_batch_before_submission(ledger, args[0],
                    writer_epoch=self.epoch, writer_revision=self._revision,
                    post_revision=self._revision+1)
        if command == 'mutation_outcome':
            from .execution import record_outcome
            with ledger.transaction():
                return record_outcome(ledger, *args, writer_epoch=self.epoch)
        if command == 'batch_outcome':
            from .execution import record_batch_outcome
            with ledger.transaction():
                return record_batch_outcome(ledger, *args, writer_epoch=self.epoch)
        if command == 'command_capacity':
            return status(ledger)
        if command == "stage_fill":
            return stage(ledger, *args)
        if command == "pending_fills":
            return pending(ledger, *args)
        if command == "apply_pending":
            key, owner, now = args
            with ledger.transaction():
                row = ledger.connection.execute("SELECT * FROM pending_fills WHERE id=?", (key,)).fetchone()
                if row is None:
                    return None
                fill = Fill(**json.loads(row["payload"]))
                stored = ledger.connection.execute("SELECT payload FROM order_evidence WHERE order_id=?",
                                                    (fill.order_id,)).fetchone()
                if stored is None:
                    return None
                order = OrderUpdate.decode(stored[0])
                if (row["owner"] != owner or order.subaccount != owner
                        or (row["scope"] is not None and row["scope"] != owner)
                        or (row["exchange_index"] is not None and row["exchange_index"] != order.exchange_index)):
                    raise InvalidData("pending fill ownership/scope conflicts")
                receipt = self._execute(ledger, "fill", (fill, now))
                if order.terminal and ledger.filled_quantity(fill.order_id) > order.filled:
                    raise InvalidData("pending executions exceed terminal order proof")
                ledger.connection.execute("DELETE FROM pending_fills WHERE id=?", (key,))
                return receipt
        if command == "venue_snapshot":
            observations, scope, now = args
            with ledger.transaction():
                seen = {o.ticker for o in observations}
                old = ledger.connection.execute("SELECT ticker,exchange_index,observed_at FROM venue_costs WHERE subaccount=?",
                                                (scope,)).fetchall()
                # Complete position enumeration can clear the observational
                # clock; never the fill inventory, P&L, orders or reservations.
                for row in old:
                    if now.isoformat() < row[2]:
                        raise InvalidData("position snapshot predates durable venue evidence")
                    if row[0] not in seen:
                        ledger.connection.execute("UPDATE venue_costs SET quantity='0',cost='0',observed_at=? "
                                                  "WHERE subaccount=? AND ticker=?",
                                                  (now.isoformat(), scope, row[0]))
                changed = []
                for observation in observations:
                    prior = ledger.connection.execute("SELECT * FROM venue_costs WHERE subaccount=? AND ticker=?",
                                                      (scope, observation.ticker)).fetchone()
                    if (prior and prior["source"] == "websocket"
                            and timedelta(0) <= now-datetime.fromisoformat(prior["observed_at"]) <= timedelta(seconds=5)
                            and (prior["exchange_index"], Decimal(prior["quantity"]), Decimal(prior["cost"])) == (
                                observation.exchange_index, observation.quantity, observation.cost)):
                        continue  # Preserve sufficient fresh primary-stream cost evidence.
                    changed.append(observation)
                observe_costs(ledger, tuple(changed), now, capacity=self.market_capacity)
            return None
        if command == "stream_cost":
            ticker, quantity, cost, scope, now = args
            rows = ledger.connection.execute("SELECT DISTINCT json_extract(payload,'$.exchange_index') "
                "FROM order_evidence WHERE json_extract(payload,'$.ticker')=? "
                "AND json_extract(payload,'$.subaccount')=? LIMIT 2", (ticker, scope)).fetchall()
            if len(rows) != 1:
                return False  # Stream lacks shard: never guess it from primary account.
            observe_cost(ledger, VenueCost(ticker, scope, rows[0][0], quantity, cost, "websocket"),
                         now, capacity=self.market_capacity)
            return True
        if command == "exit_basis":
            return exit_basis(ledger, *args)
        if command == "recover_fills":
            records, scope, now = args
            receipts, missing = [], []
            with ledger.transaction():
                for record in records:
                    fill = record.fill
                    if record.subaccount != scope:
                        raise InvalidData("recovered fill account scope conflicts")
                    row = ledger.connection.execute("SELECT payload FROM order_evidence WHERE order_id=?",
                                                    (fill.order_id,)).fetchone()
                    if row is None:
                        missing.append(fill.key)
                        continue
                    order = OrderUpdate.decode(row[0])
                    if (order.subaccount, order.exchange_index, order.ticker, order.side) != (
                            scope, record.exchange_index, fill.ticker, fill.book_side):
                        raise InvalidData("recovered fill differs from owned order scope")
                    # Preserve exact venue time even for a constructed history record.
                    receipt = self._execute(ledger, "fill", (replace(fill, executed_us=record.executed_us,
                                                                  execution_precision_us=1), now))
                    total = ledger.filled_quantity(fill.order_id)
                    if total > order.initial or (order.terminal and total > order.filled):
                        raise InvalidData("recovered executions exceed authoritative order quantity")
                    receipts.append(receipt)
            return RecoveredChunk(tuple(receipts), tuple(missing))
        if command == "fill":
            fill, now = args
            with ledger.transaction():
                row = ledger.connection.execute("SELECT payload FROM order_evidence WHERE order_id=?", (fill.order_id,)).fetchone()
                if row:
                    order = OrderUpdate.decode(row[0])
                    if fill.ticker != order.ticker or fill.book_side != order.side:
                        raise InvalidData("fill differs from owned order identity")
                inserted = ledger.record_fill(fill, now)
                if row and ledger.filled_quantity(fill.order_id) > order.initial:
                    raise InvalidData("executions exceed owned order size")
                # Schema 3 retains exactly one lot per ticker. COUNT(*) avoids
                # allocating every active market on every recovered fill.
                markets = ledger.connection.execute("SELECT COUNT(*) FROM lots").fetchone()[0]
                if markets > self.market_capacity:
                    raise InvalidData("fill exceeds bounded inventory scope")
                window = WindowRisk(ledger).observe(now)
                position = ledger.position(fill.ticker)
                order_receipt = settle_order(ledger, fill.order_id)
            return FillReceipt(inserted, position, window, order_receipt)
        if command == "observe":
            return WindowRisk(ledger).observe(*args)
        if command == "order":
            with ledger.transaction():
                result = record_order(ledger, *args)
                validate_capacity(ledger, self.command_policy, full=False)
                return result
        if command == "order_batch":
            updates, now = args
            with ledger.transaction():
                result = tuple(record_order(ledger, update, now) for update in updates)
                validate_capacity(ledger, self.command_policy, full=False)
                return result
        if command == "history":
            return stage_history(ledger, *args)
        if command == "fill_scope":
            row = ledger.connection.execute("SELECT payload FROM order_evidence WHERE order_id=?", args).fetchone()
            return OrderUpdate.decode(row[0]).subaccount if row else None
        if command == "order_evidence":
            row = ledger.connection.execute("SELECT payload FROM order_evidence WHERE order_id=?", args).fetchone()
            return OrderUpdate.decode(row[0]) if row else None
        if command == "orders":
            rows = ledger.connection.execute("SELECT order_id FROM order_evidence LIMIT 4097").fetchall()
            if len(rows) > 4096:
                raise InvalidData("order evidence exceeds bounded capacity")
            with ledger.transaction():
                return tuple(settle_order(ledger, r[0]) for r in rows)
        if command == "inventory":
            rows = ledger.connection.execute(
                "SELECT DISTINCT ticker FROM lots LIMIT ?", (self.market_capacity+1,)).fetchall()
            if len(rows) > self.market_capacity:
                raise InvalidData("inventory exceeds owner capacity")
            return Inventory(tuple(sorted((r[0], ledger.position(r[0])) for r in rows)),
                             ledger.unresolved_intents())
        if command == "reserve":
            client_id, encoded, now = args
            with ledger.transaction():
                result = ledger.reserve_intent(client_id, json.loads(encoded), now)
                validate_capacity(ledger, self.command_policy, full=False)
                return result
        if command == "transition":
            return ledger.transition_intent(*args)
        if command == "mutations":
            rows = ledger.connection.execute("SELECT * FROM mutation_attempts LIMIT 8193").fetchall()
            if len(rows) > 8192:
                raise InvalidData("mutation journal requires archival before further work")
            return tuple(dict(row) for row in rows)
        raise InvalidData("unsupported writer command")

    def _run(self):
        ledger = None
        future = None
        try:
            ledger = Ledger(self.path)  # Construct/use/close on this thread only.
            validate_capacity(ledger, self.command_policy)
            self._accounting_enabled = bool(ledger.connection.execute(
                'SELECT 1 FROM accounting_baseline WHERE id=1').fetchone())
            self._ready.set_result(None)
            while True:
                item = self._queue.get()
                if item is None:
                    break
                command, args, future = item
                try:
                    if self.failed:
                        raise InvalidData("ledger owner failed; queued command not applied")
                    # In-process authority epoch changes on restart. Any command
                    # that can mutate financial/evidence/risk state revokes leases.
                    read_only = {"portfolio", "market_inventory", "inventory", "fill_scope",
                                 "order_evidence", "pending_fills", "exit_basis", "mutations", "history_coverage",
                                 "private_epoch_gaps", "private_epoch_inspect", 'cancel_evidence',
                                 'next_entry_cancel_evidence', 'reduction_evidence',
                                 'command_capacity', 'accounting_status'}
                    post_revision = {'reserve_entry', 'reserve_entry_pair',
                                     'prepare_cancel', 'prepare_reduction',
                                     'begin_send', 'begin_batch_send',
                                     'abort_prepared', 'abort_batch',
                                     'abort_sending_before_submission',
                                     'abort_sending_batch_before_submission',
                                     'capture_accounting', 'release_accounting'}
                    # External evidence writes revoke authority even when a
                    # caller bypasses coordinator ingress. Local reservation /
                    # send steps retain the lease but recompute obligations.
                    if command not in read_only | {'reserve_entry', 'reserve_entry_pair',
                            'prepare_cancel', 'prepare_reduction', 'begin_send',
                            'begin_batch_send', 'abort_prepared', 'abort_batch',
                            'abort_sending_before_submission',
                            'abort_sending_batch_before_submission'}:
                        self._accounting_lease = None
                        self._accounting_prepared = None
                    if command not in read_only and command not in post_revision:
                        self._revision += 1
                    result = self._execute(ledger, command, args)
                    if command in {'reserve_entry', 'reserve_entry_pair', 'prepare_cancel',
                                   'prepare_reduction', 'capture_accounting',
                                   'release_accounting'}:
                        self._revision += 1
                    elif command in {'begin_send', 'begin_batch_send',
                                     'abort_prepared', 'abort_batch',
                                     'abort_sending_before_submission',
                                     'abort_sending_batch_before_submission'} and result.writer_revision == self._revision+1:
                        self._revision += 1
                except Exception as exc:
                    if command in {'fill', 'apply_pending', 'recover_fills', 'order',
                                   'order_batch', 'capture_accounting', 'release_accounting'}:
                        try:
                            from .accounting import record_failure
                            record_failure(ledger, command)
                        except Exception as journal_error:
                            self.diagnostics.emit('writer_failed', error=journal_error,
                                                  command='accounting_failure_journal')
                    self.diagnostics.emit('writer_failed', error=exc, command=command,
                                          revision=self._revision, backlog=self.backlog)
                    with self._lock:
                        self._failed = True
                    future.set_exception(InvalidData("ledger command failed; reconciliation required"))
                else:
                    future.set_result(result)  # Only after transaction commit.
        except BaseException as exc:
            self.diagnostics.emit('writer_failed', error=exc, revision=self._revision)
            with self._lock:
                self._failed = True
            if not self._ready.done():
                self._ready.set_exception(InvalidData("ledger startup failed"))
            if future is not None and not future.done():
                future.set_exception(InvalidData("ledger owner stopped during command"))
        finally:
            # Unexpected worker termination must not leave accepted callers hung.
            while not self._queue.empty():
                item = self._queue.get_nowait()
                if item is not None and not item[2].done():
                    item[2].set_exception(InvalidData("ledger owner stopped before command acknowledgement"))
            if ledger is not None:
                try:
                    ledger.close()
                except Exception as exc:
                    with self._lock:
                        self._failed = True
                    self.diagnostics.emit('writer_failed', error=exc, command='close', revision=self._revision)

    def _finish(self):
        # Queue may be full; block a helper thread, never the event loop.
        if self._thread.is_alive():
            self._queue.put(None)
        self._thread.join()

    async def close(self):
        with self._lock:
            self._closing = True
            if self._started and self._close_task is None:
                self._close_task = asyncio.create_task(asyncio.to_thread(self._finish))
            task = self._close_task
        if task is not None:
            await asyncio.shield(task)

    async def __aenter__(self):
        return await self.start()

    async def __aexit__(self, *_):
        await self.close()
