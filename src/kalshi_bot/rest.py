"""Bounded GET-only fallback. Construction/import never accesses the account.

Callers supply an explicit token budget; this module does not guess account
entitlements or start polling. No redirects, proxies, mutations or raw error logs.
"""
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal
import json
import math
import random
import re
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .transport import REST_BASE
from .observability import NO_LOG
from .values import InvalidData, integer
from .quota import QuotaGuard, QuotaRolloverPending, QuotaUnavailable, parse_candidate


@dataclass(frozen=True)
class Endpoint:
    path: str
    fields: frozenset[str]
    reasons: frozenset[str]
    authenticated: bool = True
    rows: str | None = None
    cursor: str = "cursor"
    terminal_cursor_optional: bool = False


def endpoint(path, fields, reasons, authenticated=True, rows=None, cursor="cursor",
             terminal_cursor_optional=False):
    return Endpoint(path, frozenset(fields.split()), frozenset(reasons.split()),
                    authenticated, rows, cursor, terminal_cursor_optional)


ENDPOINTS = {
    "order": endpoint("/portfolio/orders/{order_id}", "order_id", "reconcile gap"),
    "orders": endpoint("/portfolio/orders", "ticker event_ticker min_ts max_ts status limit cursor subaccount exchange_index",
                       "bootstrap reconcile gap", rows="orders"),
    "positions": endpoint("/portfolio/positions", "ticker event_ticker count_filter limit cursor subaccount exchange_index",
                          "bootstrap reconcile gap", rows="market_positions"),
    "fills": endpoint("/portfolio/fills", "ticker order_id min_ts max_ts limit cursor subaccount exchange_index",
                      "bootstrap history gap", rows="fills"),
    "historical_fills": endpoint("/historical/fills", "ticker min_ts max_ts limit cursor subaccount",
                                 "history gap", rows="fills"),
    "historical_orders": endpoint("/historical/orders", "ticker min_ts max_ts limit cursor",
                                  "history gap", rows="orders"),
    "cutoff": endpoint("/historical/cutoff", "", "history gap", False),
    "balance": endpoint("/portfolio/balance", "subaccount exchange_index", "bootstrap reconcile cash"),
    "queue_positions": endpoint("/portfolio/orders/queue_positions",
                                "market_tickers event_ticker subaccount", "reflection"),
    "settlements": endpoint("/portfolio/settlements",
                            "limit cursor ticker event_ticker min_ts max_ts subaccount",
                            "bootstrap reconcile cash", rows="settlements"),
    "subaccount_transfers": endpoint("/portfolio/subaccounts/transfers", "limit cursor",
                                     "bootstrap reconcile cash", rows="transfers",
                                     terminal_cursor_optional=True),
    "intra_exchange_transfers": endpoint("/portfolio/intra_exchange_instance_transfers",
                                         "limit cursor", "bootstrap reconcile cash",
                                         rows="transfers", terminal_cursor_optional=True),
    "deposits": endpoint("/portfolio/deposits", "limit cursor",
                         "bootstrap reconcile cash", rows="deposits",
                         terminal_cursor_optional=True),
    "withdrawals": endpoint("/portfolio/withdrawals", "limit cursor",
                            "bootstrap reconcile cash", rows="withdrawals",
                            terminal_cursor_optional=True),
    "limits": endpoint("/account/limits", "", "budget"),
    "costs": endpoint("/account/endpoint_costs", "", "budget", False),
    "incentives": endpoint("/incentive_programs", "status type incentive_description limit cursor",
                           "incentives", False, "incentive_programs", "next_cursor"),
    "markets": endpoint("/markets", "tickers status mve_filter limit cursor",
                        "candidate", False, "markets"),
    "events": endpoint("/events", "tickers limit cursor with_nested_markets with_milestones",
                       "metadata", False, "events"),
    "milestones": endpoint("/milestones", "minimum_start_date limit cursor",
                           "candidate", False, "milestones"),
    "market": endpoint("/markets/{ticker}", "ticker", "metadata", False),
    "book": endpoint("/markets/{ticker}/orderbook", "ticker depth", "canary", False),
    "event": endpoint("/events/{event_ticker}", "event_ticker", "metadata", False),
    "series": endpoint("/series/{series_ticker}", "series_ticker", "metadata", False),
    "milestone": endpoint("/milestones/{milestone_id}", "milestone_id", "metadata", False),
    "event_fees": endpoint("/events/fee_changes", "event_ticker limit cursor", "metadata", False, "event_fee_changes"),
    "series_fees": endpoint("/series/fee_changes", "series_ticker", "metadata", False),
}


def request_path(name: str, params: dict, reason: str) -> tuple[Endpoint, str]:
    spec = ENDPOINTS.get(name)
    if spec is None or reason not in spec.reasons or set(params)-spec.fields:
        raise InvalidData("unsupported read, parameters or fallback reason")
    query = dict(params)
    path = spec.path
    scoped = {'market': 'ticker', 'book': 'ticker', 'order': 'order_id', 'event': 'event_ticker',
              'series': 'series_ticker', 'milestone': 'milestone_id'}
    if name in scoped:
        key = scoped[name]
        value = query.pop(key, None)
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,199}", value):
            raise InvalidData("invalid scoped read path")
        path = path.replace("{"+key+"}", value)
    for key, value in query.items():
        if key in {"limit", "depth", "min_ts", "max_ts", "subaccount", "exchange_index"}:
            ceiling = 1000 if key in {"limit", "depth"} else 2**63-1
            if name == 'events' and key == 'limit':
                ceiling = 200
            integer(value, 1 if key in {"limit", "depth"} else 0, ceiling)
        elif name == 'events' and key in {'with_nested_markets', 'with_milestones'}:
            if value not in ('true', 'false'):
                raise InvalidData('explicit event query boolean required')
        elif not isinstance(value, str) or len(value) > 2048 or any(ord(c) < 32 for c in value):
            raise InvalidData("invalid query value")
    if "min_ts" in query and "max_ts" in query and query["min_ts"] > query["max_ts"]:
        raise InvalidData("inverted history range")
    if query:
        path += "?" + urlencode(sorted(query.items()))
    return spec, path


class TokenBudget:
    """Shared read-token bucket. Elapsed time is scheduling, never money math."""
    def __init__(self, *, rate: int, capacity: int, default_cost: int, costs=None,
                 clock=time.monotonic, sleep=asyncio.sleep, initial_tokens=None,
                 background_reserve=0, waiter_limit=128, restriction_sink=None):
        self.rate = integer(rate, 1, 1000000)
        self.capacity = integer(capacity, 1, 1000000)
        self.default_cost = integer(default_cost, 1, self.capacity)
        self.costs = dict(costs or {})
        if len(self.costs) > 2048:
            raise InvalidData("cost table too large")
        for path, cost in self.costs.items():
            if not isinstance(path, str) or not path.startswith("/") or len(path) > 300:
                raise InvalidData("invalid cost route")
            integer(cost, 1, 1000000)
        self.clock, self.sleep = clock, sleep
        self.tokens = float(self.capacity if initial_tokens is None else integer(initial_tokens,0,self.capacity))
        self.updated = clock()
        self.blocked_until = self.updated
        self.spent = 0
        self.background_reserve = integer(background_reserve, 0, self.capacity)
        self.waiter_limit = integer(waiter_limit, 1, 1024)
        self.waiters = {}
        self.changed = asyncio.Event()
        self.serial = self.throttles = self.configuration_revision = 0
        self.configured_at = None
        self._quota_owner = None
        if restriction_sink is not None and not callable(restriction_sink):
            raise InvalidData('restriction sink must be callable')
        self.restriction_sink = restriction_sink

    def _wake_waiters(self):
        previous = self.changed
        self.changed = asyncio.Event()
        previous.set()

    async def _wait_for_refill_or_change(self, delay, changed):
        timer = asyncio.create_task(self.sleep(delay))
        signal = asyncio.create_task(changed.wait())
        try:
            done, _ = await asyncio.wait((timer, signal), return_when=asyncio.FIRST_COMPLETED)
            if timer in done:
                timer.result()
        finally:
            for task in (timer, signal):
                if not task.done():
                    task.cancel()
            await asyncio.gather(timer, signal, return_exceptions=True)

    @classmethod
    def from_documents(cls, limits: dict, costs: dict, **kwargs):
        try:
            rows = costs["endpoint_costs"]
            if not isinstance(rows, list) or len(rows) > 2048:
                raise InvalidData("invalid endpoint costs")
            overrides = {}
            for row in rows:
                if row["method"] != "GET":
                    continue
                path = row["path"]
                # API cost routes may include the API prefix; normalize once.
                if path.startswith("/trade-api/v2/"):
                    path = path[len("/trade-api/v2"):]
                if path in overrides:
                    raise InvalidData("duplicate cost route")
                overrides[path] = row["cost"]
            # A published capacity is NOT the account's current available balance.
            kwargs.setdefault('initial_tokens', 0)
            kwargs.setdefault('background_reserve', min(costs['default_cost'], limits['read']['bucket_capacity']))
            return cls(rate=limits["read"]["refill_rate"], capacity=limits["read"]["bucket_capacity"],
                       default_cost=costs["default_cost"], costs=overrides, **kwargs)
        except (KeyError, TypeError, AttributeError) as exc:
            raise InvalidData("incomplete budget documents") from exc

    async def acquire(self, route: str, deadline: float, *, priority=0, _check=None):
        integer(priority, -1 if _check is not None else 0, 1)
        if self._quota_owner is not None and _check is None:
            raise QuotaUnavailable('quota_owner_required')
        if not math.isfinite(deadline) or len(self.waiters) >= self.waiter_limit:
            raise InvalidData('read budget deadline/waiter capacity invalid')
        self.serial += 1
        ticket = self.serial
        self.waiters[ticket] = priority
        self._wake_waiters()
        try:
            while True:
                revision = _check() if _check is not None else None
                now = self.clock()
                if not math.isfinite(now) or now < self.updated or now >= deadline:
                    raise InvalidData("read budget clock/deadline failure")
                cost = self.costs.get(route, self.default_cost)
                if cost > self.capacity:
                    raise InvalidData("endpoint cost exceeds available burst budget")
                self.tokens = min(self.capacity, self.tokens + (now-self.updated)*self.rate)
                self.updated = now
                first = min(self.waiters, key=lambda key:(self.waiters[key],key))
                if first != ticket:
                    # Followers wait for a queue/config change, not a polling loop.
                    await asyncio.wait_for(self.changed.wait(), deadline-now)
                    continue
                required = min(self.capacity, cost+(self.background_reserve if priority == 1 else 0))
                delay = max(0, self.blocked_until-now, (required-self.tokens)/self.rate)
                if not delay:
                    self.tokens -= cost
                    self.spent += cost
                    return revision
                # Avoid sub-ULP fake/real-clock sleeps that cannot advance time.
                # Round WAIT upward; never grant a token tolerance/overspend.
                delay = max(delay, .000001)
                if now+delay >= deadline:
                    raise InvalidData("read budget deadline exhausted")
                await self._wait_for_refill_or_change(delay, self.changed)
        finally:
            self.waiters.pop(ticket, None)
            self._wake_waiters()

    def reconfigure(self, limits, costs, *, _owner=None):
        if self._quota_owner is not None and _owner is not self._quota_owner:
            raise QuotaUnavailable('quota_owner_required')
        replacement = type(self).from_documents(limits, costs, clock=self.clock, sleep=self.sleep)
        self.rate, self.capacity = replacement.rate, replacement.capacity
        self.default_cost, self.costs = replacement.default_cost, replacement.costs
        self.background_reserve = replacement.background_reserve
        self.tokens, self.updated = 0., self.clock()
        self.configuration_revision += 1
        self.configured_at = self.updated
        self._wake_waiters()

    def status(self):
        return dict(rate=self.rate, capacity=self.capacity, spent=self.spent, queued=len(self.waiters),
            background_reserve=self.background_reserve, throttles=self.throttles,
            configuration_revision=self.configuration_revision, local_estimate_only=True,
            configuration_age_seconds=(None if self.configured_at is None else self.clock()-self.configured_at))

    def throttle(self, delay: float):
        if type(delay) not in (int,float) or not math.isfinite(delay) or delay<0:
            raise InvalidData('invalid throttle delay')
        self.tokens = 0
        self.updated = self.clock()
        self.blocked_until = max(self.blocked_until, self.updated+delay)
        self.throttles += 1
        if self.restriction_sink is not None and delay:
            self.restriction_sink('read_shared_429', delay)
        self._wake_waiters()


class PublicDiscoveryBudget(TokenBudget):
    """Local unauthenticated pacing, not an account entitlement.

    Start without banked tokens and retain 429 backoff across different URLs.
    Concurrent failures in one pause window reduce the rate only once.
    Authenticated, document-derived read budgets never use this policy.
    """
    def __init__(self, *, clock=time.monotonic, sleep=asyncio.sleep):
        super().__init__(rate=50, capacity=1, default_cost=1,
                         initial_tokens=0, clock=clock, sleep=sleep)

    def throttle(self, delay):
        previous_deadline = self.blocked_until
        super().throttle(delay)
        if self.updated >= previous_deadline:
            self.rate = max(1, self.rate//2)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


@dataclass(frozen=True)
class WireResponse:
    status: int
    body: bytes


def get_wire(url: str, headers: dict, max_bytes: int) -> WireResponse:
    """Blocking worker function; bounded body, no auth forwarding on redirects."""
    opener = build_opener(ProxyHandler({}), NoRedirect())
    request = Request(url, headers=headers, method="GET")
    deadline = time.monotonic()+10
    try:
        response = opener.open(request, timeout=5)
    except HTTPError as exc:
        status = exc.code
        exc.close()
        return WireResponse(status, b"")
    with response:
        body = bytearray()
        while True:
            if time.monotonic() > deadline:
                raise InvalidData("read response deadline exhausted")
            part = response.read1(min(65536, max_bytes+1-len(body)))
            body.extend(part)
            if len(body) > max_bytes:
                raise InvalidData("read response byte limit exceeded")
            if not part:
                return WireResponse(response.status, bytes(body))


def decode(body: bytes) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise InvalidData("duplicate JSON key")
            result[key] = value
        return result

    def invalid_constant(_):
        raise InvalidData("non-finite JSON number")

    try:
        payload = json.loads(body, parse_float=Decimal, parse_constant=invalid_constant,
                             object_pairs_hook=pairs)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise InvalidData("invalid read response JSON") from exc
    if not isinstance(payload, dict):
        raise InvalidData("read response must be an object")
    return payload


@dataclass(frozen=True)
class ReadResult:
    payload: dict
    wire_bytes: int


class ReadFailure(InvalidData):
    """Structured HTTP status only; never retain response bodies or credentials."""
    def __init__(self, status: int):
        self.status = integer(status, 100, 599)
        super().__init__(f"read failed with HTTP {status}; no proof obtained")


class ReadTransportUnavailable(InvalidData):
    """Sanitized transient transport failure; never carries its raw cause."""


@dataclass(frozen=True)
class PageSet:
    rows: tuple[dict, ...]
    pages: int
    wire_bytes: int
    source: str | None = None
    query: tuple[tuple[str, object], ...] = ()
    exhausted: bool = False
    # Exhausting cursors is NOT an atomic exchange snapshot/history guarantee.


class RestReads:
    def __init__(self, budget: TokenBudget, signer=None, *, wire=get_wire,
                 inflight_limit=32, concurrency=2, max_bytes=2097152,
                 jitter=random.random, diagnostics=NO_LOG):
        self.diagnostics = diagnostics
        self.budget, self.signer, self.wire = budget, signer, wire
        self.inflight_limit = integer(inflight_limit, 1, 128)
        self.background_limit = max(1, self.inflight_limit-2)
        self.background_inflight = 0
        self.max_bytes = integer(max_bytes, 1, 4194304)
        self.slots = asyncio.Semaphore(integer(concurrency, 1, 4))
        self.background_slots = asyncio.Semaphore(max(1, concurrency-1))
        self.inflight = {}
        self.closed = False
        self.jitter = jitter
        self.budget_refresh = None
        self.quota = None
        self.quota_supervisor = None
        self.write_quota_source = None  # Optional offline consumer of this same pair.
        self.used = False
        self.concurrency = concurrency
        self._quota_owner = object()
        self._slot_waiters = {}
        self._slot_serial = self._slot_used = self._background_used = 0
        self._slot_changed = asyncio.Event()
        self._health_wake = asyncio.Event()
        self._health_task = None
        self._health_error = None
        self._control_scope = None
        self._control_tasks = set()
        self._signer_identity = signer
        self._close_task = None

    def attach_quota(self, guard):
        if (self.used or self.closed or self.quota is not None or not isinstance(guard, QuotaGuard)
                or self.inflight_limit < 3 or self.concurrency < 2 or guard.clock is not self.budget.clock
                or self.budget._quota_owner is not None or self.budget.spent or self.budget.waiters):
            raise InvalidData('quota requires unused shared reads, matching clock and reserved capacity')
        self.quota = guard
        self.budget._quota_owner = self._quota_owner
        guard.bind(self._install_quota)
        guard.listen(self._quota_changed)

    def _install_quota(self, candidate):
        if candidate is not None:
            limits, costs = candidate.documents()
        else:
            probe = self.quota.policy.probe
            rate, capacity = probe.rate, probe.capacity
            route_costs = {'/account/limits': probe.limits_cost, '/account/endpoint_costs': probe.costs_cost}
            previous = self.quota.lease
            if previous is not None:
                old = previous.candidate
                rate, capacity = min(rate, old.read_rate), min(capacity, old.read_capacity)
                old_costs = dict(old.costs)
                route_costs = {path: max(cost, old_costs.get(path, old.default_cost))
                               for path, cost in route_costs.items()}
            limits = dict(read=dict(refill_rate=rate, bucket_capacity=capacity))
            costs = dict(default_cost=min(capacity, max(route_costs.values())), endpoint_costs=[
                dict(method='GET', path=path, cost=cost) for path, cost in route_costs.items()])
        self.budget.reconfigure(limits, costs, _owner=self._quota_owner)

    def _quota_changed(self):
        self.budget._wake_waiters()
        self._wake_slots()
        self._health_wake.set()

    def _wake_slots(self):
        old, self._slot_changed = self._slot_changed, asyncio.Event()
        old.set()

    def _guard(self, route, control_scope=None):
        if self._health_error is not None:
            raise InvalidData('quota clock supervision failed') from None
        if self.quota is None:
            return None
        if self.signer is not self._signer_identity:
            self.quota.stop()
            raise QuotaUnavailable('quota_scope_changed')
        control = control_scope is not None and control_scope is self._control_scope
        if control_scope is not None and not control:
            raise QuotaUnavailable('quota_candidate_superseded')
        return self.quota.check(route, control=control)

    def _ensure_health(self):
        if self.quota is not None and (self._health_task is None or self._health_task.done()):
            self._health_task = asyncio.create_task(self._watch_quota(), name='kalshi-quota-clock')
            self._health_task.add_done_callback(self._health_finished)

    def _health_finished(self, task):
        if not task.cancelled():
            error = task.exception()
            if error is not None:
                self._health_error = error
                try:
                    self.quota.stop()
                except Exception:
                    # Preserve the original supervised error without emitting
                    # raw callback exception text through asyncio.
                    pass
                self._quota_changed()

    async def _watch_quota(self):
        while not self.closed and (self.inflight or self.budget_refresh is not None):
            self._health_wake.clear()
            self.quota.poll()
            self.budget._wake_waiters()
            self._wake_slots()
            delay = 1.
            if self.quota.state == 'fresh':
                delay = max(.000001, min(delay, self.quota.lease.deadline_mono-self.budget.clock()))
            try:
                await asyncio.wait_for(self._health_wake.wait(), delay)
            except TimeoutError:
                pass

    async def _refresh_quota(self):
        epoch, sequence, start = self.quota.begin()
        write_source = self.write_quota_source
        if write_source is not None:
            write_source.invalidate('write_quota_refreshing')
        scope = object()
        self._control_scope = scope
        self.diagnostics.emit('quota_refresh_started', attempt=sequence)
        try:
            async with asyncio.timeout(self.quota.policy.pair_timeout):
                costs = await self._read('costs', reason='budget', coalesce_scope=(self.quota.scope, epoch, sequence),
                                         _control_scope=scope)
                limits = await self._read('limits', reason='budget', coalesce_scope=(self.quota.scope, epoch, sequence),
                                          _control_scope=scope)
                candidate = parse_candidate(limits.payload, costs.payload, scope=self.quota.scope,
                    epoch=epoch, sequence=sequence, start=start, end=self.quota._sample())
                write_snapshot = (None if write_source is None else write_source.prepare(
                    limits.payload, costs.payload, candidate))
                self.quota.install(candidate)
                if write_source is not None:
                    write_source.install(write_snapshot, candidate)
                return dict(read=self.budget.status(), write=dict(rate=candidate.write_rate,
                    capacity=candidate.write_capacity), write_enabled=False, quota=self.quota.status())
        except BaseException:
            if write_source is not None:
                write_source.invalidate('write_quota_refresh_failed')
            raise
        finally:
            # Revoke the pair first, then join actual work. No replacement pair
            # can start while a timed-out/cancelled worker is still draining.
            self._control_scope = None
            self._quota_changed()
            if self._control_tasks:
                # A pair timeout must retain ownership of already dispatched I/O.
                await asyncio.wait(tuple(self._control_tasks))

    async def refresh_budget(self):
        """Explicit account-scoped GET bootstrap/refresh, never a per-market poll.

        Caller supplies the initial conservative budget and signer. No credentials
        are loaded here. Both documents must validate before shared reconfiguration.
        """
        if self.quota_supervisor is not None:
            return await self.quota_supervisor.refresh()
        return await self._refresh_budget_owned()

    async def _refresh_budget_owned(self):
        if self.closed:
            raise InvalidData('read service closed')
        self.used = True
        if self.budget_refresh is None:
            async def refresh():
                limits, costs = await asyncio.gather(self.read('limits', reason='budget'),
                                                    self.read('costs', reason='budget'))
                # Retain write limits as information only; no write transport/bucket
                # or shard routing can be authorized by reading a quota document.
                try:
                    write = dict(rate=integer(limits.payload['write']['refill_rate'],1,1000000),
                                 capacity=integer(limits.payload['write']['bucket_capacity'],1,1000000))
                except (KeyError, TypeError) as exc:
                    raise InvalidData('incomplete account write quota document') from exc
                self.budget.reconfigure(limits.payload, costs.payload)
                self.diagnostics.emit('read_budget_updated', revision=self.budget.configuration_revision)
                return dict(read=self.budget.status(), write=write, write_enabled=False)
            task = asyncio.create_task(self._refresh_quota() if self.quota is not None else refresh())
            self.budget_refresh = task
            def done(result):
                if self.budget_refresh is result:
                    self.budget_refresh = None
                if not result.cancelled():
                    error = result.exception()
                    if isinstance(error, QuotaRolloverPending):
                        return
                    if error is not None:
                        self.diagnostics.emit('read_budget_failed',error=error)
            task.add_done_callback(done)
            self._ensure_health()
        task = self.budget_refresh
        await asyncio.wait((task,))
        return deepcopy(task.result())

    def _wire_read(self, spec, path):
        headers = {"Accept": "application/json", "Accept-Encoding": "identity"}
        if spec.authenticated:
            if self.signer is None:
                raise InvalidData("authenticated read requires an explicitly supplied signer")
            headers.update(self.signer.headers("GET", "/trade-api/v2"+path))
        response = self.wire(REST_BASE+path, headers, self.max_bytes)
        if response.status == 200:
            if not isinstance(response.body, bytes) or len(response.body) > self.max_bytes:
                raise InvalidData("invalid or oversized wire response")
            # Decode large pages off the event loop as well as blocking I/O.
            return ReadResult(decode(response.body), len(response.body))
        return response

    @asynccontextmanager
    async def _slot(self, background, *, check=None, control=False, deadline=None):
        if self.quota is not None:
            self._slot_serial += 1
            ticket = self._slot_serial
            self._slot_waiters[ticket] = -1 if control else int(background)
            self._wake_slots()
            acquired = False
            try:
                while True:
                    check()
                    eligible = [key for key, priority in self._slot_waiters.items()
                                if priority < 1 or self._background_used < self.concurrency-1]
                    if (self._slot_used < self.concurrency and eligible and
                            min(eligible, key=lambda k:(self._slot_waiters[k], k)) == ticket):
                        self._slot_waiters.pop(ticket)
                        self._slot_used += 1
                        self._background_used += int(background)
                        acquired = True
                        self._wake_slots()
                        break
                    remaining = deadline-self.budget.clock()
                    if remaining <= 0:
                        raise InvalidData('read slot deadline exhausted')
                    await asyncio.wait_for(self._slot_changed.wait(), remaining)
                yield
            finally:
                self._slot_waiters.pop(ticket, None)
                if acquired:
                    self._slot_used -= 1
                    self._background_used -= int(background)
                self._wake_slots()
            return
        if background:
            await self.background_slots.acquire()
        try:
            async with self.slots:
                yield
        finally:
            if background:
                self.background_slots.release()

    async def _fetch(self, spec, path, background=False, control_scope=None):
        deadline = self.budget.clock()+30
        check = (lambda: self._guard(spec.path, control_scope)) if self.quota is not None else None
        for attempt in range(3):
            async with self._slot(background, check=check, control=control_scope is not None, deadline=deadline):
                revision = await self.budget.acquire(spec.path, deadline,
                    priority=-1 if control_scope is not None else int(background), _check=check)
                # No await between debit and dispatch; same configuration revision.
                if check is not None and check() != revision:
                    raise QuotaUnavailable('quota_revision_changed')
                try:
                    response = await asyncio.to_thread(self._wire_read, spec, path)
                except Exception as exc:
                    self.diagnostics.emit('rest_transport_failed', error=exc, endpoint=spec.path, attempt=attempt+1)
                    raise ReadTransportUnavailable(
                        "read transport failed; no proof obtained") from None
            delay = 0.5 * 2**attempt + 0.25*self.jitter()
            if isinstance(response, WireResponse) and response.status == 429:
                # The shared account pause still matters if this caller timed out.
                self.budget.throttle(delay)
            if check is not None and check() != revision:
                raise QuotaUnavailable('quota_revision_changed')
            if self.budget.clock() > deadline:
                raise InvalidData("read operation deadline exhausted")
            if isinstance(response, ReadResult):
                return response
            if response.status not in {429, 500, 502, 503, 504} or attempt == 2:
                self.diagnostics.emit('rest_failed', endpoint=spec.path, http_status=response.status, attempt=attempt+1)
                raise ReadFailure(response.status)
            self.diagnostics.emit('rest_retry', endpoint=spec.path, http_status=response.status, attempt=attempt+1)
            if response.status != 429:
                await self.budget.sleep(delay)
        raise AssertionError("unreachable")

    async def read(self, name: str, *, reason: str, coalesce_scope=None, **params) -> ReadResult:
        if '_control_scope' in params:
            raise InvalidData('unsupported read parameters')
        return await self._read(name, reason=reason, coalesce_scope=coalesce_scope, **params)

    async def _read(self, name: str, *, reason: str, coalesce_scope=None, _control_scope=None, **params):
        if self.closed:
            raise InvalidData("read service closed")
        spec, path = request_path(name, params, reason)
        self.used = True
        revision = self._guard(spec.path, _control_scope)
        try:
            hash(coalesce_scope)
        except TypeError as exc:
            raise InvalidData('invalid read coalescing scope') from exc
        key = (name, path, coalesce_scope, revision)
        task = self.inflight.get(key)
        if task is None:
            background = reason in {'metadata','incentives','reflection'}
            admission_limit = self.inflight_limit-int(self.quota is not None and _control_scope is None)
            if (len(self.inflight) >= admission_limit or
                    (background and self.background_inflight >= self.background_limit)):
                raise InvalidData("read in-flight budget exceeded")
            task = asyncio.create_task(self._fetch(spec, path, background, _control_scope))
            self.inflight[key] = task
            if _control_scope is not None:
                self._control_tasks.add(task)
            if background:
                self.background_inflight += 1

            def finished(done):
                self._control_tasks.discard(done)
                if self.inflight.get(key) is done:
                    self.inflight.pop(key)
                    if background:
                        self.background_inflight -= 1
                if not done.cancelled():
                    done.exception()
            task.add_done_callback(finished)
            self._ensure_health()
        # Cancellation of one caller cannot cancel a shared request or free a
        # thread slot while its blocking I/O is still running.
        await asyncio.wait((task,))
        result = task.result()
        if self._guard(spec.path, _control_scope) != revision:
            raise QuotaUnavailable('quota_revision_changed')
        return ReadResult(deepcopy(result.payload), result.wire_bytes)

    async def collect(self, name: str, *, reason: str, max_pages=50,
                      coalesce_scope=None,
                      max_rows=10000, byte_limit=8388608, **params) -> PageSet:
        integer(max_pages, 1, 100)
        integer(max_rows, 1, 10000)
        integer(byte_limit, 1, 16777216)
        spec, _ = request_path(name, params, reason)
        if spec.rows is None or "cursor" in params:
            raise InvalidData("complete enumeration requires a paged endpoint and first page")
        initial_query = tuple(sorted(params.items()))
        params = {"limit": 100, **params}
        rows, cursors, size = [], set(), 0
        deadline = self.budget.clock()+30
        for page in range(1, max_pages+1):
            if self.budget.clock() >= deadline:
                raise InvalidData("enumeration deadline exhausted; result is incomplete")
            result = await self.read(name, reason=reason, coalesce_scope=coalesce_scope, **params)
            if self.budget.clock() > deadline:
                raise InvalidData("enumeration deadline exhausted; result is incomplete")
            data = result.payload.get(spec.rows)
            cursor_missing = spec.cursor not in result.payload
            if (name in {"orders", "positions", "historical_orders", "fills", "historical_fills",
                         "settlements", "subaccount_transfers", "intra_exchange_transfers",
                         "deposits", "withdrawals", "event_fees"} and cursor_missing
                    and not (spec.terminal_cursor_optional and isinstance(data, list)
                             and len(data) < params["limit"])):
                raise InvalidData("required pagination cursor missing; result is incomplete")
            cursor = result.payload.get(spec.cursor, "")  # Some terminal cash pages omit it.
            if (not isinstance(data, list) or any(not isinstance(row, dict) for row in data)
                    or not isinstance(cursor, str) or len(cursor) > 2048):
                raise InvalidData("invalid page rows or cursor")
            size += result.wire_bytes
            if size > byte_limit or len(rows)+len(data) > max_rows:
                raise InvalidData("pagination resource limit; result is incomplete")
            rows.extend(data)
            if not cursor:
                return PageSet(tuple(rows), page, size, name, initial_query, True)
            if cursor in cursors:
                raise InvalidData("pagination cursor cycle; result is incomplete")
            cursors.add(cursor)
            params["cursor"] = cursor
        raise InvalidData("page budget exhausted; result is incomplete")

    async def close(self):
        self.closed = True
        if self.quota is not None:
            self.quota.stop()
            self._quota_changed()
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close_owned(), name='kalshi-rest-close')
            def finished(task):
                if not task.cancelled():
                    error = task.exception()
                    if error is not None:
                        self.diagnostics.emit('rest_close_failed', error=error)
            self._close_task.add_done_callback(finished)
        await asyncio.shield(self._close_task)

    async def _close_owned(self):
        if self.budget_refresh is not None:
            await asyncio.wait((self.budget_refresh,))
        if self._control_tasks:
            await asyncio.wait(tuple(self._control_tasks))
        if self.inflight:
            await asyncio.wait(tuple(self.inflight.values()))
        if self._health_task is not None:
            await asyncio.wait((self._health_task,))
