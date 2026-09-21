"""Bounded versioned metadata cache; refresh only for explicitly missing REST fields.

TTL is a required caller input, not an adopted strategy refresh policy. No poller
or venue calls are created by this module. Revocation defeats an in-flight read.
"""
import asyncio
from dataclasses import dataclass
import json
import math
import time

from .values import InvalidData, identity, integer


@dataclass(frozen=True)
class Cached:
    revision: int
    observed: float
    expires: float
    encoded: str


class MetadataCache:
    def __init__(self, *, capacity=128, entry_bytes=65536, clock=time.monotonic):
        self.capacity = integer(capacity, 1, 1024)
        self.entry_bytes = integer(entry_bytes, 1, 1048576)
        self.clock = clock
        self.epochs = {}
        self.values = {}
        self.pending = {}
        self.closed = False

    def _key(self, key):
        identity(key)
        if self.closed:
            raise InvalidData("metadata cache closed")
        if key not in self.epochs:
            if len(self.epochs) >= self.capacity:
                raise InvalidData("metadata key capacity exceeded")
            self.epochs[key] = 0

    def revoke(self, key):
        self._key(key)
        self.epochs[key] += 1
        self.values.pop(key, None)

    def get(self, key):
        self._key(key)
        value = self.values.get(key)
        now = self.clock()
        if not math.isfinite(now) or value is None or not value.observed <= now < value.expires:
            raise InvalidData("metadata missing or expired")
        return value.revision, json.loads(value.encoded)

    async def refresh(self, key, fetch, *, ttl: float):
        self._key(key)
        if isinstance(ttl, bool) or not isinstance(ttl, (int, float)) or not math.isfinite(ttl) or not 0 < ttl <= 3600:
            raise InvalidData("explicit bounded metadata TTL required")
        task = self.pending.get(key)
        if task is None:
            epoch = self.epochs[key]
            task = asyncio.create_task(self._load(key, epoch, fetch, ttl))
            self.pending[key] = task
            def done(t):
                if self.pending.get(key) is t:
                    del self.pending[key]
                if not t.cancelled():
                    t.exception()
            task.add_done_callback(done)
        await asyncio.shield(task)
        return self.get(key)

    async def _load(self, key, epoch, fetch, ttl):
        started = self.clock()
        if not math.isfinite(started):
            raise InvalidData("invalid metadata clock")
        async with asyncio.timeout(30):
            value = await fetch()
        if not isinstance(value, dict):
            raise InvalidData("metadata response must be an object")
        encoded = json.dumps(value, allow_nan=False, separators=(",", ":"))
        if len(encoded.encode()) > self.entry_bytes:
            raise InvalidData("metadata byte capacity exceeded")
        now = self.clock()
        if (self.closed or self.epochs[key] != epoch or not math.isfinite(now)
                or now < started or now >= started+ttl):
            raise InvalidData("metadata read superseded or expired")
        self.epochs[key] += 1
        self.values[key] = Cached(self.epochs[key], started, started+ttl, encoded)

    async def close(self):
        self.closed = True
        tasks = tuple(self.pending.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.values.clear()
