"""One bounded startup coverage barrier, not eligibility or order authority."""
import math

from .values import InvalidData, integer


class InitialRankingCheckpoint:
    def __init__(self, scope, *, clock, timeout=120):
        self.scope = dict(scope)
        integer(len(self.scope), 1, 1024)
        self.timeout = integer(timeout, 1, 300)
        self.clock = clock
        self.started_at = self.last_clock = self.released_at = None
        self.timed_out_at = None
        self.reason = None
        self.release_reason = None
        self.versions = None
        self.market_versions = None
        self.evaluated = set()
        self.resets = 0

    def _time(self):
        now = self.clock()
        if (type(now) not in (int, float) or not math.isfinite(now)
                or (self.last_clock is not None and now < self.last_clock)):
            raise InvalidData('initial ranking clock invalid or regressed')
        self.last_clock = now
        return now

    def start(self):
        if self.started_at is None:
            self.started_at = self._time()

    def sync(self, versions, market_versions=None):
        # A reconnect/source epoch cannot contribute stale initial coverage.
        # Do not extend the deadline; an initial-only barrier never re-arms.
        if self.reason == 'coverage_complete':
            return
        if self.versions is not None and versions != self.versions:
            self.evaluated.clear()
            self.resets += 1
        elif self.market_versions is not None and market_versions is not None:
            changed = {ticker for ticker in self.scope
                       if self.market_versions.get(ticker) != market_versions.get(ticker)}
            if changed:
                # A reward refresh only invalidates coverage whose economics
                # changed. Unrelated markets retain their completed ranking.
                self.evaluated.difference_update(changed)
                self.resets += 1
        self.versions = versions
        self.market_versions = (None if market_versions is None else
                                {ticker: market_versions.get(ticker) for ticker in self.scope})

    def observe(self, ticker):
        if ticker not in self.scope:
            raise InvalidData('initial ranking observation outside scope')
        if self.started_at is not None and self.reason != 'coverage_complete':
            self.evaluated.add(ticker)

    def ready(self):
        now = self._time()
        if self.started_at is None:
            return False
        if len(self.evaluated) == len(self.scope) and self.reason != 'coverage_complete':
            self.release_reason = self.release_reason or 'coverage_complete'
            self.reason = 'coverage_complete'
            self.released_at = self.released_at or now
        elif self.reason is None:
            if now-self.started_at >= self.timeout:
                # An incomplete timeout is diagnostic, never permission to let
                # early $1 rows occupy slots before unseen $2 candidates.
                self.timed_out_at = self.timed_out_at or now
        return self.reason is not None

    def release_for_priority_capacity(self, *, candidates, required):
        """Open early only when current $2 rows can fill every available pair slot."""
        candidates = integer(candidates, 0, 1024)
        required = integer(required, 0, 15)
        now = self._time()
        if (self.started_at is not None and self.reason is None and required > 0
                and candidates >= required):
            self.reason = 'priority_capacity_met'
            self.release_reason = self.reason
            self.released_at = now
        return self.reason is not None

    def status(self):
        # Coverage is historical; readiness of orders is always checked anew.
        now = self._time()
        missing = sorted(set(self.scope)-self.evaluated)
        shards = {name: dict(total=0, evaluated=0) for name in set(self.scope.values())}
        for ticker, name in self.scope.items():
            shards[name]['total'] += 1
            shards[name]['evaluated'] += ticker in self.evaluated
        state = self.reason or ('timeout_incomplete' if self.timed_out_at is not None else
                                ('waiting' if self.started_at is not None else 'not_started'))
        return dict(state=state,
            timeout_seconds=self.timeout, total_markets=len(self.scope),
            evaluated_markets=len(self.evaluated), missing_markets=len(missing),
            missing_samples=missing[:8], shards=shards, source_resets=self.resets,
            timed_out=self.timed_out_at is not None,
            release_reason=self.release_reason,
            elapsed_seconds=(None if self.started_at is None else
                             (self.released_at if self.released_at is not None else now)-self.started_at),
            historical_coverage=True, grants_order_authority=False)
