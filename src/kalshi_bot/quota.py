"""Expiring account-wide Read evidence. No I/O, persistence or trading authority."""
import asyncio
from dataclasses import dataclass, field
import math

from .observability import NO_LOG
from .values import InvalidData, integer, utc

CONTROL_ROUTES = frozenset(('/account/limits', '/account/endpoint_costs'))


class QuotaUnavailable(InvalidData):
    def __init__(self, reason='quota_stale'):
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class QuotaRolloverPending(QuotaUnavailable):
    """Valid near-boundary evidence which cannot confer a new read lease."""
    scope: 'QuotaScope'
    epoch: int
    sequence: int
    expiry_wall: int
    expiry_mono: float
    reason: str = field(default='quota_rollover_pending', init=False)

    def __post_init__(self):
        InvalidData.__init__(self, self.reason)


@dataclass(frozen=True)
class ProbeConfig:
    # Deliberately no default production allowance.
    rate: int
    capacity: int
    limits_cost: int
    costs_cost: int

    def __post_init__(self):
        for value in (self.rate, self.capacity, self.limits_cost, self.costs_cost):
            integer(value, 1, 1000000)
        if max(self.limits_cost, self.costs_cost) > self.capacity:
            raise InvalidData('probe cost exceeds capacity')


@dataclass(frozen=True)
class QuotaPolicy:
    probe: ProbeConfig
    maximum_age: float = 300
    refresh_lead: float = 90
    expiry_margin: float = 5
    clock_tolerance: float = 2
    pair_timeout: float = 65
    attempts: int = 3
    cooldown: float = 60

    def __post_init__(self):
        if not isinstance(self.probe, ProbeConfig):
            raise InvalidData('explicit probe configuration required')
        for value in (self.maximum_age, self.refresh_lead, self.expiry_margin,
                      self.clock_tolerance, self.pair_timeout, self.cooldown):
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise InvalidData('invalid quota policy duration')
        integer(self.attempts, 1, 3)
        if not self.pair_timeout < self.refresh_lead < self.maximum_age <= 3600:
            raise InvalidData('incoherent quota freshness policy')


@dataclass(frozen=True, eq=False)
class QuotaScope:
    """Opaque identity; never an API key or account identifier."""
    identity: object = field(default_factory=object, repr=False)


@dataclass(frozen=True)
class QuotaCandidate:
    scope: QuotaScope
    epoch: int
    sequence: int
    start_mono: float
    start_wall: float
    end_mono: float
    end_wall: float
    read_rate: int
    read_capacity: int
    write_rate: int
    write_capacity: int
    default_cost: int
    costs: tuple
    grant_expiry: int | None

    def documents(self):
        return (dict(read=dict(refill_rate=self.read_rate, bucket_capacity=self.read_capacity)),
                dict(default_cost=self.default_cost, endpoint_costs=[
                    dict(method='GET', path=path, cost=cost) for path, cost in self.costs]))


@dataclass(frozen=True)
class QuotaLease:
    candidate: QuotaCandidate
    revision: int
    deadline_mono: float
    deadline_wall: float


def _label(value):
    if not isinstance(value, str) or not value or len(value) > 128 or any(ord(c) < 32 for c in value):
        raise InvalidData('invalid quota label')
    return value


def parse_candidate(limits, costs, *, scope, epoch, sequence, start, end):
    """Complete bounded parse before touching any shared configuration."""
    try:
        _label(limits['usage_tier'])
        read, write = limits['read'], limits['write']
        numbers = tuple(integer(obj[key], 1, 1000000) for obj in (read, write)
                        for key in ('refill_rate', 'bucket_capacity'))
        grants = limits['grants']
        if not isinstance(grants, list) or len(grants) > 128:
            raise InvalidData('invalid grant count')
        expiry = None
        for row in grants:
            lane = row['exchange_instance']
            if lane not in ('event_contract', 'margined'):
                raise InvalidData('unknown quota lane')
            _label(row['level'])
            _label(row['source'])
            if 'expires_ts' in row:
                stamp = row['expires_ts']
                if stamp is None:
                    if lane == 'event_contract':
                        raise QuotaUnavailable('grant_expiry_unknown')
                    continue
                integer(stamp, 1, 253402300799)
                if lane == 'event_contract':
                    expiry = stamp if expiry is None else min(expiry, stamp)
        default = integer(costs['default_cost'], 1, numbers[1])
        rows = costs['endpoint_costs']
        if not isinstance(rows, list) or len(rows) > 2048:
            raise InvalidData('invalid cost count')
        overrides, seen = {}, set()
        for row in rows:
            method, path = _label(row['method']), row['path']
            value = integer(row['cost'], 1, 1000000)
            if not isinstance(path, str) or not path.startswith('/') or len(path) > 300 or any(ord(c) < 33 for c in path):
                raise InvalidData('invalid cost route')
            if path.startswith('/trade-api/v2/'):
                path = path[len('/trade-api/v2'):]
            if (method, path) in seen:
                raise InvalidData('duplicate cost route')
            seen.add((method, path))
            if method == 'GET':
                overrides[path] = value
        if not isinstance(scope, QuotaScope):
            raise InvalidData('invalid quota scope')
        integer(epoch, 1, 2**63-1)
        integer(sequence, 1, 2**63-1)
        if any(type(x) not in (int, float) or not math.isfinite(x) for x in (*start, *end)):
            raise InvalidData('invalid observation clock')
        if end[0] < start[0] or end[1] < start[1]:
            raise InvalidData('observation clock regressed')
        return QuotaCandidate(scope, epoch, sequence, *start, *end, *numbers,
                              default, tuple(sorted(overrides.items())), expiry)
    except (KeyError, TypeError, AttributeError) as exc:
        raise InvalidData('incomplete quota documents') from exc


class QuotaGuard:
    def __init__(self, policy, *, clock, now, scope=None, diagnostics=NO_LOG):
        if not isinstance(policy, QuotaPolicy):
            raise InvalidData('explicit quota policy required')
        self.policy, self.clock, self.now = policy, clock, now
        self.scope = scope if scope is not None else QuotaScope()
        if not isinstance(self.scope, QuotaScope):
            raise InvalidData('invalid quota scope')
        self.diagnostics = diagnostics
        self.epoch, self.sequence, self.revision = 1, 0, 0
        self.lease = None
        self.state = 'uninitialized'
        self.reason = 'quota_uninitialized'
        self.anchor = self.last = self._sample()
        self.changed = asyncio.Event()
        self.listeners = []
        self._apply = None

    def _sample(self):
        mono, wall = self.clock(), utc(self.now()).timestamp()
        if type(mono) not in (int, float) or not math.isfinite(mono) or not math.isfinite(wall):
            raise QuotaUnavailable('quota_clock_fault')
        return mono, wall

    def listen(self, callback):
        if len(self.listeners) >= 4 or callback in self.listeners:
            raise InvalidData('quota listener bound exceeded')
        self.listeners.append(callback)

    def _notify(self):
        old, self.changed = self.changed, asyncio.Event()
        old.set()
        for callback in tuple(self.listeners):
            callback()

    def bind(self, apply):
        if self._apply is not None:
            raise InvalidData('quota guard already owned')
        self._apply = apply
        apply(None)  # Empty conservative probe on the SAME bucket.

    def _invalidate(self, state, reason):
        if self.state == state and self.reason == reason:
            return
        self.state, self.reason = state, reason
        self.revision += 1
        if state == 'stale' and self._apply is not None:
            self._apply(None)
        self.diagnostics.emit('quota_'+('clock_fault' if state == 'clock_fault' else state), revision=self.revision)
        self._notify()

    def poll(self):
        if self.state in ('stopped', 'clock_fault'):
            return False
        try:
            mono, wall = self._sample()
            if (mono < self.last[0] or wall < self.last[1] or
                    abs((mono-self.anchor[0])-(wall-self.anchor[1])) > self.policy.clock_tolerance):
                raise QuotaUnavailable('quota_clock_fault')
            self.last = mono, wall
        except (InvalidData, ValueError, OverflowError):
            self._invalidate('clock_fault', 'quota_clock_fault')
            return False
        if self.lease is not None and self.state == 'fresh':
            if mono >= self.lease.deadline_mono or wall >= self.lease.deadline_wall:
                self._invalidate('stale', 'quota_stale')
        return self.state == 'fresh'

    def check(self, route, *, control=False):
        available = self.poll()
        if self.state in ('stopped', 'clock_fault') or (not available and not (control and route in CONTROL_ROUTES)):
            raise QuotaUnavailable(self.reason)
        return self.revision

    def begin(self):
        self.check('/account/endpoint_costs', control=True)
        self.sequence += 1
        return self.epoch, self.sequence, self._sample()

    def install(self, candidate):
        self.check('/account/limits', control=True)
        if (candidate.scope is not self.scope or candidate.epoch != self.epoch or
                candidate.sequence != self.sequence):
            raise QuotaUnavailable('quota_candidate_superseded')
        mono, wall = self._sample()
        age_wall = candidate.start_wall+self.policy.maximum_age
        age_mono = candidate.start_mono+self.policy.maximum_age
        hard_wall = age_wall
        if candidate.grant_expiry is not None:
            hard_wall = min(hard_wall, candidate.grant_expiry-self.policy.expiry_margin)
        hard_mono = candidate.start_mono + (hard_wall-candidate.start_wall)
        if mono-candidate.start_mono > self.policy.pair_timeout:
            raise QuotaUnavailable('quota_candidate_expired')
        remaining = min(hard_mono-mono, hard_wall-wall)
        if remaining <= self.policy.refresh_lead:
            expiry = candidate.grant_expiry
            expiry_mono = (None if expiry is None else
                           candidate.start_mono+(expiry-candidate.start_wall))
            if (expiry is not None and expiry > wall and expiry_mono > mono
                    and min(age_mono-mono, age_wall-wall) > self.policy.refresh_lead):
                old = self.lease.candidate if self.state == 'fresh' and self.lease is not None else None
                if (old is not None and (old.read_rate, old.read_capacity, old.default_cost,
                        old.costs, old.grant_expiry) !=
                        (candidate.read_rate, candidate.read_capacity, candidate.default_cost,
                         candidate.costs, candidate.grant_expiry)):
                    self._invalidate('stale', 'quota_stale')
                raise QuotaRolloverPending(candidate.scope, candidate.epoch, candidate.sequence,
                                           expiry, expiry_mono)
            raise QuotaUnavailable('quota_candidate_expired')
        if self._apply is None:
            raise InvalidData('quota guard not attached')
        self._apply(candidate)
        self.revision += 1
        self.lease = QuotaLease(candidate, self.revision, hard_mono, hard_wall)
        self.state, self.reason = 'fresh', None
        self.diagnostics.emit('quota_fresh', revision=self.revision)
        self._notify()

    def stop(self):
        if self.state != 'stopped':
            self.epoch += 1
            self._invalidate('stopped', 'quota_stopped')

    async def wait_available(self):
        while not self.poll():
            if self.state == 'stopped':
                raise QuotaUnavailable('quota_stopped')
            await self.changed.wait()

    def status(self):
        available = self.poll()
        lease = self.lease
        return dict(state=self.state, available=available, reason=self.reason,
                    revision=self.revision, write_enabled=False,
                    age_seconds=None if lease is None else max(0, self.last[0]-lease.candidate.start_mono),
                    remaining_seconds=None if lease is None else max(0, min(
                        lease.deadline_mono-self.last[0], lease.deadline_wall-self.last[1])))
