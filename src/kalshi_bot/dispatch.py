"""Bounded offline mutation dispatcher; no transport creation or live authority.

The queue retains only market reevaluation keys. It never stores a prepared
receipt or treats a prior advisory plan as current. One retained task refreshes
the candidate, reserves write capacity, refreshes again, prepares durably, and
hands the exact receipt to the writer's sole injected executor.
"""
import asyncio
from collections import deque
from dataclasses import dataclass, field

from .command_types import (CancelEvidence, CommandDenied, ReductionEvidence)
from .execution import (InjectedExecutor, encoded_request, validate_entry_pair,
                        validate_request)
from .portfolio import PortfolioView
from .values import InvalidData, decimal, identity, integer
from .write_budget import BATCH_ORDERS, ORDERS, WriteBudget
from .writer import LedgerWriter


SAFETY_CANCEL = 'safety_cancel'
DUE_IOC = 'due_ioc'
PASSIVE_REDUCER = 'passive_reducer'
ENTRY_PAIR = 'entry_pair'
QUOTE_CANCEL = 'quote_cancel'
_PRIORITY = {SAFETY_CANCEL: 0, DUE_IOC: 1, PASSIVE_REDUCER: 2, QUOTE_CANCEL: 3, ENTRY_PAIR: 4}


@dataclass(frozen=True)
class DispatchCandidate:
    """Fresh, source-bound command candidate returned by the injected planner."""
    ticker: str
    priority: str
    attempt_id: str
    request: dict
    evidence: CancelEvidence | ReductionEvidence
    shard: int

    def __post_init__(self):
        identity(self.ticker)
        identity(self.attempt_id)
        if self.priority not in _PRIORITY:
            raise InvalidData('invalid dispatch priority')
        integer(self.shard, 0, 2**31-1)
        kind = 'cancel' if self.priority in {SAFETY_CANCEL, QUOTE_CANCEL} else 'create'
        validate_request(kind, self.request)
        if self.request['exchange_index'] != self.shard:
            raise InvalidData('dispatch shard differs from request route')
        if kind == 'cancel':
            if not isinstance(self.evidence, CancelEvidence):
                raise InvalidData('cancel candidate requires cancel evidence')
            expected = (self.request['order_id'], self.request['market_ticker'],
                        self.request['subaccount'], self.request['exchange_index'])
            actual = (self.evidence.order_id, self.evidence.ticker,
                      self.evidence.subaccount, self.evidence.exchange_index)
            if self.ticker != self.request['market_ticker'] or actual != expected:
                raise InvalidData('cancel candidate evidence scope changed')
        else:
            if not isinstance(self.evidence, ReductionEvidence):
                raise InvalidData('reducer candidate requires reduction evidence')
            tif = self.request['time_in_force']
            expected_tif = ('immediate_or_cancel' if self.priority == DUE_IOC
                            else 'good_till_canceled')
            if (self.request['reduce_only'] is not True or tif != expected_tif
                    or self.ticker != self.request['ticker']
                    or (self.evidence.ticker, self.evidence.subaccount,
                        self.evidence.exchange_index, self.evidence.request_json) !=
                       (self.ticker, self.request['subaccount'], self.shard,
                        encoded_request(self.request))):
                raise InvalidData('reducer candidate evidence scope changed')

    @property
    def operation(self):
        if self.priority in {SAFETY_CANCEL, QUOTE_CANCEL}:
            return 'DELETE', ORDERS+'/'+self.request['order_id']
        return 'POST', ORDERS

    @property
    def units(self):
        return 1

    @property
    def budget_shard(self):
        return self.shard


@dataclass(frozen=True)
class EntryPairCandidate:
    ticker: str
    priority: str
    batch_id: str
    requests: tuple[dict, dict]
    view: PortfolioView
    free_cash: object
    fee_per_contract_bound: object
    shard: int

    def __post_init__(self):
        identity(self.ticker); identity(self.batch_id)
        if self.priority != ENTRY_PAIR or not isinstance(self.view, PortfolioView):
            raise InvalidData('invalid entry pair candidate')
        validate_entry_pair(self.requests)
        integer(self.shard, 0, 2**31-1)
        cash, fee = decimal(self.free_cash), decimal(self.fee_per_contract_bound)
        if cash < 0 or not 0 <= fee <= 1:
            raise InvalidData('invalid entry pair cash or fee bound')
        if (self.ticker != self.requests[0]['ticker']
                or any(row['ticker'] != self.ticker
                       or row['exchange_index'] != self.shard for row in self.requests)):
            raise InvalidData('entry pair route changed')
        object.__setattr__(self, 'free_cash', cash)
        object.__setattr__(self, 'fee_per_contract_bound', fee)

    @property
    def attempt_id(self):
        return self.batch_id

    @property
    def operation(self):
        return 'POST', BATCH_ORDERS

    @property
    def units(self):
        return 2

    @property
    def budget_shard(self):
        return 0


@dataclass(frozen=True)
class DispatchResult:
    state: str
    ticker: str | None = None
    priority: str | None = None
    attempt_id: str | None = None
    blockers: tuple[str, ...] = ()
    retry_after: float | None = None
    order_id: str | None = None
    order_ids: tuple[str, ...] = ()
    live_ready: bool = field(default=False, init=False)


@dataclass(frozen=True)
class DispatcherStatus:
    queued: tuple
    active: tuple | None
    high_water: int
    failed: bool
    stopping: bool
    live_ready: bool = field(default=False, init=False)


class MutationDispatcher:
    """Caller-driven, coalescing dispatcher with one writing worker.

    `refresh` is awaited twice and must return a new DispatchCandidate (or
    None): once to discover exact routing, then again after token reservation.
    No sleeps or automatic retries are owned here. A WAITING result remains
    queued and tells the caller when reevaluation can be attempted.
    """
    def __init__(self, writer, executor, budget, *, refresh, clock_pair, now,
                 capacity=128, offline_fixture=False):
        from .live_session import permits
        if offline_fixture is not True and not permits(writer.live_session, writer):
            raise InvalidData('offline_fixture must be literally True')
        self.offline_fixture = offline_fixture is True
        if (not isinstance(writer, LedgerWriter)
                or not isinstance(executor, InjectedExecutor)
                or executor.writer is not writer
                or not isinstance(budget, WriteBudget)):
            raise InvalidData('single writer/executor and write budget required')
        if not callable(refresh) or not callable(clock_pair) or not callable(now):
            raise InvalidData('dispatcher dependencies must be callable')
        self.writer, self.executor, self.budget = writer, executor, budget
        self.refresh, self.clock_pair, self.now = refresh, clock_pair, now
        self.capacity = integer(capacity, 1, 128)
        self._queues = {value: deque() for value in _PRIORITY.values()}
        self._pending = {}
        self._active = None
        self._active_key = None
        self._high_water = 0
        self._failed = False
        self._stopping = False
        writer.claim_dispatcher(self)

    def submit(self, ticker, priority):
        ticker = identity(ticker)
        if priority not in _PRIORITY:
            raise InvalidData('invalid dispatch priority')
        if self._stopping or self._failed:
            return False
        rank = _PRIORITY[priority]
        old = self._pending.get(ticker)
        if old is not None and old <= rank:
            return False
        if old is None and len(self._pending) >= self.capacity:
            self._failed = True
            raise InvalidData('dispatch reevaluation capacity exceeded')
        self._pending[ticker] = rank
        self._queues[rank].append(ticker)
        self._high_water = max(self._high_water, len(self._pending))
        return True

    def _take(self):
        for rank in range(len(self._queues)):
            queue = self._queues[rank]
            while queue:
                ticker = queue.popleft()
                if self._pending.get(ticker) == rank:
                    del self._pending[ticker]
                    return ticker, rank
        return None

    @staticmethod
    def _priority(rank):
        return next(name for name, value in _PRIORITY.items() if value == rank)

    def _validate_candidate(self, value, ticker, priority):
        if value is None:
            return None
        expected = EntryPairCandidate if priority == ENTRY_PAIR else DispatchCandidate
        if not isinstance(value, expected):
            raise InvalidData('refresh must return a typed dispatch candidate')
        if (value.ticker, value.priority) != (ticker, priority):
            raise InvalidData('refresh returned another dispatch key')
        return value

    async def _discard(self, permit):
        self.budget.discard_if_outstanding(permit, now=self.clock_pair())

    async def _process(self, ticker, priority):
        first = self._validate_candidate(
            await self.refresh(ticker, priority), ticker, priority)
        if self._stopping:
            return DispatchResult('INTERRUPTED', ticker, priority,
                                  blockers=('dispatcher_stopping',))
        if first is None:
            return DispatchResult('BLOCKED', ticker, priority,
                                  blockers=('current_candidate_missing',))
        method, route = first.operation
        permit = self.budget.try_reserve(
            method, route, shard=first.budget_shard, units=first.units,
            now=self.clock_pair())
        if permit is None:
            delay = self.budget.ready_delay(
                method, route, shard=first.budget_shard, units=first.units,
                now=self.clock_pair())
            self.submit(ticker, priority)
            return DispatchResult('WAITING', ticker, priority,
                first.attempt_id, ('write_budget_unavailable',), delay)
        receipt = None
        consumed = False
        try:
            current = self._validate_candidate(
                await self.refresh(ticker, priority), ticker, priority)
            if self._stopping:
                await self._discard(permit)
                return DispatchResult('INTERRUPTED', ticker, priority,
                                      blockers=('dispatcher_stopping',))
            if current is None:
                await self._discard(permit)
                return DispatchResult('BLOCKED', ticker, priority,
                    first.attempt_id, ('current_candidate_missing',))
            if (current.operation != first.operation or current.shard != first.shard
                    or current.units != first.units):
                await self._discard(permit)
                self.submit(ticker, priority)
                return DispatchResult('WAITING', ticker, priority,
                    current.attempt_id, ('candidate_route_changed',), 0.0)
            if priority == ENTRY_PAIR:
                from .config import BotConfig
                prepared = await self.writer.reserve_entry_pair(
                    current.requests, batch_id=current.batch_id,
                    view=current.view, config=BotConfig(), now=self.now(),
                    free_cash=current.free_cash, account_known=True,
                    offline_fixture=self.offline_fixture,
                    fee_per_contract_bound=current.fee_per_contract_bound)
                receipt = prepared.batch
            elif priority in {SAFETY_CANCEL, QUOTE_CANCEL}:
                prepared = await self.writer.prepare_cancel(
                    current.attempt_id, current.request,
                    evidence=current.evidence, now=self.now())
                receipt = prepared.receipt
            else:
                prepared = await self.writer.prepare_reduction(
                    current.attempt_id, current.request,
                    evidence=current.evidence, now=self.now())
                receipt = prepared.receipt
            if self._stopping:
                if receipt is not None:
                    if priority == ENTRY_PAIR:
                        await self.writer.abort_batch(receipt)
                    else:
                        await self.writer.abort_prepared(receipt)
                    receipt = None
                await self._discard(permit)
                return DispatchResult('INTERRUPTED', ticker, priority,
                                      blockers=('dispatcher_stopping',))
            if not prepared.reserved:
                if receipt is not None:
                    if priority == ENTRY_PAIR:
                        await self.writer.abort_batch(receipt)
                    else:
                        await self.writer.abort_prepared(receipt)
                    receipt = None
                await self._discard(permit)
                return DispatchResult('BLOCKED', ticker, priority,
                    current.attempt_id, prepared.blockers)
            try:
                self.budget.check_permit(permit, method, route,
                    shard=current.budget_shard, units=current.units,
                    now=self.clock_pair())
            except Exception:
                if priority == ENTRY_PAIR:
                    await self.writer.abort_batch(receipt)
                else:
                    await self.writer.abort_prepared(receipt)
                receipt = None
                raise
            def consume_at_send_edge():
                nonlocal consumed
                if self._stopping:
                    raise CommandDenied(('dispatcher_stopping',))
                self.budget.consume(permit, method, route,
                    shard=current.budget_shard, units=current.units,
                    now=self.clock_pair())
                consumed = True
                if self._stopping:
                    raise CommandDenied(('dispatcher_stopping',))
            try:
                if priority == ENTRY_PAIR:
                    result = await self.executor.execute_prepared_batch(
                        receipt, before_invoke=consume_at_send_edge)
                else:
                    result = await self.executor.execute_prepared(
                        receipt, before_invoke=consume_at_send_edge)
            except CommandDenied as exc:
                # If the executor rejected before SENDING, this proves the
                # prepared command was not submitted. If it already advanced,
                # abort_prepared safely returns already-used without mutation.
                if priority == ENTRY_PAIR:
                    await self.writer.abort_batch(receipt)
                else:
                    await self.writer.abort_prepared(receipt)
                receipt = None
                if self.executor.failed:
                    raise
                await self._discard(permit)
                return DispatchResult('BLOCKED', ticker, priority,
                    current.attempt_id, exc.blockers)
            if priority == ENTRY_PAIR:
                if result.phase != 'ACK':
                    self._failed = True
                    return DispatchResult('FAILED', ticker, priority,
                        current.attempt_id,
                        ('entry_pair_partial_reconciliation_required',),
                        order_ids=result.order_ids)
                return DispatchResult('ACK', ticker, priority, current.attempt_id,
                                      order_ids=result.order_ids)
            return DispatchResult(result.phase, ticker, priority, current.attempt_id,
                                  order_id=result.order_id)
        except BaseException:
            if receipt is not None and not consumed:
                if priority == ENTRY_PAIR:
                    await self.writer.abort_batch(receipt)
                else:
                    await self.writer.abort_prepared(receipt)
            await self._discard(permit)
            raise

    async def run_one(self):
        if self._failed:
            return DispatchResult('FAILED', blockers=('dispatcher_failed',))
        if self._stopping:
            return DispatchResult('INTERRUPTED', blockers=('dispatcher_stopping',))
        if self._active is not None:
            return DispatchResult('BLOCKED', blockers=('dispatcher_busy',))
        selected = self._take()
        if selected is None:
            return DispatchResult('IDLE')
        ticker, rank = selected
        priority = self._priority(rank)
        task = asyncio.create_task(self._process(ticker, priority),
                                   name='kalshi-mutation-dispatch')
        self._active, self._active_key = task, (ticker, priority)
        cancelled = False
        try:
            while not task.done():
                try:
                    await asyncio.wait((task,))
                except asyncio.CancelledError:
                    cancelled = True
            result = task.result()
        except BaseException:
            self._failed = True
            raise
        finally:
            self._active = self._active_key = None
        if cancelled:
            raise asyncio.CancelledError
        return result

    def stop(self):
        self._stopping = True

    async def close(self):
        self.stop()
        task = self._active
        if task is None:
            return
        cancelled = False
        while not task.done():
            try:
                await asyncio.wait((task,))
            except asyncio.CancelledError:
                cancelled = True
        task.result()
        if cancelled:
            raise asyncio.CancelledError

    def status(self):
        queued = tuple((self._priority(rank), ticker)
            for rank, queue in self._queues.items() for ticker in queue
            if self._pending.get(ticker) == rank)
        return DispatcherStatus(queued, self._active_key, self._high_water,
                                self._failed, self._stopping)
