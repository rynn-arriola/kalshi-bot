"""Explicit, bounded, atomic telemetry checkpoint; no financial-ledger access."""
import asyncio
import json
import os
from pathlib import Path
import tempfile

from .rest import decode
from .values import InvalidData
from .windows import WindowsLease
from .reward_tracker import RewardTracker


MAX_BYTES = 8*1024*1024


def _write(path, payload):
    with WindowsLease('reward-checkpoint:'+str(path)):
        _write_owned(path,payload)


def _write_owned(path, payload):
    candidate = RewardTracker(scope=payload['scope'])
    candidate.restore(payload)
    if path.exists():
        prior = RewardTracker(scope=payload['scope'])
        prior.restore(_read(path))
        for key, old in prior.records.items():
            new = candidate.records.get(key)
            if (new is None or new.program != old.program or new.first_at != old.first_at
                    or new.last_at < old.last_at or new.estimate < old.estimate
                    or new.observed_seconds < old.observed_seconds
                    or new.qualifying_seconds < old.qualifying_seconds
                    or new.unknown_seconds < old.unknown_seconds
                    or (old.conflict and not new.conflict)):
                raise InvalidData('reward checkpoint would lose retained evidence')
    encoded = json.dumps(payload, separators=(',', ':'), allow_nan=False).encode()
    if len(encoded) > MAX_BYTES:
        raise InvalidData('reward checkpoint byte limit')
    # Directory creation/selection belongs to the explicit caller.
    fd, temporary = tempfile.mkstemp(prefix='.reward-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def _read(path):
    with path.open('rb') as stream:
        raw = stream.read(MAX_BYTES+1)
    if len(raw) > MAX_BYTES:
        raise InvalidData('reward checkpoint byte limit')
    return decode(raw)


class RewardCheckpoint:
    def __init__(self, path):
        self.path = Path(path).resolve()
        if self.path.suffix != '.json':
            raise InvalidData('separate JSON telemetry path required')
        self.active = None

    async def _run(self, function, *args):
        if self.active is not None:
            raise InvalidData('reward checkpoint already in progress')
        task = self.active = asyncio.create_task(asyncio.to_thread(function,self.path,*args))
        cancelled = False
        try:
            while not task.done():
                try:
                    await asyncio.wait((task,))
                except asyncio.CancelledError:
                    cancelled = True
            result = task.result()
            if cancelled: raise asyncio.CancelledError
            return result
        finally:
            self.active = None

    async def save(self, tracker):
        # Capture on the event-loop owner before background disk work.
        if self.active is not None:
            raise InvalidData('reward checkpoint already in progress')
        await self._run(_write,tracker.checkpoint())

    async def load(self, tracker):
        if tracker.records:
            raise InvalidData('restore only before tracker observations')
        revision = tracker.revision
        data = await self._run(_read)
        if tracker.revision != revision or tracker.records:
            raise InvalidData('reward tracker changed while loading checkpoint')
        tracker.restore(data)
