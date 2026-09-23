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
        self.reason = None
        self.versions = None
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

    def sync(self, versions):
        # A reconnect/source epoch cannot contribute stale initial coverage.
        # Do not extend the deadline; an initial-only barrier never re-arms.
        if self.reason is not None:
            return
        if self.versions is not None and versions != self.versions:
            self.evaluated.clear()
            self.resets += 1
        self.versions = versions

    def observe(self, ticker):
        if ticker not in self.scope:
            raise InvalidData('initial ranking observation outside scope')
        if self.started_at is not None and self.reason is None:
            self.evaluated.add(ticker)

    def ready(self):
        now = self._time()
        if self.started_at is None:
            return False
        if self.reason is None:
            if len(self.evaluated) == len(self.scope):
                self.reason = 'coverage_complete'
            elif now-self.started_at >= self.timeout:
                self.reason = 'timeout_partial'
            if self.reason is not None:
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
        return dict(state=self.reason or ('waiting' if self.started_at is not None else 'not_started'),
            timeout_seconds=self.timeout, total_markets=len(self.scope),
            evaluated_markets=len(self.evaluated), missing_markets=len(missing),
            missing_samples=missing[:8], shards=shards, source_resets=self.resets,
            elapsed_seconds=(None if self.started_at is None else
                             (self.released_at if self.released_at is not None else now)-self.started_at),
            historical_coverage=True, grants_order_authority=False)
