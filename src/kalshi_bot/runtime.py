"""Recovery engine with opt-in injected dispatch; no live CLI or mutations.

Construction opens nothing. A caller explicitly supplies already configured
GET reads, single-use reader factories, UTC clock and history scope. The owner
must close the writer after run() returns so accepted writes finish draining.
"""
import asyncio
from datetime import timedelta
import random
import time
from uuid import uuid4

from .account import AccountCoordinator, UnscopedPositionUpdate
from .adapters import parse_fill
from .books import BookConnection
from .continuity import PrivateEpoch, assess_continuity, starting_candidate
from .engine import EventEngine
from .config import BotConfig
from .management import InventoryManager
from .metadata_scheduler import MetadataScheduler
from .quota import QuotaUnavailable
from .observability import NO_LOG
from .transport import WebSocketReaders, topology
from .values import InvalidData, integer, utc


def readonly_reader_factory(signer, *, connector=None):
    """Factory only; does not open sockets or load credentials."""
    def create(spec):
        kwargs = {} if connector is None else {"connector": connector}
        return WebSocketReaders(signer, (spec,), capacity=256, byte_capacity=2*1024*1024, **kwargs)
    return create


class RecoveryReads:
    """One pass shares a repair-count budget as well as underlying REST tokens."""
    def __init__(self, reads):
        self.reads, self.order_lookups = reads, 0

    async def read(self, name, **kwargs):
        if name == "order":
            if self.order_lookups >= 32:
                raise InvalidData("recovery order-lookup budget exhausted")
            self.order_lookups += 1
        return await self.reads.read(name, **kwargs)

    async def collect(self, name, **kwargs):
        return await self.reads.collect(name, **kwargs)


class RecoveryRuntime:
    def __init__(self, writer, reads, reader_factory, *, tickers, subaccount,
                 history_start, now, evaluate, deadline_handler, lifecycle_handler,
                 invalidate=lambda ticker: None, clock=time.monotonic,
                 sleep=asyncio.sleep, jitter=lambda: random.uniform(.8, 1.2), attempts=3,
                 diagnostics=NO_LOG, market_inputs=None, quota_supervisor=None,
                 accounting_boundary=None, observation_only=False, opening_reference=None):
        if type(observation_only) is not bool:
            raise InvalidData('observation_only must be a boolean')
        self.observation_only = observation_only
        self.live_session = writer.live_session
        if observation_only and self.live_session is not None:
            raise InvalidData('observation runtime cannot own a live session')
        if opening_reference is not None and self.live_session is None:
            raise InvalidData('opening approval requires explicit live composition')
        self.opening_reference = opening_reference
        self.diagnostics = diagnostics
        self.writer, self.reads, self.reader_factory = writer, reads, reader_factory
        self.now, self.clock, self.sleep, self.jitter = now, clock, sleep, jitter
        self.history_start = utc(history_start)
        self.accounting_boundary = utc(accounting_boundary) if accounting_boundary is not None else None
        self.accounting_result = None
        if self.history_start >= utc(now()):
            raise InvalidData("explicit nonempty startup history scope required")
        self.attempt_limit = integer(attempts, 1, 8)
        self.specs = topology(tuple(tickers), market_capacity=writer.market_capacity)
        self.account = AccountCoordinator(writer, subaccount=subaccount, capacity=writer.market_capacity, clock=clock)
        shards = {s.name: BookConnection(s.tickers) for s in self.specs if s.name.startswith("book-")}
        self.lost = {name: asyncio.Event() for name in shards}
        self.invalidate = invalidate
        self.management = InventoryManager(self)
        self._evaluate_callback, self._deadline_callback = evaluate, deadline_handler
        self.engine = EventEngine(shards, private_handler=self._private, evaluate=self._evaluate,
            deadline_handler=self._deadline, invalidate=self._invalidate_market, clock=clock,
            book_lost=lambda name: self.lost[name].set(), diagnostics=diagnostics)
        self.lifecycle_handler = lifecycle_handler
        self.market_inputs = market_inputs
        if market_inputs is not None:
            if market_inputs.tickers != frozenset(tickers):
                raise InvalidData('runtime/input market scope mismatch')
            market_inputs.bind(self.management.set_terms,self.management.revoke_terms)
        self.account_lock = asyncio.Lock()
        self.recovery_lock = asyncio.Lock()
        self.recovery_requested = asyncio.Event()
        self.stop_requested = asyncio.Event()
        self.account_subscribed = False
        self.reader_states = {s.name: "not_started" for s in self.specs}
        self.connection_attempts = {s.name: 0 for s in self.specs}
        self.reader_failures = {s.name: 0 for s in self.specs}
        self.recovery_state = "not_started"
        self.recovery_attempts = 0
        self.recovery_passes = 0
        self.last_reports = None
        self.history_inspection = None
        self.ingress_revision = 0
        self.history_ingress_revision = None
        self.used = False
        self.running = False
        self._run_cancelled = False
        self._shutdown_task = None
        self.dispatch_supervisor = None  # Explicit offline attachment only.
        self.selection = None  # Advisory only, attached before runtime start.
        self.incentives = None  # One shared-budget catalog; explicit offline opt-in.
        self.rewards = None  # Actual-order telemetry only; never financial authority.
        self.admission = None  # Explicit offline subscription owner, not order authority.
        self._epoch = None
        self._epoch_ingress = 0
        self._epoch_fills = 0
        self._epoch_ambiguous = False
        self._unscoped_position_requested = False
        self._persisted_epoch_gaps = None
        self.continuity_assessment = None
        self.quota_supervisor = quota_supervisor
        self.quota = getattr(reads, 'quota', None)
        if quota_supervisor is not None:
            if (quota_supervisor.reads is not reads or quota_supervisor.guard is not self.quota
                    or quota_supervisor.used or (market_inputs is not None and market_inputs.reads is not reads)):
                raise InvalidData('runtime quota service mismatch')
        if self.quota is not None and quota_supervisor is None:
            raise InvalidData('guarded runtime requires its quota supervisor')
        self._quota_available = False
        if self.quota is not None:
            self.quota.listen(self._quota_transition)
        self.metadata_scheduler = (MetadataScheduler(market_inputs, diagnostics=diagnostics,
            defer=lambda: bool(self.engine.private or self.account._processing or
                               self.recovery_state == 'recovering')) if market_inputs is not None else None)

    def _quota_transition(self):
        if self.dispatch_supervisor is not None:
            self.dispatch_supervisor.changed()
        available = self.quota.state == 'fresh'
        was_available, self._quota_available = self._quota_available, available
        if was_available and not available:
            self._revoke()
        elif available and not was_available and self.recovery_state != 'blocked_retry_exhausted':
            self.request_recovery()

    def _invalidate_market(self, ticker):
        self.management.invalidate(ticker)
        if self.selection is not None:
            self.selection.invalidate(ticker)
        if self.rewards is not None:
            self.rewards.invalidate(ticker)
        self.invalidate(ticker)

    def attach_selection(self, *, offline_fixture=False):
        from .selection_runtime import RuntimeSelection
        if self.used or self.stop_requested.is_set() or self.selection is not None:
            raise InvalidData('selection requires unused runtime')
        self.selection = RuntimeSelection(self, offline_fixture=offline_fixture)
        return self.selection

    def attach_dispatch(self, source, dispatcher, *, offline_fixture=False):
        """Opt-in dispatch for fixtures or explicit sessions; never observation."""
        from .dispatch_supervisor import DispatchSupervisor
        if (self.observation_only or self.used or self.stop_requested.is_set() or self.dispatch_supervisor is not None
                or getattr(source, 'runtime', None) is not self):
            raise InvalidData('dispatch requires matching unused runtime')
        service = DispatchSupervisor(source, dispatcher, offline_fixture=offline_fixture)
        self.dispatch_supervisor = service
        return service

    def attach_incentives(self, *, offline_fixture=False, interval=300, attempts=3):
        from .incentive_discovery import IncentiveDiscovery
        service = IncentiveDiscovery(self, offline_fixture=offline_fixture,
                                     interval=interval, attempts=attempts)
        self.incentives = service
        # The catalog becomes the sole program producer; revoke manual fixtures.
        self.selection.programs.clear()
        service._changed()
        return service

    def attach_rewards(self, *, scope, offline_fixture=False, checkpoint_path=None,
                       reflection_interval=4, checkpoint_interval=60):
        from .reward_runtime import RuntimeRewards
        self.rewards = RuntimeRewards(self,scope=scope,offline_fixture=offline_fixture,
            checkpoint_path=checkpoint_path,reflection_interval=reflection_interval,
            checkpoint_interval=checkpoint_interval)
        return self.rewards

    def attach_admission(self, *, offline_fixture=False):
        from .admission import MarketAdmission
        self.admission = MarketAdmission(self,offline_fixture=offline_fixture)
        return self.admission

    def request_dispatch(self, ticker, priority):
        if self.dispatch_supervisor is None:
            raise InvalidData('offline dispatch not attached')
        return self.dispatch_supervisor.request(ticker, priority)

    async def _evaluate(self, ticker, book, generation):
        await self.management.refresh(ticker)
        self._request_inventory_dispatch(ticker)
        if self.selection is not None:
            self.selection.refresh(ticker)
            if (self.dispatch_supervisor is not None
                    and self.selection.current(ticker)):
                from .dispatch import ENTRY_PAIR
                self.dispatch_supervisor.request(ticker, ENTRY_PAIR)
        if self.rewards is not None:
            self.rewards.refresh(ticker)
        await self._evaluate_callback(ticker, book, generation)

    async def _deadline(self, ticker):
        await self.management.refresh(ticker)
        self._request_inventory_dispatch(ticker)
        if self.selection is not None:
            self.selection.refresh(ticker)
        if self.rewards is not None:
            self.rewards.refresh(ticker)
        await self._deadline_callback(ticker)

    def _request_inventory_dispatch(self, ticker):
        """Queue a key, never a command; the source revalidates before dispatch.

        Do not call from management.refresh itself: source.refresh also calls
        that method and would continuously resubmit its own dispatch key.
        """
        if self.dispatch_supervisor is None or self.stop_requested.is_set():
            return
        from .dispatch import SAFETY_CANCEL, DUE_IOC, PASSIVE_REDUCER
        plan = self.management.current(ticker)
        if plan is None or plan.exit is None:
            return
        if (self.entry_pause_active
                and any(r.owned and not r.reducing and not r.order.terminal
                        for r in plan.inventory.orders)):
            self.request_dispatch(ticker, SAFETY_CANCEL)
        elif (plan.exit.mode in {'flat', 'passive', 'cancel_before_ioc'}
                and plan.passive.cancel_ids):
            self.request_dispatch(ticker, SAFETY_CANCEL)
        elif plan.exit.mode == 'ioc':
            self.request_dispatch(ticker, DUE_IOC)
        elif plan.exit.mode == 'passive':
            self.request_dispatch(ticker, PASSIVE_REDUCER)

    async def risk_view(self):
        return await self.writer.portfolio(subaccount=self.account.subaccount, now=self.now())

    async def refresh_exit_inputs(self, ticker):
        """Bounded control-plane refresh, never called from a book tick handler."""
        if self.market_inputs is None:
            raise InvalidData('market input service not configured')
        if self.metadata_scheduler.running:
            raise InvalidData('use scheduled refresh request while runtime owns metadata')
        return await self.market_inputs.refresh(ticker)

    def request_exit_input_refresh(self, ticker, *, retry=False):
        if self.metadata_scheduler is None:
            raise InvalidData('market input service not configured')
        return self.metadata_scheduler.request(ticker, retry=retry)

    async def inspect_history_coverage(self, *, start, end):
        """Explicit local control-plane inspection; never a live recovery lease."""
        result = await self.writer.history_coverage(subaccount=self.account.subaccount, start=start, end=end)
        self.history_inspection = result
        self._refresh_continuity()
        return result

    async def inspect_private_epochs(self, *, limit=128):
        """Explicit local control-plane read; no venue request or authority."""
        return await self.writer.inspect_private_epochs(subaccount=self.account.subaccount, limit=limit)

    def inspect_starting_account(self, *, proposed_boundary):
        report = self.account.current_report(self.now())
        return starting_candidate(report, proposed_boundary=proposed_boundary,
            subaccount=self.account.subaccount, writer_epoch=self.writer.epoch,
            writer_revision=self.writer.revision, continuity=self._refresh_continuity())

    async def _load_continuity_history(self):
        if self._persisted_epoch_gaps is None:
            count = await self.writer.private_epoch_gap_count(
                subaccount=self.account.subaccount,
                exclude_epoch_id=self._epoch.epoch_id if self._epoch and self._epoch.closed_at is None else None)
            # An epoch may close while the read is queued; never overwrite a
            # locally recorded gap with an older count.
            self._persisted_epoch_gaps = max(self._persisted_epoch_gaps or 0, count)
            self._refresh_continuity()

    def _refresh_continuity(self, *, operational=False):
        report = self.account.current_report(self.now())
        history = self.last_reports[0] if self.last_reports else None
        self.continuity_assessment = assess_continuity(subaccount=self.account.subaccount,
            generation=self.account.generation, writer_epoch=self.writer.epoch,
            writer_revision=self.writer.revision, report=report, recovery=history,
            coverage=None if operational else self.history_inspection, epoch=self._epoch,
            history_ingress_revision=self.history_ingress_revision,
            ingress_revision=self.ingress_revision,
            persisted_gap_count=self._persisted_epoch_gaps,
            epoch_ambiguous=self._epoch_ambiguous)
        return self.continuity_assessment

    async def inspect_entry(self, request):
        """Integrated fail-closed gate; never grants a live reservation."""
        view = await self.risk_view()
        report = self.account.current_report(self.now())
        return await self.writer.reserve_entry(request,
            attempt_id=request['client_order_id'], view=view,
            config=BotConfig(), now=self.now(),
            free_cash=report.snapshot.available_balance if report else 0,
            account_known=False, offline_fixture=False)

    @property
    def entry_pause_active(self):
        """Operator/recovery pause or durable hard loss hold; never a cap reset."""
        window = getattr(self.accounting_result, 'window', None)
        return bool((self.live_session is not None and self.live_session.entries_paused)
                    or (window is not None and window.held))

    @property
    def entry_allowed(self):
        from .live_session import permits
        lease = self.writer._accounting_lease
        return (permits(self.live_session, self.writer)
                and not self.entry_pause_active
                and self.accounting_result is not None and self.accounting_result.released
                and lease is not None and lease.fence.current()
                and not self.stop_requested.is_set())

    @property
    def live_components_enabled(self):
        from .live_session import permits
        return permits(self.live_session, self.writer)

    def request_recovery(self):
        self.last_reports = None
        self._refresh_continuity()
        self.recovery_requested.set()  # Coalesced, never a task per market/event.

    def _revoke(self):
        self.ingress_revision += 1
        self.last_reports = None
        self.account._invalidate()
        for ticker in self.engine.market_shard:
            self._invalidate_market(ticker)
        self._refresh_continuity()

    async def _stage(self, event):
        msg = event["msg"]
        return await self.writer.stage_fill(parse_fill(event), owner=self.account.subaccount,
            scope=msg.get("subaccount"), exchange_index=msg.get("exchange_index"), now=self.now())

    async def _private(self, event, generation):
        async with self.account_lock:
            if event.get("type") == "fill":
                # Reader callback staged before enqueue. Old epochs keep positive
                # evidence in the inbox, but cannot update current projections.
                key = parse_fill(event).key
                receipt = await self.account.apply_pending_fill(key, generation=generation, now=self.now())
                if receipt is None:
                    self.request_recovery()
                else:
                    await self.management.refresh(event["msg"]["market_ticker"])
                    self._request_inventory_dispatch(event["msg"]["market_ticker"])
                return
            if generation != self.account.generation or not self.account.connected:
                return  # Old order/position projection will be re-enumerated.
            result = await self.account.on_event(event, generation=generation, received_at=self.now())
            if isinstance(result, UnscopedPositionUpdate):
                self._epoch_ambiguous = True
                if not self._unscoped_position_requested:
                    self._unscoped_position_requested = True
                    self.request_recovery()
                return
            if event.get('type') == 'market_position':
                self.request_recovery()
            if result is not None and getattr(result, "owned", False):
                waiting = await self.writer.pending_fills(self.account.subaccount, result.order.order_id)
                for item in waiting[:32]:
                    receipt = await self.account.apply_pending_fill(item.fill.key,
                        generation=generation, now=self.now())
                    if receipt is not None and receipt.order is not None:
                        result = receipt.order
                if len(waiting) > 32:
                    self.request_recovery()
            if result is not None and getattr(result, "awaiting_fills", False):
                self.request_recovery()
            ticker = event.get("msg", {}).get("ticker", event.get("msg", {}).get("market_ticker"))
            if ticker is not None:
                await self.management.refresh(ticker)
                self._request_inventory_dispatch(ticker)

    async def _consume(self, spec, event, generation, acknowledged, ready=None):
        kind = event.get("type")
        if self.stop_requested.is_set():
            # The transport may already have removed this event from its bounded
            # queue when shutdown begins. Positive fill evidence must still reach
            # the durable inbox; every event crossing this boundary invalidates a
            # clean drain because it will not be dispatched normally.
            if spec.name == "account" and kind == "fill":
                self._revoke()
                await self._stage(event)
                if (self._epoch is not None and self._epoch.generation == generation
                        and self._epoch.closed_at is None):
                    self._epoch_fills += 1
            return False
        if spec.name == "account" and generation != self.account.generation:
            return True
        if spec.name in self.engine.shards and generation != self.engine.shards[spec.name].generation:
            return True
        if kind == "subscribed":
            msg = event.get("msg", {})
            channel = msg.get("channel")
            integer(msg.get("sid"), 1, 2**63-1)
            if channel not in spec.channels or event.get("id") != 1:
                raise InvalidData("unexpected subscription acknowledgment")
            if channel in acknowledged:
                raise InvalidData("duplicate subscription acknowledgment")
            acknowledged.add(channel)
            if acknowledged == set(spec.channels):
                if spec.name == "account":
                    if not self.account.connected:
                        return True
                    marker = PrivateEpoch(
                        uuid4().hex, self.account.subaccount, generation, self.writer.epoch,
                        tuple(sorted(acknowledged)), self.now())
                    # Own the identity before awaiting its accepted writer command.
                    # Writer commands survive caller cancellation, so teardown can
                    # close this exact marker even if its acknowledgement is lost.
                    self._epoch = marker
                    self._epoch_ingress = self._epoch_fills = 0
                    self._epoch_ambiguous = self._unscoped_position_requested = False
                    try:
                        self._epoch = await self.writer.open_private_epoch(marker)
                    except BaseException:
                        self._persisted_epoch_gaps = None
                        self._refresh_continuity()
                        raise
                    else:
                        self._refresh_continuity()
                self.reader_states[spec.name] = "subscribed"
                if spec.name=='lifecycle' and self.market_inputs is not None:
                    self.market_inputs.subscribed(generation,msg['sid'])
                self.diagnostics.emit('reader_subscribed', stream=spec.name, generation=generation)
                if ready is not None:
                    ready.set()
                if spec.name == "account":
                    self.account_subscribed = True
                    self.request_recovery()
            return True
        if kind == "error":
            raise InvalidData("subscription rejected")
        if spec.name == "account":
            if generation != self.account.generation:
                return
            if not self.account_subscribed:
                # A private event before every required ACK has no opened local
                # epoch. Preserve positive fill evidence, then reconnect rather
                # than later declaring the span clean.
                self._revoke()
                if kind == 'fill':
                    await self._stage(event)
                raise InvalidData('private event before complete subscription')
            self._revoke()  # At ingestion, before queue/disk waits; not at dispatch.
            if kind == "fill":
                await self._stage(event)  # Acknowledged durable evidence before enqueue.
                self._epoch_fills += 1
            if self.engine.submit_private(event, generation=generation):
                self._epoch_ingress += 1
        elif spec.name in self.engine.shards:
            self.engine.submit_book(spec.name, event, generation=generation)
        else:
            if self.market_inputs is not None:
                self.market_inputs.ingest(event,generation=generation)
            await self.lifecycle_handler(event)
        return True

    async def _connection(self, spec, *, attempt_start=0):
        for attempt in range(attempt_start,self.attempt_limit):
            if self.stop_requested.is_set() or self.writer.failed or self.engine.failed:
                return
            self.connection_attempts[spec.name] += 1
            self.reader_states[spec.name] = "connecting"
            self.diagnostics.emit('reader_connecting', stream=spec.name, attempt=attempt+1)
            if spec.name == "account":
                # Previous transport is joined before this iteration. Drain queued
                # old-epoch events; their fills remain durable even while disconnected.
                await self.engine.private_idle.wait()
                async with self.account_lock:
                    generation = self.account.connect_generation()
                    if self.engine.begin_private_epoch() != generation:
                        raise InvalidData("account/engine epoch mismatch")
            elif spec.name in self.engine.shards:
                self.lost[spec.name].clear()
                generation = self.engine.begin_book_epoch(spec.name)
            else:
                generation = attempt+1
                if self.market_inputs is not None:
                    self.market_inputs.begin(generation)
            acknowledged = set()
            ready = asyncio.Event()
            reader_error = False
            drain_error = None
            delivery_inflight = 0
            delivery_failed = False
            delivery_idle = asyncio.Event()
            delivery_idle.set()
            epoch_open_confirmed = False
            async def consume(name, event):
                nonlocal delivery_inflight, delivery_failed, epoch_open_confirmed
                if name != spec.name:
                    raise InvalidData("reader source mismatch")
                tracked = spec.name == 'account' and event.get('type') != 'subscribed'
                if tracked:
                    delivery_inflight += 1
                    delivery_idle.clear()
                try:
                    delivered = await self._consume(spec, event, generation, acknowledged, ready)
                    if (spec.name == 'account' and event.get('type') == 'subscribed'
                            and self.account_subscribed and self._epoch is not None
                            and self._epoch.generation == generation):
                        epoch_open_confirmed = True
                    if tracked and delivered is False:
                        delivery_failed = True
                except BaseException:
                    if tracked:
                        delivery_failed = True
                    raise
                finally:
                    if tracked:
                        delivery_inflight -= 1
                        if delivery_inflight == 0:
                            delivery_idle.set()
            # Factory/construction faults must be observed by the runtime owner,
            # not treated as successful connections or silently retried forever.
            reader_owner = self.reader_factory(spec)
            reader = asyncio.create_task(reader_owner.run(consume), name='kalshi-'+spec.name)
            lost = (asyncio.create_task(self.lost[spec.name].wait())
                    if spec.name in self.lost else None)
            async def finalize():
                """Own this generation's teardown after every exit path."""
                nonlocal delivery_failed, drain_error
                self.reader_states[spec.name] = "stopped" if self.stop_requested.is_set() else "disconnected"
                if spec.name == "account":
                    self.account_subscribed = False
                    self.account.disconnect()
                    self._revoke()
                elif spec.name in self.engine.shards:
                    self.engine._lose_book(spec.name)
                else:
                    if self.market_inputs is not None:
                        self.market_inputs.disconnect()
                    self._revoke()
                if spec.name == 'account' and delivery_inflight:
                    try:
                        async with asyncio.timeout(1):
                            await delivery_idle.wait()
                    except TimeoutError:
                        delivery_failed = True
                reader.cancel()
                if lost:
                    lost.cancel()
                await asyncio.gather(reader, *([lost] if lost else []), return_exceptions=True)
                if spec.name == 'account':
                    # The joined reader is now the only possible prior consumer.
                    # Retain positive fills still buffered at teardown before the
                    # marker closes. Other buffered events cannot be applied as a
                    # normal ordered stream and therefore invalidate the span.
                    local_queue = getattr(reader_owner, 'queue', None)
                    if local_queue is not None and callable(getattr(local_queue, 'get_nowait', None)):
                        for _ in range(256):
                            try:
                                item = local_queue.get_nowait()
                            except asyncio.QueueEmpty:
                                break
                            delivery_failed = True
                            try:
                                event = item
                                if isinstance(item, tuple):
                                    if len(item) != 3:
                                        raise InvalidData('invalid buffered reader item')
                                    queued_name, event, wire_bytes = item
                                    if (queued_name != spec.name or type(wire_bytes) is not int
                                            or wire_bytes < 0):
                                        raise InvalidData('invalid buffered reader provenance')
                                    if hasattr(reader_owner, 'queued_bytes'):
                                        reader_owner.queued_bytes = max(0,
                                            reader_owner.queued_bytes-wire_bytes)
                                if isinstance(event, BaseException):
                                    raise InvalidData('buffered reader failure')
                                if not isinstance(event, dict):
                                    raise InvalidData('invalid buffered private event')
                                if event.get('type') == 'fill':
                                    await self._stage(event)
                                    self._epoch_fills += 1
                            except Exception as exc:
                                if drain_error is None:
                                    drain_error = exc
                if (spec.name == "account" and self._epoch is not None
                        and self._epoch.generation == generation and self._epoch.closed_at is None):
                    local_queue = getattr(reader_owner, 'queue', None)
                    reader_drained = (local_queue is not None and callable(getattr(local_queue, 'empty', None))
                        and local_queue.empty() and getattr(reader_owner, 'queued_bytes', 0) == 0
                        and delivery_inflight == 0 and not delivery_failed)
                    clean = (self.stop_requested.is_set() and not self._run_cancelled
                        and not reader_error and not self.engine.failed and not self.writer.failed
                        and reader_drained and self.engine.private_idle.is_set()
                        and not self._epoch_ambiguous)
                    reason = ('stopped' if clean else 'writer_failure' if self.writer.failed else
                              'engine_failure' if self.engine.failed else
                              'scope_ambiguous' if self._epoch_ambiguous else
                              'undrained' if not reader_drained or not self.engine.private_idle.is_set() else
                              'reader_error' if reader_error else 'cancelled')
                    self._epoch = await self.writer.close_private_epoch(self._epoch.epoch_id,
                        closed_at=self.now(), ingress_count=self._epoch_ingress,
                        durable_fill_count=self._epoch_fills, terminal_reason=reason,
                        clean_local_delivery=clean)
                    if epoch_open_confirmed and self._persisted_epoch_gaps is not None:
                        self._persisted_epoch_gaps += int(not clean)
                    else:
                        # The open acknowledgement was interrupted or failed after
                        # submission. Re-read the durable truth rather than infer
                        # whether that accepted command committed.
                        self._persisted_epoch_gaps = await self.writer.private_epoch_gap_count(
                            subaccount=self.account.subaccount)
                    self._refresh_continuity()
                if drain_error is not None:
                    self.diagnostics.emit('reader_failed', error=drain_error,
                        stream=spec.name, generation=generation, attempt=attempt+1)
                    raise InvalidData('account reader drain failed; reconciliation required') from None
            try:
                # Missing/rejected acknowledgments cannot park a connection forever.
                handshake = asyncio.create_task(ready.wait())
                try:
                    done, _ = await asyncio.wait((reader, handshake), timeout=10,
                                                 return_when=asyncio.FIRST_COMPLETED)
                    if reader in done:
                        await reader
                        raise InvalidData("reader ended before subscription")
                    if handshake not in done:
                        raise InvalidData("subscription acknowledgment timed out")
                finally:
                    handshake.cancel()
                    await asyncio.gather(handshake, return_exceptions=True)
                if lost is None:
                    # Connection cancellation enters the controlled teardown
                    # below; it must not implicitly cancel an in-flight private
                    # callback before that callback is accounted for.
                    await asyncio.shield(reader)
                else:
                    await asyncio.wait((reader, lost), return_when=asyncio.FIRST_COMPLETED)
                    if reader.done():
                        await reader
                raise InvalidData("reader ended or book proof lost")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Bounded retry, no raw response/credential logging. Writer/engine
                # failure is permanent for this runtime and cannot be retried away.
                self.reader_states[spec.name] = "disconnected"
                reader_error = True
                self.reader_failures[spec.name] = attempt+1
                self.diagnostics.emit('reader_failed', error=exc, stream=spec.name,
                                      generation=generation, attempt=attempt+1)
            finally:
                # Teardown can already be active when runtime shutdown cancels
                # this connection. Keep one retained owner for the reader join,
                # fill drain and marker close through every later cancellation.
                finalizer = asyncio.create_task(finalize(), name='kalshi-'+spec.name+'-finalize')
                finalizer_cancelled = False
                while not finalizer.done():
                    try:
                        await asyncio.shield(finalizer)
                    except asyncio.CancelledError:
                        finalizer_cancelled = True
                finalizer.result()
                if finalizer_cancelled:
                    raise asyncio.CancelledError
            if attempt+1 < self.attempt_limit and not self.writer.failed and not self.engine.failed:
                await self.sleep(min(30, 2**attempt)*self.jitter())
        self.reader_states[spec.name] = "retry_exhausted"
        self.diagnostics.emit('reader_exhausted', stream=spec.name, attempt=self.attempt_limit)

    async def recover_once(self):
        """One attempt; never a proof of complete account history or entry readiness."""
        if self.recovery_lock.locked():
            raise InvalidData("recovery already in flight")
        async with self.recovery_lock:
            await self._load_continuity_history()
            return await self._repair()

    async def _repair(self):
        if not self.account_subscribed or not self.account.connected or self.writer.failed:
            return False
        generation = self.account.generation
        reads = RecoveryReads(self.reads)
        await self.engine.private_idle.wait()
        if generation != self.account.generation or not self.account.connected:
            return False
        first = await self.account.reconcile(reads, now=self.now)
        if first is None:
            return False
        history_ingress = self.ingress_revision
        history = await self.account.recover_history(reads, start=self.history_start,
                                                    end=self.now(), now=self.now)
        if history is None:
            return False
        pending = await self.writer.pending_fills(self.account.subaccount)
        attempted = set()
        for item in pending:
            if generation != self.account.generation or not self.account.connected:
                return False
            known = await self.writer.order_evidence(item.fill.order_id)
            if known is None and item.fill.order_id not in attempted and len(attempted) < 32:
                attempted.add(item.fill.order_id)
                await self.account.recover_pending_order(reads, item, now=self.now)
            async with self.account_lock:
                await self.account.apply_pending_fill(item.fill.key, generation=generation, now=self.now())
        # Fills can be recovered while the durable order still says "resting".
        # Absence from resting enumeration is a reason to ask, never to cancel
        # locally or release its reservation. Bound repair GETs across all phases.
        visible = {o.order_id for o in first.snapshot.orders}
        for receipt in await self.writer.orders():
            if receipt.awaiting_fills or (not receipt.order.terminal and receipt.order.order_id not in visible):
                if reads.order_lookups >= 32:
                    return False
                await self.account.recover_order(reads, receipt.order.order_id, now=self.now)
            if generation != self.account.generation or not self.account.connected:
                return False
        final = await self.account.reconcile(reads, now=self.now)
        if final is None or generation != self.account.generation:
            return False
        remaining = await self.writer.pending_fills(self.account.subaccount)
        if (self.account.report is not final or not self.account.connected
                or self.engine.private or self.account._processing):
            return False
        self.last_reports = (history, final)
        self.history_ingress_revision = history_ingress
        active = {p.ticker for p in final.snapshot.positions if p.quantity}
        active.update(r.order.ticker for r in self.account.order_states.values() if not r.order.terminal)
        for ticker in sorted(active):
            await self.management.refresh(ticker)
            self._request_inventory_dispatch(ticker)
        if self.account.report is not final or generation != self.account.generation:
            return False
        # Exact local agreement is necessary, never complete venue/history proof.
        repaired = (not remaining and not history.missing_fill_keys
                and history.enumeration is not None and not history.enumeration.omitted_rows
                and self.account.current_report(self.now()) is final and final.audit.consistent
                and not self._epoch_ambiguous
                and history_ingress == self.ingress_revision
                and (history.generation, history.subaccount) ==
                    (self.account.generation, self.account.subaccount))
        self.recovery_passes += int(repaired)
        self._refresh_continuity()
        if repaired and self.accounting_boundary is not None:
            if self.opening_reference is not None:
                status = await self.writer.accounting_status()
                if 'operator_boundary_not_approved' in status.blockers:
                    captured = await self.account.reconcile_accounting(
                        reads, proposed_boundary=self.accounting_boundary,
                        continuity=self._refresh_continuity(operational=True), now=self.now)
                    await self.writer.approve_opening(
                        checkpoint_digest=captured.status.checkpoint_digest,
                        captured_digest=captured.captured_digest,
                        reference=self.opening_reference, now=self.now())
                    # Approval advances the writer revision. Obtain a new
                    # source-fenced report before granting a dispatch lease.
                    self.request_recovery()
                    return False
            self.accounting_result = await self.account.reconcile_accounting(
                reads, proposed_boundary=self.accounting_boundary,
                continuity=self._refresh_continuity(operational=True), now=self.now, release=True)
            repaired = self.accounting_result.released
        return repaired

    async def _recover(self):
        while not self.stop_requested.is_set():
            await self.recovery_requested.wait()
            attempt = 0
            while attempt < self.attempt_limit:
                if self.quota is not None and not self.quota.poll():
                    self.recovery_state = 'awaiting_quota'
                    try:
                        await self.quota.wait_available()
                    except QuotaUnavailable:
                        if self.quota.state == 'stopped':
                            return
                        raise
                self.recovery_requested.clear()
                if not self.account_subscribed:
                    self.recovery_state = "awaiting_account_stream"
                    break
                self.recovery_state = "recovering"
                self.recovery_attempts += 1
                self.diagnostics.emit('recovery_started', attempt=attempt+1, generation=self.account.generation)
                try:
                    # Bounds the whole pass; individual account proofs retain 5s.
                    async with asyncio.timeout(20):
                        repaired = await self.recover_once()
                except QuotaUnavailable:
                    self.recovery_attempts -= 1
                    self.recovery_state = 'awaiting_quota'
                    if self.quota is not None:
                        try:
                            await self.quota.wait_available()
                        except QuotaUnavailable:
                            if self.quota.state == 'stopped':
                                return
                            raise
                    continue
                except (InvalidData, TimeoutError, OSError) as exc:
                    self.diagnostics.emit('recovery_failed', error=exc, attempt=attempt+1,
                                          generation=self.account.generation)
                    repaired = False
                if self.writer.failed or self.engine.failed:
                    self.recovery_state = "durable_or_engine_failure"
                    self._revoke()
                    return
                if repaired and not self.recovery_requested.is_set():
                    self.recovery_state = "repaired_entries_blocked"
                    for ticker in self.engine.market_shard:
                        self.engine.dirty.mark(ticker)
                    self.engine.wake.set()
                    self.diagnostics.emit('recovery_repaired', generation=self.account.generation)
                    break
                if self._epoch_ambiguous:
                    if self.recovery_requested.is_set() and attempt+1 < self.attempt_limit:
                        # The event may have overtaken an already running REST
                        # pass. Allow one bounded post-event scoped attempt.
                        attempt += 1
                        continue
                    self.recovery_state = 'blocked_scope_ambiguous'
                    self.recovery_requested.clear()
                    break
                self.diagnostics.emit('recovery_incomplete', attempt=attempt+1, generation=self.account.generation)
                if attempt+1 == self.attempt_limit:
                    self.recovery_state = "blocked_retry_exhausted"
                    self.recovery_requested.clear()
                    self._revoke()
                    self.diagnostics.emit('recovery_exhausted', attempt=self.attempt_limit)
                    break
                await self.sleep(min(30, 2**attempt)*self.jitter())
                attempt += 1

    def stop(self):
        if self.live_session is not None:
            self.live_session.close()
        if self.admission is not None:
            self.admission.stop()
        if self.incentives is not None:
            self.incentives.stop()
        if self.dispatch_supervisor is not None:
            self.dispatch_supervisor.stop()
        if self.quota_supervisor is not None:
            self.quota_supervisor.stop()
        if self.rewards is not None:
            self.rewards.stop()
        self.stop_requested.set()
        self.engine.stop()
        self.account_subscribed = False
        self.account.disconnect()
        if self.market_inputs is not None:
            self.metadata_scheduler.stop()
        self._revoke()

    async def _live_refresh(self):
        """Cash/account completeness has no full WS snapshot: refresh centrally.

        Reuse the single recovery worker/budget, only when the previous pass
        finished and its short-lived report is expiring. Never reset exhaustion.
        """
        while not self.stop_requested.is_set():
            if (self.account_subscribed and self.recovery_state == 'repaired_entries_blocked'
                    and not self.recovery_requested.is_set()
                    and (self.dispatch_supervisor is None
                         or self.dispatch_supervisor.dispatcher.status().active is None)):
                # Preparation itself advances the writer revision, temporarily
                # hiding current_report while its dedicated send lease is valid.
                # Do not mistake that for an expired source and revoke the
                # in-flight command. Actual ingress still revokes immediately;
                # every outcome already requests authoritative recovery.
                report = self.account.current_report(self.now())
                if report is None or (utc(self.now())-report.observed_at).total_seconds() >= 3:
                    self.request_recovery()
            try:
                await asyncio.wait_for(self.stop_requested.wait(), .5)
            except TimeoutError:
                pass

    async def _shutdown(self, tasks):
        """One retained cleanup owner; child failures cannot disappear in gather."""
        failures = []
        try:
            self.stop()
            if self.dispatch_supervisor is not None:
                try:
                    await self.dispatch_supervisor.close()
                except BaseException as exc:
                    failures.append(exc)
            if self.incentives is not None:
                try:
                    await self.incentives.close()
                except BaseException as exc:
                    failures.append(exc)
            if self.rewards is not None:
                try:
                    await self.rewards.close()
                except BaseException as exc:
                    failures.append(exc)
            for task in tasks:
                task.cancel()
            results = await asyncio.gather(*tasks, return_exceptions=True)
            failures.extend(result for result in results
                if isinstance(result, BaseException)
                and not isinstance(result, asyncio.CancelledError))
            if self.metadata_scheduler is not None:
                try:
                    await self.metadata_scheduler.close()
                except BaseException as exc:
                    failures.append(exc)
            if self.quota_supervisor is not None:
                try:
                    await self.quota_supervisor.close()
                except BaseException as exc:
                    failures.append(exc)
            if failures:
                self.diagnostics.emit('runtime_failed', error=failures[0])
                raise InvalidData('runtime cleanup failed; reconciliation required') from None
        finally:
            self.running = False
            self.diagnostics.emit('runtime_stopped')

    async def run(self):
        if self.used:
            raise InvalidData("runtime cannot be reused")
        self.used, self.running = True, True
        tasks = []
        dispatch_task = None
        incentive_task = None
        admission_task = None
        reward_task = None
        primary_error = None
        try:
            await self._load_continuity_history()
            if self.rewards is not None:
                await self.rewards.start()
            self.diagnostics.ensure_healthy()
            self.diagnostics.emit('runtime_started')
            tasks = [asyncio.create_task(self.engine.run(), name='kalshi-engine'),
                     asyncio.create_task(self._recover(), name='kalshi-recovery'),
                     asyncio.create_task(self._diagnostic_health(), name='kalshi-log-health')]
            if self.live_session is not None or self.observation_only:
                tasks.append(asyncio.create_task(self._live_refresh(), name='kalshi-account-refresh'))
            if self.metadata_scheduler is not None:
                tasks.append(asyncio.create_task(self.metadata_scheduler.run(), name='kalshi-metadata'))
            if self.incentives is not None:
                incentive_task = asyncio.create_task(self.incentives.run(), name='kalshi-incentives')
                tasks.append(incentive_task)
            if self.admission is not None:
                admission_task = asyncio.create_task(self.admission.run(),name='kalshi-admission')
                tasks.append(admission_task)
            if self.rewards is not None and self.rewards.service_required:
                reward_task = asyncio.create_task(self.rewards.run(),name='kalshi-rewards')
                tasks.append(reward_task)
            if self.quota_supervisor is not None:
                tasks.append(asyncio.create_task(self.quota_supervisor.run(), name='kalshi-quota'))
            if self.dispatch_supervisor is not None:
                dispatch_task = asyncio.create_task(self.dispatch_supervisor.run(), name='kalshi-dispatch')
                tasks.append(dispatch_task)
            tasks.extend(asyncio.create_task(self.admission.book_loop(spec)
                if self.admission is not None and spec.name in self.engine.shards
                else self._connection(spec)) for spec in self.specs)
            stop = asyncio.create_task(self.stop_requested.wait())
            tasks.append(stop)
            # Reader exhaustion returns normally; engine/recovery faults stop peers.
            while not stop.done():
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    if task is not stop:
                        tasks.remove(task)
                        # Once observed here, its result belongs to the main run
                        # path. Remove it before propagating so retained cleanup
                        # does not count and mask the same failure a second time.
                        task.result()
                        if task is dispatch_task and not self.stop_requested.is_set():
                            raise InvalidData('dispatch service ended without runtime stop')
                        if task is incentive_task and not self.stop_requested.is_set():
                            raise InvalidData('incentive service ended without runtime stop')
                        if task is admission_task and not self.stop_requested.is_set():
                            raise InvalidData('admission service ended without runtime stop')
                        if task is reward_task and not self.stop_requested.is_set():
                            raise InvalidData('reward service ended without runtime stop')
                    if task is stop or self.engine.failed or self.writer.failed:
                        self.stop_requested.set()
                if self.stop_requested.is_set():
                    break
        except asyncio.CancelledError:
            self._run_cancelled = True
            self.diagnostics.emit('runtime_cancelled')
            raise
        except Exception as exc:
            primary_error = exc
            self.diagnostics.emit('runtime_failed', error=exc)
            raise
        finally:
            # Fence submission before scheduling the asynchronous cleanup task.
            if self.dispatch_supervisor is not None:
                self.dispatch_supervisor.stop()
            if self._shutdown_task is None:
                self._shutdown_task = asyncio.create_task(
                    self._shutdown(tuple(tasks)), name='kalshi-runtime-shutdown')
            cancelled_during_cleanup = False
            while not self._shutdown_task.done():
                try:
                    await asyncio.wait((self._shutdown_task,))
                except asyncio.CancelledError:
                    # Caller cancellation must not abandon readers, durable fill
                    # retention or marker finalization. Publish cancellation only
                    # after the retained cleanup owner has finished.
                    self._run_cancelled = True
                    cancelled_during_cleanup = True
                except BaseException:
                    if primary_error is None:
                        raise
                    break
            try:
                self._shutdown_task.result()
            except BaseException:
                if primary_error is None:
                    raise
            if cancelled_during_cleanup:
                raise asyncio.CancelledError

    async def _diagnostic_health(self):
        while not self.stop_requested.is_set():
            self.diagnostics.ensure_healthy()
            # Logging failure cannot leave an idle runtime silently unobserved.
            await asyncio.sleep(.25)

    def status(self):
        return dict(live_ready=self.entry_allowed, entry_allowed=self.entry_allowed, running=self.running,
            recovery=self.recovery_state, recovery_attempts=self.recovery_attempts,
            completed_repair_passes=self.recovery_passes, readers=dict(self.reader_states),
            connection_attempts=dict(self.connection_attempts), engine=self.engine.status(),
            account_verification=self.verification_status(), logging=self.diagnostics.status(),
            read_budget=self.reads.budget.status() if hasattr(self.reads,'budget') else None,
            quota=self.quota_supervisor.status() if self.quota_supervisor is not None else dict(state='unmanaged'),
            dispatch=self.dispatch_supervisor.status() if self.dispatch_supervisor is not None else None,
            selection=self.selection.status() if self.selection is not None else None,
            incentives=self.incentives.status() if self.incentives is not None else None,
            rewards=self.rewards.status() if self.rewards is not None else None,
            admission=self.admission.status() if self.admission is not None else None,
            metadata=self.metadata_scheduler.status() if self.metadata_scheduler is not None else None)

    def verification_status(self):
        quota_available = self.quota is None or self.quota.poll()
        # poll() may synchronously revoke account/history evidence through its
        # listener. Capture all status fields only after that transition.
        continuity = self._refresh_continuity()
        report = self.account.current_report(self.now())
        history = self.last_reports[0] if self.last_reports else None
        blockers = list(report.blockers) if report else ["current_account_snapshot_missing"]
        if not quota_available:
            blockers.append('quota_unavailable')
        if (history is None or self.history_ingress_revision != self.ingress_revision
                or (history.generation, history.subaccount) !=
                (self.account.generation, self.account.subaccount)):
            blockers.append("current_history_pass_missing")
        elif history.missing_fill_keys:
            blockers.append("unbound_fills_not_imported")
        receipt = history.enumeration if history else None
        if receipt is not None and receipt.omitted_rows:
            blockers.append('previously_observed_fills_omitted')
        inspection = self.history_inspection
        return dict(local_snapshot_consistent=bool(report and report.audit.consistent),
            history_interval_us=([history.start_us, history.end_us] if history else None),
            history_cutoff_us=history.cutoff_us if history else None,
            history_enumeration=(dict(requested_interval_us=[receipt.start_us, receipt.end_us],
                eligible_end_us=receipt.eligible_end_us, rows=receipt.row_count,
                omitted_rows=receipt.omitted_rows, complete_account_proof=False) if receipt else None),
            durable_history_inspection=(dict(interval_us=[inspection.start_us, inspection.end_us],
                gap_count=len(inspection.gaps), receipt_count=len(inspection.receipt_ids),
                omission_receipts=inspection.omission_receipts, historical_only=True,
                complete_account_proof=False) if inspection else None),
            continuity=dict(local_evidence_consistent=continuity.local_evidence_consistent,
                venue_handoff_proven=False, stream_span_state=continuity.stream_span_state,
                stream_epoch_id=continuity.stream_epoch_id,
                persisted_gap_count=self._persisted_epoch_gaps,
                receipt_count=len(continuity.receipt_ids), gap_count=len(continuity.interval_gaps),
                blockers=continuity.blockers, ready_for_entry=False),
            blockers=list(dict.fromkeys(blockers)), live_ready=False)
