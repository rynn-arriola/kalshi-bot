"""Current inventory decisions -> injected activation-gated dispatcher.

One pinned proof, not a queue of authorizations. The dispatcher refreshes it
before and after quota reservation; durable receipts remain the writer's job.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import uuid4

from .adapters import create_payload
from .dispatch import (DispatchCandidate, EntryPairCandidate, MutationDispatcher,
                       SAFETY_CANCEL, DUE_IOC, PASSIVE_REDUCER, ENTRY_PAIR)
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


class InventoryDispatchSource:
    """Offline composition seam for the existing, sole management owner.

    Caller submits market keys and awaits dispatcher.run_one(). No polling,
    independent risk owner, live mode or recursive worker.
    """
    def __init__(self, runtime, *, offline_fixture=False):
        if offline_fixture is not True or not isinstance(runtime, RecoveryRuntime):
            raise InvalidData('actual runtime and literal offline_fixture=True required')
        self.runtime = runtime
        self._proof = None
        self._refreshing = False
        self._generation = 0
        self._stopped = False

    def dispatcher(self, budget, *, invoke, clock_pair, pause_seconds=1.):
        """Compose matching producer/executor callbacks; still injected only."""
        outcomes = MutationOutcomeOwner(budget, invoke=invoke, clock_pair=clock_pair,
            notify=self._mutation_observed, pause_seconds=pause_seconds, offline_fixture=True)
        executor = InjectedExecutor(self.runtime.writer, invoke=outcomes,
            validate_proof=self.validate_proof, offline_fixture=True,
            now=self.runtime.now, diagnostics=self.runtime.diagnostics,
            after_outcome=self._mutation_observed)
        return MutationDispatcher(self.runtime.writer, executor, budget,
            refresh=self.refresh, clock_pair=clock_pair, now=self.runtime.now,
            offline_fixture=True)

    def _mutation_observed(self, notice=None):
        self._proof = None
        self._generation += 1
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

    def _plan_current(self, plan, report_observed_at, *, sending=False):
        if not self._available():
            return False
        runtime = self.runtime
        now = utc(runtime.now())
        if not timedelta(0) <= now-report_observed_at <= timedelta(seconds=5):
            return False
        manager = runtime.management
        if sending:
            current = manager.current_for_dispatch(plan.ticker,
                prior_revision=plan.inventory.writer_revision)
        else:
            current = manager.current(plan.ticker)
        if current is not plan or plan.book_revision < 0:
            return False
        if plan.inventory.position and plan.terms is not None and now >= plan.terms.close_at:
            return False
        # A still-fresh price cannot carry an action across an age/deadline or
        # IOC retry boundary. A new evaluation, not an old passive quote, wins.
        next_at = plan.exit.next_at
        if next_at is not None and plan.observed_at < next_at <= now:
            return False
        journal = plan.inventory.exit_journal
        if plan.exit.mode == 'ioc' and journal.started_at is not None:
            if not timedelta(0) <= now-journal.started_at < timedelta(seconds=30):
                return False
        return True

    async def refresh(self, ticker, priority):
        # Concurrent refresh cannot leave either caller holding authority.
        self._generation += 1
        generation = self._generation
        self._proof = None
        if (self._refreshing or not self._available()
                or ticker not in self.runtime.engine.market_shard
                or priority not in {SAFETY_CANCEL, DUE_IOC, PASSIVE_REDUCER,
                                    ENTRY_PAIR}):
            return None
        self._refreshing = True
        try:
            runtime = self.runtime
            report = runtime.account.current_report(runtime.now())
            if report is None:
                return None
            plan = await runtime.management.refresh(ticker)
            if priority == ENTRY_PAIR and runtime.selection is not None:
                runtime.selection.refresh(ticker)
            if (plan is None or plan.exit is None or plan.inventory.blockers
                    or not self._plan_current(plan, report.observed_at)
                    or runtime.account.current_report(runtime.now()) is not report):
                return None
            if priority == ENTRY_PAIR:
                release = runtime.accounting_result
                inputs = runtime.market_inputs
                selection = runtime.selection
                source = (inputs.values.get(('market', ticker))
                          if inputs is not None else None)
                result = inputs.results.get(ticker) if inputs is not None else None
                if (release is None or not release.released or release.window is None
                        or selection is None or not selection.current(ticker)
                        or inputs is None or result is None or result.terms is not plan.terms
                        or source is None or not inputs._fresh(source)
                        or plan.terms.taker_fee_per_contract_bound is None):
                    return None
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
                    return None
                row = rows[0]
                requests = []
                for quote in sorted(row.quotes, key=lambda value: value.side):
                    request = create_payload(ticker=ticker,
                        client_id=str(uuid4()),
                        outcome='yes' if quote.side == 'bid' else 'no',
                        outcome_price=(quote.yes_price if quote.side == 'bid'
                                       else 1-quote.yes_price),
                        quantity=quote.quantity, bands=plan.terms.bands)
                    request.update(subaccount=runtime.account.subaccount,
                                   exchange_index=source.value.exchange)
                    requests.append(request)
                view = await runtime.risk_view()
                if (generation != self._generation
                        or not self._plan_current(plan, report.observed_at)
                        or runtime.account.current_report(runtime.now()) is not report
                        or not selection.current(ticker)
                        or inputs.values.get(('market', ticker)) is not source
                        or inputs.results.get(ticker) is not result
                        or not inputs._fresh(source)
                        or (view.epoch, view.revision) !=
                           (runtime.writer.epoch, runtime.writer.revision)):
                    return None
                candidate = EntryPairCandidate(ticker, priority, str(uuid4()),
                    tuple(requests), view, report.snapshot.available_balance,
                    plan.terms.taker_fee_per_contract_bound,
                    source.value.exchange)
                self._proof = _Proof(plan, report.observed_at, 'batch_create',
                    tuple(encoded_request(request) for request in requests))
                return candidate
            exit_plan, passive = plan.exit, plan.passive
            journal = plan.inventory.exit_journal
            if journal is None or journal.unresolved_ioc or journal.cancel_ids:
                return None
            if priority == SAFETY_CANCEL:
                # Only the cancellation selected by the existing strategy.
                # Never bypass a blocked/wait/attention exit via its subplan.
                allowed = {'await_terminal_cancellation_and_fill_proof'}
                if (exit_plan.mode not in {'flat', 'passive', 'cancel_before_ioc'}
                        or exit_plan.blockers or not passive.cancel_ids
                        or set(passive.blockers)-allowed):
                    return None
                evidence = await runtime.writer.cancel_evidence(passive.cancel_ids[0])
                if evidence is None:
                    return None
                request = dict(order_id=evidence.order_id, market_ticker=ticker,
                    subaccount=runtime.account.subaccount, exchange_index=evidence.exchange_index)
                kind = 'cancel'
            else:
                mode = 'ioc' if priority == DUE_IOC else 'passive'
                if (exit_plan.mode != mode or exit_plan.blockers or plan.terms is None
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
                    or not self._plan_current(plan, report.observed_at)
                    or runtime.account.current_report(runtime.now()) is not report):
                return None
            candidate = DispatchCandidate(ticker, priority, str(uuid4()), request,
                                          evidence, request['exchange_index'])
            self._proof = _Proof(plan, report.observed_at, kind, encoded_request(request))
            return candidate
        finally:
            self._refreshing = False

    def validate_proof(self, kind, request):
        """Synchronous pre/post-SENDING fence; no reads, awaits or network."""
        proof = self._proof
        encoded = (tuple(encoded_request(row) for row in request)
                   if kind == 'batch_create' and type(request) is tuple
                   else encoded_request(request) if isinstance(request, dict)
                   else None)
        return (proof is not None and kind == proof.kind
                and encoded == proof.request_json
                and self._plan_current(proof.plan, proof.report_observed_at, sending=True))
