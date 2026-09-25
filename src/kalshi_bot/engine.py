"""Offline-injectable event owner; no transport creation or order authority.

Private events and safety deadlines precede bounded public-book batches.
Book deltas are never coalesced. Only downstream market evaluation is coalesced.
Reconnect is an explicit caller action, independently scoped to each shard.
"""
import asyncio
from collections import deque
import json
import math
import time

from .books import BookConnection, ProofLost
from .scheduler import DirtyScheduler
from .observability import NO_LOG
from .values import InvalidData, identity, integer


class EventEngine:
    def __init__(self, shards: dict[str, BookConnection], *, private_handler,
                 evaluate, deadline_handler, capacity=8192, byte_capacity=16*1024*1024,
                 clock=time.monotonic, invalidate=lambda ticker: None, book_lost=lambda name: None,
                 diagnostics=NO_LOG):
        self.diagnostics = diagnostics
        if not 1 <= len(shards) <= 4 or any(not isinstance(b, BookConnection) for b in shards.values()):
            raise InvalidData("one to four validated book shards required")
        tickers = [t for b in shards.values() for t in b.tickers]
        if len(set(tickers)) != len(tickers) or len(tickers) > 1024:
            raise InvalidData("book ownership must be unique and bounded")
        for name in shards:
            identity(name)
        self.shards = dict(shards)
        self.market_shard = {t: name for name, b in shards.items() for t in b.tickers}
        self.private_handler, self.evaluate, self.deadline_handler = private_handler, evaluate, deadline_handler
        self.invalidate = invalidate
        self.book_lost = book_lost
        self.private_idle = asyncio.Event()
        self.private_idle.set()
        self.capacity = integer(capacity, 1, 65536)
        self.byte_capacity = integer(byte_capacity, 1024, 64*1024*1024)
        self.private = deque()
        self.public = {name: deque() for name in shards}
        self.public_bytes = {name: 0 for name in shards}
        self.private_bytes = 0
        self.private_generation = 0
        self.clock = clock
        self.last_clock = self._time()
        self.dirty = DirtyScheduler(len(tickers))
        self.deadlines = DirtyScheduler(len(tickers))
        for ticker in tickers:
            self.dirty.register(ticker)
            self.deadlines.register(ticker)
        self.wake = asyncio.Event()
        self.stopped = self.failed = self.running_step = False
        self.cursor = 0
        self.processed = self.decisions = self.high_water = 0
        self.book_failures = {name: 0 for name in shards}
        self.book_received = {}  # bounded by subscribed markets, ingress not dequeue clock
        self.send_edge_drains = self.send_edge_events = 0
        self.evaluation_catchups = 0

    def _time(self):
        now = self.clock()
        if not math.isfinite(now):
            raise InvalidData("invalid event clock")
        return now

    def _check(self):
        self.diagnostics.ensure_healthy()
        if self.failed or self.stopped:
            raise InvalidData("event owner stopped or failed")

    def begin_private_epoch(self):
        self._check()
        # Never silently discard a buffered fill on reconnect.
        if self.private:
            self.failed = True
            raise InvalidData("private reconnect requires draining or explicit recovery")
        self.private_generation += 1
        for ticker in self.market_shard:
            self.invalidate(ticker)
        return self.private_generation

    def begin_book_epoch(self, name):
        self._check()
        shard = self.shards[name]
        for ticker in shard.tickers:
            self.invalidate(ticker)
            self.book_received.pop(ticker, None)
        self.public[name].clear()
        self.public_bytes[name] = 0
        return shard.reconnect()

    def _lose_book(self, name):
        self.diagnostics.emit('book_proof_lost', stream=name, generation=self.shards[name].generation)
        self.shards[name].invalidate()
        for ticker in self.shards[name].tickers:
            self.invalidate(ticker)
        self.public[name].clear()
        self.public_bytes[name] = 0
        self.book_failures[name] += 1
        self.book_lost(name)

    def replace_book_scope(self, name, tickers, *, capacity):
        """Only after the reader is joined and its owner proves removals clear.

        Synchronous control-plane commit. Never call from a market evaluation.
        The caller supplies ownership proof; this primitive supplies epoch fences.
        """
        self._check()
        if self.running_step:
            raise InvalidData('scope replacement during engine dispatch')
        old = self.shards[name]
        replacement = BookConnection(tuple(tickers), max_levels=old.max_levels)
        other = set(self.market_shard)-old.tickers
        if other & replacement.tickers or len(other | replacement.tickers) > capacity:
            raise InvalidData('replacement scope exceeds unique capacity')
        integer(capacity,1,1024)
        self.dirty.capacity = self.deadlines.capacity = capacity
        for ticker in old.tickers:
            self.invalidate(ticker)
            self.book_received.pop(ticker,None)
        for ticker in old.tickers-replacement.tickers:
            self.market_shard.pop(ticker)
            self.dirty.unregister(ticker)
            self.deadlines.unregister(ticker)
        for ticker in replacement.tickers:
            self.market_shard[ticker] = name
            self.dirty.register(ticker)
            self.deadlines.register(ticker)
        # Fence old deliveries before the next begin_book_epoch call as well.
        replacement.generation = old.generation+1
        self.shards[name] = replacement
        self.public[name].clear()
        self.public_bytes[name] = 0
        self.wake.set()

    @staticmethod
    def _freeze(event):
        if not isinstance(event, dict):
            raise InvalidData("event object required")
        raw = json.dumps(event, allow_nan=False, separators=(",", ":"))
        size = len(raw.encode())
        if size > 1048576:
            raise InvalidData("event exceeds one-megabyte budget")
        return raw, size

    def submit_private(self, event, *, generation):
        self._check()
        if generation != self.private_generation or generation == 0:
            return False
        try:
            raw, size = self._freeze(event)
            if len(self.private) >= self.capacity or self.private_bytes+size > self.byte_capacity:
                raise InvalidData("private queue overflow; account proof lost")
        except Exception as exc:
            self.diagnostics.emit('private_ingress_failed', error=exc, generation=generation, backlog=self.backlog)
            self.failed = True
            for ticker in self.market_shard:
                self.invalidate(ticker)
            self.wake.set()
            raise
        self.private.append((raw, size, generation))
        self.private_idle.clear()
        self.private_bytes += size
        self.wake.set()
        self.high_water = max(self.high_water, self.backlog)
        return True

    def submit_book(self, name, event, *, generation, received_at=None):
        self._check()
        shard = self.shards[name]
        if generation != shard.generation:
            return False
        try:
            if shard.failed:
                raise ProofLost("book shard requires recovery")
            now = self._time()
            received = now if received_at is None else received_at
            if (type(received) not in (float, int) or not math.isfinite(received)
                    or received < 0 or received > now):
                raise ProofLost('invalid book ingress clock')
            raw, size = self._freeze(event)
            if len(self.public[name]) >= self.capacity or self.public_bytes[name]+size > self.byte_capacity:
                raise ProofLost("public queue overflow; shard proof lost")
        except Exception:
            self._lose_book(name)
            self.wake.set()
            raise
        self.public[name].append((raw, size, generation, received))
        self.public_bytes[name] += size
        self.wake.set()
        self.high_water = max(self.high_water, self.backlog)
        return True

    @property
    def backlog(self):
        return len(self.private)+sum(map(len, self.public.values()))

    def schedule(self, ticker, when):
        self._check()
        self.deadlines.schedule(ticker, when)
        self.wake.set()

    def _apply_public_batch(self, name):
        """One synchronous bounded turn; shared by the event and send owners."""
        applied = 0
        for _ in range(min(64, len(self.public[name]))):
            raw, size, generation, received = self.public[name].popleft()
            self.public_bytes[name] -= size
            try:
                ticker = self.shards[name].apply(json.loads(raw), generation=generation)
            except ProofLost as exc:
                self.diagnostics.emit('book_proof_lost', error=exc, stream=name, generation=generation)
                self._lose_book(name)
                break
            self.processed += 1
            applied += 1
            if ticker is not None:
                self.book_received[ticker] = received
                self.dirty.mark(ticker)
        return applied

    def catch_up_book(self, ticker):
        """Validate queued frames before a send fence, never ignore the queue.

        No await or advisory callback: the normal ordered parser owns sequence,
        scope and epoch checks. Private work and already-due safety timers keep
        precedence. A burst larger than one batch remains blocked.
        """
        self._check()
        name = self.market_shard.get(ticker)
        due = self.deadlines.next_deadline()
        if name is None or self.private or (due is not None and due <= self._time()):
            return False
        if self.public[name]:
            self.send_edge_drains += 1
            self.send_edge_events += self._apply_public_batch(name)
            self.wake.set()
        return not self.public[name] and not self.shards[name].failed

    async def step(self):
        self._check()
        if self.running_step:
            raise InvalidData("only one event owner may dispatch")
        self.running_step = True
        try:
            now = self._time()
            if now < self.last_clock:
                raise InvalidData("event clock regressed")
            self.last_clock = now
            # A full private backlog cannot starve already due inventory timers.
            for ticker in self.deadlines.take(now, limit=1024):
                await self.deadline_handler(ticker)
            for _ in range(min(32, len(self.private))):
                raw, size, generation = self.private.popleft()
                self.private_bytes -= size
                await self.private_handler(json.loads(raw), generation)
                self.processed += 1
            if self.private or self.stopped:
                return
            names = tuple(self.shards)
            name = names[self.cursor % len(names)]
            self.cursor += 1
            self._apply_public_batch(name)
            for _ in range(8):
                selected = self.dirty.take(self._time(), limit=1)
                if not selected:
                    break
                ticker = selected[0]
                owner = self.market_shard[ticker]
                shard = self.shards[owner]
                if shard.failed or ticker not in shard.books:
                    continue
                if self.public[owner]:
                    # D-130: a continuously busy shard must not postpone all of
                    # its markets. Apply one bounded ordered batch (the same
                    # synchronous catch-up used at the send edge) and evaluate
                    # only if that fully drains the shard.
                    self.evaluation_catchups += 1
                    if not self.catch_up_book(ticker):
                        self.dirty.mark(ticker)
                        continue
                    # This evaluation observes every frame just applied.
                    self.dirty.clear(ticker)
                    shard = self.shards[owner]
                    if shard.failed or ticker not in shard.books:
                        continue
                # Awaited work may receive a private update: defer entry decisions.
                if self.private or self.stopped:
                    self.dirty.mark(ticker)
                    continue
                await self.evaluate(ticker, shard.books[ticker], shard.generation)
                self.decisions += 1
                # Ranking/Decimal work may have no internal await. Give readers,
                # private events and timers a turn after each market decision.
                await asyncio.sleep(0)
                due = self.deadlines.next_deadline()
                if self.private or (due is not None and due <= self._time()):
                    break
        except BaseException as exc:
            self.diagnostics.emit('engine_cancelled' if isinstance(exc, asyncio.CancelledError)
                                  else 'engine_failed', error=exc, backlog=self.backlog)
            self.failed = True
            for shard in self.shards.values():
                shard.invalidate()
            for ticker in self.market_shard:
                self.invalidate(ticker)
            raise
        finally:
            self.running_step = False
            if not self.private:
                self.private_idle.set()

    def stop(self):
        # Local dispatch stop only: never claims existing venue orders canceled.
        self.stopped = True
        for shard in self.shards.values():
            shard.invalidate()
        for ticker in self.market_shard:
            self.invalidate(ticker)
        self.wake.set()

    async def run(self):
        try:
            while not self.stopped:
                self.wake.clear()
                await self.step()
                if self.backlog or self.dirty.pending:
                    await asyncio.sleep(0)
                    continue
                due = self.deadlines.next_deadline()
                timeout = max(0, due-self._time()) if due is not None else None
                try:
                    async with asyncio.timeout(timeout):
                        await self.wake.wait()
                except TimeoutError:
                    pass
        finally:
            self.stop()

    def status(self):
        return dict(live_ready=False, stopped=self.stopped, failed=self.failed,
                    backlog=self.backlog, high_water=self.high_water,
                    processed=self.processed, decisions=self.decisions,
                    send_edge_drains=self.send_edge_drains,
                    send_edge_events=self.send_edge_events,
                    evaluation_catchups=self.evaluation_catchups,
                    book_failures=dict(self.book_failures))
