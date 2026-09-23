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
        self._paused_cancel_notice = None

    def dispatcher(self, budget, *, invoke, clock_pair, pause_seconds=1.):
        """Compose matching producer/executor callbacks and an explicit transport."""
        outcomes = MutationOutcomeOwner(budget, invoke=invoke, clock_pair=clock_pair,
            notify=self._mutation_observed, pause_seconds=pause_seconds,
            offline_fixture=self.offline_fixture, live_session=self.runtime.live_session)
        executor = InjectedExecutor(self.runtime.writer, invoke=outcomes,
            validate_proof=self.validate_proof, offline_fixture=self.offline_fixture,
            now=self.runtime.now, diagnostics=self.runtime.diagnostics,
            after_outcome=self._mutation_observed)
        return MutationDispatcher(self.runtime.writer, executor, budget,
            refresh=self.refresh, clock_pair=clock_pair, now=self.runtime.now,
            offline_fixture=self.offline_fixture, after_result=self._dispatch_result)

    def _dispatch_result(self, result):
        selection = self.runtime.selection
        if selection is not None and result.priority == ENTRY_PAIR:
            selection.record_dispatch_result(result)

    def _mutation_observed(self, notice=None):
        paused_cancel = isinstance(self._proof, _PausedCancelProof)
        self._proof = None
        self._generation += 1
        if (notice is not None and notice.kind == 'cancel'
                and self.runtime.entry_pause_active and paused_cancel):
            if notice.http_status is not None:
                self.runtime.diagnostics.emit('mutation_failed',
                    http_status=notice.http_status, market=notice.ticker,
                    order=notice.subject_id)
                self.runtime.diagnostics.ensure_healthy()
            self._paused_cancel_notice = notice.ticker
            return
        if notice is None and self._paused_cancel_notice is not None:
            ticker, self._paused_cancel_notice = self._paused_cancel_notice, None
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
        self.runtime._revoke()
        self.runtime.request_recovery()  # Existing coalesced owner; no task/read here.
        if notice is not None and notice.http_status is not None:
            self.runtime.diagnostics.emit('mutation_failed', http_status=notice.http_status,
                market=notice.ticker, order=notice.subject_id)
            self.runtime.diagnostics.ensure_healthy()

    def stop(self):
        self._stopped = True
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
        def blocked(reason):
            if priority == ENTRY_PAIR:
                self.last_entry_block = dict(ticker=ticker, reason=reason,
                    observed_at=utc(self.runtime.now()).isoformat(), historical_only=True)
            return None

        # Concurrent refresh cannot leave either caller holding authority.
        self._generation += 1
        generation = self._generation
        self._proof = None
        if (self._refreshing or not self._available()
                or ticker not in self.runtime.engine.market_shard
                or priority not in {SAFETY_CANCEL, DUE_IOC, PASSIVE_REDUCER,
                                    ENTRY_PAIR, QUOTE_CANCEL}):
            return blocked('entry_runtime_unavailable')
        self._refreshing = True
        try:
            runtime = self.runtime
            if priority == SAFETY_CANCEL and runtime.entry_pause_active:
                evidence = await runtime.writer.next_entry_cancel_evidence(
                    ticker, subaccount=runtime.account.subaccount)
                if (evidence is None or generation != self._generation
                        or not self._available() or not runtime.entry_pause_active):
                    return None
                request = dict(order_id=evidence.order_id, market_ticker=ticker,
                    subaccount=evidence.subaccount,
                    exchange_index=evidence.exchange_index)
                candidate = DispatchCandidate(ticker, priority, str(uuid4()),
                    request, evidence, evidence.exchange_index)
                self._proof = _PausedCancelProof(runtime.writer.epoch,
                    evidence.writer_revision, encoded_request(request))
                return candidate
            report = runtime.account.current_report(runtime.now())
            if report is None:
                return blocked('entry_account_report_unavailable')
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
                proposal = await selection.propose(
                    window=release.window,
                    free_cash=report.snapshot.available_balance)
                rows = tuple(row for row in proposal.additions if row.ticker == ticker)
                if (proposal.blockers or len(rows) != 1
                        or runtime.account.current_report(runtime.now()) is not report
                        or not selection.current(ticker)
                        or inputs.values.get(('market', ticker)) is not source
                        or inputs.results.get(ticker) is not result
                        or not inputs._fresh(source)):
                    return blocked('entry_proposal_missing_or_changed')
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
                view = await runtime.risk_view()
                if (generation != self._generation
                        or not self._plan_current(plan, report.observed_at)
                        or runtime.account.current_report(runtime.now()) is not report
                        or not selection.dispatch_proof_current(entry_selection)
                        or inputs.values.get(('market', ticker)) is not source
                        or inputs.results.get(ticker) is not result
                        or not inputs._fresh(source)
                        or (view.epoch, view.revision) !=
                           (runtime.writer.epoch, runtime.writer.revision)):
                    return blocked('entry_sources_changed_after_risk_read')
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
            return (kind == 'cancel' and encoded == proof.request_json
                and self.runtime.entry_pause_active
                and proof.writer_epoch == self.runtime.writer.epoch
                and self.runtime.writer.revision in {
                    proof.writer_revision+1, proof.writer_revision+2}
                and self._available())
        return (proof is not None and kind == proof.kind
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
