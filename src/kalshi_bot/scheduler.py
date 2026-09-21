"""Coalesced dirty markets and bounded due timers; no all-market busy loop."""
from collections import deque
import heapq
import math

from .values import InvalidData, identity, integer


class DirtyScheduler:
    def __init__(self, capacity: int):
        self.capacity = integer(capacity, 1, 1024)
        self.managed: set[str] = set()
        self._dirty: set[str] = set()
        self._queue: deque[str] = deque()
        self._due: dict[str, float] = {}
        self._heap: list[tuple[float, str]] = []

    def register(self, ticker: str):
        identity(ticker)
        if ticker not in self.managed and len(self.managed) >= self.capacity:
            raise InvalidData("managed-market capacity exceeded")
        self.managed.add(ticker)

    def mark(self, ticker: str):
        if ticker not in self.managed:
            raise InvalidData("unregistered market")
        if ticker not in self._dirty:
            self._dirty.add(ticker)
            self._queue.append(ticker)

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
        while self._queue and len(selected) < limit:
            ticker = self._queue.popleft()
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
        return bool(self._queue)
