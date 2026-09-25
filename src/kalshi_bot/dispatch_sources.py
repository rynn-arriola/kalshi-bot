"""Current inventory decisions -> injected activation-gated dispatcher.

One pinned proof, not a queue of authorizations. The dispatcher refreshes it
before and after quota reservation; durable receipts remain the writer's job.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import uuid4

from .adapters import create_payload
from .dispatch import (DispatchCandidate, EntryPairCandidate, MutationDispatcher,
                       SAFETY_CANCEL, DUE_IOC, PASSIVE_REDUCER, ENTRY_PAIR, QUOTE_CANCEL)
from .execution import InjectedExecutor, encoded_request
from .exits import ioc_payload
from .management import ManagedPlan
from .mutation_outcomes import MutationOutcomeOwner
from .runtime import RecoveryRuntime
from .values import InvalidData, utc


@dataclass(frozen=True)
class _Proof:
    plan: ManagedPlan
    report_observed_at: datetime
    kind: str
    request_json: object
    entry_selection: object = None
    maintenance_cycle: object = None


@dataclass(frozen=True)
class _PausedCancelProof:
    writer_epoch: str
    writer_revision: int
    request_json: str


@dataclass(frozen=True)
class _RiskCancelProof(_PausedCancelProof):
    cycle: object


class InventoryDispatchSource:
    """Activation-gated composition for the existing, sole management owner.

    Caller submits market keys and awaits dispatcher.run_one(). No polling,
    independent risk owner or recursive worker.
    """
    def __init__(self, runtime, *, offline_fixture=False):
        if (not isinstance(runtime, RecoveryRuntime) or runtime.observation_only
                or not (offline_fixture is True or runtime.live_components_enabled)):
            raise InvalidData('actual runtime and literal offline_fixture=True required')
        self.runtime = runtime
        self.offline_fixture = offline_fixture is True
        self._proof = None
        self._refreshing = False
        self._generation = 0
        self._stopped = False
        self.last_entry_block = None
        self.entry_block_counts = {}
        self._paused_cancel_notice = None
        self._risk_cancel_notice = None
        # Scheduling intent only, never execution authority. A popped key is
        # not proof that the latched pair has no further cancelable orders.
        self._risk_drain_cycle = None
        self._risk_retry_started = None
        self._risk_retry_at = 0.
        self._risk_retry_count = 0
        self.risk_cancel_deferrals = 0
        # D-130: per-turn evidence that no command reached transport.
        self._executor = None
        self._transport_invoked = False
        self._rebase_requested = False

    @property
    def risk_drain_pending(self):
        maintenance = self.runtime.maintenance
        return (self._risk_drain_cycle is not None and maintenance is not None
                and maintenance.cycle is self._risk_drain_cycle)

    def resume_risk_drain(self):
        """Private-event wake plus existing 0.5s watchdog; no new polling task."""
        owner = self.runtime.dispatch_supervisor
        if (not self.risk_drain_pending or owner is None or not owner.running
                or owner.stopping or owner.failed or self._stopped
                or self.runtime.stop_requested.is_set()):
            return
        now = self.runtime.clock()
        state = owner.dispatcher.status()
        if state.active is not None or state.failed or state.stopping:
            return  # Join an in-flight outcome before expiring its retry window.
        if (self._risk_retry_started is not None
                and (not 0 <= now-self._risk_retry_started < 5
                     or self._risk_retry_count >= 8)):
            self._risk_drain_cycle = None
            self.runtime.request_recovery('risk_cancel_retry_exhausted')
            return
        if now >= self._risk_retry_at and self._available():
            owner.request(self._risk_drain_cycle.ticker, QUOTE_CANCEL)

    def dispatcher(self, budget, *, invoke, clock_pair, pause_seconds=1.):
        """Compose matching producer/executor callbacks and an explicit transport."""
        outcomes = MutationOutcomeOwner(budget, invoke=invoke, clock_pair=clock_pair,
            notify=self._mutation_observed, pause_seconds=pause_seconds,
            offline_fixture=self.offline_fixture, live_session=self.runtime.live_session)
        executor = InjectedExecutor(self.runtime.writer, invoke=outcomes,
            validate_proof=self.validate_proof, offline_fixture=self.offline_fixture,
            now=self.runtime.now, diagnostics=self.runtime.diagnostics,
            after_outcome=self._mutation_observed)
        self._executor = executor
        return MutationDispatcher(self.runtime.writer, executor, budget,
            refresh=self.refresh, clock_pair=clock_pair, now=self.runtime.now,
            offline_fixture=self.offline_fixture, after_result=self._dispatch_result)

    def _dispatch_result(self, result):
        if (result.priority in {SAFETY_CANCEL, QUOTE_CANCEL, DUE_IOC, PASSIVE_REDUCER}
                and result.state == 'ACK'):
            # Called only after the sole dispatcher has durably recorded the
            # result. Observation, rejection and UNKNOWN do not earn progress.
            self.runtime.recovery_action_progress += 1
            if (self.runtime.recovery_state == 'blocked_retry_exhausted'
                    and not self.runtime._post_drain_recovery_pending):
                # The last failed pass can finish between outcome notification
                # and this post-persistence callback. Do not lose this new ACK;
                # rapid paused/risk drains retain their shared idle wake instead.
                self.runtime.request_recovery('safety_mutation_persisted')
        if self.runtime.maintenance is not None:
            self.runtime.maintenance.dispatch_result(result)
            self.runtime.maintenance.wake_deferred_risk()
        if (self.risk_drain_pending and result.priority == QUOTE_CANCEL
                and result.ticker == self._risk_drain_cycle.ticker):
            if result.state == 'ACK':
                self._risk_retry_started = None
                self._risk_retry_count = 0
                self._risk_retry_at = 0.
            elif result.state == 'BLOCKED' and set(result.blockers) <= {
                    'current_candidate_missing', 'stale_writer_evidence',
                    'risk_account_book_proof_stale', 'proof_changed_before_submission'}:
                now = self.runtime.clock()
                if self._risk_retry_started is None:
                    self._risk_retry_started = now
                self._risk_retry_count += 1
                self._risk_retry_at = now+.25
                self.risk_cancel_deferrals += 1
                count = self.risk_cancel_deferrals
                if count & (count-1) == 0:
                    self.runtime.diagnostics.emit('risk_cancel_deferred',
                        market=result.ticker, count=count,
                        blockers=result.blockers, blocker_count=len(result.blockers))
            elif result.state not in {'WAITING', 'ACK'}:
                self._risk_drain_cycle = None
                self.runtime.request_recovery('risk_cancel_outcome')
        selection = self.runtime.selection
        if selection is not None and result.priority == ENTRY_PAIR:
            selection.record_dispatch_result(result)
            # Resume advisory work deferred while this exact entry was active,
            # even on a blocked attempt and without requiring another book tick.
            if result.ticker in self.runtime.engine.market_shard:
                self.runtime.engine.dirty.mark(result.ticker)
                self.runtime.engine.wake.set()

    def _mutation_observed(self, notice=None):
        risk = self._proof if isinstance(self._proof, _RiskCancelProof) else None
        paused_cancel = isinstance(self._proof, _PausedCancelProof)
        self._proof = None
        self._generation += 1
        if notice is not None:
            self._transport_invoked = True
        if notice is not None and risk is not None and notice.kind == 'cancel':
            # The exact risk pair was already latched while account proof was
            # current. Revoke all entry authority now; only its remaining owned
            # entry ID may drain before the final account reconciliation.
            self.runtime._revoke()
            self._risk_cancel_notice = (notice, risk.cycle)
            return
        if notice is None and self._risk_cancel_notice is not None:
            (observed, cycle), self._risk_cancel_notice = self._risk_cancel_notice, None
            owner = self.runtime.dispatch_supervisor
            if (observed.outcome == 'ack' and self.runtime.maintenance is not None
                    and self.runtime.maintenance.cycle is cycle):
                self.runtime._post_drain_recovery_pending = True
                if owner is not None and owner.running and not owner.stopping:
                    owner.request(cycle.ticker, QUOTE_CANCEL)
                return
            self._risk_drain_cycle = None
            self.runtime.request_recovery('risk_cancel_outcome')
            return
        if (notice is not None and notice.kind == 'cancel'
                and self.runtime.entry_pause_active and paused_cancel):
            if notice.http_status is not None and notice.http_status != 404:
                self.runtime.diagnostics.emit('mutation_failed',
                    http_status=notice.http_status, market=notice.ticker,
                    order=notice.subject_id)
                self.runtime.diagnostics.ensure_healthy()
            self._paused_cancel_notice = (notice.ticker, notice.http_status)
            return
        if notice is None and self._paused_cancel_notice is not None:
            (ticker, status), self._paused_cancel_notice = self._paused_cancel_notice, None
            if status == 404:
                # The cancel itself was definitively rejected, but 404 does not
                # prove whether the original order filled or was canceled.
                # Require fresh terminal/history evidence before another send.
                self.runtime._revoke()
                self.runtime.request_recovery()
                return
            # The durable ACK/UNKNOWN now exists. Invalidate old recovery proof,
            # but let the exact cancel queue drain before the existing live
            # refresh owner starts a full REST pass.
            self.runtime.last_reports = None
            self.runtime._refresh_continuity()
            self.runtime._post_drain_recovery_pending = True
            owner = self.runtime.dispatch_supervisor
            if owner is not None and owner.running and not owner.stopping:
                owner.request(ticker, SAFETY_CANCEL)
            return
        self._paused_cancel_notice = None
        if (notice is None and not self._transport_invoked
                and self._executor is not None and self._executor.last_denied
                and not self._executor.failed):
            # D-130: proven unsent; no venue effect. After the dispatcher's
            # own abort commits, after_turn re-audits the unchanged snapshot
            # (or falls back to this ordinary recovery). Owner proof is
            # already revoked above.
            self._rebase_requested = True
            return
        self.runtime._revoke()
        self.runtime.request_recovery('mutation_observed' if notice is not None
                                      else 'mutation_persisted')
        if notice is not None and notice.http_status is not None:
            self.runtime.diagnostics.emit('mutation_failed', http_status=notice.http_status,
                market=notice.ticker, order=notice.subject_id)
            self.runtime.diagnostics.ensure_healthy()

    async def after_turn(self, result):
        """D-130: bound recovery after dispatcher turns with no transport call.

        Runs on the sole dispatch owner after the turn's durable aborts. Any
        transport invocation, failed owner or non-blocked result keeps the
        ordinary conservative recovery path.
        """
        requested, self._rebase_requested = self._rebase_requested, False
        invoked, self._transport_invoked = self._transport_invoked, False
        runtime = self.runtime
        if self._stopped or runtime.stop_requested.is_set():
            return
        unsent = (not invoked and result.state in {'BLOCKED', 'WAITING'}
                  and self._executor is not None and not self._executor.failed)
        report = runtime.account.report
        stale_by_revision = (report is not None and report.audit is not None
            and report.audit.writer_revision != runtime.writer.revision)
        if unsent and (requested or stale_by_revision):
            if await runtime.rebase_after_unsent() or not requested:
                return
        if requested:
            runtime._revoke()
            runtime.request_recovery('mutation_persisted')

    def stop(self):
        self._stopped = True
        self._risk_drain_cycle = None
        self._proof = None
        self._generation += 1

    def _available(self):
        runtime = self.runtime
        return (not self._stopped and not runtime.stop_requested.is_set()
                and not runtime.engine.stopped and not runtime.engine.failed
                and not runtime.engine.private and not runtime.account._processing
                and runtime.account.connected and not runtime.writer.failed)

    def _plan_current(self, plan, report_observed_at, *, sending=False,
                      require_book=True):
        if not self._available():
            return False
        runtime = self.runtime
        if require_book and not runtime.engine.catch_up_book(plan.ticker):
            return False
        now = utc(runtime.now())
        if not timedelta(0) <= now-report_observed_at <= timedelta(seconds=5):
            return False
        manager = runtime.management
        if sending:
            current = manager.current_for_dispatch(plan.ticker,
                prior_revision=plan.inventory.writer_revision,
                require_market=require_book)
        else:
            current = manager.current(plan.ticker, require_market=require_book)
        if current is not plan or (require_book and plan.book_revision < 0):
            return False
        if require_book:
            if plan.inventory.position and plan.terms is not None and now >= plan.terms.close_at:
                return False
            # A still-fresh price cannot carry a create across an age/deadline
            # or IOC retry boundary. Exact owned cancellation uses no price.
            next_at = plan.exit.next_at
            if next_at is not None and plan.observed_at < next_at <= now:
                return False
            journal = plan.inventory.exit_journal
            if plan.exit.mode == 'ioc' and journal.started_at is not None:
                if not timedelta(0) <= now-journal.started_at < timedelta(seconds=30):
                    return False
        return True

    async def refresh(self, ticker, priority):
        def blocked(reason, details=()):
            if priority == ENTRY_PAIR:
                self._record_entry_block(ticker, reason, details)
            return None

        # Concurrent refresh cannot leave either caller holding authority.
        self._generation += 1
        generation = self._generation
        self._proof = None
        maintenance = self.runtime.maintenance
        cycle = maintenance.cycle if maintenance is not None else None
        risk_drain = (priority == QUOTE_CANCEL and cycle is not None
                      and cycle.reason == 'fill_risk_withdrawal' and cycle.ticker == ticker)
        if risk_drain and self._risk_drain_cycle is not cycle:
            self._risk_drain_cycle = cycle
            self._risk_retry_started = None
            self._risk_retry_count = 0
            self._risk_retry_at = 0.
        if (self._refreshing or not self._available()
                or ticker not in self.runtime.engine.market_shard
                or priority not in {SAFETY_CANCEL, DUE_IOC, PASSIVE_REDUCER,
                                    ENTRY_PAIR, QUOTE_CANCEL}):
            return blocked('entry_runtime_unavailable')
        self._refreshing = True
        try:
            runtime = self.runtime
            if risk_drain:
                evidence = await runtime.writer.next_entry_cancel_evidence(
                    ticker, subaccount=runtime.account.subaccount)
                if (generation != self._generation or not self._available()
                        or maintenance.cycle is not cycle):
                    return None
                if evidence is None or evidence.order_id not in cycle.order_ids:
                    # A completed, current durable read ends fast drain, NOT
                    # order/fill reconciliation. Never retry ACK/UNKNOWN orders.
                    self._risk_drain_cycle = None
                    return None
                request = dict(order_id=evidence.order_id, market_ticker=ticker,
                    subaccount=evidence.subaccount, exchange_index=evidence.exchange_index)
                self._proof = _RiskCancelProof(runtime.writer.epoch,
                    evidence.writer_revision, encoded_request(request), cycle)
                return DispatchCandidate(ticker, priority, str(uuid4()), request,
                                         evidence, evidence.exchange_index)
            if priority == SAFETY_CANCEL and runtime.entry_pause_active:
                evidence = await runtime.writer.next_entry_cancel_evidence(
                    ticker, subaccount=runtime.account.subaccount)
                if (generation != self._generation or not self._available()
                        or not runtime.entry_pause_active):
                    return None
                if evidence is not None:
                    request = dict(order_id=evidence.order_id, market_ticker=ticker,
                        subaccount=evidence.subaccount,
                        exchange_index=evidence.exchange_index)
                    candidate = DispatchCandidate(ticker, priority, str(uuid4()),
                        request, evidence, evidence.exchange_index)
                    self._proof = _PausedCancelProof(runtime.writer.epoch,
                        evidence.writer_revision, encoded_request(request))
                    return candidate
                # The pause-only fast path deliberately selects entry orders.
                # Once none remain, continue through the source-verified plan
                # below so an aged passive reducer can be canceled before IOC.
            report = runtime.account.current_report(runtime.now())
            if report is None:
                return blocked('entry_account_report_unavailable')
            if (priority not in {SAFETY_CANCEL, QUOTE_CANCEL}
                    and not runtime.engine.catch_up_book(ticker)):
                return blocked('entry_book_catchup_pending')
            # Read durable risk BEFORE freezing a price/selection proof. Reading
            # it inside proposal and again afterwards creates two unnecessary
            # await windows in which valid incoming books invalidate that proof.
            view = await runtime.risk_view() if priority == ENTRY_PAIR else None
            plan = await runtime.management.refresh(ticker)
            if priority == ENTRY_PAIR and runtime.selection is not None:
                runtime.selection.refresh(ticker)
            if (plan is None or plan.exit is None or plan.inventory.blockers
                    or not self._plan_current(plan, report.observed_at,
                                              require_book=priority not in {SAFETY_CANCEL, QUOTE_CANCEL})
                    or runtime.account.current_report(runtime.now()) is not report):
                return blocked('entry_management_proof_unavailable')
            if priority == ENTRY_PAIR:
                if not self.offline_fixture and not runtime.entry_allowed:
                    return blocked('entry_authority_unavailable')
                release = runtime.accounting_result
                inputs = runtime.market_inputs
                selection = runtime.selection
                source = (inputs.values.get(('market', ticker))
                          if inputs is not None else None)
                result = inputs.results.get(ticker) if inputs is not None else None
                if (release is None or not release.released or release.window is None
                        or selection is None or not selection.current(ticker)
                        or inputs is None or result is None or result.terms is not plan.terms
                        or getattr(result, 'blockers', ())
                        or source is None or not inputs._fresh(source)
                        or plan.terms.taker_fee_per_contract_bound is None):
                    return blocked('entry_selection_or_metadata_unavailable')
                proposal = selection._propose_current(
                    window=release.window,
                    free_cash=report.snapshot.available_balance,
                    report=report, view=view)
                rows = tuple(row for row in proposal.additions if row.ticker == ticker)
                if (proposal.blockers or len(rows) != 1
                        or runtime.account.current_report(runtime.now()) is not report
                        or not selection.current(ticker)
                        or inputs.values.get(('market', ticker)) is not source
                        or inputs.results.get(ticker) is not result
                        or not inputs._fresh(source)):
                    details = []
                    if proposal.blockers: details.append('proposal_blocked')
                    if len(rows) != 1: details.append('candidate_not_selected')
                    if runtime.account.current_report(runtime.now()) is not report:
                        details.append('account_report_changed')
                    if not selection.current(ticker): details.append('selection_changed')
                    if inputs.values.get(('market', ticker)) is not source:
                        details.append('metadata_source_changed')
                    if inputs.results.get(ticker) is not result:
                        details.append('metadata_result_changed')
                    if not inputs._fresh(source): details.append('metadata_expired')
                    return blocked('entry_proposal_missing_or_changed', details)
                row = rows[0]
                observation = selection._observation(ticker)
                programs = () if observation is None else tuple(
                    p for p in observation.programs if p.program_id == row.program_id)
                if len(programs) != 1:
                    return blocked('entry_program_unavailable')
                entry_selection = selection.capture_dispatch_proof(
                    ticker, row.program_id, row.valid_until)
                if entry_selection is None:
                    return blocked('entry_selection_proof_changed')
                expires = int(min(plan.terms.deadline, programs[0].end).timestamp())
                if expires <= utc(runtime.now()).timestamp():
                    return blocked('entry_horizon_ended')
                requests = []
                for quote in sorted(row.quotes, key=lambda value: value.side):
                    request = create_payload(ticker=ticker,
                        client_id=str(uuid4()),
                        outcome='yes' if quote.side == 'bid' else 'no',
                        outcome_price=(quote.yes_price if quote.side == 'bid'
                                       else 1-quote.yes_price),
                        quantity=quote.quantity, bands=plan.terms.bands)
                    request.update(subaccount=runtime.account.subaccount,
                                   exchange_index=source.value.exchange,
                                   expiration_time=expires)
                    requests.append(request)
                if (generation != self._generation
                        or not self._plan_current(plan, report.observed_at)
                        or runtime.account.current_report(runtime.now()) is not report
                        or not selection.dispatch_proof_current(entry_selection)
                        or inputs.values.get(('market', ticker)) is not source
                        or inputs.results.get(ticker) is not result
                        or not inputs._fresh(source)
                        or (view.epoch, view.revision) !=
                           (runtime.writer.epoch, runtime.writer.revision)):
                    return blocked('entry_sources_changed_before_prepare',
                        self._entry_source_changes(plan, report, entry_selection, source, result, view))
                candidate = EntryPairCandidate(ticker, priority, str(uuid4()),
                    tuple(requests), view, report.snapshot.available_balance,
                    plan.terms.taker_fee_per_contract_bound,
                    source.value.exchange)
                if runtime.maintenance is not None:
                    if not runtime.maintenance.entry_allowed(ticker, row.program_id):
                        return blocked('incumbent_maintenance_reserved')
                    runtime.maintenance.bind(programs[0])
                self._proof = _Proof(plan, report.observed_at, 'batch_create',
                    tuple(encoded_request(request) for request in requests),
                    entry_selection)
                selection.stage_dispatch_evidence(candidate.batch_id, row,
                    tuple(request['client_order_id'] for request in requests))
                return candidate
            exit_plan, passive = plan.exit, plan.passive
            journal = plan.inventory.exit_journal
            if journal is None or journal.unresolved_ioc or journal.cancel_ids:
                return None
            maintenance_cycle = None
            if priority == QUOTE_CANCEL:
                owner = runtime.maintenance
                target = owner.cancel_target(plan) if owner is not None else None
                if target is None or plan.passive.blockers:
                    return None
                maintenance_cycle = owner.cycle
                evidence = await runtime.writer.cancel_evidence(target)
                if evidence is None or owner.cycle is not maintenance_cycle:
                    return None
                request = dict(order_id=evidence.order_id, market_ticker=ticker,
                    subaccount=runtime.account.subaccount, exchange_index=evidence.exchange_index)
                kind = 'cancel'
            elif priority == SAFETY_CANCEL:
                # Only the cancellation selected by the existing strategy.
                # Never bypass a blocked/wait/attention exit via its subplan.
                allowed = {'await_terminal_cancellation_and_fill_proof'}
                paused = runtime.entry_pause_active
                entry_ids = tuple(sorted(r.order.order_id for r in plan.inventory.orders
                    if r.owned and not r.reducing and not r.order.terminal)) if paused else ()
                if not entry_ids:
                    overflow = runtime.entry_overflow_ids()
                    entry_ids = tuple(sorted(r.order.order_id for r in plan.inventory.orders
                                             if r.order.order_id in overflow))
                deferred = (exit_plan.mode == 'passive_deferred'
                            and exit_plan.blockers == ('ordinary_exit_depth_or_loss',))
                if not entry_ids and (exit_plan.mode not in {'flat', 'passive', 'passive_deferred', 'cancel_before_ioc'}
                        or (exit_plan.blockers and not deferred) or not passive.cancel_ids
                        or set(passive.blockers)-allowed):
                    return None
                evidence = await runtime.writer.cancel_evidence(
                    entry_ids[0] if entry_ids else passive.cancel_ids[0])
                if evidence is None:
                    return None
                request = dict(order_id=evidence.order_id, market_ticker=ticker,
                    subaccount=runtime.account.subaccount, exchange_index=evidence.exchange_index)
                kind = 'cancel'
            else:
                mode = 'ioc' if priority == DUE_IOC else 'passive'
                deferred = (mode == 'passive' and exit_plan.mode == 'passive_deferred'
                            and exit_plan.blockers == ('ordinary_exit_depth_or_loss',))
                if ((exit_plan.mode != mode and not deferred)
                        or (exit_plan.blockers and not deferred) or plan.terms is None
                        or passive.cancel_ids or passive.keep_id is not None
                        or (mode == 'passive' and passive.blockers)):
                    return None
                positions = [p for p in report.snapshot.positions if p.ticker == ticker]
                if len(positions) != 1 or positions[0].quantity != plan.inventory.position:
                    return None
                position = plan.inventory.position
                client_id = str(uuid4())
                if mode == 'ioc':
                    request = ioc_payload(ticker=ticker, client_id=client_id,
                        position=position, limit_price=exit_plan.limit_price,
                        bands=plan.terms.bands)
                else:
                    if passive.reduce_side is None or passive.reduce_quantity != abs(position):
                        return None
                    request = create_payload(ticker=ticker, client_id=client_id,
                        outcome='no' if position > 0 else 'yes',
                        outcome_price=1-exit_plan.limit_price if position > 0 else exit_plan.limit_price,
                        quantity=abs(position), bands=plan.terms.bands,
                        reducing=True, position=position)
                request.update(subaccount=runtime.account.subaccount,
                               exchange_index=positions[0].exchange_index)
                evidence = await runtime.writer.reduction_evidence(request, now=runtime.now())
                kind = 'create'
            if (evidence is None or generation != self._generation
                    or not self._plan_current(plan, report.observed_at,
                                              require_book=priority not in {SAFETY_CANCEL, QUOTE_CANCEL})
                    or runtime.account.current_report(runtime.now()) is not report):
                return None
            candidate = DispatchCandidate(ticker, priority, str(uuid4()), request,
                                          evidence, request['exchange_index'])
            self._proof = _Proof(plan, report.observed_at, kind, encoded_request(request),
                                 maintenance_cycle=maintenance_cycle)
            return candidate
        finally:
            self._refreshing = False

    def _record_entry_block(self, ticker, reason, details=()):
        self.last_entry_block = dict(ticker=ticker, reason=reason,
            details=list(details), observed_at=utc(self.runtime.now()).isoformat(),
            historical_only=True)
        self.entry_block_counts[reason] = self.entry_block_counts.get(reason, 0)+1
        count = self.entry_block_counts[reason]
        # Keep exact counters in status, representative explanations in logs.
        # A moving public book can reject many candidates in a single second.
        if count & (count-1) == 0:
            self.runtime.diagnostics.emit('entry_dispatch_blocked', market=ticker,
                count=count, blockers=(reason, *details), blocker_count=1+len(details))

    def _entry_plan_changes(self, plan):
        """Bounded local attribution only; never new execution authority."""
        r, reasons = self.runtime, []
        now = utc(r.now())
        name = r.engine.market_shard.get(plan.ticker)
        shard = r.engine.shards.get(name)
        book = None if shard is None else shard.books.get(plan.ticker)
        if r.engine.private or r.account._processing: reasons.append('private_work_pending')
        if name is not None and r.engine.public[name]: reasons.append('book_queue_pending')
        if shard is None or shard.failed or shard.generation != plan.book_generation:
            reasons.append('book_generation_changed')
        elif book is None or not book.valid or book.revision != plan.book_revision:
            reasons.append('book_revision_changed')
        received = r.engine.book_received.get(plan.ticker)
        if received is None or not 0 <= r.clock()-received <= 5:
            reasons.append('book_expired')
        if r.management._plans.get(plan.ticker) is not plan: reasons.append('plan_replaced')
        if not timedelta(0) <= now-plan.observed_at <= timedelta(seconds=5):
            reasons.append('plan_expired')
        return reasons

    def _entry_source_changes(self, plan, report, selection, source, result, view):
        r, now = self.runtime, utc(self.runtime.now())
        reasons = self._entry_plan_changes(plan)
        if r.account.current_report(now) is not report: reasons.append('account_report_changed')
        if (view.epoch, view.revision) != (r.writer.epoch, r.writer.revision):
            reasons.append('writer_revision_changed')
        if not r.selection.dispatch_proof_current(selection): reasons.append('selection_changed')
        if r.market_inputs.values.get(('market', plan.ticker)) is not source:
            reasons.append('metadata_source_changed')
        if r.market_inputs.results.get(plan.ticker) is not result:
            reasons.append('metadata_result_changed')
        if not r.market_inputs._fresh(source): reasons.append('metadata_expired')
        return tuple(reasons)

    def validate_proof(self, kind, request):
        """Synchronous pre/post-SENDING fence; no reads, awaits or network."""
        if not self.offline_fixture:
            from .live_session import permits
            if not permits(self.runtime.live_session, self.runtime.writer):
                return False
            if kind == 'batch_create' and self.runtime.entry_pause_active:
                return False
        proof = self._proof
        encoded = (tuple(encoded_request(row) for row in request)
                   if kind == 'batch_create' and type(request) is tuple
                   else encoded_request(request) if isinstance(request, dict)
                   else None)
        if isinstance(proof, _PausedCancelProof):
            if kind != 'cancel' or not isinstance(request, dict):
                return False
            cancel_authorized = (self.runtime.maintenance is not None
                and self.runtime.maintenance.cycle is proof.cycle
                and proof.cycle.reason == 'fill_risk_withdrawal'
                and request.get('order_id') in proof.cycle.order_ids
                if isinstance(proof, _RiskCancelProof) else self.runtime.entry_pause_active)
            return (kind == 'cancel' and encoded == proof.request_json
                and cancel_authorized
                and proof.writer_epoch == self.runtime.writer.epoch
                and self.runtime.writer.revision in {
                    proof.writer_revision+1, proof.writer_revision+2}
                and self._available())
        valid = (proof is not None and kind == proof.kind
                and encoded == proof.request_json
                and (proof.maintenance_cycle is None
                     or (self.runtime.maintenance is not None
                         and self.runtime.maintenance.cycle is proof.maintenance_cycle
                         and self.runtime.maintenance._cycle_current(
                             proof.plan, proof.maintenance_cycle)
                         and not proof.plan.inventory.position))
                and self._plan_current(proof.plan, proof.report_observed_at, sending=True,
                                       require_book=kind != 'cancel')
                and (kind != 'batch_create'
                     or (proof.entry_selection is not None
                         and self.runtime.selection is not None
                         and self.runtime.selection.dispatch_proof_current(
                             proof.entry_selection))))
        if not valid and kind == 'batch_create' and isinstance(proof, _Proof):
            r, plan = self.runtime, proof.plan
            reasons = self._entry_plan_changes(plan)
            if not self._available(): reasons.append('runtime_unavailable')
            if encoded != proof.request_json: reasons.append('request_changed')
            if (plan.generation, plan.account_revision) != (r.account.generation, r.account.revision):
                reasons.append('account_source_changed')
            if not timedelta(0) <= utc(r.now())-proof.report_observed_at <= timedelta(seconds=5):
                reasons.append('account_report_expired')
            if r.writer.revision not in {plan.inventory.writer_revision+1, plan.inventory.writer_revision+2}:
                reasons.append('writer_revision_changed')
            if r.selection is None or not r.selection.dispatch_proof_current(proof.entry_selection):
                reasons.append('selection_changed')
            self._record_entry_block(plan.ticker, 'entry_send_proof_changed',
                                     reasons or ('other_source_boundary',))
        return valid
