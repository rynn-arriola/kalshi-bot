"""D-145 Layer 1: Kalshi order groups as a venue-side cap on entry fills.

Every entry pair is created inside its exchange shard's current group. Kalshi
counts matched contracts in the group over a rolling 15 seconds; at the limit
it cancels every other order in the group and refuses new ones until reset.
That cap works with no reaction latency and while this process is offline.

Exits and reducers are never placed in a group, so a trigger can never cancel
an exit. A shard without a known, active group places no new entries (fail
closed). A trigger is reset only after a full recovery has proven the account
since the trigger, every position has a non-blocked exit plan and a settle
period has passed. A new private-stream generation abandons the old groups
(their state may have been missed) and creates fresh ones.
"""
import asyncio
from dataclasses import dataclass

from .values import InvalidData, identity, integer

# The group limit is one entry's size plus one contract: a single entry fill
# never triggers it (rewards keep running on the other markets), while a second
# order filling within Kalshi's 15-second window does, whatever Kalshi's exact
# reach/exceed boundary is.
GROUP_LIMIT_EXTRA = 1

EVENT_TYPES = frozenset(('created', 'triggered', 'reset', 'deleted', 'limit_updated'))


def group_contracts_limit():
    from .config import active
    size = active().entry_contracts
    if size != int(size):
        raise InvalidData('order group limit requires whole-contract entries')
    return int(size)+GROUP_LIMIT_EXTRA


def validate_group_request(kind, request):
    if not isinstance(request, dict):
        raise InvalidData('invalid order group request')
    if kind == 'group_create':
        if set(request) != {'subaccount', 'exchange_index', 'contracts_limit'}:
            raise InvalidData('group create requires exact scope and limit')
        integer(request['contracts_limit'], 1, 100000)
    elif kind == 'group_reset':
        if set(request) != {'order_group_id', 'subaccount', 'exchange_index'}:
            raise InvalidData('group reset requires exact group scope')
        identity(request['order_group_id'])
    else:
        raise InvalidData('unsupported order group command')
    integer(request['subaccount'], 0, 63)
    integer(request['exchange_index'], 0, 2**31-1)


@dataclass
class ShardGroup:
    shard: int
    group_id: str | None = None
    state: str = 'missing'  # missing | active | triggered
    account_generation: int | None = None
    triggered_at: float | None = None
    next_attempt: float = 0.0
    failures: int = 0


class OrderGroups:
    RETRY_SECONDS = (30, 60, 120, 300)
    RESET_SETTLE_SECONDS = 60.0
    TICK_SECONDS = 1.0
    CREATE_PATH = '/portfolio/order_groups/create'

    def __init__(self, runtime, transport, *, shards):
        self.runtime, self.transport = runtime, transport
        shards = tuple(shards)
        if not shards or len(set(shards)) != len(shards):
            raise InvalidData('order groups require distinct exchange shards')
        self.groups = {integer(s, 0, 2**31-1): ShardGroup(s) for s in shards}
        self.creates = self.resets = self.triggers = self.failures = 0
        self.unknown_updates = 0
        self.last_error = None

    # ----- entry gating -------------------------------------------------
    def group_for(self, shard):
        """The active group id for new entries on this shard, else None."""
        g = self.groups.get(shard)
        if (g is None or g.state != 'active' or g.group_id is None
                or g.account_generation != self.runtime.account.generation):
            return None
        return g.group_id

    # ----- private stream -----------------------------------------------
    def on_update(self, msg):
        """Apply one ``order_group_updates`` message; unknown groups are ignored."""
        try:
            kind, group_id = msg['event_type'], identity(msg['order_group_id'])
        except (KeyError, TypeError, InvalidData):
            self.unknown_updates += 1
            return None
        if kind not in EVENT_TYPES:
            self.unknown_updates += 1
            return None
        g = next((g for g in self.groups.values() if g.group_id == group_id), None)
        if g is None:
            self.unknown_updates += 1
            return None
        r = self.runtime
        if kind == 'triggered' and g.state != 'triggered':
            g.state, g.triggered_at = 'triggered', r.clock()
            self.triggers += 1
            r.diagnostics.emit('order_group_triggered', count=self.triggers)
            r.request_recovery('order_group_triggered')
        elif kind == 'reset' and g.state == 'triggered' and self._reset_ready(g):
            g.state, g.triggered_at = 'active', None
        elif kind == 'deleted':
            self._abandon(g)
        return kind

    def _abandon(self, g):
        g.group_id, g.state, g.triggered_at = None, 'missing', None
        g.account_generation, g.next_attempt = None, 0.0

    # ----- reset gate ---------------------------------------------------
    def _reset_ready(self, g):
        r = self.runtime
        now = r.clock()
        if g.triggered_at is None or now-g.triggered_at < self.RESET_SETTLE_SECONDS:
            return False
        recovered = r.__dict__.get('last_full_recovery_mono')
        if recovered is None or recovered <= g.triggered_at:
            return False  # A full recovery must prove the account after the trigger.
        if not r.entry_allowed:
            return False
        report = r.account.current_report(r.now())
        if report is None or not report.positions_match or report.audit.blockers:
            return False
        for row in report.snapshot.positions:
            if not row.quantity:
                continue
            plan = r.management.current(row.ticker, require_market=False)
            if (plan is None or plan.exit is None
                    or plan.exit.mode in {'attention', 'blocked'}):
                return False
        return True

    # ----- venue writes ---------------------------------------------------
    def _budget(self):
        service = self.runtime.dispatch_supervisor
        if service is None:
            raise InvalidData('order groups require the dispatcher write budget')
        return service.dispatcher.budget, service.dispatcher.clock_pair

    async def _write(self, shard, method, route, kind, request):
        budget, clock_pair = self._budget()
        permit = budget.try_reserve(method, route, shard=shard, now=clock_pair())
        if permit is None:
            return None  # Budget busy: retry on a later tick, not a failure.
        try:
            budget.consume(permit, method, route, shard=shard, now=clock_pair())
            return await self.transport.order_group(kind, request)
        finally:
            budget.discard_if_outstanding(permit, now=clock_pair())

    def _failed(self, g, exc):
        g.failures += 1
        self.failures += 1
        self.last_error = type(exc).__name__
        delay = self.RETRY_SECONDS[min(g.failures, len(self.RETRY_SECONDS))-1]
        g.next_attempt = self.runtime.clock()+delay
        self.runtime.diagnostics.emit('order_group_failed', count=self.failures)

    async def _create(self, g):
        r = self.runtime
        generation = r.account.generation
        request = dict(subaccount=r.account.subaccount, exchange_index=g.shard,
                       contracts_limit=group_contracts_limit())
        try:
            response = await self._write(g.shard, 'POST', self.CREATE_PATH, 'group_create', request)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._failed(g, exc)
            return False
        if response is None:
            return False
        try:
            group_id = identity(response['order_group_id'])
            if integer(response.get('subaccount', request['subaccount']), 0, 63) != request['subaccount']:
                raise InvalidData('order group created outside account scope')
        except (KeyError, TypeError, InvalidData) as exc:
            self._failed(g, exc)
            return False
        if r.account.generation != generation:
            return False  # Stream changed while creating: make a fresh one.
        g.group_id, g.state, g.account_generation = group_id, 'active', generation
        g.failures, g.triggered_at = 0, None
        self.creates += 1
        r.diagnostics.emit('order_group_created', count=self.creates)
        return True

    async def _reset(self, g):
        r = self.runtime
        request = dict(order_group_id=g.group_id, subaccount=r.account.subaccount,
                       exchange_index=g.shard)
        route = '/portfolio/order_groups/'+g.group_id+'/reset'
        try:
            response = await self._write(g.shard, 'PUT', route, 'group_reset', request)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._failed(g, exc)
            return False
        if response is None:
            return False
        g.state, g.triggered_at, g.failures = 'active', None, 0
        self.resets += 1
        r.diagnostics.emit('order_group_reset', count=self.resets)
        r._entry_dirty = True
        return True

    async def tick(self):
        r = self.runtime
        for g in self.groups.values():
            if r.stop_requested.is_set():
                return
            if (g.group_id is not None and g.state != 'triggered'
                    and g.account_generation != r.account.generation):
                self._abandon(g)  # Updates may have been missed on the old stream.
            if not r.account.connected or r.clock() < g.next_attempt:
                continue
            if g.state == 'missing':
                await self._create(g)
            elif g.state == 'triggered' and self._reset_ready(g):
                if g.account_generation != r.account.generation:
                    self._abandon(g)  # A fresh group replaces an unobservable one.
                else:
                    await self._reset(g)

    async def run(self):
        r = self.runtime
        while not r.stop_requested.is_set():
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.failures += 1
                self.last_error = type(exc).__name__
            try:
                await asyncio.wait_for(r.stop_requested.wait(), self.TICK_SECONDS)
            except TimeoutError:
                pass

    def status(self):
        return dict(limit_extra_contracts=GROUP_LIMIT_EXTRA,
            shards={str(s): dict(state=g.state, active=self.group_for(s) is not None,
                                 failures=g.failures)
                    for s, g in sorted(self.groups.items())},
            creates=self.creates, resets=self.resets, triggers=self.triggers,
            failures=self.failures, unknown_updates=self.unknown_updates,
            last_error=self.last_error, reset_settle_seconds=self.RESET_SETTLE_SECONDS)
