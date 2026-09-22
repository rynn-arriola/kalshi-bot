"""Offline, caller-driven write budget primitive; no scheduler or live authority.

Only explicit event-order POST / DELETE operations are modeled. One owner must
share this instance across subaccounts and clients of its account. QuotaScope is
an opaque identity, not proof of account ownership or protection against cloning
budgets in other instances/processes. No I/O, clocks, sleeps, retries or tasks are
owned here. All clock pairs are (monotonic seconds, UTC Unix seconds).
"""
from dataclasses import dataclass, field
from fractions import Fraction
from functools import lru_cache
import math
import re

from .quota import QuotaScope, QuotaUnavailable, parse_candidate
from .values import InvalidData, integer


ORDERS = '/portfolio/events/orders'
BATCH_ORDERS = ORDERS + '/batched'
CANCEL = ORDERS + '/{order_id}'
_METHODS = frozenset(('GET', 'POST', 'DELETE', 'PUT', 'PATCH', 'HEAD', 'OPTIONS'))
_SEGMENT = re.compile(
    r'(?:[A-Za-z0-9_.-]+|\{[A-Za-z_][A-Za-z0-9_]*\}|:[A-Za-z_][A-Za-z0-9_]*|\*[A-Za-z_][A-Za-z0-9_]*)')


def _number(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise InvalidData('finite nonnegative clock/duration required')
    return Fraction(value)


def _pair(value):
    if type(value) not in (tuple, list) or len(value) != 2:
        raise InvalidData('monotonic and UTC clock pair required')
    return tuple(_number(part) for part in value)


def _route(method, path):
    if type(method) is not str or method not in _METHODS:
        raise InvalidData('canonical HTTP method required')
    if type(path) is not str or len(path) > 300 or not path.startswith('/'):
        raise InvalidData('invalid cost route')
    if path.startswith('/trade-api/v2/'):
        path = path[len('/trade-api/v2'):]
    parts = path[1:].split('/')
    if any(part in ('.', '..') or not _SEGMENT.fullmatch(part) for part in parts):
        raise InvalidData('invalid cost route')
    # Current venue cost documents use Express-style ``:name`` templates,
    # while older fixtures/OpenAPI use ``{name}``.  Store one canonical key.
    parts = ['{'+part[1:]+'}' if part.startswith(':') else part for part in parts]
    return '/'+('/'.join(parts))


@lru_cache(maxsize=512)
def _operation_cached(method, route):
    route = _route(method, route)
    if method == 'POST' and route in {ORDERS, BATCH_ORDERS}:
        return route, route
    if method == 'DELETE' and route.startswith(ORDERS + '/'):
        order_id = route[len(ORDERS) + 1:]
        if (order_id != 'batched' and
                re.fullmatch(r'[A-Za-z0-9_-]+', order_id)):
            return route, CANCEL
    raise InvalidData('unsupported single event-order operation')


def _operation(method, route):
    # Validate hashability/types before entering the bounded cache so malformed
    # caller input retains the public InvalidData contract.
    if type(method) is not str or type(route) is not str:
        raise InvalidData('canonical HTTP method and route required')
    return _operation_cached(method, route)


@dataclass(frozen=True, init=False)
class WriteQuotaSnapshot:
    """Immutable evidence parsed from both full injected documents.

    TTL is local fixture policy, measured from the START of observation, not a
    venue guarantee. Grant expiry uses the earliest event_contract grant; absent
    expiry is permanent and unknown/null event expiry fails closed.
    """
    scope: QuotaScope
    epoch: int
    sequence: int
    start: tuple
    end: tuple
    ttl: Fraction
    rate: int
    capacity: int
    default_cost: int
    costs: tuple
    grant_expiry: int | None
    _deadlines: tuple

    def __init__(self, limits, costs, *, scope, epoch, sequence, start, end, ttl):
        start_pair, end_pair = _pair(start), _pair(end)
        lifetime = _number(ttl)
        if not 0 < lifetime <= 3600:
            raise InvalidData('TTL must be positive and at most 3600 seconds')
        candidate = parse_candidate(limits, costs, scope=scope, epoch=epoch,
                                    sequence=sequence, start=start, end=end)
        overrides = {}
        # candidate.costs is GET-only and must never supply write costs.
        for row in costs['endpoint_costs']:
            key = (row['method'], _route(row['method'], row['path']))
            if key in overrides:
                raise InvalidData('duplicate normalized method/route cost')
            overrides[key] = integer(row['cost'], 1, 1000000)
        values = dict(scope=scope, epoch=epoch, sequence=sequence,
                      start=start_pair, end=end_pair, ttl=lifetime,
                      rate=candidate.write_rate, capacity=candidate.write_capacity,
                      default_cost=candidate.default_cost,
                      costs=tuple(sorted(overrides.items())),
                      grant_expiry=candidate.grant_expiry)
        for name, value in values.items():
            object.__setattr__(self, name, value)
        mono, wall = (stamp + self.ttl for stamp in self.start)
        if self.grant_expiry is not None:
            wall = min(wall, self.grant_expiry)
            mono = min(mono, self.start[0] + self.grant_expiry - self.start[1])
        object.__setattr__(self, '_deadlines', (mono, wall))

    @property
    def deadlines(self):
        return self._deadlines


@dataclass(frozen=True, slots=True)
class WritePermit:
    method: str
    route: str
    shard: int
    revision: int
    cost: int


@dataclass(frozen=True)
class WriteBudgetStatus:
    """Local telemetry only; fresh evidence is not permission to trade."""
    revision: int
    reason: str | None
    outstanding: int
    # (shard, exact available local tokens, reserved cost, pause seconds left)
    buckets: tuple
    live_ready: bool = field(default=False, init=False)


@dataclass
class _Bucket:
    updated: Fraction
    tokens: Fraction = Fraction(0)
    held: int = 0
    pause_until: Fraction = Fraction(0)


class WriteBudget:
    """Synchronous offline primitive, NOT a queue or priority dispatcher.

    ready_delay returns a local scheduling hint, or None when no time-only path
    exists under current evidence/capacity. try_reserve debits immediately and
    returns a frozen single-use permit, or None. consume must be called without
    an intervening await immediately before any future dispatch; it checks the
    issued object AND stored terms. It does not itself authorize/send an order.
    Discard/expiry never refund. Refresh resets tokens and permits, retaining
    each shard's injected 429 pause. Pauses are caller policy, not venue promises.

    Clock regression (either clock) permanently latches this instance closed,
    including refresh. Recreation with newly observed evidence is required; an
    old monotonic domain cannot safely carry cooldowns into a reset clock.
    Single-owner calls only; this class provides no thread/process coordination.
    """

    def __init__(self, snapshot, *, shards, now, offline_fixture=False,
                 max_permits=128):
        if offline_fixture is not True:
            raise InvalidData('offline_fixture must be literally True')
        if type(snapshot) is not WriteQuotaSnapshot:
            raise InvalidData('explicit write quota snapshot required')
        if type(shards) not in (tuple, list, set, frozenset) or not 1 <= len(shards) <= 128:
            raise InvalidData('one to 128 explicit shards required')
        checked = [integer(shard, 0, 2**31 - 1) for shard in shards]
        if len(set(checked)) != len(checked):
            raise InvalidData('duplicate shard')
        self._max_permits = integer(max_permits, 1, 128)
        self._last = _pair(now)
        self._last_raw = tuple(now)
        self._clock_fault = False
        self._snapshot = snapshot
        self._revision = 1
        self._permits = {}
        self._buckets = {shard: _Bucket(self._last[0]) for shard in checked}
        self._validate_fresh(snapshot, self._last)
        self._costs = dict(snapshot.costs)

    @staticmethod
    def _validate_fresh(snapshot, now):
        if snapshot.end[0] > now[0] or snapshot.end[1] > now[1]:
            raise QuotaUnavailable('write_quota_future')
        if now[0] >= snapshot.deadlines[0] or now[1] >= snapshot.deadlines[1]:
            raise QuotaUnavailable('write_quota_expired')

    def _sample(self, now):
        if (type(now) in (tuple, list) and len(now) == 2 and
                all(type(new) is type(old) and new == old
                    for new, old in zip(now, self._last_raw))):
            current = self._last
        else:
            current = _pair(now)
        if current[0] < self._last[0] or current[1] < self._last[1]:
            self._clock_fault = True
        self._last = current
        self._last_raw = tuple(now)
        if self._clock_fault:
            self._clear()
            raise QuotaUnavailable('write_clock_regressed')
        return current

    def _clear(self):
        self._permits.clear()
        for bucket in self._buckets.values():
            bucket.tokens, bucket.held = Fraction(0), 0
            bucket.updated = self._last[0]

    def _poll(self, now):
        try:
            current = self._sample(now)
            self._validate_fresh(self._snapshot, current)
        except QuotaUnavailable as exc:
            self._clear()
            return exc.reason
        return None

    def _refill(self, shard):
        # Healthy hot operations touch only their shard, not the whole account.
        bucket = self._buckets[shard]
        if bucket.updated == self._last[0]:
            return bucket
        elapsed = max(Fraction(0), self._last[0] - max(bucket.updated, bucket.pause_until))
        bucket.tokens = min(self._snapshot.capacity - bucket.held,
                            bucket.tokens + elapsed * self._snapshot.rate)
        bucket.updated = self._last[0]
        return bucket

    def _terms(self, method, route, shard, units=1):
        integer(shard, 0, 2**31 - 1)
        integer(units, 1, 30)
        if shard not in self._buckets:
            raise InvalidData('shard is not configured')
        route, cost_route = _operation(method, route)
        cost = self._costs.get((method, cost_route), self._snapshot.default_cost)*units
        return route, cost

    def _readiness(self, method, route, shard, now, units=1):
        route, cost = self._terms(method, route, shard, units)
        if self._poll(now) is not None or len(self._permits) >= self._max_permits:
            return route, cost, None
        bucket = self._refill(shard)
        if cost > self._snapshot.capacity - bucket.held:
            return route, cost, None
        if bucket.pause_until <= self._last[0] and bucket.tokens >= cost:
            return route, cost, 0.0
        delay = (max(Fraction(0), bucket.pause_until - self._last[0]) +
                 max(Fraction(0), cost - bucket.tokens) / self._snapshot.rate)
        if (self._last[0] + delay >= self._snapshot.deadlines[0] or
                self._last[1] + delay >= self._snapshot.deadlines[1]):
            return route, cost, None
        return route, cost, float(delay)

    def ready_delay(self, method, route, *, shard, now, units=1):
        """Inspect readiness; no token debit. Caller rechecks after any wait."""
        return self._readiness(method, route, shard, now, units)[2]

    def try_reserve(self, method, route, *, shard, now, units=1):
        route, cost, delay = self._readiness(method, route, shard, now, units)
        if delay != 0:
            return None
        bucket = self._buckets[shard]
        # Exact comparison: a rounded scheduling hint can never grant tokens.
        if bucket.tokens < cost or self._last[0] < bucket.pause_until:
            return None
        permit = WritePermit(method, route, shard, self._revision, cost)
        self._permits[id(permit)] = (permit, self._fields(permit))
        bucket.tokens -= cost
        bucket.held += cost
        return permit

    @staticmethod
    def _fields(permit):
        return (permit.method, permit.route, permit.shard, permit.revision, permit.cost)

    def _take(self, permit):
        stored = self._permits.get(id(permit))
        if type(permit) is not WritePermit or stored is None or stored[0] is not permit:
            raise InvalidData('unknown or already used write permit')
        del self._permits[id(permit)]
        expected = stored[1]
        self._buckets[expected[2]].held -= expected[4]
        actual = self._fields(permit)
        if any(type(a) is not type(b) or a != b for a, b in zip(actual, expected)):
            raise InvalidData('altered write permit')
        return expected

    def consume(self, permit, method, route, *, shard, now, units=1):
        reason = self._poll(now)
        if reason is not None:
            raise QuotaUnavailable(reason)
        route, cost = self._terms(method, route, shard, units)
        self._refill(shard)
        expected = self._take(permit)
        if expected != (method, route, shard, self._revision, cost):
            raise InvalidData('write permit dispatch mismatch')
        if self._last[0] < self._buckets[shard].pause_until:
            raise QuotaUnavailable('write_429_pause')
        return permit

    def check_permit(self, permit, method, route, *, shard, now, units=1):
        """Check an outstanding permit before SENDING without consuming it.

        The executor must still call consume synchronously at the send edge:
        this check cannot reserve freshness across an awaited writer handoff.
        """
        reason = self._poll(now)
        if reason is not None:
            raise QuotaUnavailable(reason)
        route, cost = self._terms(method, route, shard, units)
        self._refill(shard)
        stored = self._permits.get(id(permit))
        if (type(permit) is not WritePermit or stored is None
                or stored[0] is not permit):
            raise InvalidData('unknown or already used write permit')
        expected = (method, route, shard, self._revision, cost)
        if stored[1] != expected or self._fields(permit) != expected:
            raise InvalidData('write permit dispatch mismatch')
        if self._last[0] < self._buckets[shard].pause_until:
            raise QuotaUnavailable('write_429_pause')
        return permit

    def discard(self, permit, *, now):
        reason = self._poll(now)
        if reason is not None:
            raise QuotaUnavailable(reason)
        stored = self._permits.get(id(permit))
        if stored is not None:
            self._refill(stored[1][2])
        self._take(permit)

    def discard_if_outstanding(self, permit, *, now):
        """Release a known reservation without refund; consumed is a no-op.

        This is for retained dispatcher cleanup where execution may have
        consumed the permit before raising. Malformed permit types are rejected;
        absent permits (including a copy) are no-ops and cannot authorize use.
        """
        if type(permit) is not WritePermit:
            raise InvalidData('typed write permit required')
        reason = self._poll(now)
        if reason is not None:
            return False
        stored = self._permits.get(id(permit))
        if stored is None:
            return False
        if stored[0] is not permit:
            raise InvalidData('write permit identity conflict')
        self._refill(stored[1][2])
        self._take(permit)
        return True

    def refresh(self, snapshot, *, now):
        current = self._sample(now)
        if type(snapshot) is not WriteQuotaSnapshot:
            raise InvalidData('explicit write quota snapshot required')
        old = self._snapshot
        if snapshot.scope is not old.scope:
            raise InvalidData('quota scope switch')
        if ((snapshot.epoch, snapshot.sequence) <= (old.epoch, old.sequence) or
                any(new < previous for new, previous in zip(snapshot.start, old.end))):
            raise InvalidData('reordered quota snapshot')
        self._validate_fresh(snapshot, current)
        self._snapshot = snapshot
        self._costs = dict(snapshot.costs)
        self._revision += 1
        self._clear()

    def pause_429(self, *, shard, seconds, now):
        """Apply even a late old-revision 429 to the CURRENT shard bucket."""
        integer(shard, 0, 2**31 - 1)
        if shard not in self._buckets:
            raise InvalidData('shard is not configured')
        duration = _number(seconds)
        if duration <= 0:
            raise InvalidData('positive explicit pause required')
        current = self._sample(now)
        bucket = self._buckets[shard]
        bucket.pause_until = max(bucket.pause_until, current[0] + duration)
        bucket.tokens, bucket.held, bucket.updated = Fraction(0), 0, current[0]
        self._permits = {key: item for key, item in self._permits.items()
                         if item[1][2] != shard}

    def status(self, *, now):
        reason = self._poll(now)
        if reason is None:
            for shard in self._buckets:
                self._refill(shard)
        return WriteBudgetStatus(self._revision, reason, len(self._permits), tuple(
            (shard, bucket.tokens, bucket.held,
             float(max(Fraction(0), bucket.pause_until - self._last[0])))
            for shard, bucket in sorted(self._buckets.items())))
