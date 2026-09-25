"""Coalesced dirty markets and bounded due timers; no all-market busy loop."""
from collections import OrderedDict
import heapq
import math

from .values import InvalidData, identity, integer


class DirtyScheduler:
    def __init__(self, capacity: int):
        self.capacity = integer(capacity, 1, 1024)
        self.managed: set[str] = set()
        self._dirty: set[str] = set()
        self._queue = OrderedDict()
        self._priority = OrderedDict()
        self._priority_streak = 0
        self._due: dict[str, float] = {}
        self._heap: list[tuple[float, str]] = []

    def register(self, ticker: str):
        identity(ticker)
        if ticker not in self.managed and len(self.managed) >= self.capacity:
            raise InvalidData("managed-market capacity exceeded")
        self.managed.add(ticker)

    def mark(self, ticker: str, *, priority=False):
        if ticker not in self.managed:
            raise InvalidData("unregistered market")
        if type(priority) is not bool:
            raise InvalidData("literal scheduling priority required")
        if priority:
            self._queue.pop(ticker, None)
            self._priority.setdefault(ticker, None)
            self._dirty.add(ticker)
        elif ticker not in self._dirty:
            self._dirty.add(ticker)
            self._queue[ticker] = None

    def clear(self, ticker: str):
        """Drop a pending evaluation mark (not timers) already being served."""
        self._dirty.discard(ticker)
        self._queue.pop(ticker, None)
        self._priority.pop(ticker, None)

    def unregister(self, ticker: str):
        self.managed.discard(ticker)
        self._dirty.discard(ticker)
        self._due.pop(ticker, None)
        self._queue.pop(ticker, None)
        self._priority.pop(ticker, None)
        self._heap = [(at, t) for at, t in self._heap if t != ticker]
        heapq.heapify(self._heap)

    def schedule(self, ticker: str, monotonic_deadline: float):
        if ticker not in self.managed or not math.isfinite(monotonic_deadline):
            raise InvalidData("invalid deadline")
        self._due[ticker] = monotonic_deadline
        heapq.heappush(self._heap, (monotonic_deadline, ticker))
        if len(self._heap) > 2*self.capacity:
            self._heap = [(value, key) for key, value in self._due.items()]
            heapq.heapify(self._heap)

    def take(self, now: float, *, limit: int = 32) -> list[str]:
        if not math.isfinite(now):
            raise InvalidData("invalid monotonic clock")
        integer(limit, 1, 1024)
        while self._heap and self._heap[0][0] <= now:
            due, ticker = heapq.heappop(self._heap)
            if self._due.get(ticker) == due:
                del self._due[ticker]
                self.mark(ticker)
        selected = []
        while (self._queue or self._priority) and len(selected) < limit:
            # Revalidation cannot sit behind an entire catalog, but repeated
            # priority work must leave at least one in four turns for discovery.
            urgent = self._priority and (not self._queue or self._priority_streak < 3)
            queue = self._priority if urgent else self._queue
            ticker, _ = queue.popitem(last=False)
            self._priority_streak = min(3, self._priority_streak+1) if urgent else 0
            self._dirty.remove(ticker)
            selected.append(ticker)
        return selected

    def due_for(self, ticker: str):
        if ticker not in self.managed:
            raise InvalidData("unregistered market")
        return self._due.get(ticker)

    def next_deadline(self) -> float | None:
        while self._heap and self._due.get(self._heap[0][1]) != self._heap[0][0]:
            heapq.heappop(self._heap)
        return self._heap[0][0] if self._heap else None

    @property
    def pending(self) -> bool:
        return bool(self._queue or self._priority)
