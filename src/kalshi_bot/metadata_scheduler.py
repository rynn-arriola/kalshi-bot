"""Bounded event/deadline-driven control plane; never order authority."""
import asyncio
from collections import OrderedDict
import heapq
import math

from .observability import NO_LOG
from .market_inputs import InputRefreshSuperseded
from .values import InvalidData, integer, utc
from .quota import QuotaUnavailable


class MetadataScheduler:
    REBIND_HOLD = 5

    def __init__(self, service, *, defer=lambda: False, concurrency=2, attempts=3,
                 timeout=30, minimum_interval=.05, diagnostics=NO_LOG):
        self.service, self.defer, self.diagnostics = service, defer, diagnostics
        self.concurrency = integer(concurrency, 1, 2)
        self.attempt_limit = integer(attempts, 1, 8)
        for value in (timeout, minimum_interval):
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise InvalidData('finite positive metadata scheduling limits required')
        if timeout > 30 or minimum_interval > 1:
            raise InvalidData('metadata scheduling limit too large')
        self.timeout, self.minimum_interval = timeout, minimum_interval
        self.heap, self.due, self.ready, self.active = [], {}, OrderedDict(), {}
        self.dirty, self.exhausted = set(), set()
        self.failures, self.not_before = {}, {}
        self.serial = self.completed = self.started = self.high_water = 0
        self.wake = asyncio.Event()
        self.running = self.used = self.stopping = False
        self.last_clock = None
        self.rebind_target = None
        self.rebind_until = 0
        self.retired = {}  # Bounded retry tombstones; rotation cannot reset exhaustion.
        self.quota = getattr(service.reads, 'quota', None)
        if self.quota is not None:
            self.quota.listen(self.wake.set)
        service.listen(self._signal)

    def _expire_rebind(self):
        if self.rebind_target is not None and self.service.clock() >= self.rebind_until:
            self.rebind_target = None
            self.rebind_until = 0

    def _rebind_retained(self, tickers):
        removed = self.service.tickers-set(tickers)
        return set(self.retired) | {t for t in removed if t in self.failures or t in self.exhausted}

    def request_rebind(self, tickers):
        """Briefly quiesce new workers so an exact scope replacement can drain."""
        target = frozenset(tickers)
        if (self.stopping or self.service.closed
                or len(target) > 1024 or len(self._rebind_retained(target)) > 1024):
            return False
        self.rebind_target = target
        self.rebind_until = self.service.clock()+self.REBIND_HOLD
        self.wake.set()
        return True

    def cancel_rebind(self, tickers=None):
        target = None if tickers is None else frozenset(tickers)
        self._expire_rebind()
        if self.rebind_target is not None and (target is None or target == self.rebind_target):
            self.rebind_target = None
            self.rebind_until = 0
            self.wake.set()

    def can_rebind(self, tickers):
        target = frozenset(tickers)
        self._expire_rebind()
        retain = self._rebind_retained(target)
        return (not self.stopping and not self.service.closed and not self.active
                and not self.service.pending and not self.service.retiring
                and not self.service.refreshing and len(retain) <= 1024
                and (self.rebind_target is None or self.rebind_target == target))

    def rebind_scope(self, tickers):
        if not self.can_rebind(tickers):
            raise InvalidData('metadata scope replacement deferred')
        old = self.service.tickers
        self.service.rebind_scope(tickers)
        for ticker in old-self.service.tickers:
            if ticker in self.failures or ticker in self.exhausted:
                self.retired[ticker] = (self.failures.get(ticker,0),ticker in self.exhausted,
                                        self.not_before.get(ticker,0))
            for mapping in (self.due,self.ready,self.failures,self.not_before): mapping.pop(ticker,None)
            self.dirty.discard(ticker)
            self.exhausted.discard(ticker)
        self.heap = [(at,serial,t) for at,serial,t in self.heap if t in self.service.tickers]
        heapq.heapify(self.heap)
        for ticker in self.service.tickers-old:
            prior = self.retired.pop(ticker,None)
            if prior is not None:
                failures,exhausted,not_before = prior
                self.failures[ticker] = failures
                self.not_before[ticker] = not_before
                if exhausted: self.exhausted.add(ticker)
            self.request(ticker)
        self.cancel_rebind(tickers)
        self.wake.set()

    def _signal(self, kind, ticker):
        if kind == 'disconnected':
            self.due.clear()
            self.heap.clear()
            self.ready.clear()
            self.dirty.clear()
            for task, _ in self.active.values():
                task.cancel()
        elif not self.stopping:
            if kind == 'connected':
                for market in sorted(self.service.tickers):
                    self.request(market)
            elif kind == 'changed':
                self.request(ticker)
            else:
                raise InvalidData('unsupported metadata scheduling notification')
        self.wake.set()

    def _queue(self, ticker, when):
        when = max(when, self.not_before.get(ticker, when))
        prior = self.due.get(ticker)
        if ticker in self.ready or (prior is not None and prior[0] <= when):
            return
        self.serial += 1
        value = (when, self.serial)
        self.due[ticker] = value
        heapq.heappush(self.heap, (*value, ticker))
        if len(self.heap) > 2*len(self.service.tickers):
            self.heap = [(deadline, serial, key) for key, (deadline, serial) in self.due.items()]
            heapq.heapify(self.heap)

    def request(self, ticker, *, retry=False):
        if ticker not in self.service.tickers or type(retry) is not bool:
            raise InvalidData('metadata request outside managed scope')
        if self.stopping or self.service.closed:
            return False
        if retry:
            self.exhausted.discard(ticker)
            self.failures.pop(ticker, None)
            # Explicit retry is not permission to bypass an existing cooldown.
        if ticker in self.exhausted or not self.service.connected:
            return False
        if ticker in self.active:
            self.dirty.add(ticker)
        else:
            self._queue(ticker, self.service.clock())
        self.wake.set()
        return True

    async def _refresh(self, ticker):
        async with asyncio.timeout(self.timeout):
            return await self.service.refresh(ticker)

    def _finished(self):
        for ticker, (task, generation) in tuple(self.active.items()):
            if not task.done():
                continue
            self.active.pop(ticker)
            dirty = ticker in self.dirty
            self.dirty.discard(ticker)
            try:
                task.result()
            except asyncio.CancelledError:
                if self.service.connected and not self.stopping:
                    self.request(ticker)
                continue
            except QuotaUnavailable:
                # Infrastructure hold is not a market retry. Keep earlier counts.
                if self.service.connected and not self.stopping:
                    self.ready[ticker] = None
                continue
            except InputRefreshSuperseded:
                # Lifecycle/review evidence legitimately won the race. The
                # service revoked the stale output; retry without consuming a
                # market failure attempt or installing exponential backoff.
                if generation == self.service.generation and self.service.connected:
                    self.request(ticker)
                continue
            except (InvalidData, TimeoutError, OSError) as exc:
                if generation != self.service.generation or not self.service.connected:
                    if self.service.connected:
                        self.request(ticker)
                    continue
                failures = self.failures.get(ticker, 0)+1
                self.failures[ticker] = failures
                self.not_before[ticker] = self.service.clock()+min(30, 2**(failures-1))
                if failures >= self.attempt_limit:
                    self.exhausted.add(ticker)
                    self.diagnostics.emit('metadata_exhausted', market=ticker, attempt=failures, error=exc)
                else:
                    self.diagnostics.emit('metadata_retry', market=ticker, attempt=failures, error=exc)
                    self.request(ticker)
                continue
            # Unexpected exceptions intentionally escape to runtime supervision.
            if generation != self.service.generation or not self.service.connected:
                if self.service.connected:
                    self.request(ticker)
                continue
            self.failures.pop(ticker, None)
            self.completed += 1
            self._queue(ticker, self.service.clock() if dirty else self.service.next_refresh_at(ticker))

    def _clock_check(self):
        mono, wall = self.service.clock(), utc(self.service.now())
        if not math.isfinite(mono):
            raise InvalidData('invalid metadata monotonic clock')
        if self.last_clock is not None:
            old_mono, old_wall = self.last_clock
            elapsed, seconds = mono-old_mono, (wall-old_wall).total_seconds()
            if elapsed < 0 or seconds < 0 or abs(elapsed-seconds) > 1:
                raise InvalidData('metadata clock discontinuity; restart requires fresh evidence')
        self.last_clock = mono, wall

    def step(self):
        """One bounded scheduling turn, also usable with injected fixture clocks."""
        self._clock_check()
        self._expire_rebind()
        self._finished()
        now = self.service.clock()
        while self.heap and self.heap[0][0] <= now:
            deadline, serial, ticker = heapq.heappop(self.heap)
            if self.due.get(ticker) != (deadline, serial):
                continue
            self.due.pop(ticker)
            if not self.stopping and self.service.connected and ticker not in self.exhausted:
                # Expired evidence is revoked even when both workers are busy.
                self.service._clear_terms(ticker)
                self.ready[ticker] = None
        quota_ready = self.quota is None or self.quota.poll()
        if (not self.stopping and self.service.connected and quota_ready and not self.defer()
                and self.rebind_target is None):
            while self.ready and len(self.active) < self.concurrency:
                ticker, _ = self.ready.popitem(last=False)
                self.not_before[ticker] = now+self.minimum_interval
                task = asyncio.create_task(self._refresh(ticker), name='kalshi-metadata-refresh')
                task.add_done_callback(lambda _: self.wake.set())
                self.active[ticker] = task, self.service.generation
                self.started += 1
                self.high_water = max(self.high_water, len(self.active))
        # A small clock/stop watchdog does no REST reads or market scans.
        return max(.001, min(.25, self.heap[0][0]-now if self.heap else .25,
                             .05 if self.ready and quota_ready else .25))

    def stop(self):
        self.stopping = True
        self.cancel_rebind()
        self.service.disconnect()
        self.wake.set()

    async def close(self):
        self.stop()
        await asyncio.gather(*(task for task, _ in self.active.values()), return_exceptions=True)
        self.active.clear()
        await self.service.close()

    async def run(self):
        if self.used:
            raise InvalidData('metadata scheduler cannot be reused')
        self.used = self.running = True
        try:
            if self.service.connected:
                self._signal('connected', None)
            while not self.stopping:
                self.wake.clear()
                delay = self.step()
                try:
                    await asyncio.wait_for(self.wake.wait(), delay)
                except TimeoutError:
                    pass
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.diagnostics.emit('metadata_scheduler_failed', error=exc)
            raise
        finally:
            await self.close()
            self.running = False

    def status(self):
        return dict(running=self.running, pending=len(self.due)+len(self.ready),
            active=len(self.active), heap=len(self.heap), exhausted=len(self.exhausted),
            started=self.started, completed=self.completed, high_water=self.high_water,
            rebind_reserved=self.rebind_target is not None,
            live_authority=False)
