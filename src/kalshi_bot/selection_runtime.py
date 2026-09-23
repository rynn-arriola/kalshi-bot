"""Opt-in offline selection on existing runtime observations; no venue I/O."""
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal

from .config import BotConfig
from .quoting import Program
from .ranking import seconds
from .selection import MarketSelector, SelectionReport
from .values import InvalidData, decimal, identity, utc


@dataclass(frozen=True)
class ProgramObservation:
    programs: tuple[Program, ...]
    observed_at: datetime
    valid_until: datetime


@dataclass(frozen=True)
class SelectionDispatchProof:
    ticker: str
    program: Program
    observation: ProgramObservation
    source_proof: object
    valid_until: datetime


@dataclass(frozen=True)
class PriorityCandidateHint:
    """Bounded discovery memory; schedules refresh but never authorizes entry."""
    ticker: str
    program_id: str
    observed_at: datetime
    earning_until: datetime
    gross_hourly_usd: Decimal
    source_versions: tuple

    def projected_remaining(self, now):
        now = utc(now)
        if now >= self.earning_until:
            return decimal(0)
        return self.gross_hourly_usd*seconds(self.earning_until-now)/decimal(3600)


class RuntimeSelection:
    def __init__(self, runtime, *, offline_fixture=False, initial_timeout=120):
        from .runtime import RecoveryRuntime
        if (not isinstance(runtime, RecoveryRuntime)
                or not (offline_fixture is True or runtime.observation_only
                        or runtime.live_components_enabled)):
            raise InvalidData('matching offline runtime required')
        self.runtime = runtime
        self.selector = MarketSelector(max(runtime.writer.market_capacity,
                                           len(runtime.engine.market_shard)))
        self.programs = {}
        self._last_observed = {}  # Retain high-water marks after invalid publication.
        self._proofs = {}
        self._rejected = {}  # One static code per subscribed ticker, not raw errors.
        self._discovery = None
        self._last_additions = ()
        self.candidate_inputs = None  # Explicit live composition only.
        self.last_proposal = None  # Bounded historical diagnostics, not authority.
        self._priority_hints = {}  # Advisory only; current proofs still authorize.
        self._priority_refresh = set()
        self._dispatch_selection_evidence = {}
        from .initial_ranking import InitialRankingCheckpoint
        self.initial_ranking = (InitialRankingCheckpoint(runtime.engine.market_shard,
            clock=runtime.clock, timeout=initial_timeout) if runtime.broad_discovery else None)

    def start(self):
        if self.initial_ranking is not None:
            self.initial_ranking.start()

    def _initial_progress(self, ticker=None):
        gate = self.initial_ranking
        if gate is None or gate.reason == 'coverage_complete':
            return
        r = self.runtime
        catalog = r.incentives.current() if r.incentives is not None else None
        gate.sync((tuple((name, shard.generation, shard.failed)
                         for name, shard in r.engine.shards.items()),
                   r.market_inputs.generation if r.market_inputs is not None else None,
                   (catalog.generation, catalog.observed_mono) if catalog is not None else None))
        if ticker is not None:
            gate.observe(ticker)

    def initial_ranking_ready(self):
        if self.initial_ranking is None:
            return True
        self._initial_progress()
        return self.initial_ranking.ready()

    def _source_versions(self, ticker):
        r = self.runtime
        catalog = r.incentives.current() if r.incentives is not None else None
        shard = r.engine.shards[r.engine.market_shard[ticker]]
        return (shard.generation,
                getattr(r.market_inputs, 'generation', None),
                getattr(catalog, 'generation', None),
                r.account.generation, r.writer.epoch, r.writer.revision)

    def _priority_candidate(self, rows, now):
        threshold = BotConfig().priority_projected_reward_usd
        candidates = []
        for row in rows:
            end = row.earning_until or row.program_end
            if (row.blockers or row.gross_hourly_usd is None
                    or row.gross_hourly_usd <= 0 or now >= end):
                continue
            remaining = row.gross_hourly_usd*seconds(end-now)/decimal(3600)
            if remaining >= threshold:
                candidates.append((remaining, row))
        return max(candidates, default=(None, None), key=lambda item:item[0])[1]

    def _current_priority(self, ticker, now):
        if not self.current(ticker):
            return False
        rows = tuple(row for row in self.selector.board.markets.get(ticker, ())
                     if row.observed_at <= now < row.valid_until)
        return self._priority_candidate(rows, now) is not None

    def _remember_priority(self, ticker):
        now = utc(self.runtime.now())
        row = self._priority_candidate(self.selector.board.markets.get(ticker, ()), now)
        if row is None:
            return
        hint = PriorityCandidateHint(ticker, row.program_id, row.observed_at,
            row.earning_until or row.program_end, row.gross_hourly_usd,
            self._source_versions(ticker))
        prior = self._priority_hints.get(ticker)
        if prior is None or hint.observed_at >= prior.observed_at:
            self._priority_hints[ticker] = hint

    def _forget_priority(self, ticker):
        self._priority_hints.pop(ticker, None)
        self._priority_refresh.discard(ticker)

    def _resolve_priority(self, ticker, observation, *, transient=False):
        """Supersede a hint only with a complete newer market evaluation."""
        rows = self.selector.board.markets.get(ticker, ())
        row = self._priority_candidate(rows, utc(self.runtime.now()))
        if row is not None:
            self._priority_hints[ticker] = PriorityCandidateHint(
                ticker, row.program_id, row.observed_at,
                row.earning_until or row.program_end, row.gross_hourly_usd,
                self._source_versions(ticker))
            self._priority_refresh.discard(ticker)
            return
        old = self._priority_hints.get(ticker)
        program_ids = {program.program_id for program in observation.programs}
        if not transient or old is None or old.program_id not in program_ids:
            self._forget_priority(ticker)

    def priority_refresh_pending(self, ticker):
        """Pure scheduler priority predicate; it grants no source authority."""
        return ticker in self._priority_refresh

    def invalidate(self, ticker):
        self._remember_priority(ticker)
        self.selector.invalidate(ticker)
        self._proofs.pop(ticker, None)

    def set_programs(self, ticker, programs, *, observed_at, valid_until):
        """Publish scoped definitions, never account earnings or live authority.

        Producer must finish its bounded metadata enumeration first. Publication
        replaces even an empty set and invalidates older ranking evidence.
        """
        if self.runtime.incentives is not None:
            raise InvalidData('programs owned by incentive discovery')
        if ticker not in self.runtime.engine.market_shard:
            raise InvalidData('programs outside subscribed scope')
        self.programs.pop(ticker, None)
        self.invalidate(ticker)
        if self.runtime.rewards is not None:
            self.runtime.rewards.invalidate(ticker)
        observed, until, now = utc(observed_at), utc(valid_until), utc(self.runtime.now())
        if (type(programs) is not tuple or len(programs) > 16
                or any(not isinstance(p, Program) or p.ticker != ticker for p in programs)
                or len({p.program_id for p in programs}) != len(programs)
                or not observed <= now < until or until-observed > timedelta(hours=1)
                or (ticker in self._last_observed and observed < self._last_observed[ticker])):
            raise InvalidData('invalid or regressed bounded program observation')
        if self.runtime.stop_requested.is_set() or self.runtime.engine.stopped:
            raise InvalidData('selection owner stopped')
        self.programs[ticker] = ProgramObservation(programs, observed, until)
        self._last_observed[ticker] = observed
        self.runtime.engine.dirty.mark(ticker)
        self.runtime.engine.wake.set()

    def _observation(self, ticker):
        service = self.runtime.incentives
        if service is None:
            return self.programs.get(ticker)
        catalog = service.current()
        return catalog.observations.get(ticker) if catalog is not None else None

    async def discovery_candidates(self):
        """Read-only refill/discovery plan, preserving all known/uncertain owners.

        This does not reconfigure sockets. A future subscription owner must
        revalidate the returned source and drain any removed flat/clear scope.
        """
        from .discovery_candidates import CandidateDiscovery, DiscoveryCandidates
        r = self.runtime
        service = r.incentives
        catalog = service.current() if service is not None else None
        report = r.account.current_report(r.now())
        view = await r.risk_view()
        if (not self._available() or view.blockers or report is None
                or not report.positions_match or report.audit.blockers
                or r.account.current_report(r.now()) is not report
                or (view.epoch,view.revision) != (r.writer.epoch,r.writer.revision)
                or (service is not None and catalog is not service.current())):
            # Missing ownership evidence means every subscribed market stays.
            keep = tuple(sorted(r.engine.market_shard))
            return DiscoveryCandidates(keep,keep,0,None)
        owned = {t for t,v in view.positions if v} | {t for t,v in view.exposure if v}
        # A market's management plan may reveal holds beyond aggregate dollars.
        owned.update(t for t,p in r.management._plans.items() if p.inventory.orders
                     or p.inventory.blockers or p.inventory.position
                     or (p.inventory.exit_journal is not None and
                         (p.inventory.exit_journal.unresolved_ioc or p.inventory.exit_journal.cancel_ids)))
        incumbents = tuple(t for t in self._last_additions if self.current(t))
        if self._discovery is None: self._discovery = CandidateDiscovery()
        eligible = (self.candidate_inputs.eligible(catalog, r.now())
                    if self.candidate_inputs is not None and catalog is not None else None)
        candidates = self._discovery.choose(catalog,now=r.now(),budget=r.writer.market_capacity,
                                      protected=tuple(sorted(owned)),incumbents=incumbents,
                                      eligible=eligible,
                                      subscribed=tuple(sorted(r.engine.market_shard)))
        release = r.accounting_result
        window = release.window if release is not None and release.released else None
        now = utc(r.now())
        refill = (window is not None and not window.held and window.start <= now < window.end
                  and timedelta(0) <= now-window.observed_at <= timedelta(seconds=5)
                  and timedelta(0) <= now-view.observed_at <= timedelta(seconds=5)
                  and view.entry_count+2 <= window.cap)
        return replace(candidates, refill=refill)

    def _record_proposal(self, result):
        counts = {}
        for _, reasons in result.exclusions:
            for reason in set(reasons):
                counts[reason] = counts.get(reason, 0)+1
        self.last_proposal = dict(observed_at=utc(self.runtime.now()).isoformat(),
            additions=len(result.additions), blockers=list(result.blockers),
            priority_additions=sum(row.gross_remaining_usd is not None
                and row.gross_remaining_usd >= BotConfig().priority_projected_reward_usd
                for row in result.additions),
            addition_samples=[dict(ticker=row.ticker,
                projected_remaining_usd=str(row.gross_remaining_usd))
                for row in result.additions[:8]],
            priority_revalidation_pending=len(self._priority_refresh),
            priority_revalidation_samples=sorted(self._priority_refresh)[:8],
            fallback_reason=('priority_candidates_resolved' if any(
                row.gross_remaining_usd is not None
                and row.gross_remaining_usd < BotConfig().priority_projected_reward_usd
                for row in result.additions) else None),
            exclusion_counts=counts, exclusion_samples=list(result.exclusions[:8]),
            historical_only=True)
        return result

    def _available(self):
        r = self.runtime
        r.diagnostics.ensure_healthy()
        return (not r.stop_requested.is_set() and not r.engine.stopped and not r.engine.failed
                and not r.engine.private and not r.account._processing and r.account.connected
                and not r.writer.failed)

    def current(self, ticker):
        if self.runtime.admission is not None and self.runtime.admission.transitioning:
            return False
        proof = self._proofs.get(ticker)
        if proof is None or not self._available():
            return False
        plan, observation, report = proof
        now = utc(self.runtime.now())
        return ((self.candidate_inputs is None or not self.candidate_inputs.blockers(ticker, now))
                and observation is self._observation(ticker)
                and observation.observed_at <= now < observation.valid_until
                and self.runtime.account.current_report(now) is report
                and self.runtime.management.current(ticker) is plan)

    def capture_dispatch_proof(self, ticker, program_id, valid_until):
        """Pin entry-only selection inputs before the writer advances revision."""
        ticker, program_id, valid_until = identity(ticker), identity(program_id), utc(valid_until)
        if not self.initial_ranking_ready() or not self.current(ticker):
            return None
        source = self._proofs.get(ticker)
        observation = self._observation(ticker)
        programs = () if observation is None else tuple(
            program for program in observation.programs if program.program_id == program_id)
        if len(programs) != 1:
            return None
        proof = SelectionDispatchProof(ticker, programs[0], observation, source, valid_until)
        if not self.dispatch_proof_current(proof):
            return None
        row = next((row for row in self.selector.board.ranked_programs(
            now=self.runtime.now(), by='selection')
            if row.ticker == ticker and row.program_id == program_id), None)
        if row is not None:
            threshold = BotConfig().priority_projected_reward_usd
            self._dispatch_selection_evidence[ticker] = dict(
                ticker=ticker, program_id=program_id,
                prepared_at=utc(self.runtime.now()).isoformat(),
                projected_remaining_usd=(None if row.gross_remaining_usd is None
                                         else str(row.gross_remaining_usd)),
                tier=('priority' if row.gross_remaining_usd is not None
                      and row.gross_remaining_usd >= threshold else 'fallback'),
                valid_until=valid_until.isoformat())
            while len(self._dispatch_selection_evidence) > 64:
                self._dispatch_selection_evidence.pop(next(iter(self._dispatch_selection_evidence)))
        return proof

    def dispatch_proof_current(self, proof):
        """Synchronous send fence that tolerates only the writer's own prepare."""
        if (not isinstance(proof, SelectionDispatchProof) or not self._available()
                or not self.initial_ranking_ready()):
            return False
        r, now = self.runtime, utc(self.runtime.now())
        if r.admission is not None and r.admission.transitioning:
            return False
        observation = self._observation(proof.ticker)
        return (self._proofs.get(proof.ticker) is proof.source_proof
                and (r.maintenance is None or r.maintenance.entry_allowed(
                    proof.ticker, proof.program.program_id))
                and observation is proof.observation
                and any(program is proof.program for program in observation.programs)
                and observation.observed_at <= now < observation.valid_until
                and now < proof.valid_until
                and (self.candidate_inputs is None
                     or not self.candidate_inputs.blockers(proof.ticker, now)))

    def refresh(self, ticker):
        """Synchronous dirty-market work AFTER management refresh; no extra DB read."""
        self.invalidate(ticker)
        r = self.runtime
        if not self._available():
            return
        now = utc(r.now())
        observation = self._observation(ticker)
        if observation is None and r.incentives is not None and r.incentives.current() is not None:
            # A complete current catalog can rule out an unrewarded market
            # without waiting for a book/metadata combination it cannot use.
            self._forget_priority(ticker)
            self._initial_progress(ticker)
            return
        if (observation is not None and not observation.programs
                and observation.observed_at <= now < observation.valid_until):
            self._forget_priority(ticker)
            self._initial_progress(ticker)
            return
        plan = r.management.current(ticker)
        report = r.account.current_report(now)
        if (observation is None or not observation.programs or plan is None or plan.terms is None
                or report is None or not report.positions_match
                or not observation.observed_at <= now < observation.valid_until):
            return
        _, book = r.management._book(ticker)
        if book is None:
            return
        blockers = plan.inventory.blockers + report.audit.blockers
        if self.candidate_inputs is not None:
            blockers += self.candidate_inputs.blockers(ticker, now)
        # Any owned order remains protected. A private receipt is NOT proof of
        # public-book reflection; do not manufacture a current reward share.
        if plan.inventory.orders:
            blockers += ('owned_orders_reward_reflection_unverified',)
        journal = plan.inventory.exit_journal
        if journal is not None and (journal.unresolved_ioc or journal.cancel_ids):
            blockers += ('pending_inventory_mutation',)
        until = min(observation.valid_until, plan.terms.valid_until,
                    report.observed_at+timedelta(seconds=5), now+timedelta(seconds=5))
        if until <= now:
            return
        try:
            self.selector.update(book, observation.programs, terms=plan.terms, now=now,
                valid_until=until, position=plan.inventory.position, blockers=blockers)
        except InvalidData as exc:
            self.invalidate(ticker)
            self._forget_priority(ticker)
            if ticker not in self._rejected:
                r.diagnostics.emit('selection_inputs_rejected', market=ticker, error=exc)
                r.diagnostics.ensure_healthy()
            self._rejected[ticker] = ('unsupported_selection_inputs',)
            self._initial_progress(ticker)
            return  # One unsupported market must not stop inventory management.
        self._rejected.pop(ticker, None)
        self._proofs[ticker] = (plan, observation, report)
        self._resolve_priority(ticker, observation, transient=bool(blockers))
        self._initial_progress(ticker)

    def _clean_priority_memory(self, now):
        threshold = BotConfig().priority_projected_reward_usd
        for ticker, hint in tuple(self._priority_hints.items()):
            if (ticker not in self.runtime.engine.market_shard
                    or hint.projected_remaining(now) < threshold):
                self._forget_priority(ticker)
            elif self._current_priority(ticker, now):
                self._priority_refresh.discard(ticker)

    def _request_priority_revalidation(self, *, now, available_pairs, protected):
        """Queue one bounded 2x-slot batch ahead of optional metadata work."""
        self._clean_priority_memory(now)
        protected = set(protected)
        self._priority_refresh.intersection_update(self._priority_hints)
        self._priority_refresh.difference_update(protected)
        if not self._priority_refresh and available_pairs > 0:
            candidates = [(hint.projected_remaining(now), ticker)
                for ticker, hint in self._priority_hints.items()
                if ticker not in protected and not self._current_priority(ticker, now)]
            candidates.sort(key=lambda item:(-item[0], item[1]))
            limit = min(30, 2*available_pairs)
            self._priority_refresh.update(ticker for _, ticker in candidates[:limit])
            scheduler = self.runtime.metadata_scheduler
            if scheduler is not None:
                for ticker in tuple(self._priority_refresh):
                    scheduler.request(ticker)
        return bool(self._priority_refresh)

    def _priority_only(self, result, reason):
        threshold = BotConfig().priority_projected_reward_usd
        priority = tuple(row for row in result.additions
            if row.gross_remaining_usd is not None
            and row.gross_remaining_usd >= threshold)
        deferred = tuple((row.ticker, (reason,)) for row in result.additions
                         if row not in priority)
        capital = sum((row.capital_usd+self.selector._fees[(row.ticker,row.program_id)]
                       for row in priority), decimal(0))
        return replace(result, additions=priority,
                       exclusions=result.exclusions+deferred,
                       estimated_capital=capital)

    async def propose(self, *, window, free_cash):
        """Read-only advisory batch; recheck all retained source proofs after await.

        Risk window is an existing owner observation. Do not call observe() on
        every tick: it mutates writer risk state and revokes account leases.
        """
        r = self.runtime
        # Record timeout/complete state, but do not let an incomplete timeout
        # authorize fallback entries. A current all-$2 slate may open the gate
        # early once it can fill every presently available two-order slot.
        initial_ready = self.initial_ranking_ready()
        if r.admission is not None and r.admission.transitioning:
            return self._record_proposal(SelectionReport((),(),(),('subscription_handoff_in_progress',)))
        report = r.account.current_report(r.now())
        if not self._available() or report is None:
            return self._record_proposal(SelectionReport((), (), (), ('selection_sources_unavailable',)))
        view = await r.risk_view()
        if (not self._available() or r.account.current_report(r.now()) is not report
                or (view.epoch, view.revision) != (r.writer.epoch, r.writer.revision)):
            return self._record_proposal(SelectionReport((), (), (), ('selection_sources_changed',)))
        protected = tuple(t for t, plan in r.management._plans.items()
                          if plan.inventory.position or plan.inventory.orders or plan.inventory.blockers
                          or (plan.inventory.exit_journal is not None and
                              (plan.inventory.exit_journal.unresolved_ioc or plan.inventory.exit_journal.cancel_ids)))
        # A caller cannot increase the independently observed cash ceiling.
        cash = min(decimal(free_cash), report.snapshot.available_balance)
        result = self.selector.propose(view=view, window=window, free_cash=cash,
            account_known=report.positions_match and not report.audit.blockers,
            now=r.now(), protected=protected, current=self.current,
            continuations=r.maintenance.continuation() if r.maintenance is not None else None,
            entry_allowed=r.maintenance.entry_allowed if r.maintenance is not None else lambda t,p: True)
        if not initial_ready:
            config = BotConfig()
            available_pairs = max(0, (window.cap-view.entry_count)//2)
            priority = sum(row.gross_remaining_usd is not None
                           and row.gross_remaining_usd >= config.priority_projected_reward_usd
                           for row in result.additions)
            gate = self.initial_ranking
            if (gate is None or not gate.release_for_priority_capacity(
                    candidates=priority, required=min(15, available_pairs))):
                return self._record_proposal(SelectionReport(
                    (), result.retained, result.exclusions, ('initial_ranking_pending',)))
        gate = self.initial_ranking
        if gate is not None and gate.reason == 'priority_capacity_met':
            # Early release proves only the current $2 slate. Keep collecting
            # full coverage and never let a later source change turn that proof
            # into permission for a partially ranked $1 fallback.
            result = self._priority_only(result, 'initial_priority_only')
        available_pairs = max(0, (window.cap-view.entry_count)//2)
        if self._request_priority_revalidation(now=utc(r.now()),
                available_pairs=available_pairs, protected=protected):
            result = self._priority_only(result, 'priority_revalidation_pending')
            if not result.additions:
                result = replace(result, blockers=tuple(dict.fromkeys(
                    result.blockers+('priority_revalidation_pending',))))
        if any(not self.current(row.ticker) or utc(r.now()) >= row.valid_until for row in result.additions):
            return self._record_proposal(SelectionReport((), result.retained, (), ('selection_sources_changed',)))
        accounted = {row.ticker for row in result.additions} | {t for t, _ in result.exclusions}
        missing = tuple((t, self._rejected.get(t, ('selection_evidence_unavailable',)))
                        for t in sorted(r.engine.market_shard) if t not in accounted)
        self._last_additions = tuple(row.ticker for row in result.additions)
        return self._record_proposal(replace(result, exclusions=result.exclusions+missing))

    def status(self):
        return dict(authorized=False, program_markets=sum(
                        self._observation(t) is not None for t in self.runtime.engine.market_shard),
                    cached_markets=len(self.selector.board.markets),
                    current_markets=sum(self.current(t) for t in tuple(self._proofs)),
                    rejected_markets=len(self._rejected),
                    priority_candidate_memory=len(self._priority_hints),
                    priority_candidate_samples=[dict(ticker=ticker,
                        program_id=hint.program_id,
                        projected_remaining_usd=str(hint.projected_remaining(self.runtime.now())),
                        observed_at=hint.observed_at.isoformat(),
                        source_versions=list(hint.source_versions))
                        for ticker,hint in sorted(self._priority_hints.items())[:8]],
                    priority_revalidation_pending=len(self._priority_refresh),
                    priority_revalidation_samples=sorted(self._priority_refresh)[:8],
                    dispatch_selection_evidence=list(
                        self._dispatch_selection_evidence.values())[-8:],
                    last_proposal=self.last_proposal,
                    initial_ranking=(self.initial_ranking.status()
                                     if self.initial_ranking is not None else None),
                    venue_requests=0, automatic_repricing=self.runtime.maintenance is not None,
                    candidate_inputs=(self.candidate_inputs.status()
                                      if self.candidate_inputs is not None else None))
