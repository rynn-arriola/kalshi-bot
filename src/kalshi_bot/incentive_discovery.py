"""One bounded, supervised reward catalog; injected/offline attachment only."""
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import json
import math
from types import MappingProxyType
from typing import Mapping

from .quota import QuotaUnavailable
from .quoting import parse_program
from .rest import PageSet, RestReads
from .selection_runtime import ProgramObservation
from .values import InvalidData, identity, integer, utc


QUERY = tuple(sorted(dict(status='active', type='liquidity', limit=1000).items()))


@dataclass(frozen=True)
class IncentiveCatalog:
    generation: int
    observations: Mapping[str, ProgramObservation]
    excluded: frozenset[str]
    content_digest: str
    observed_at: datetime
    valid_until: datetime
    observed_mono: float
    deadline_mono: float
    pages: int
    rows: int
    wire_bytes: int
    market_digests: Mapping[str, str] | None = None


def _content_digest(observations, excluded):
    programs = []
    for ticker, observation in sorted(observations.items()):
        programs.append((ticker, tuple(sorted((p.program_id, p.start.isoformat(), p.end.isoformat(),
            str(p.target), p.discount_bps, p.pool_centicents, p.paid_out,
            p.max_reward_centicents) for p in observation.programs))))
    payload = json.dumps((programs, tuple(sorted(excluded))), separators=(',', ':'),
                         ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(payload.encode('ascii')).hexdigest()


def _market_digests(observations, excluded):
    """Return stable per-market semantics for incremental ranking invalidation."""
    digests = {}
    for ticker in sorted(set(observations) | set(excluded)):
        observation = observations.get(ticker)
        programs = (() if observation is None else tuple(sorted((p.program_id,
            p.start.isoformat(), p.end.isoformat(), str(p.target), p.discount_bps,
            p.pool_centicents, p.paid_out, p.max_reward_centicents)
            for p in observation.programs)))
        payload = json.dumps((ticker, ticker in excluded, programs), separators=(',', ':'),
                             ensure_ascii=True, allow_nan=False)
        digests[ticker] = hashlib.sha256(payload.encode('ascii')).hexdigest()
    return MappingProxyType(digests)


class IncentiveDiscovery:
    # Finding 218: exhaustion is a pause, not a permanent stop. Without the
    # catalog every market loses selection evidence, so a burst of 429s must
    # not end entries until a restart.
    EXHAUSTED_COOLDOWN_SECONDS = 120

    def __init__(self, runtime, *, offline_fixture=False, interval=300, attempts=3):
        from .runtime import RecoveryRuntime
        if (not isinstance(runtime, RecoveryRuntime)
                or not (offline_fixture is True or runtime.observation_only
                        or runtime.live_components_enabled)
                or runtime.used or runtime.stop_requested.is_set()
                or runtime.selection is None or runtime.incentives is not None
                or not isinstance(runtime.reads, RestReads) or runtime.reads.closed
                or runtime.reads.budget.clock is not runtime.clock):
            raise InvalidData('unused offline runtime with matching shared reads required')
        self.runtime, self.reads = runtime, runtime.reads
        self.interval = integer(interval, 60, 3600)
        self.attempt_limit = integer(attempts, 1, 8)
        self.catalog = None
        self.active = self.task = None
        self.wake = asyncio.Event()
        self.used = self.running = self.stopping = self.failed = False
        self.exhausted = False
        self.exhausted_until = 0.
        self.cooldown_retries = 0
        self.generation = self.failures = self.completed = self.started = 0
        self.next_at = self.not_before = 0.
        self.last_clock = None
        self.quota = getattr(self.reads, 'quota', None)
        if self.quota is not None:
            self.quota.listen(self.wake.set)

    def _clock(self):
        mono, wall = self.runtime.clock(), utc(self.runtime.now())
        if type(mono) not in (int, float) or not math.isfinite(mono):
            raise InvalidData('invalid incentive clock')
        if self.last_clock is not None:
            old_mono, old_wall = self.last_clock
            elapsed, seconds = mono-old_mono, (wall-old_wall).total_seconds()
            if elapsed < 0 or seconds < 0 or abs(elapsed-seconds) > 1:
                raise InvalidData('incentive clock discontinuity')
        self.last_clock = mono, wall
        return mono, wall

    def _changed(self):
        # Only subscribed markets, never a full-catalog scan on the book path.
        r = self.runtime
        for ticker in r.engine.market_shard:
            r.selection.invalidate(ticker)
            if r.rewards is not None:
                r.rewards.invalidate(ticker)
            if not r.engine.stopped:
                r.engine.dirty.mark(ticker)
        r.engine.wake.set()
        if r.admission is not None:
            r.admission.request()

    def _revoke(self):
        if self.catalog is not None:
            self.catalog = None
            self._changed()

    def current(self):
        if self.stopping or self.failed or self.runtime.stop_requested.is_set():
            return None
        try:
            mono, wall = self._clock()
        except InvalidData:
            self.failed = True
            self._revoke()
            self.wake.set()
            return None
        value = self.catalog
        if value is not None and not (value.observed_mono <= mono < value.deadline_mono
                and value.observed_at <= wall < value.valid_until):
            self._revoke()
            value = None
        if self.quota is not None and not self.quota.poll():
            self._revoke()
            value = None
        return value

    def request(self, *, retry=False):
        if type(retry) is not bool:
            raise InvalidData('explicit incentive retry flag required')
        if self.stopping or self.failed:
            return False
        if retry:
            self.exhausted = False
            self.failures = 0
        if self.exhausted:
            return False
        self.generation += 1
        self._revoke()
        self.next_at = self.runtime.clock()
        self.wake.set()
        return True

    async def _refresh(self, generation):
        mono, observed = self._clock()
        until = observed+timedelta(seconds=self.interval)
        async with asyncio.timeout(30):
            pages = await self.reads.collect('incentives', reason='incentives',
                max_pages=100, max_rows=10000, byte_limit=8388608,
                # Never re-age an older wire call retained after caller timeout.
                coalesce_scope=object(),
                **dict(QUERY))
            if (not isinstance(pages, PageSet) or not pages.exhausted
                    or pages.source != 'incentives' or pages.query != QUERY
                    or type(pages.rows) is not tuple or len(pages.rows) > 10000):
                raise InvalidData('incomplete or unscoped incentive enumeration')
            integer(pages.pages, 1, 100)
            integer(pages.wire_bytes, 0, 8388608)
            grouped, excluded, seen = {}, set(), set()
            for index, row in enumerate(pages.rows):
                if index % 128 == 0:
                    await asyncio.sleep(0)
                    if self.stopping or generation != self.generation:
                        return None
                if not isinstance(row, dict) or row.get('incentive_type') != 'liquidity':
                    raise InvalidData('incentive response scope conflict')
                ticker, program_id = identity(row.get('market_ticker')), identity(row.get('id'))
                if program_id in seen:
                    raise InvalidData('duplicate incentive identity across pages')
                seen.add(program_id)
                try:
                    program = parse_program(row)
                except InvalidData:
                    excluded.add(ticker)
                    grouped.pop(ticker, None)
                    continue
                if ticker in excluded or program.paid_out or not program.start <= observed < program.end:
                    continue
                group = grouped.setdefault(ticker, [])
                if len(group) == 16:
                    excluded.add(ticker)
                    grouped.pop(ticker)
                else:
                    group.append(program)
            observations = {}
            for index, (ticker, programs) in enumerate(grouped.items()):
                if index % 128 == 0:
                    await asyncio.sleep(0)
                    if self.stopping or generation != self.generation:
                        return None
                observations[ticker] = ProgramObservation(tuple(programs), observed, until)
            end_mono, end_wall = self._clock()
            if (self.stopping or generation != self.generation
                    or end_mono >= mono+self.interval or end_wall >= until):
                return None
            if self.quota is not None and not self.quota.poll():
                raise QuotaUnavailable('incentive_quota_unavailable')
            excluded = frozenset(excluded)
            return IncentiveCatalog(generation, MappingProxyType(observations), excluded,
                _content_digest(observations, excluded), observed, until, mono,
                mono+self.interval, pages.pages, len(pages.rows), pages.wire_bytes,
                _market_digests(observations, excluded))

    def step(self):
        """Bounded scheduling turn, deterministic with fixture clocks."""
        mono, _ = self._clock()
        self.runtime.diagnostics.ensure_healthy()
        self.current()
        if self.failed:
            raise InvalidData('incentive discovery failed')
        quota_ready = self.quota is None or self.quota.poll()
        if self.active is not None and self.active.done():
            task, self.active = self.active, None
            try:
                value = task.result()
            except QuotaUnavailable:
                value = None  # Infrastructure hold does not spend data retries.
            except (InvalidData, TimeoutError, OSError) as exc:
                value = None
                self.failures += 1
                self.not_before = mono+min(30, 2**(self.failures-1))
                self.exhausted = self.failures >= self.attempt_limit
                if self.exhausted:
                    self.exhausted_until = mono+self.EXHAUSTED_COOLDOWN_SECONDS
                self.runtime.diagnostics.emit('incentives_exhausted' if self.exhausted
                    else 'incentives_retry', attempt=self.failures, error=exc)
            # Unexpected bugs escape to the runtime's fail-closed supervisor.
            if (value is not None and not self.stopping and quota_ready
                    and value.generation == self.generation
                    and mono < value.deadline_mono and utc(self.runtime.now()) < value.valid_until):
                self.catalog = value
                self.failures = 0
                self.completed += 1
                self.next_at = value.deadline_mono
                self._changed()
        if self.exhausted and not self.stopping and mono >= self.exhausted_until:
            self.exhausted = False
            self.failures = 0
            self.cooldown_retries += 1
            self.runtime.diagnostics.emit('incentives_resumed', attempt=self.cooldown_retries)
        r = self.runtime
        deferred = bool(r.engine.private or r.account._processing or r.recovery_state == 'recovering')
        if (not self.stopping and self.active is None and not self.exhausted and quota_ready
                and not deferred and mono >= max(self.next_at, self.not_before)):
            self._revoke()
            self.started += 1
            self.not_before = mono+1  # Invalidations cannot create a hot retry loop.
            self.active = asyncio.create_task(self._refresh(self.generation), name='kalshi-incentive-refresh')
            self.active.add_done_callback(lambda _: self.wake.set())
        return .25  # Clock/safety watchdog only; no idle REST or catalog scans.

    def stop(self):
        self.stopping = True
        self.generation += 1
        self._revoke()
        if self.active is not None and not self.active.done():
            self.active.cancel()
        self.wake.set()

    async def close(self):
        self.stop()
        # Retain ownership across repeated caller cancellation. RestReads owns
        # any shared wire call; cancelling this waiter never releases its slot.
        cancelled = False
        task = self.active
        if task is not None:
            while not task.done():
                try:
                    await asyncio.wait((task,))
                except asyncio.CancelledError:
                    cancelled = True
            self.active = None
            try:
                task.result()
            except (asyncio.CancelledError, InvalidData, TimeoutError, OSError):
                pass
        if cancelled:
            raise asyncio.CancelledError

    async def run(self):
        if self.used:
            raise InvalidData('incentive service cannot be reused')
        self.used = self.running = True
        self.task = asyncio.current_task()
        try:
            while not self.stopping:
                self.wake.clear()
                delay = self.step()
                try:
                    await asyncio.wait_for(self.wake.wait(), delay)
                except TimeoutError:
                    pass
        except Exception as exc:
            self.failed = True
            self.runtime.diagnostics.emit('incentives_failed', error=exc)
            raise
        finally:
            try:
                await self.close()
            finally:
                self.running = False

    def status(self):
        value = self.current()
        return dict(running=self.running, stopping=self.stopping, failed=self.failed,
            active=self.active is not None, exhausted=self.exhausted, failures=self.failures,
            cooldown_retries=self.cooldown_retries,
            started=self.started, completed=self.completed,
            current_markets=len(value.observations) if value else 0,
            excluded_markets=len(value.excluded) if value else 0,
            enumerated_rows=value.rows if value else 0, authorized=False)
