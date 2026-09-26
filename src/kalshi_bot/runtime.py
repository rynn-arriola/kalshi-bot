"""Recovery engine with opt-in injected dispatch; no live CLI or mutations.

Construction opens nothing. A caller explicitly supplies already configured
GET reads, single-use reader factories, UTC clock and history scope. The owner
must close the writer after run() returns so accepted writes finish draining.
"""
import asyncio
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import random
import time
from uuid import uuid4

from .account import AccountCoordinator, UnscopedPositionUpdate
from .adapters import parse_fill
from .books import BookConnection
from .continuity import PrivateEpoch, assess_continuity, starting_candidate
from .engine import EventEngine
from .config import BotConfig, active as active_config
from .management import InventoryManager
from .metadata_scheduler import MetadataScheduler
from .quota import QuotaUnavailable
from .rest import ReadFailure, ReadTransportUnavailable
from .observability import NO_LOG, RECOVERY_CAUSES
from .transport import WebSocketReaders, topology
from .values import InvalidData, integer, utc


@dataclass(frozen=True)
class _SteadyAccountScope:
    """Exact full-cap/flat snapshot allowed to suppress optional discovery work.

    This is scheduling evidence only.  It never substitutes for a current
    account report, accounting lease, selection proof or dispatch authority.
    """
    account_generation: int
    account_revision: int
    writer_epoch: str
    writer_revision: int
    ingress_revision: int
    window_end: datetime
    snapshot_signature: tuple
    tickers: frozenset[str]


@dataclass(frozen=True)
class _RoutineAccountProof:
    """Historical renewal anchor, never a current entry/accounting lease."""
    source: tuple
    snapshot_signature: tuple
    receipt_ids: tuple[str, ...]
    end_us: int
    window_end: datetime


def readonly_reader_factory(signer, *, connector=None):
    """Factory only; does not open sockets or load credentials."""
    def create(spec):
        kwargs = {} if connector is None else {"connector": connector}
        # Lifecycle has its separate D-090 bound. Broad public shards need room
        # for a complete snapshot burst; account and small-book bounds stay put.
        capacity, byte_capacity = ((8192, 16*1024*1024)
                                   if spec.name == "lifecycle"
                                   else (2048, 8*1024*1024)
                                   if spec.name.startswith('book-') and len(spec.tickers) > 128
                                   else (256, 2*1024*1024))
        return WebSocketReaders(signer, (spec,), capacity=capacity,
                                byte_capacity=byte_capacity, **kwargs)
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
                 reader_healthy_seconds=60,
                 diagnostics=NO_LOG, market_inputs=None, quota_supervisor=None,
                 accounting_boundary=None, observation_only=False, opening_reference=None,
                 broad_discovery=False, book_connections=2):
        if type(observation_only) is not bool:
            raise InvalidData('observation_only must be a boolean')
        self.observation_only = observation_only
        if type(broad_discovery) is not bool:
            raise InvalidData('broad_discovery must be a boolean')
        self.broad_discovery = broad_discovery
        self._entry_dirty = False
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
        if (not isinstance(reader_healthy_seconds, (int, float))
                or isinstance(reader_healthy_seconds, bool)
                or not 1 <= reader_healthy_seconds <= 3600):
            raise InvalidData('reader healthy reset must be 1..3600 seconds')
        self.reader_healthy_seconds = float(reader_healthy_seconds)
        self.specs = topology(tuple(tickers),
                              market_capacity=1024 if broad_discovery else writer.market_capacity,
                              book_connections=book_connections)
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
        self.reader_retry_rounds = {s.name: 0 for s in self.specs}
        self.recovery_state = "not_started"
        self.recovery_attempts = 0
        self.recovery_dispatch_waits = 0
        self.recovery_dispatch_wait_ms = 0
        self.recovery_retry_rounds = 0
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
        self._post_drain_recovery_pending = False
        self.recovery_action_progress = 0
        self._safety_recovery_retries = set()
        self._steady_account_scope = None
        self._routine_account_proof = None
        # D-134: the last released proof and the history floor it was bound
        # to. It survives only the bot's own acknowledged order updates.
        self._last_proof = None
        self._account_ingress_at = None
        self._own_renewal_retries = 0
        self.own_order_renewal = dict(attempts=0, completed=0, retries=0, escalations=0)
        self.chained_recoveries = 0
        self._chained_pass = False
        self.routine_refresh_attempts = 0
        self.routine_refresh_completed = 0
        self.routine_refresh_escalations = 0
        self.routine_refresh_phase = 'idle'
        self.routine_refresh_elapsed_ms = 0
        self.routine_refresh_phase_ms = {}
        self._recovery_reason = 'source_change'
        self.recovery_request_counts = {}
        self.recovery_attempt_counts = {}
        self.recovery_phase = 'idle'
        self.recovery_last_phase = 'idle'
        self.recovery_elapsed_ms = 0
        self.recovery_phase_ms = {}
        self.recovery_final_reaudits = 0
        self.steady_refresh_attempts = 0
        self.steady_refresh_completed = 0
        self.steady_refresh_escalations = 0
        self.suppressed_market_evaluations = 0
        self.unsent_rebases = 0
        self.history_scope = None
        self.history_scope_warnings = 0
        self.recovery_risk_drain_waits = 0
        self.selection = None  # Advisory only, attached before runtime start.
        self.incentives = None  # One shared-budget catalog; explicit offline opt-in.
        self.rewards = None  # Actual-order telemetry only; never financial authority.
        self.maintenance = None  # Opt-in same-market policy, never a writer.
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
            concurrency=4 if broad_discovery else 2,
            priority=self._metadata_priority,
            defer=lambda: bool(self.engine.private or self.account._processing))
            if market_inputs is not None else None)

    def _metadata_priority(self, ticker):
        """Owned safety first, then remembered priority, then discovery."""
        plan = self.management._plans.get(ticker)
        if ((plan is not None and (plan.inventory.position or plan.inventory.orders))
                or (self.maintenance is not None and ticker in self.maintenance.bindings)):
            return 2
        if (self.selection is not None
                and self.selection.priority_refresh_pending(ticker)):
            return 1
        return 0

    def _quota_transition(self):
        if self.dispatch_supervisor is not None:
            self.dispatch_supervisor.changed()
        available = self.quota.state == 'fresh'
        was_available, self._quota_available = self._quota_available, available
        if was_available and not available:
            self._revoke()
        elif available and not was_available and self.recovery_state != 'blocked_retry_exhausted':
            self.request_recovery('quota_restored')

    def _invalidate_market(self, ticker):
        self.management.invalidate(ticker)
        if self.selection is not None:
            self.selection.invalidate(ticker)
        if self.rewards is not None:
            self.rewards.invalidate(ticker)
        self.invalidate(ticker)

    def attach_selection(self, *, offline_fixture=False, initial_timeout=120):
        from .selection_runtime import RuntimeSelection
        if self.used or self.stop_requested.is_set() or self.selection is not None:
            raise InvalidData('selection requires unused runtime')
        self.selection = RuntimeSelection(self, offline_fixture=offline_fixture,
                                          initial_timeout=initial_timeout)
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
        if self.broad_discovery:
            raise InvalidData('broad discovery owns a fixed reviewed book scope')
        self.admission = MarketAdmission(self,offline_fixture=offline_fixture)
        return self.admission

    def attach_maintenance(self):
        from .quote_maintenance import QuoteMaintenance
        if self.used or self.maintenance is not None or self.rewards is None:
            raise InvalidData('maintenance requires unused selected reward runtime')
        self.maintenance = QuoteMaintenance(self)
        return self.maintenance

    def _request_quote_dispatch(self, ticker):
        if self.maintenance is None or self.dispatch_supervisor is None or self.stop_requested.is_set():
            return
        source = getattr(self.dispatch_supervisor, 'source', None)
        if source is not None and self.maintenance.risk_cycle_for(ticker) is not None:
            # D-131 item 7: every latched protective cycle drains through its
            # own record; book churn must not bypass its deferred-cancel backoff.
            source.request_risk_drain(ticker)
            return
        plan = self.management.current(ticker, require_market=False)
        if plan is not None and self.maintenance.cancel_target(plan) is not None:
            from .dispatch import QUOTE_CANCEL
            self.request_dispatch(ticker, QUOTE_CANCEL)

    def request_dispatch(self, ticker, priority):
        if self.dispatch_supervisor is None:
            raise InvalidData('offline dispatch not attached')
        return self.dispatch_supervisor.request(ticker, priority)

    def request_entry_drain(self):
        """Wake exact owned-entry cancellation without waiting for a plan.

        The account cache only supplies scheduling keys. The dispatcher still
        obtains current durable cancel evidence before preparing each command.
        """
        if not self.entry_pause_active or self.stop_requested.is_set():
            return
        owner = self.dispatch_supervisor
        if owner is None or owner.stopping:
            return
        from .dispatch import SAFETY_CANCEL
        tickers = {r.order.ticker for r in self.account.order_states.values()
                   if r.owned and not r.reducing and not r.order.terminal}
        for ticker in sorted(tickers):
            if ticker in self.engine.market_shard:
                owner.request(ticker, SAFETY_CANCEL)

    def entry_dispatch_active(self, ticker):
        owner = self.dispatch_supervisor
        from .dispatch import ENTRY_PAIR
        return owner is not None and owner.dispatcher.status().active == (ticker, ENTRY_PAIR)

    async def _evaluate(self, ticker, book, generation):
        # The entry source owns this ticker's advisory plan until its result.
        # Ingestion and deadlines still invalidate actual source changes.
        if self.entry_dispatch_active(ticker):
            return
        scope = self._current_steady_account_scope()
        if scope is not None and ticker not in scope:
            # At the exact resting-entry cap, existing rewarded owners are
            # retained rather than displaced for rank.  Continue applying every
            # WebSocket delta, but avoid rebuilding empty-market inventory and
            # ranking plans until a vacancy or conflicting account evidence
            # clears this scheduling hint.  Safety/authority consumers never use
            # this hint and all owned markets remain on the normal path.
            self.suppressed_market_evaluations += 1
            return
        await self.management.refresh(ticker, background=True)
        if self.entry_dispatch_active(ticker):
            return  # Dispatch may have started during the inventory read.
        self._request_inventory_dispatch(ticker)
        if self.selection is not None:
            self.selection.refresh(ticker)
            if self.dispatch_supervisor is not None:
                from .dispatch import ENTRY_PAIR
                if self.broad_discovery:
                    # Unrewarded evaluations also advance selection coverage.
                    self._entry_dirty = True
                elif self.selection.current(ticker):
                    self.dispatch_supervisor.request(ticker, ENTRY_PAIR)
        if self.rewards is not None:
            self.rewards.refresh(ticker)
        if self.maintenance is not None:
            self.maintenance.refresh(ticker)
            self._request_quote_dispatch(ticker)
        await self._evaluate_callback(ticker, book, generation)

    async def _deadline(self, ticker):
        plan = await self.management.refresh(ticker)
        if plan is not None and not plan.inventory.position:
            self._safety_recovery_retries.discard(ticker)
        if (self.recovery_state == 'blocked_retry_exhausted'
                and plan is not None and plan.inventory.position
                and ticker not in self._safety_recovery_retries):
            now = utc(self.now())
            age_due = (plan.inventory.first_seen_at is not None
                       and now-plan.inventory.first_seen_at >= timedelta(seconds=900))
            deadline_due = plan.terms is not None and now >= plan.terms.deadline
            if age_due or deadline_due:
                # One inventory-episode retry at the existing safety boundary.
                # It reacquires current account proof before any IOC; it never
                # dispatches from the stale plan that triggered this wake-up.
                self._safety_recovery_retries.add(ticker)
                self.request_recovery()
                self.diagnostics.emit('safety_recovery_rearmed', market=ticker)
                await self._deadline_callback(ticker)
                return
        self._request_inventory_dispatch(ticker)
        if self.selection is not None:
            self.selection.refresh(ticker)
        if self.rewards is not None:
            self.rewards.refresh(ticker)
        if self.maintenance is not None:
            self.maintenance.refresh(ticker)
            self._request_quote_dispatch(ticker)
        await self._deadline_callback(ticker)

    async def _ranked_entry_turn(self):
        """One advisory key per turn, never one entry request per public tick.

        The ordinary dispatch source still reproposes/revalidates before every
        reservation. Inventory priorities remain on their existing immediate path.
        """
        if (self.selection is None or not self._entry_dirty
                or self.dispatch_supervisor is None or not self.entry_allowed):
            return
        state = self.dispatch_supervisor.dispatcher.status()
        if state.active is not None or state.queued or state.stopping or state.failed:
            return  # Never compete with pending cancellation/inventory work.
        release = self.accounting_result
        report = self.account.current_report(self.now())
        if release is None or not release.released or release.window is None or report is None:
            return
        self._entry_dirty = False
        proposal = await self.selection.propose(window=release.window,
            free_cash=report.snapshot.available_balance)
        if (proposal.blockers or not proposal.additions or not self.entry_allowed
                or self.accounting_result is not release
                or self.account.current_report(self.now()) is not report):
            return
        ticker = proposal.additions[0].ticker
        state = self.dispatch_supervisor.dispatcher.status()
        if state.active is not None or state.queued or state.stopping or state.failed:
            self._entry_dirty = True
            return
        if self.selection.current(ticker):
            from .dispatch import ENTRY_PAIR
            self.dispatch_supervisor.request(ticker, ENTRY_PAIR)

    async def _ranked_entries(self):
        while not self.stop_requested.is_set():
            await asyncio.sleep(.25)
            await self._ranked_entry_turn()

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
        elif ((overflow := self.entry_overflow_ids())
              and overflow.intersection(r.order.order_id for r in plan.inventory.orders)):
            self.request_dispatch(ticker, SAFETY_CANCEL)
        elif (plan.exit.mode in {'flat', 'passive', 'passive_deferred', 'cancel_before_ioc'}
                and plan.passive.cancel_ids):
            self.request_dispatch(ticker, SAFETY_CANCEL)
        elif plan.exit.mode == 'ioc':
            self.request_dispatch(ticker, DUE_IOC)
        elif plan.exit.mode in {'passive', 'passive_deferred'}:
            self.request_dispatch(ticker, PASSIVE_REDUCER)

    def current_entry_orders(self):
        """Bounded exact account/order join; no new read or guessed reducer flag."""
        report = self.account.current_report(self.now())
        if report is None or not report.positions_match or report.audit.blockers:
            return None
        rows = []
        for row in report.snapshot.orders:
            receipt = self.account.order_states.get(row.order_id)
            if receipt is None or not receipt.owned:
                return None
            own = receipt.order
            if (own.client_id, own.ticker, own.side, own.yes_price, own.remaining,
                own.exchange_index, own.terminal) != (row.client_id, row.ticker,
                row.book_side, row.yes_price, row.remaining, row.exchange_index, False):
                return None
            if not receipt.reducing:
                rows.append(row)
        return tuple(rows)

    def entry_overflow_ids(self):
        """Honor the existing ratcheted ceiling on resting entries, pairs first.

        Position markets remain with inventory management. Stable admission order
        breaks ties; this never imports Poly's risk numbers or reward estimates.
        """
        window = getattr(self.accounting_result, 'window', None)
        now = utc(self.now())
        if (window is None or not window.start <= now < window.end
                or not timedelta(0) <= now-window.observed_at <= timedelta(seconds=5)):
            return frozenset()
        rows = self.current_entry_orders()
        if rows is None or len(rows) <= window.cap:
            return frozenset()
        report = self.account.current_report(now)
        positioned = {p.ticker for p in report.snapshot.positions if p.quantity}
        kept = {o.order_id for o in rows if o.ticker in positioned}
        remaining = max(0, window.cap-len(kept))
        ranks = ({t:i for i,t in enumerate(self.maintenance.bindings)}
                 if self.maintenance is not None else {})
        ordered = sorted((o for o in rows if o.ticker not in positioned),
                         key=lambda o: (ranks.get(o.ticker, 1024), o.ticker, o.book_side, o.order_id))
        groups = {}
        for row in ordered:
            groups.setdefault(row.ticker, []).append(row)
        for group in groups.values():
            pair = [next((o for o in group if o.book_side == side), None) for side in ('bid','ask')]
            if remaining >= 2 and all(pair):
                kept.update(o.order_id for o in pair)
                remaining -= 2
        for row in ordered:
            if remaining and row.order_id not in kept:
                kept.add(row.order_id)
                remaining -= 1
        return frozenset(o.order_id for o in ordered if o.order_id not in kept)

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
            config=active_config(), now=self.now(),
            free_cash=report.snapshot.available_balance if report else 0,
            account_known=False, offline_fixture=False)

    @property
    def entry_pause_active(self):
        """Operator/recovery pause or durable hard loss hold; never a cap reset."""
        window = getattr(self.accounting_result, 'window', None)
        return bool((self.live_session is not None and self.live_session.entries_paused)
                    or (window is not None and window.held)
                    or self.__dict__.get('_recovery_safety_pause', False))

    # D-141: a runtime that cannot prove its account also cannot protect resting
    # entries (fill-risk reflection needs a current account). Pull them until a
    # full recovery succeeds, and retry that recovery on a slow bounded cadence
    # instead of waiting for an operator.
    SAFETY_PAUSE_STATES = frozenset(('blocked_retry_exhausted', 'blocked_scope_ambiguous',
                                     'durable_or_engine_failure'))
    # Quick first, then bounded: most causes clear in minutes (funding status,
    # venue lag); a persistent one costs one read-only pass every 5 minutes.
    EXHAUSTED_RETRY_SECONDS = (30, 60, 120, 300)

    @property
    def recovery_state(self):
        return self.__dict__.get('_recovery_state')

    @recovery_state.setter
    def recovery_state(self, state):
        self._recovery_state = state
        if state in self.SAFETY_PAUSE_STATES:
            self._recovery_blocked_at = self.clock()
            if not self.__dict__.get('_recovery_safety_pause', False):
                self._recovery_safety_pause = True
                self.recovery_safety_pauses = self.__dict__.get('recovery_safety_pauses', 0)+1
                diagnostics = self.__dict__.get('diagnostics')
                if diagnostics is not None:
                    diagnostics.emit('recovery_safety_pause', count=self.recovery_safety_pauses)
                # The live refresh owner drains within half a second (_safety_tick).
        elif state == 'repaired_entries_blocked':
            self._recovery_safety_pause = False
            self._exhausted_retries = 0

    async def _resolve_unknown_creates(self, reads):
        """D-143: an UNKNOWN create older than ten minutes is either found in
        Kalshi's complete live (all statuses) or archived order list for its
        market and bound, or recorded as never created (REJECTED)."""
        from hashlib import sha256
        import json as _json
        from .execution import UNKNOWN_ABSENCE_SECONDS
        from .orders import parse_order
        from .recovery import fetch_archived_orders
        now = utc(self.now())
        stale = [row for row in await self.writer.unknown_creates()
                 if (now-utc(datetime.fromisoformat(row[3]))).total_seconds()
                    >= UNKNOWN_ABSENCE_SECONDS]
        if not stale:
            return False
        changed = False
        subaccount = self.account.subaccount
        for ticker in sorted({row[2] for row in stale}):
            rows = [row for row in stale if row[2] == ticker]
            earliest = min(utc(datetime.fromisoformat(row[3])) for row in rows)
            live = await reads.collect('orders', reason='reconcile', ticker=ticker,
                subaccount=subaccount, min_ts=max(0, int(earliest.timestamp())-60),
                max_rows=4096)
            archived = await fetch_archived_orders(reads, subaccount=subaccount, ticker=ticker)
            found = {row.get('client_order_id'): row for row in live.rows}
            archived_ids = {order.client_id for order in archived.orders}
            evidence = sha256(_json.dumps(dict(ticker=ticker, observed=now.isoformat(),
                live_rows=len(live.rows), live_pages=live.pages, live_exhausted=live.exhausted,
                archived=len(archived.orders), policy='D-143'),
                sort_keys=True).encode()).hexdigest()
            for attempt_id, client, _, _ in rows:
                if client in found:
                    await self.writer.order_batch((parse_order(found[client], scope=subaccount),), now)
                    changed = True
                elif client in archived_ids:
                    continue  # The archive path binds it through ordinary recovery.
                elif live.exhausted and await self.writer.resolve_unknown_create_absent(
                        attempt_id, evidence_digest=evidence, now=now):
                    self.unknown_creates_resolved = self.__dict__.get('unknown_creates_resolved', 0)+1
                    self.diagnostics.emit('unknown_create_resolved', count=self.unknown_creates_resolved)
                    changed = True
        return changed

    EXCHANGE_STATUS_SECONDS = 30

    async def _exchange_status(self):
        """D-144: follow Kalshi maintenance and trading pauses.

        While Kalshi is not active, no new entry is placed; resting entries are
        cancelled by Kalshi itself (every entry sets cancel_order_on_pause) and
        cancels may be unavailable, so none are sent. On resume a full
        recovery re-proves the account before trading continues. A failed
        status read changes nothing: account proofs keep their own rules.
        """
        while not self.stop_requested.is_set():
            try:
                result = await self.reads.read('exchange_status', reason='metadata')
                payload = result.payload
                exchange, trading = payload.get('exchange_active'), payload.get('trading_active')
                if type(exchange) is bool and type(trading) is bool:
                    self._apply_exchange_status(exchange and trading)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.exchange_status_failures = self.__dict__.get('exchange_status_failures', 0)+1
            try:
                await asyncio.wait_for(self.stop_requested.wait(), self.EXCHANGE_STATUS_SECONDS)
            except TimeoutError:
                pass

    def _apply_exchange_status(self, active):
        paused = self.__dict__.get('_venue_paused', False)
        if not active and not paused:
            self._venue_paused = True
            self.venue_pauses = self.__dict__.get('venue_pauses', 0)+1
            self.diagnostics.emit('venue_paused', count=self.venue_pauses)
        elif active and paused:
            self._venue_paused = False
            self.diagnostics.emit('venue_resumed', count=self.venue_pauses)
            if not self.stop_requested.is_set():
                self.request_recovery('venue_resumed')

    def _safety_tick(self):
        """D-141: pull entries while unsafe; retry recovery on its schedule."""
        self._retry_exhausted_recovery()
        if self.__dict__.get('_recovery_safety_pause', False):
            self.request_entry_drain()  # Idempotent: exact owned entries only.

    def _retry_exhausted_recovery(self):
        """D-141: re-attempt full recovery on 30 s, 1, 2, then every 5 minutes."""
        retries = self.__dict__.get('_exhausted_retries', 0)
        wait = self.EXHAUSTED_RETRY_SECONDS[min(retries, len(self.EXHAUSTED_RETRY_SECONDS)-1)]
        if (self.recovery_state == 'blocked_retry_exhausted' and self.account_subscribed
                and not self.recovery_requested.is_set() and not self.writer.failed
                and not self.stop_requested.is_set()
                and self.clock()-self.__dict__.get('_recovery_blocked_at', self.clock()) >= wait):
            self._recovery_blocked_at = self.clock()
            self._exhausted_retries = retries+1
            self.request_recovery('exhausted_retry')
            return True
        return False

    @property
    def accounting_result(self):
        return self.__dict__.get('_accounting_result')

    @accounting_result.setter
    def accounting_result(self, result):
        self._accounting_result = result
        # D-141: every external cash movement the release accepted is visible.
        for item in getattr(result, 'cash_adjustments', ()) or ():
            counts = self.__dict__.setdefault('cash_adjustment_counts', {})
            counts[item.kind] = counts.get(item.kind, 0)+1
            diagnostics = self.__dict__.get('diagnostics')
            if diagnostics is not None:
                diagnostics.emit('cash_adjusted', cash_kind=item.kind,
                                 amount_cents=int(item.amount*100))

    @property
    def entry_allowed(self):
        from .live_session import permits
        lease = self.writer._accounting_lease
        return (permits(self.live_session, self.writer)
                and not self.entry_pause_active
                and not self.__dict__.get('_venue_paused', False)
                and self.accounting_result is not None and self.accounting_result.released
                and lease is not None and lease.fence.current()
                and not self.stop_requested.is_set())

    @property
    def live_components_enabled(self):
        from .live_session import permits
        return permits(self.live_session, self.writer)

    @property
    def recovery_phase(self):
        return self.__dict__.get('_recovery_phase', 'idle')

    @recovery_phase.setter
    def recovery_phase(self, phase):
        # Diagnostic wall time per phase of the latest full pass; never proof.
        clock = self.__dict__.get('clock')
        now = clock() if clock is not None else None
        previous = self.__dict__.get('_recovery_phase', 'idle')
        since = self.__dict__.get('_recovery_phase_since')
        live = self.__dict__.setdefault('_recovery_phase_live', {})
        if previous != 'idle' and since is not None and now is not None:
            live[previous] = live.get(previous, 0)+max(0, int((now-since)*1000))
        if phase == 'idle':
            if previous != 'idle':
                self.recovery_phase_ms = dict(live)
            live.clear()
        self._recovery_phase, self._recovery_phase_since = phase, now

    def request_recovery(self, reason='source_change'):
        self._steady_account_scope = None
        self._routine_account_proof = None
        reason = reason if type(reason) is str and reason in RECOVERY_CAUSES else 'unknown'
        self._recovery_reason = reason
        self.recovery_request_counts[reason] = self.recovery_request_counts.get(reason, 0)+1
        self.last_reports = None
        self._refresh_continuity()
        self.recovery_requested.set()  # Coalesced, never a task per market/event.

    def _request_post_drain_recovery(self):
        """One bounded reconciliation after new durable stop/risk-cancel outcomes.

        A recovery pass may exhaust while the rapid cancel queue is changing
        its snapshot. Once that queue drains, these new outcomes justify one
        new pass, not an unlimited retry or a claim that the account is flat.
        """
        if (not self._post_drain_recovery_pending
                or self.stop_requested.is_set() or self.writer.failed or self.engine.failed
                or self.recovery_lock.locked() or self.recovery_state == 'recovering'):
            return False
        owner = self.dispatch_supervisor
        if owner is None:
            return False
        if getattr(getattr(owner, 'source', None), 'risk_drain_pending', False):
            return False  # A temporarily blocked, popped key is not a drain.
        state = owner.dispatcher.status()
        if state.active is not None or state.queued or state.failed or state.stopping:
            return False
        self._post_drain_recovery_pending = False
        self.request_recovery('post_drain')
        return True

    async def rebase_after_unsent(self):
        """D-130: keep scheduling evidence across a proven-unsent command.

        Returns True when the current report and/or routine renewal anchor
        were re-bound to the new writer revision, or recovery already owns the
        gap. False means the caller must use the ordinary full recovery. This
        never extends a lease, restores accounting authority or imports venue
        evidence; routine renewal still re-reads the complete account.
        """
        if self.stop_requested.is_set() or self.writer.failed or self.engine.failed:
            return True
        if self.recovery_requested.is_set() or self.recovery_lock.locked():
            return True
        proof, ingress = self._routine_account_proof, self.ingress_revision
        report = self.account.report
        rebased = None
        if report is not None:
            try:
                rebased = await self.account.rebase_unsent(report, now=self.now())
            except InvalidData:
                rebased = None
        if self.ingress_revision != ingress or self.recovery_requested.is_set():
            return self.recovery_requested.is_set()
        source = self._routine_source()
        anchored = (proof is not None and self._routine_account_proof is proof
                    and proof.source[:3]+proof.source[4:] == source[:3]+source[4:])
        if anchored:
            self._routine_account_proof = replace(proof, source=source)
        if rebased is not None:
            self._record_steady_account_scope(rebased)
            self.unsent_rebases += 1
            self._entry_dirty = True  # One fresh ranked turn; never a hot loop.
            if self.rewards is not None:
                # Reward joins bind the exact report object; rejoin now, as
                # routine renewal does, instead of waiting for the timer.
                self.rewards.request_reflection()
        self.diagnostics.emit('account_rebased_unsent',
            outcome='recovered' if (rebased is not None or anchored) else 'source_changed')
        return rebased is not None or anchored

    # D-131: full recovery re-proves fills from the opening boundary inside a
    # 5 s evidence token, and history staging is capped at 10,000 fills. Warn
    # long before either limit; moving the boundary is an operator decision.
    HISTORY_WARN_ROWS = 5000
    HISTORY_WARN_MS = 2500

    def _observe_history_scope(self, history, elapsed):
        rows = history.seen
        elapsed_ms = max(0, int(elapsed*1000))
        self.history_scope = dict(rows=rows, row_limit=10000, elapsed_ms=elapsed_ms,
                                  token_ms=5000, pages=history.enumeration.pages
                                  if history.enumeration is not None else None)
        if rows >= self.HISTORY_WARN_ROWS or elapsed_ms >= self.HISTORY_WARN_MS:
            self.history_scope_warnings += 1
            count = self.history_scope_warnings
            if count & (count-1) == 0:
                self.diagnostics.emit('history_scope_high', count=rows,
                                      elapsed_ms=elapsed_ms)

    def _revoke(self, economic=True):
        self._steady_account_scope = None
        self._routine_account_proof = None
        self.ingress_revision += 1
        self.last_reports = None
        self.account._invalidate(economic=economic)
        for ticker in self.engine.market_shard:
            self._invalidate_market(ticker)
        self._refresh_continuity()

    @staticmethod
    def _snapshot_signature(report):
        snapshot = report.snapshot
        return (snapshot.positions, snapshot.orders, snapshot.available_balance,
                snapshot.subaccount)

    def _routine_source(self):
        return (self.account.generation, self.account.revision, self.writer.epoch,
                self.writer.revision, self.ingress_revision,
                self._epoch.epoch_id if self._epoch is not None else None)

    def _record_routine_proof(self, receipt_ids, history):
        self._routine_account_proof = None
        report = self.account.current_report(self.now())
        result = self.accounting_result
        lease = self.writer._accounting_lease
        if (report is None or result is None or not result.released
                or result.window is None or result.window.held
                or lease is None or not lease.fence.current()
                or self.recovery_requested.is_set() or self.stop_requested.is_set()
                or history is None or history.enumeration is None
                or history.enumeration.omitted_rows or not receipt_ids
                or len(receipt_ids) >= 128):
            return
        self._routine_account_proof = _RoutineAccountProof(self._routine_source(),
            self._snapshot_signature(report), tuple(receipt_ids),
            history.enumeration.eligible_end_us, result.window.end)
        self._last_proof = (self._routine_account_proof, self.account.history_floor)

    # D-134: bound the carried receipt chain well below the 128-receipt proof
    # cap; beyond it, full recovery re-proves from the opening boundary.
    CHAIN_RECEIPT_LIMIT = 100
    # Let the venue's own order updates for an acknowledged command arrive
    # before renewing, instead of racing them.
    OWN_ORDER_SETTLE_SECONDS = .3
    OWN_ORDER_RETRIES = 3

    def _chain_anchor(self):
        """D-134: the last released proof, while nothing economic happened since.

        Valid only in the same account connection, writer epoch and private
        stream epoch, with an unchanged history floor. Fills, positions,
        foreign or unsettled orders, reconnects and every other invalidation
        move the floor and end reuse.
        """
        last = self._last_proof
        if last is None:
            return None
        proof, floor = last
        source = self._routine_source()
        if (floor != self.account.history_floor or self._epoch_ambiguous
                or (proof.source[0], proof.source[2], proof.source[5]) !=
                   (source[0], source[2], source[5])
                or len(proof.receipt_ids) >= self.CHAIN_RECEIPT_LIMIT):
            return None
        return proof

    def _current_own_order_anchor(self):
        proof = self._chain_anchor()
        owner = self.dispatch_supervisor
        state = owner.dispatcher.status() if owner is not None else None
        if (proof is None or self._routine_account_proof is not None
                or utc(self.now()) >= proof.window_end
                or not self.account_subscribed or not self.account.connected
                or self.engine.private or self.account._processing
                or self.writer.failed or self.engine.failed or self.engine.stopped
                or self.stop_requested.is_set() or self.recovery_requested.is_set()
                or (state is not None and (state.active is not None or state.queued
                    or state.stopping or state.failed))):
            return None
        return proof

    def own_order_acknowledged(self):
        """An acknowledged own command: renew instead of full recovery if possible."""
        self._account_ingress_at = self.clock()
        return (self._chain_anchor() is not None and not self.recovery_requested.is_set()
                and not self.recovery_lock.locked())

    # D-136: the only audit blockers a just-acknowledged own order can cause
    # before the venue's REST enumeration lists it. Bounded retry, then full
    # recovery; every other blocker is evidence and escalates at once.
    OWN_ORDER_PENDING_BLOCKERS = frozenset(('owned_working_order_missing',
                                            'unbound_order_intents'))

    def _own_order_unexplained(self, report, proof):
        """None when only the bot's own working orders (and cash with them) changed."""
        signature = self._snapshot_signature(report)
        positions, orders, balance, subaccount = proof.snapshot_signature
        audit = report.audit
        if signature[0] != positions or signature[3] != subaccount:
            return 'position_changed'
        if signature[2] != balance and signature[1] == orders:
            return 'cash_changed'
        if not report.positions_match:
            return 'position_mismatch'
        if audit is None:
            return 'audit_blocked'
        if audit.consistent:
            return None
        if set(audit.blockers) <= self.OWN_ORDER_PENDING_BLOCKERS:
            return 'order_not_visible'
        return 'audit_blocked'

    def _snapshot_explained(self, report, proof, *, own_orders):
        if not own_orders:
            return self._snapshot_signature(report) == proof.snapshot_signature
        return self._own_order_unexplained(report, proof) is None

    def _current_routine_proof(self):
        proof = self._routine_account_proof
        owner = self.dispatch_supervisor
        state = owner.dispatcher.status() if owner is not None else None
        if (proof is None or proof.source != self._routine_source()
                or utc(self.now()) >= proof.window_end
                or not self.account_subscribed or not self.account.connected
                or self.engine.private or self.account._processing or self._epoch_ambiguous
                or self.writer.failed or self.engine.failed or self.engine.stopped
                or self.stop_requested.is_set() or self.recovery_requested.is_set()
                or (state is not None and (state.active is not None or state.queued
                    or state.stopping or state.failed))):
            return None
        return proof

    async def _refresh_routine_account(self, anchor=None):
        """Renew through existing release checks; never replay full startup work.

        A bounded receipt chain preserves the complete original interval. Every
        tail is empty, omission-free and checked by the writer at release.
        Fresh cash/funding/settlement enumeration remains mandatory: unchanged
        balance alone cannot establish unchanged economics.

        D-134: with ``anchor`` (the last released proof, still valid under the
        history floor) the same renewal runs after the bot's own acknowledged
        orders: positions must be unchanged, only working orders (and cash
        with them) may differ, the writer audit must be consistent and the
        elapsed history tail must be empty.
        """
        own = anchor is not None
        proof = anchor if own else self._current_routine_proof()
        if proof is None or self.recovery_lock.locked():
            return False
        start_source = self._routine_source()
        writer_source = (start_source[2], start_source[3]) if own else (proof.source[2], proof.source[3])
        started = self.clock()
        self.routine_refresh_phase_ms = {}
        if own:
            self.own_order_renewal['attempts'] += 1
        else:
            self.routine_refresh_attempts += 1
        succeeded = False
        failure = None
        released = None
        unexplained = False
        async with self.recovery_lock:
            try:
                async with asyncio.timeout(20):
                    self.routine_refresh_phase = 'snapshot_and_tail'
                    end = utc(self.now())
                    start = datetime.fromtimestamp(proof.end_us//1_000_000,
                        tz=timezone.utc).replace(microsecond=proof.end_us%1_000_000)
                    if end <= start:
                        return False
                    reads = RecoveryReads(self.reads)
                    # Join both requests even if one fails; no orphaned read
                    # may race the fallback recovery owner.
                    history, reconciled = await asyncio.gather(
                        self.account.extend_empty_history(reads, start=start, end=end, now=self.now),
                        self.account.reconcile(reads, now=self.now,
                            expected_writer_source=writer_source,
                            prepare_accounting_boundary=self.accounting_boundary),
                        return_exceptions=True)
                    self.routine_refresh_phase_ms['snapshot_and_tail'] = max(
                        0, int((self.clock()-started)*1000))
                    for value in (history, reconciled):
                        if isinstance(value, BaseException):
                            raise value
                    if reconciled is None:
                        return False
                    report, prepared = reconciled
                    expected = start_source if own else proof.source
                    unexplained = (report is not None and self.account.current_report(self.now()) is report
                                   and not self._snapshot_explained(report, proof, own_orders=own))
                    if unexplained and own:
                        unexplained = self._own_order_unexplained(report, proof)
                    if (history is None or report is None
                            or history.enumeration.omitted_rows
                            or (self._chain_anchor() if own else self._routine_account_proof) is not proof
                            or self.recovery_requested.is_set()
                            or self._routine_source()[:3]+self._routine_source()[4:] !=
                               expected[:3]+expected[4:]
                            or self.account.current_report(self.now()) is not report
                            or not self._snapshot_explained(report, proof, own_orders=own)):
                        return False
                    self.last_reports = (history, report)
                    self.history_ingress_revision = self.ingress_revision
                    ids = proof.receipt_ids+(history.enumeration.receipt_id,)
                    continuity = replace(self._refresh_continuity(operational=True), receipt_ids=ids)
                    self.routine_refresh_phase = 'accounting_release'
                    release_started = self.clock()
                    self.accounting_result = await self.account.release_prepared_accounting(
                        prepared, continuity=continuity, now=self.now)
                    released = self.accounting_result.released
                    self.routine_refresh_phase_ms['accounting_release'] = max(
                        0, int((self.clock()-release_started)*1000))
                    # Release advances writer revision itself. The account owner
                    # supplies its new audit; never rebase an earlier snapshot.
                    if (not self.accounting_result.released
                            or self.recovery_requested.is_set()
                            or self.account.current_report(self.now()) is None
                            or self.writer._accounting_lease is None
                            or not self.writer._accounting_lease.fence.current()):
                        return False
                    self._record_routine_proof(ids, history)
                    report = self.account.current_report(self.now())
                    scope = self._record_steady_account_scope(report)
                    self._schedule_account_refresh(scope)
                    if self.rewards is not None:
                        self.rewards.request_reflection()
                    if own:
                        self.own_order_renewal['completed'] += 1
                        self._own_renewal_retries = 0
                    else:
                        self.routine_refresh_completed += 1
                    succeeded = True
                    return True
            except (InvalidData, QuotaUnavailable, TimeoutError, OSError) as exc:
                failure = exc
                return False
            finally:
                self.routine_refresh_elapsed_ms = max(0, int((self.clock()-started)*1000))
                failed_phase = self.routine_refresh_phase
                self.routine_refresh_phase = 'idle'
                if not succeeded:
                    self.account.revoke_accounting()
                    cause = 'own_order_renewal_failed' if own else 'routine_refresh_failed'
                    if own and released is False:
                        self._last_proof = None  # Release rejected the chain itself.
                    if (own and failure is None and released is None
                            and unexplained in (False, 'order_not_visible')
                            and self._own_renewal_retries < self.OWN_ORDER_RETRIES
                            and self._chain_anchor() is not None):
                        # A non-economic source change raced this attempt (for
                        # example the venue's own order update arriving). Retry
                        # the same bounded renewal instead of a full recovery.
                        self._own_renewal_retries += 1
                        self.own_order_renewal['retries'] += 1
                    else:
                        self._own_renewal_retries = 0
                        if own:
                            self.own_order_renewal['escalations'] += 1
                        else:
                            self.routine_refresh_escalations += 1
                        self.request_recovery(cause)
                    self.diagnostics.emit('account_refresh_failed', error=failure,
                        cause=cause, phase=failed_phase,
                        elapsed_ms=self.routine_refresh_elapsed_ms,
                        outcome=('quota_wait' if isinstance(failure, QuotaUnavailable)
                            else 'timeout' if isinstance(failure, TimeoutError)
                            else 'io' if isinstance(failure, OSError)
                            else 'invalid_data' if failure is not None
                            else unexplained if isinstance(unexplained, str)
                            else 'source_changed'))

    def _schedule_account_refresh(self, scope):
        # A just-canceled owner can be flat and absent from inventory repair.
        # Reevaluate its exact terminal/fill proof before broad catalog work;
        # priority is scheduling only, never ACK-based capacity release.
        cycle = self.maintenance.cycle if self.maintenance is not None else None
        if cycle is not None:
            self.engine.dirty.mark(cycle.ticker, priority=True)
        for ticker in getattr(self.maintenance, 'risk_latched', ()):
            if ticker in self.engine.market_shard:
                self.engine.dirty.mark(ticker, priority=True)
        for ticker in scope or self.engine.market_shard:
            self.engine.dirty.mark(ticker)
        self.engine.wake.set()

    def _current_steady_account_scope(self):
        """Return an exact scheduling scope, never live/account authority."""
        value = self._steady_account_scope
        if value is None:
            return None
        gate = self.selection.initial_ranking if self.selection is not None else None
        now = utc(self.now())
        if (not self.broad_discovery or gate is None or gate.reason != 'coverage_complete'
                or not self.account.connected or self.engine.stopped or self.engine.failed
                or self.writer.failed or self.stop_requested.is_set()
                or now >= value.window_end
                or (self.account.generation, self.account.revision) !=
                   (value.account_generation, value.account_revision)
                or (self.writer.epoch, self.writer.revision) !=
                   (value.writer_epoch, value.writer_revision)
                or self.ingress_revision != value.ingress_revision):
            self._steady_account_scope = None
            return None
        return value.tickers

    def _record_steady_account_scope(self, report, *, expected_signature=None):
        """Remember exact full-cap/flat state only to bound optional CPU work."""
        self._steady_account_scope = None
        gate = self.selection.initial_ranking if self.selection is not None else None
        window = getattr(self.accounting_result, 'window', None)
        now = utc(self.now())
        dispatcher = self.dispatch_supervisor.dispatcher.status() if self.dispatch_supervisor else None
        signature = self._snapshot_signature(report)
        rows = self.current_entry_orders()
        if (not self.broad_discovery or gate is None or gate.reason != 'coverage_complete'
                or report is not self.account.current_report(now)
                or not self.account.connected or self.engine.stopped or self.engine.failed
                or self.writer.failed or self.stop_requested.is_set()
                or report.audit is None or report.audit.blockers or not report.audit.consistent
                or not report.positions_match
                or report.snapshot.positions or rows is None
                or len(rows) != len(report.snapshot.orders)
                or window is None or window.held or not window.start <= now < window.end
                or window.cap <= 0 or len(rows) != window.cap
                or (expected_signature is not None and signature != expected_signature)
                or (dispatcher is not None and (dispatcher.active is not None or dispatcher.queued
                    or dispatcher.stopping or dispatcher.failed))):
            return None
        value = _SteadyAccountScope(self.account.generation, self.account.revision,
            self.writer.epoch, self.writer.revision, self.ingress_revision, window.end,
            signature, frozenset(row.ticker for row in rows))
        self._steady_account_scope = value
        return value.tickers

    async def _refresh_steady_account(self):
        """Refresh a proven full-cap/flat snapshot without a full history pass.

        The account REST enumeration remains exact and source-fenced.  Any
        changed economic/account state or concurrent full-recovery request drops
        this optimization and queues the ordinary recovery owner.
        """
        scope = self._current_steady_account_scope()
        if scope is None or self.recovery_requested.is_set() or self.recovery_lock.locked():
            return False
        owner = self.dispatch_supervisor
        if owner is not None:
            state = owner.dispatcher.status()
            if state.active is not None or state.queued or state.stopping or state.failed:
                return False
        async with self.recovery_lock:
            scope = self._current_steady_account_scope()
            if scope is None or self.recovery_requested.is_set():
                return False
            prior = self._steady_account_scope
            self.steady_refresh_attempts += 1
            failure = None
            try:
                async with asyncio.timeout(20):
                    report = await self.account.reconcile(RecoveryReads(self.reads), now=self.now)
            except (InvalidData, QuotaUnavailable, TimeoutError, OSError) as exc:
                failure = exc
                report = None
            if (report is None or self.recovery_requested.is_set()
                    or (self.account.generation, self.account.revision, self.ingress_revision) !=
                       (prior.account_generation, prior.account_revision, prior.ingress_revision)):
                self.steady_refresh_escalations += 1
                self.request_recovery('steady_refresh_failed')
                self.diagnostics.emit('account_refresh_failed', error=failure,
                    cause='steady_refresh_failed', phase='first_snapshot', outcome='source_changed')
                return False
            refreshed = self._record_steady_account_scope(
                report, expected_signature=prior.snapshot_signature)
            if refreshed != scope:
                self.steady_refresh_escalations += 1
                self.request_recovery('steady_refresh_failed')
                self.diagnostics.emit('account_refresh_failed', cause='steady_refresh_failed',
                    phase='first_snapshot', outcome='source_changed')
                return False
            if self.last_reports is not None:
                self.last_reports = (self.last_reports[0], report)
            self._refresh_continuity()
            for ticker in sorted(scope):
                await self.management.refresh(ticker)
                self._request_inventory_dispatch(ticker)
                if self.selection is not None:
                    self.selection.refresh(ticker)
                if self.rewards is not None:
                    self.rewards.refresh(ticker)
                if self.maintenance is not None:
                    self.maintenance.refresh(ticker)
                    self._request_quote_dispatch(ticker)
            if self.rewards is not None:
                self.rewards.request_reflection()
            self.steady_refresh_completed += 1
            return True

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
                    self.request_recovery('private_fill_pending')
                else:
                    await self.management.refresh(event["msg"]["market_ticker"])
                    self._request_inventory_dispatch(event["msg"]["market_ticker"])
                self._resume_risk_drain()
                return
            if generation != self.account.generation or not self.account.connected:
                return  # Old order/position projection will be re-enumerated.
            result = await self.account.on_event(event, generation=generation, received_at=self.now())
            if isinstance(result, UnscopedPositionUpdate):
                self._epoch_ambiguous = True
                if not self._unscoped_position_requested:
                    self._unscoped_position_requested = True
                    self.request_recovery('private_scope_ambiguous')
                return
            if event.get('type') == 'market_position':
                self.request_recovery('private_position')
            if result is not None and getattr(result, "owned", False):
                waiting = await self.writer.pending_fills(self.account.subaccount, result.order.order_id)
                for item in waiting[:32]:
                    receipt = await self.account.apply_pending_fill(item.fill.key,
                        generation=generation, now=self.now())
                    if receipt is not None and receipt.order is not None:
                        result = receipt.order
                if len(waiting) > 32:
                    self.request_recovery('private_order_pending')
            if result is not None and getattr(result, "awaiting_fills", False):
                self.request_recovery('private_order_pending')
            ticker = event.get("msg", {}).get("ticker", event.get("msg", {}).get("market_ticker"))
            if ticker is not None:
                await self.management.refresh(ticker)
                self._request_inventory_dispatch(ticker)
            self._resume_risk_drain()

    def _resume_risk_drain(self):
        source = getattr(self.dispatch_supervisor, 'source', None)
        if source is not None:
            source.resume_risk_drain()

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
                    self.request_recovery('account_subscribed')
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
            # At ingestion, before queue/disk waits; not at dispatch. An order
            # update's economics are classified by the account owner (D-134).
            self._revoke(economic=kind != 'user_order')
            self._account_ingress_at = self.clock()
            if kind == "fill":
                await self._stage(event)  # Acknowledged durable evidence before enqueue.
                self._epoch_fills += 1
            if self.engine.submit_private(event, generation=generation):
                self._epoch_ingress += 1
        elif spec.name in self.engine.shards:
            self.engine.submit_book(spec.name, event, generation=generation,
                                    received_at=event.pop('_received_mono', None))
        else:
            if self.market_inputs is not None:
                self.market_inputs.ingest(event,generation=generation)
            await self.lifecycle_handler(event)
        return True

    async def _connection(self, spec, *, attempt_start=0):
        """Own one reader for the runtime lifetime.

        Every source gets bounded attempt rounds and a capped inter-round
        cooldown. Financial/sequence authority stays revoked while disconnected;
        persistence only prevents a transient outage from silently retiring the
        reader. A subscription ACK alone never resets failure history: one
        connection must remain subscribed for the configured healthy interval.
        """
        first = attempt_start
        while not self.stop_requested.is_set() and not self.writer.failed and not self.engine.failed:
            stable = await self._connection_round(spec, attempt_start=first,
                                                  final_exhaustion=False)
            first = 0
            if self.stop_requested.is_set() or self.writer.failed or self.engine.failed:
                return
            if stable:
                self.reader_retry_rounds[spec.name] = 0
            self.reader_retry_rounds[spec.name] += 1
            self.reader_states[spec.name] = 'retry_wait'
            self.diagnostics.emit('reader_retry_wait', stream=spec.name,
                                  attempt=self.connection_attempts[spec.name])
            rounds = self.reader_retry_rounds[spec.name]
            await self.sleep(min(300, 30*(2**min(rounds-1, 3)))*self.jitter())

    async def _connection_round(self, spec, *, attempt_start=0, final_exhaustion=True):
        attempt = attempt_start
        stable_seen = False
        while attempt < self.attempt_limit:
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
                # Persistent lifecycle rounds must never reuse an earlier source
                # generation after their local attempt index restarts at zero.
                generation = self.connection_attempts[spec.name]
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
            subscribed_at = None
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
                    subscribed_at = self.clock()
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
                self.reader_failures[spec.name] = (self.connection_attempts[spec.name]
                    if spec.name == 'lifecycle' else attempt+1)
                self.diagnostics.emit('reader_failed', error=exc, stream=spec.name,
                                      generation=generation,
                                      attempt=self.reader_failures[spec.name])
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
            stable = (subscribed_at is not None
                      and self.clock()-subscribed_at >= self.reader_healthy_seconds)
            if stable:
                stable_seen = True
                attempt = 0
            else:
                attempt += 1
            if attempt < self.attempt_limit and not self.writer.failed and not self.engine.failed:
                await self.sleep(min(30, 2**max(0, attempt-1))*self.jitter())
        if final_exhaustion:
            self.reader_states[spec.name] = "retry_exhausted"
            self.diagnostics.emit('reader_exhausted', stream=spec.name,
                                  attempt=self.reader_failures[spec.name])
        return stable_seen

    async def recover_once(self):
        """One attempt; never a proof of complete account history or entry readiness."""
        if self.recovery_lock.locked():
            raise InvalidData("recovery already in flight")
        async with self.recovery_lock:
            started = self.clock()
            self.recovery_phase = 'history'
            self._chained_pass = False
            repaired = False
            try:
                await self._load_continuity_history()
                repaired = await self._repair()
                return repaired
            finally:
                if self._chained_pass:
                    if repaired:
                        self.chained_recoveries += 1
                    else:
                        # Never retry a chained pass: the next attempt re-proves
                        # from the opening boundary (e.g. an archived receipt).
                        self._last_proof = None
                self.recovery_last_phase = self.recovery_phase
                self.recovery_elapsed_ms = max(0, int((self.clock()-started)*1000))
                self.recovery_phase = 'idle'

    async def _repair(self):
        if not self.account_subscribed or not self.account.connected or self.writer.failed:
            return False
        generation = self.account.generation
        reads = RecoveryReads(self.reads)
        await self.engine.private_idle.wait()
        if generation != self.account.generation or not self.account.connected:
            return False
        self.recovery_phase = 'first_snapshot'
        # D-134: download history concurrently with the first snapshot. Its
        # import still runs after the snapshot under the ordinary token; any
        # private event in between discards it and fetches again.
        history_end = self.now()
        # D-134: while nothing economic happened since the last release, its
        # receipt chain still proves [opening boundary, chain end); enumerate
        # only after it. Otherwise re-prove from the opening boundary.
        chain, history_start = self._chain_anchor(), self.history_start
        chained_ids = ()
        if chain is not None:
            chain_end = datetime.fromtimestamp(chain.end_us//1_000_000,
                tz=timezone.utc).replace(microsecond=chain.end_us%1_000_000)
            if self.history_start < chain_end < utc(history_end):
                history_start, chained_ids = chain_end, chain.receipt_ids
        self._chained_pass = bool(chained_ids)
        prefetched = self.account.prefetch_history(reads, start=history_start,
                                                   end=history_end, now=self.now)
        history_started = self.clock()
        try:
            first = await self.account.reconcile(reads, now=self.now)
        except BaseException:
            await self.account.discard_prefetch(prefetched)
            raise
        if first is None:
            await self.account.discard_prefetch(prefetched)
            return False
        first_mark, lookups = self.account.report_mark(first), reads.order_lookups
        history_ingress = self.ingress_revision
        self.recovery_phase = 'history'
        history = await self.account.recover_history(reads, start=history_start,
                                                    end=history_end, now=self.now,
                                                    prefetched=prefetched)
        if history is None:
            return False
        self._observe_history_scope(history, self.clock()-history_started)
        history_reports = [history]
        release_receipt_ids = chained_ids+(history.enumeration.receipt_id,)
        self.recovery_phase = 'pending_fills'
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
        self.recovery_phase = 'missing_orders'
        for receipt in await self.writer.orders():
            if receipt.awaiting_fills or (not receipt.order.terminal and receipt.order.order_id not in visible):
                if reads.order_lookups >= 32:
                    return False
                await self.account.recover_order(reads, receipt.order.order_id, now=self.now)
            if generation != self.account.generation or not self.account.connected:
                return False
        # D-143: old UNKNOWN creates are bound or resolved from complete venue
        # order lists; any change forces the ordinary final venue read.
        unknown_changed = await self._resolve_unknown_creates(reads)
        self.recovery_phase = 'final_snapshot'
        final = None
        if (self.accounting_boundary is not None and not pending and not unknown_changed
                and reads.order_lookups == lookups and history.enumeration is not None
                and int(utc(self.now()).timestamp()*1_000_000) > history.enumeration.eligible_end_us):
            # D-133: nothing but local history/settlement work ran since the
            # first snapshot. Re-audit it instead of reading the venue again;
            # the tail snapshot below must still match it before release.
            final = await self.account.reaudit_recovered(first_mark, now=self.now())
            self.recovery_final_reaudits += final is not None
        reaudited = final is not None
        if final is None:
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
        self.recovery_phase = 'management'
        for ticker in sorted(active):
            await self.management.refresh(ticker)
            self._request_inventory_dispatch(ticker)
        if self.account.report is not final or generation != self.account.generation:
            return False
        prepared_accounting = None
        if self.accounting_boundary is not None:
            # Inventory/order refresh can consume the five-second evidence
            # lease.  Enumerate only the elapsed empty tail concurrently with
            # the final account snapshot.  A new fill rejects this shortcut and
            # is imported by the next full pass.  Do not widen either lease.
            prior_signature = self._snapshot_signature(final)
            history_ingress = self.ingress_revision
            end = utc(self.now())
            start_us = history.enumeration.eligible_end_us
            end_us = int(end.timestamp()*1_000_000)
            if end_us > start_us:
                self.recovery_phase = 'tail_snapshot'
                start = datetime.fromtimestamp(start_us//1_000_000,
                    tz=timezone.utc).replace(microsecond=start_us%1_000_000)
                history, reconciled = await asyncio.gather(
                    self.account.extend_empty_history(
                        reads, start=start, end=end, now=self.now),
                    self.account.reconcile(reads, now=self.now,
                        prepare_accounting_boundary=self.accounting_boundary),
                    return_exceptions=True)
                for value in (history, reconciled):
                    if isinstance(value, BaseException):
                        raise value
                if history is None or reconciled is None:
                    return False
                final, prepared_accounting = reconciled
                history_reports.append(history)
                release_receipt_ids += (history.enumeration.receipt_id,)
            elif reaudited:
                return False  # A re-audited snapshot never releases without a fresh read.
            if (final is None or generation != self.account.generation
                    or self.account.report is not final or not self.account.connected
                    or self.engine.private or self.account._processing):
                return False
            remaining = await self.writer.pending_fills(self.account.subaccount)
            self.last_reports = (history, final)
            self.history_ingress_revision = history_ingress
            if self._snapshot_signature(final) != prior_signature:
                self._refresh_continuity()
                return False
        # Exact local agreement is necessary, never complete venue/history proof.
        repaired = (not remaining
                and all(not item.missing_fill_keys and item.enumeration is not None
                        and not item.enumeration.omitted_rows for item in history_reports)
                and self.account.current_report(self.now()) is final and final.audit.consistent
                and not self._epoch_ambiguous
                and history_ingress == self.ingress_revision
                and (history.generation, history.subaccount) ==
                    (self.account.generation, self.account.subaccount))
        self.recovery_passes += int(repaired)
        self._refresh_continuity()
        if repaired and self.accounting_boundary is not None:
            self.recovery_phase = 'accounting_release'
            release_continuity = replace(
                self._refresh_continuity(operational=True),
                receipt_ids=tuple(dict.fromkeys(release_receipt_ids)))
            if self.opening_reference is not None:
                status = await self.writer.accounting_status()
                if 'operator_boundary_not_approved' in status.blockers:
                    captured = await self.account.reconcile_accounting(
                        reads, proposed_boundary=self.accounting_boundary,
                        continuity=release_continuity, now=self.now)
                    if (self.stop_requested.is_set() or not self.account.connected
                            or generation != self.account.generation
                            or captured.status.checkpoint_digest is None
                            or {'opening_source_stale', 'opening_local_state_changed'}
                                .intersection(captured.status.holds)):
                        return False
                    await self.writer.approve_opening(
                        checkpoint_digest=captured.status.checkpoint_digest,
                        captured_digest=captured.captured_digest,
                        reference=self.opening_reference, now=self.now())
                    # Approval advances the writer revision. Obtain a new
                    # source-fenced report before granting a dispatch lease.
                    self.request_recovery('opening_approved')
                    return False
            if prepared_accounting is not None:
                self.accounting_result = await self.account.release_prepared_accounting(
                    prepared_accounting, continuity=release_continuity, now=self.now)
            else:
                self.accounting_result = await self.account.reconcile_accounting(
                    reads, proposed_boundary=self.accounting_boundary,
                    continuity=release_continuity, now=self.now, release=True)
            repaired = self.accounting_result.released
            if repaired:
                self._record_routine_proof(release_receipt_ids, history)
        if repaired:
            self.recovery_phase = 'complete'
        return repaired

    async def _recover(self):
        while not self.stop_requested.is_set():
            await self.recovery_requested.wait()
            attempt = 0
            transient_failure = False
            while attempt < self.attempt_limit:
                # A private event may request recovery while routine renewal
                # still owns this lock. Join it before spending a retry or
                # starting the whole-pass timeout; never race two owners.
                async with self.recovery_lock:
                    pass
                if self.stop_requested.is_set():
                    return
                if self.quota is not None and not self.quota.poll():
                    self.recovery_state = 'awaiting_quota'
                    try:
                        await self.quota.wait_available()
                    except QuotaUnavailable:
                        if self.quota.state == 'stopped':
                            return
                        raise
                # Transport observation revokes proof immediately, but its
                # ACK/UNKNOWN still has to cross the writer before a REST
                # snapshot can be joined. Coalesce both notifications while
                # joining the sole dispatch owner, outside the pass timeout.
                if self.dispatch_supervisor is not None:
                    if self.dispatch_supervisor.dispatcher.status().active is not None:
                        self.recovery_state = 'awaiting_dispatch_outcome'
                        self.recovery_dispatch_waits += 1
                    joined_at = self.clock()
                    await self.dispatch_supervisor.dispatcher.wait_idle()
                    # D-130: every recovery cause (routine failure, quota,
                    # persisted mutation) joins a pending protective drain.
                    # The drain has its own 5 s/8-attempt escalation; this wait
                    # is bounded and never suppresses the requested pass.
                    source = getattr(self.dispatch_supervisor, 'source', None)
                    if source is not None and source.risk_drain_pending:
                        self.recovery_state = 'awaiting_risk_drain'
                        self.recovery_risk_drain_waits += 1
                        for _ in range(100):
                            if (not source.risk_drain_pending or self.stop_requested.is_set()
                                    or self.clock()-joined_at >= 5):
                                break
                            source.resume_risk_drain()
                            await asyncio.sleep(.05)
                        await self.dispatch_supervisor.dispatcher.wait_idle()
                    self.recovery_dispatch_wait_ms = max(0, int((self.clock()-joined_at)*1000))
                if self.stop_requested.is_set():
                    return
                self.recovery_requested.clear()
                if not self.account_subscribed:
                    self.recovery_state = "awaiting_account_stream"
                    break
                self.recovery_state = "recovering"
                self.recovery_attempts += 1
                cause = self._recovery_reason
                self.recovery_attempt_counts[cause] = self.recovery_attempt_counts.get(cause, 0)+1
                transient_failure = False
                recovery_started = self.clock()
                self.diagnostics.emit('recovery_started', attempt=attempt+1,
                    generation=self.account.generation, cause=cause)
                completed_before = self.recovery_passes
                actions_before = self.recovery_action_progress
                pass_returned = False
                try:
                    # Bounds the whole pass; individual account proofs retain 5s.
                    async with asyncio.timeout(20):
                        repaired = await self.recover_once()
                        pass_returned = True
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
                        generation=self.account.generation, cause=cause,
                        phase=self.recovery_last_phase, elapsed_ms=self.recovery_elapsed_ms)
                    transient_failure = (isinstance(exc,
                        (ReadTransportUnavailable, TimeoutError, OSError))
                        or (isinstance(exc, ReadFailure)
                            and exc.status in {429, 500, 502, 503, 504}))
                    repaired = False
                if self.writer.failed or self.engine.failed:
                    self.recovery_state = "durable_or_engine_failure"
                    self._revoke()
                    return
                if repaired and not self.recovery_requested.is_set():
                    self.recovery_retry_rounds = 0
                    self.recovery_state = "repaired_entries_blocked"
                    if self.rewards is not None:
                        self.rewards.request_reflection()
                    # A full-cap/flat runtime has no available entry slot and
                    # D-098 retains qualifying owners.  Refresh those exact
                    # owners after recovery; a vacancy or any source change
                    # clears the hint and restores complete-universe work.
                    account = self.account.current_report(self.now())
                    scope = (self._record_steady_account_scope(account)
                             if account is not None else None)
                    self._schedule_account_refresh(scope)
                    self.diagnostics.emit('recovery_repaired', generation=self.account.generation,
                        cause=cause, phase=self.recovery_last_phase,
                        elapsed_ms=max(0, int((self.clock()-recovery_started)*1000)))
                    break
                if ((self.recovery_passes > completed_before
                        or (pass_returned and not self._epoch_ambiguous
                            and self.recovery_action_progress > actions_before))
                        and self.recovery_requested.is_set()):
                    # A source-consistent pass can authorize one safety action.
                    # Its durable mutation immediately requests a fresh pass and
                    # invalidates the report that authorized it. Treat that as
                    # forward progress, not as one of the bounded failed attempts;
                    # A durable cancel/reducer ACK can supersede an incomplete
                    # pass before it increments recovery_passes. Its fresh
                    # notification must not be erased by retry exhaustion.
                    # ACK is progress only, never terminal/fill/account proof.
                    self.recovery_state = 'progressed_retry_queued'
                    self.diagnostics.emit('recovery_progressed',
                        attempt=attempt+1, generation=self.account.generation,
                        cause=cause, phase=self.recovery_last_phase)
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
                self.diagnostics.emit('recovery_incomplete', attempt=attempt+1,
                    generation=self.account.generation, cause=cause,
                    phase=self.recovery_last_phase, elapsed_ms=self.recovery_elapsed_ms)
                if attempt+1 == self.attempt_limit:
                    if transient_failure:
                        self.recovery_retry_rounds += 1
                        self.recovery_state = 'transient_retry_wait'
                        self._revoke()
                        delay = min(300, 30*(2**min(self.recovery_retry_rounds-1, 3)))
                        self.diagnostics.emit('recovery_retry_wait',
                            attempt=self.recovery_retry_rounds)
                        await self.sleep(delay*self.jitter())
                        if (not self.stop_requested.is_set() and self.account_subscribed
                                and not self.writer.failed and not self.engine.failed):
                            self.request_recovery('transient_retry')
                        break
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

        A successful accounting proof can renew using a bounded empty history
        tail and fresh account/cash evidence, at any occupancy/ranking state.
        Otherwise retain the full-cap observation shortcut or ordinary recovery.
        """
        while not self.stop_requested.is_set():
            self._resume_risk_drain()
            self._request_post_drain_recovery()
            self._safety_tick()
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
                snapshot_started = self.account._report_monotonic
                # A paused runtime needs a current flat snapshot for shutdown,
                # not another entry lease. Give the supervisor the normal
                # report interval to consume it after a slow recovery pass.
                renewal_due = (not self.entry_pause_active
                    and self._current_routine_proof() is not None
                    and snapshot_started is not None and self.clock()-snapshot_started >= 3)
                drain = (self.dispatch_supervisor.dispatcher.status()
                         if self.dispatch_supervisor is not None else None)
                risk_pending = getattr(getattr(self.dispatch_supervisor, 'source', None),
                                       'risk_drain_pending', False)
                drain_pending = (risk_pending or (self._post_drain_recovery_pending
                    and drain is not None and (drain.active is not None or drain.queued)))
                if not drain_pending and (report is None or renewal_due
                        or (utc(self.now())-report.observed_at).total_seconds() >= 3):
                    # Full-cap scope limits optional market work; it does not
                    # renew accounting. A snapshot-only refresh writes new audit
                    # revisions and invalidates the retained renewal proof/lease.
                    anchor = self._current_own_order_anchor()
                    if self._current_routine_proof() is not None:
                        await self._refresh_routine_account()
                    elif anchor is not None:
                        # D-134: renew after the bot's own acknowledged orders
                        # once their venue updates have had time to arrive.
                        if (self._account_ingress_at is None or self.clock()-self._account_ingress_at
                                >= self.OWN_ORDER_SETTLE_SECONDS):
                            await self._refresh_routine_account(anchor=anchor)
                    elif self._current_steady_account_scope() is not None and report is not None:
                        refreshed = await self._refresh_steady_account()
                        if (not refreshed and self._current_steady_account_scope() is None
                                and not self.recovery_requested.is_set()):
                            self.request_recovery()
                    else:
                        self.request_recovery('snapshot_freshness')
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
            if self.selection is not None:
                self.selection.start()
            tasks = [asyncio.create_task(self.engine.run(), name='kalshi-engine'),
                     asyncio.create_task(self._recover(), name='kalshi-recovery'),
                     asyncio.create_task(self._diagnostic_health(), name='kalshi-log-health')]
            if self.live_session is not None or self.observation_only:
                tasks.append(asyncio.create_task(self._live_refresh(), name='kalshi-account-refresh'))
            if self.live_session is not None and self.reads is not None:
                tasks.append(asyncio.create_task(self._exchange_status(), name='kalshi-exchange-status'))
                if self.maintenance is not None:
                    # D-145: fill protection has its own queue reader.
                    tasks.append(asyncio.create_task(self.maintenance.run_queue_reader(),
                                                     name='kalshi-fill-protection'))
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
                if self.broad_discovery:
                    tasks.append(asyncio.create_task(self._ranked_entries(), name='kalshi-ranked-entries'))
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
        next_summary = self.clock()+60
        while not self.stop_requested.is_set():
            self.diagnostics.ensure_healthy()
            if self.clock() >= next_summary:
                self._diagnostic_summary()
                next_summary = self.clock()+60
            # Logging failure cannot leave an idle runtime silently unobserved.
            await asyncio.sleep(.25)

    def _diagnostic_summary(self):
        """Bounded in-memory counters, once per minute; never account I/O."""
        report = self.account.current_report(self.now())
        owner = self.dispatch_supervisor
        dispatch = owner.dispatcher.status() if owner is not None else None
        rewards = self.rewards
        self.diagnostics.emit('runtime_health',
            recovery_requests=sum(self.recovery_request_counts.values()),
            recovery_attempts=self.recovery_attempts, repair_passes=self.recovery_passes,
            routine_completed=self.routine_refresh_completed,
            routine_escalations=self.routine_refresh_escalations,
            steady_completed=self.steady_refresh_completed,
            cause=self._recovery_reason, phase=self.recovery_phase,
            resting_orders=len(report.snapshot.orders) if report is not None else None,
            positions=len(report.snapshot.positions) if report is not None else None,
            entry_allowed=int(self.entry_allowed), backlog=self.engine.status()['backlog'],
            dispatch_queued=dispatch.queued if dispatch is not None else 0,
            reflection_completed=rewards.reflection_completed if rewards is not None else 0,
            reflection_failures=rewards.reflection_failures if rewards is not None else 0,
            reflection_deferred=rewards.reflection_deferred if rewards is not None else 0,
            reflection_superseded=rewards.reflection_superseded if rewards is not None else 0,
            reflection_quota_deferred=rewards.reflection_quota_deferred if rewards is not None else 0,
            checkpoint_failures=rewards.checkpoint_failures if rewards is not None else 0,
            logging_backlog=self.diagnostics.status().get('backlog', 0))

    def status(self):
        return dict(live_ready=self.entry_allowed, entry_allowed=self.entry_allowed, running=self.running,
            discovery_mode='broad_reviewed' if self.broad_discovery else 'bounded_admission',
            recovery=self.recovery_state, recovery_attempts=self.recovery_attempts,
            recovery_trigger=self._recovery_reason,
            recovery_request_counts=dict(self.recovery_request_counts),
            recovery_attempt_counts=dict(self.recovery_attempt_counts),
            recovery_phase=self.recovery_phase, recovery_last_phase=self.recovery_last_phase,
            recovery_elapsed_ms=self.recovery_elapsed_ms,
            recovery_phase_ms=dict(self.recovery_phase_ms),
            recovery_final_reaudits=self.recovery_final_reaudits,
            recovery_action_progress=self.recovery_action_progress,
            recovery_dispatch_waits=self.recovery_dispatch_waits,
            recovery_dispatch_wait_ms=self.recovery_dispatch_wait_ms,
            recovery_risk_drain_waits=self.recovery_risk_drain_waits,
            unsent_rebases=self.unsent_rebases,
            history_scope=self.history_scope,
            reducer_reprice=dict(holds=self.management.reprice_holds,
                                 releases=self.management.reprice_releases),
            history_scope_warnings=self.history_scope_warnings,
            recovery_retry_rounds=self.recovery_retry_rounds,
            completed_repair_passes=self.recovery_passes,
            own_order_renewal=dict(self.own_order_renewal),
            recovery_safety_pause=bool(self.__dict__.get('_recovery_safety_pause', False)),
            recovery_safety_pauses=self.__dict__.get('recovery_safety_pauses', 0),
            exhausted_retries=self.__dict__.get('_exhausted_retries', 0),
            unknown_creates_resolved=self.__dict__.get('unknown_creates_resolved', 0),
            venue_paused=bool(self.__dict__.get('_venue_paused', False)),
            venue_pauses=self.__dict__.get('venue_pauses', 0),
            exchange_status_failures=self.__dict__.get('exchange_status_failures', 0),
            cash_adjustment_counts=dict(self.__dict__.get('cash_adjustment_counts', {})),
            chained_recoveries=self.chained_recoveries,
            history_floor=self.account.history_floor,
            routine_account_refresh=dict(attempts=self.routine_refresh_attempts,
                completed=self.routine_refresh_completed,
                escalations=self.routine_refresh_escalations,
                phase=self.routine_refresh_phase, elapsed_ms=self.routine_refresh_elapsed_ms,
                phase_ms=dict(self.routine_refresh_phase_ms),
                retained_receipts=(len(self._routine_account_proof.receipt_ids)
                    if self._routine_account_proof is not None else 0)),
            steady_account_refresh=dict(attempts=self.steady_refresh_attempts,
                completed=self.steady_refresh_completed,
                escalations=self.steady_refresh_escalations,
                scoped_markets=(len(self._current_steady_account_scope() or ())),
                suppressed_market_evaluations=self.suppressed_market_evaluations,
                grants_authority=False),
            readers=dict(self.reader_states),
            connection_attempts=dict(self.connection_attempts),
            reader_retry_rounds=dict(self.reader_retry_rounds), engine=self.engine.status(),
            account_verification=self.verification_status(), logging=self.diagnostics.status(),
            read_budget=self.reads.budget.status() if hasattr(self.reads,'budget') else None,
            quota=self.quota_supervisor.status() if self.quota_supervisor is not None else dict(state='unmanaged'),
            dispatch=self.dispatch_supervisor.status() if self.dispatch_supervisor is not None else None,
            selection=self.selection.status() if self.selection is not None else None,
            incentives=self.incentives.status() if self.incentives is not None else None,
            rewards=self.rewards.status() if self.rewards is not None else None,
            maintenance=self.maintenance.status() if self.maintenance is not None else None,
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
                gap_count=len(inspection.gaps), receipt_count=inspection.receipt_count,
                active_receipt_count=len(inspection.receipt_ids),
                archived_receipt_count=inspection.archived_receipts,
                archive_count=inspection.archive_count,
                omission_receipts=inspection.omission_receipts, historical_only=True,
                complete_account_proof=False) if inspection else None),
            continuity=dict(local_evidence_consistent=continuity.local_evidence_consistent,
                venue_handoff_proven=False, stream_span_state=continuity.stream_span_state,
                stream_epoch_id=continuity.stream_epoch_id,
                persisted_gap_count=self._persisted_epoch_gaps,
                receipt_count=len(continuity.receipt_ids), gap_count=len(continuity.interval_gaps),
                blockers=continuity.blockers, ready_for_entry=False),
            blockers=list(dict.fromkeys(blockers)), live_ready=False)
