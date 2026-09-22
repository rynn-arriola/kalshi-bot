"""Bounded offline market-scope owner; no order creation or cancellation."""
import asyncio
from dataclasses import dataclass, replace
from datetime import timedelta

from .values import InvalidData, utc


@dataclass(frozen=True)
class ScopeChange:
    name: str
    before: frozenset
    after: tuple
    catalog: object
    result: asyncio.Future


async def join_cancelled(task):
    """Retain a child through repeated caller cancellation; never detach it."""
    task.cancel()
    cancelled = False
    while not task.done():
        try:
            await asyncio.wait((task,))
        except asyncio.CancelledError:
            cancelled = True
    if not task.cancelled(): task.result()
    if cancelled: raise asyncio.CancelledError


class MarketAdmission:
    def __init__(self, runtime, *, offline_fixture=False):
        from .runtime import RecoveryRuntime
        if (not isinstance(runtime,RecoveryRuntime)
                or not (offline_fixture is True or runtime.observation_only
                        or runtime.live_components_enabled)
                or runtime.used or runtime.admission is not None or runtime.selection is None
                or runtime.incentives is None or runtime.stop_requested.is_set()):
            raise InvalidData('unused offline runtime with selection and discovery required')
        self.runtime = runtime
        self.signals = {name:asyncio.Event() for name in runtime.engine.shards}
        self.pending = None
        self.cycling = False
        self.wake = asyncio.Event()
        self.requested = True
        self.stopping = self.used = self.running = False
        self.task = None
        self.cursor = self.completed = self.deferred = 0
        self.state = 'idle'
        self.next_at = 0.
        self.interval = runtime.incentives.interval

    @property
    def transitioning(self):
        return self.pending is not None

    def request(self):
        if not self.stopping:
            self.requested = True
            self.wake.set()

    def _ready(self):
        r = self.runtime
        due = r.engine.deadlines.next_deadline()
        return (not self.stopping and not r.stop_requested.is_set()
                and (r.live_session is None or not r.live_session.entries_paused)
                and (r.dispatch_supervisor is None
                     or r.dispatch_supervisor.dispatcher.status().active is None)
                and r.selection._available() and not r.engine.running_step
                and r.recovery_state != 'recovering'
                and (due is None or due > r.clock()+1))

    def _current(self, change, report, revision, ingress):
        r = self.runtime
        return (self._ready() and r.writer.revision == revision and r.ingress_revision == ingress
                and r.account.current_report(r.now()) is report
                and r.incentives.current() is change.catalog
                and r.engine.shards[change.name].tickers == change.before)

    async def removable(self, change):
        """Fresh exact inventory proof, repeated after the old reader is joined."""
        r = self.runtime
        report = r.account.current_report(r.now())
        if not self._ready() or report is None or not report.positions_match or report.audit.blockers:
            return False
        ingress = r.ingress_revision
        view = await r.risk_view()
        if (view.epoch != r.writer.epoch or view.blockers
                or not timedelta(0) <= utc(r.now())-view.observed_at <= timedelta(seconds=5)
                or not self._current(change,report,view.revision,ingress)):
            return False
        removed = change.before-set(change.after)
        owned = {t for t,v in view.positions if v} | {t for t,v in view.exposure if v}
        owned.update(o.ticker for o in report.snapshot.orders)
        if removed & owned: return False
        for ticker in sorted(removed):
            row = await r.writer.market_inventory(ticker,subaccount=r.account.subaccount)
            journal = row.exit_journal
            if (not self._current(change,report,view.revision,ingress)
                    or (row.writer_epoch,row.writer_revision) != (view.epoch,view.revision)
                    or row.position or row.orders or row.blockers
                    or (journal is not None and (journal.unresolved_ioc or journal.cancel_ids))):
                return False
        scope = (set(r.engine.market_shard)-change.before) | set(change.after)
        candidate_inputs = r.selection.candidate_inputs
        if candidate_inputs is not None and any(
                candidate_inputs.blockers(ticker, r.now())
                for ticker in set(change.after)-change.before):
            return False
        return (len(scope) <= r.writer.market_capacity
                and (r.metadata_scheduler is None or r.metadata_scheduler.can_rebind(scope))
                and self._current(change,report,view.revision,ingress))

    async def commit_joined(self, change):
        """Called exclusively by the book-loop owner after complete reader teardown."""
        r = self.runtime
        if self.pending is not change or change.result.done() or not await self.removable(change):
            return False
        if self.pending is not change or change.result.done():
            return False  # Caller cancellation during the final writer awaits.
        removed = change.before-set(change.after)
        scope = (set(r.engine.market_shard)-change.before) | set(change.after)
        # No awaits between final source validation and the bounded scope commit.
        r.engine.replace_book_scope(change.name,change.after,capacity=r.writer.market_capacity)
        r.specs = tuple(replace(s,tickers=change.after) if s.name == change.name else s for s in r.specs)
        if r.metadata_scheduler is not None: r.metadata_scheduler.rebind_scope(scope)
        for ticker in change.after:
            r.management.unmanaged.discard(ticker)
        for ticker in removed:
            r.management.revoke_terms(ticker)
            r.management._logged_states.pop(ticker,None)
            r.management.unmanaged.discard(ticker)
            for mapping in (r.selection.programs,r.selection._last_observed,r.selection._rejected):
                mapping.pop(ticker,None)
        self.completed += 1
        return True

    async def book_loop(self, spec):
        """Stable supervised task; only its book reader is replaced."""
        r = self.runtime
        signal = self.signals[spec.name]
        while not self.stopping and not r.stop_requested.is_set():
            spec = next(s for s in r.specs if s.name == spec.name)
            signal.clear()
            child = asyncio.create_task(r._connection(spec,
                attempt_start=r.reader_failures[spec.name]),name='kalshi-scope-reader-'+spec.name)
            wake = asyncio.create_task(signal.wait())
            change = None
            try:
                done,_ = await asyncio.wait((child,wake),return_when=asyncio.FIRST_COMPLETED)
                if child in done:
                    child.result()
                    return  # Exhaustion cannot be reset by a discovery request.
                change = self.pending
                await join_cancelled(child)
                if change is not None and change.name == spec.name:
                    accepted = await self.commit_joined(change)
                    if not change.result.done(): change.result.set_result(accepted)
            finally:
                try:
                    await join_cancelled(child)
                finally:
                    await join_cancelled(wake)
                    active = self.pending
                    if active is not None and active.name == spec.name and not active.result.done():
                        active.result.set_result(False)

    async def cycle(self):
        if self.cycling: raise InvalidData('one market rotation at a time')
        self.cycling = True
        try:
            return await self._cycle()
        finally:
            self.cycling = False

    async def _cycle(self):
        r = self.runtime
        if not self._ready():
            self.state = 'deferred'
            return False
        candidates = await r.selection.discovery_candidates()
        if candidates.source is None or not self._ready():
            self.state = 'sources_unavailable'
            return False
        existing = set(r.engine.market_shard)
        desired = set(candidates.tickers)
        names = tuple(sorted(r.engine.shards))
        deferred = False
        for offset in range(len(names)):
            name = names[(self.cursor+offset) % len(names)]
            if r.reader_states[name] != 'subscribed' or r.reader_failures[name] >= r.attempt_limit:
                deferred |= r.reader_states[name] != 'subscribed' and existing != desired
                continue
            before = r.engine.shards[name].tickers
            remove = sorted(before-desired-set(candidates.protected))[:16]
            # Keep a bounded anchor if no replacement would remain on this shard.
            after = set(before)-set(remove)
            room = r.writer.market_capacity-(len(existing)-len(remove))
            additions = [t for t in candidates.tickers if t not in existing][:min(16,room)]
            after |= set(additions)
            if not after:
                after.add(min(before))
            if after == before: continue
            future = asyncio.get_running_loop().create_future()
            change = ScopeChange(name,before,tuple(sorted(after)),candidates.source,future)
            if not await self.removable(change):
                self.deferred += 1
                deferred = True
                continue
            self.pending = change
            self.state = 'rotating'
            self.signals[name].set()
            try:
                await asyncio.wait((future,))
                accepted = future.result()
                self.state = 'awaiting_snapshots' if accepted else 'deferred'
                if not accepted: self.deferred += 1
                self.cursor = (self.cursor+offset+1) % len(names)
                return accepted
            finally:
                # Cancellation is not permission for an unobserved late commit.
                if not future.done(): future.set_result(False)
                if self.pending is change: self.pending = None
        # An idle-metadata/source race is not a stable slate. Retry through the
        # existing one-second backoff instead of sleeping a full catalog period.
        self.state = 'deferred' if deferred else 'stable'
        return False

    def stop(self):
        self.stopping = True
        if self.pending is not None and not self.pending.result.done():
            self.pending.result.set_result(False)
        self.wake.set()

    async def run(self):
        if self.used: raise InvalidData('market admission cannot be reused')
        self.used = self.running = True
        self.task = asyncio.current_task()
        try:
            while not self.stopping:
                self.wake.clear()
                now = self.runtime.clock()
                if now >= self.next_at:
                    self.requested = False
                    await self.cycle()
                    self.next_at = now+(1 if self.state in {'deferred','sources_unavailable'}
                                        else self.interval)
                delay = max(.01,min(1,self.next_at-self.runtime.clock()))
                try:
                    await asyncio.wait_for(self.wake.wait(),delay)
                except TimeoutError:
                    pass
                if self.requested:
                    self.next_at = min(self.next_at,self.runtime.clock()+1)
        finally:
            self.stop()
            self.running = False

    def status(self):
        return dict(state=self.state,running=self.running,rotating=self.transitioning,
                    completed=self.completed,deferred=self.deferred,authorized=False)
