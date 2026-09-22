"""Actual-order reward telemetry on existing runtime sources; no order authority."""
from datetime import timedelta
import hashlib

from .quoting import Quote
from .reward_tracker import RewardTracker
from .values import InvalidData, utc


class RuntimeRewards:
    def __init__(self, runtime, *, scope, offline_fixture=False):
        from .runtime import RecoveryRuntime
        if (offline_fixture is not True or not isinstance(runtime, RecoveryRuntime)
                or runtime.used or runtime.selection is None or runtime.rewards is not None
                or runtime.stop_requested.is_set()):
            raise InvalidData('unused matching offline reward runtime required')
        self.runtime = runtime
        self.tracker = RewardTracker(scope=scope)
        self._reflection, self._proofs = {}, {}
        self.blocker = None

    def invalidate(self, ticker):
        self._reflection.pop(ticker,None)
        self._proofs.pop(ticker,None)
        self.tracker.invalidate(ticker)

    def _sources(self, ticker):
        r = self.runtime
        if ticker not in r.engine.market_shard or not r.selection._available():
            return None
        plan = r.management.current(ticker)
        observation = r.selection._observation(ticker)
        report = r.account.current_report(r.now())
        now = utc(r.now())
        if (plan is None or plan.terms is None or observation is None or report is None
                or not observation.observed_at <= now < observation.valid_until
                or not report.positions_match or report.audit.blockers or plan.inventory.blockers):
            return None
        _, book = r.management._book(ticker)
        if book is None: return None
        return plan, observation, report, book

    @staticmethod
    def _orders(plan):
        receipts = plan.inventory.orders
        if len(receipts) > 30 or any(not r.owned or r.awaiting_fills or r.order.terminal
                or r.order.status != 'resting' or r.order.remaining <= 0 for r in receipts):
            return None
        return tuple(Quote(r.order.side,r.order.yes_price,r.order.remaining) for r in receipts)

    def confirm_reflection_fixture(self, ticker, *, offline_fixture=False):
        """Test-only proof injection, not an inference from aggregate depth.

        A production reflection producer remains a separate reviewed boundary.
        The next private/book/program/management revision invalidates this claim.
        """
        if offline_fixture is not True:
            raise InvalidData('production reflection proof is not implemented')
        source = self._sources(ticker)
        if source is None or self._orders(source[0]) is None:
            self.invalidate(ticker)
            raise InvalidData('current actual-order sources required')
        self._reflection[ticker] = source[:3]

    def refresh(self, ticker):
        if self.blocker is not None:
            return
        try:
            self._refresh(ticker)
        except InvalidData:
            # Bounded telemetry exhaustion/invalid clocks cannot stop inventory
            # management. Retain history, revoke rates and expose a sticky fault.
            self.blocker = 'reward_observation_rejected'
            self._reflection.clear()
            self._proofs.clear()
            for market in tuple(self.tracker._by_market):
                self.tracker.invalidate(market)

    def _refresh(self, ticker):
        r = self.runtime
        source = self._sources(ticker)
        if source is None:
            self.invalidate(ticker)
            return
        plan, observation, report, book = source
        quotes = self._orders(plan)
        reflected = self._reflection.get(ticker)
        known = quotes == () or (reflected is not None and all(
            a is b for a,b in zip(reflected,source[:3])))
        # Hash only canonical order identities/terms, never credentials/payloads.
        ownership = repr(tuple(sorted((o.order.order_id,o.order.side,str(o.order.yes_price),
                                      str(o.order.remaining)) for o in plan.inventory.orders)))
        continuity = (r.writer.epoch,plan.generation,plan.book_generation,
                      hashlib.sha256(ownership.encode()).hexdigest())
        now = utc(r.now())
        until = min(now+timedelta(seconds=5),observation.valid_until,plan.terms.valid_until,
                    report.observed_at+timedelta(seconds=5))
        if until <= now:
            self.invalidate(ticker)
            return
        programs = tuple(p for p in observation.programs
                         if plan.inventory.orders or p.program_id in self.tracker.records)
        # Never register hypothetical candidates; validate the shared book once.
        if programs and quotes is not None:
            try:
                self.tracker.observe_many(programs,book=book,bands=plan.terms.bands,quotes=quotes,
                    reflected_known=known,at=now,valid_until=until,continuity=continuity,
                    market_open=plan.terms.active)
            except InvalidData:
                # Unsupported scoring is unknown. Capacity/clock rejection of
                # this fallback reaches the sticky telemetry fault boundary.
                for program in programs:
                    self.tracker.record(program,at=now,valid_until=until,rate=None,
                                        reason='unsupported_terms')
        elif programs:
            for program in programs:
                self.tracker.record(program,at=now,valid_until=until,rate=None,
                                    reason='source_unverified')
        self._proofs[ticker] = source[:3]

    def current(self, ticker):
        if self.blocker is not None:
            return False
        source = self._sources(ticker)
        if source is None:
            self.invalidate(ticker)
            return False
        proof = self._proofs.get(ticker)
        return source is not None and proof is not None and all(
            a is b for a,b in zip(proof,source[:3]))

    def progress(self, program_id):
        record = self.tracker.records[program_id]
        ticker = record.program.ticker
        plan = self.runtime.management.current(ticker)
        exit_at = plan.terms.deadline if plan is not None and plan.terms is not None else self.runtime.now()
        return self.tracker.progress(program_id,now=self.runtime.now(),exit_at=exit_at,
                                     source_current=self.current(ticker))

    def status(self):
        return dict(tracked_programs=len(self.tracker.records), revision=self.tracker.revision,
                    blocker=self.blocker,
                    estimate_only=True, paid_rewards_verified=False,
                    production_reflection_available=False, authorized=False)
