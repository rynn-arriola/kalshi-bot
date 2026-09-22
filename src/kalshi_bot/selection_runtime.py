"""Opt-in offline selection on existing runtime observations; no venue I/O."""
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from .quoting import Program
from .selection import MarketSelector, SelectionReport
from .values import InvalidData, decimal, utc


@dataclass(frozen=True)
class ProgramObservation:
    programs: tuple[Program, ...]
    observed_at: datetime
    valid_until: datetime


class RuntimeSelection:
    def __init__(self, runtime, *, offline_fixture=False):
        from .runtime import RecoveryRuntime
        if offline_fixture is not True or not isinstance(runtime, RecoveryRuntime):
            raise InvalidData('matching offline runtime required')
        self.runtime = runtime
        self.selector = MarketSelector(runtime.writer.market_capacity)
        self.programs = {}
        self._last_observed = {}  # Retain high-water marks after invalid publication.
        self._proofs = {}
        self._rejected = {}  # One static code per subscribed ticker, not raw errors.

    def invalidate(self, ticker):
        self.selector.invalidate(ticker)
        self._proofs.pop(ticker, None)

    def set_programs(self, ticker, programs, *, observed_at, valid_until):
        """Publish scoped definitions, never account earnings or live authority.

        Producer must finish its bounded metadata enumeration first. Publication
        replaces even an empty set and invalidates older ranking evidence.
        """
        if ticker not in self.runtime.engine.market_shard:
            raise InvalidData('programs outside subscribed scope')
        self.programs.pop(ticker, None)
        self.invalidate(ticker)
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

    def _available(self):
        r = self.runtime
        r.diagnostics.ensure_healthy()
        return (not r.stop_requested.is_set() and not r.engine.stopped and not r.engine.failed
                and not r.engine.private and not r.account._processing and r.account.connected
                and not r.writer.failed)

    def current(self, ticker):
        proof = self._proofs.get(ticker)
        if proof is None or not self._available():
            return False
        plan, observation, report = proof
        now = utc(self.runtime.now())
        return (observation is self.programs.get(ticker)
                and observation.observed_at <= now < observation.valid_until
                and self.runtime.account.current_report(now) is report
                and self.runtime.management.current(ticker) is plan)

    def refresh(self, ticker):
        """Synchronous dirty-market work AFTER management refresh; no extra DB read."""
        self.invalidate(ticker)
        r = self.runtime
        if not self._available():
            return
        now = utc(r.now())
        observation = self.programs.get(ticker)
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
            if ticker not in self._rejected:
                r.diagnostics.emit('selection_inputs_rejected', market=ticker, error=exc)
                r.diagnostics.ensure_healthy()
            self._rejected[ticker] = ('unsupported_selection_inputs',)
            return  # One unsupported market must not stop inventory management.
        self._rejected.pop(ticker, None)
        self._proofs[ticker] = (plan, observation, report)

    async def propose(self, *, window, free_cash):
        """Read-only advisory batch; recheck all retained source proofs after await.

        Risk window is an existing owner observation. Do not call observe() on
        every tick: it mutates writer risk state and revokes account leases.
        """
        r = self.runtime
        report = r.account.current_report(r.now())
        if not self._available() or report is None:
            return SelectionReport((), (), (), ('selection_sources_unavailable',))
        view = await r.risk_view()
        if (not self._available() or r.account.current_report(r.now()) is not report
                or (view.epoch, view.revision) != (r.writer.epoch, r.writer.revision)):
            return SelectionReport((), (), (), ('selection_sources_changed',))
        protected = tuple(t for t, plan in r.management._plans.items()
                          if plan.inventory.position or plan.inventory.orders or plan.inventory.blockers
                          or (plan.inventory.exit_journal is not None and
                              (plan.inventory.exit_journal.unresolved_ioc or plan.inventory.exit_journal.cancel_ids)))
        # A caller cannot increase the independently observed cash ceiling.
        cash = min(decimal(free_cash), report.snapshot.available_balance)
        result = self.selector.propose(view=view, window=window, free_cash=cash,
            account_known=report.positions_match and not report.audit.blockers,
            now=r.now(), protected=protected, current=self.current)
        if any(not self.current(row.ticker) or utc(r.now()) >= row.valid_until for row in result.additions):
            return SelectionReport((), result.retained, (), ('selection_sources_changed',))
        accounted = {row.ticker for row in result.additions} | {t for t, _ in result.exclusions}
        missing = tuple((t, self._rejected.get(t, ('selection_evidence_unavailable',)))
                        for t in sorted(r.engine.market_shard) if t not in accounted)
        return replace(result, exclusions=result.exclusions+missing)

    def status(self):
        return dict(authorized=False, program_markets=len(self.programs),
                    cached_markets=len(self.selector.board.markets),
                    current_markets=sum(self.current(t) for t in self._proofs),
                    rejected_markets=len(self._rejected),
                    venue_requests=0, automatic_repricing=False)
