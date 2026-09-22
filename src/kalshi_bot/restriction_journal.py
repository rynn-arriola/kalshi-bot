"""Small durable journal for process-local quota restrictions.

Restriction writes occur only on exceptional quota/cooldown transitions. They
must finish before the affected component resumes so a sudden process loss
cannot create a fresh unrestricted replacement.
"""
import json
from pathlib import Path
from threading import Lock
import time

from .recovery_fence import FenceCooldown
from .startup import save_result
from .values import InvalidData, identity


class RestrictionJournal:
    def __init__(self, path, *, clock=time.time):
        self.path = Path(path)
        self.clock = clock
        self.lock = Lock()
        self.holds = ()
        self.deadlines = {}
        if self.path.is_file():
            if self.path.stat().st_size > 16384:
                raise InvalidData('restriction journal exceeds size limit')
            raw = json.loads(self.path.read_text(encoding='utf-8'))
            if (type(raw) is not dict or set(raw) != {'version', 'holds', 'cooldowns'}
                    or raw['version'] != 1 or type(raw['holds']) is not list
                    or type(raw['cooldowns']) is not list):
                raise InvalidData('invalid restriction journal')
            holds = tuple(identity(value) for value in raw['holds'])
            cooldowns = tuple(FenceCooldown.from_dict(value)
                              for value in raw['cooldowns'])
            if len(set(holds)) != len(holds) or len(holds) > 32:
                raise InvalidData('invalid restriction journal holds')
            if len({item.name for item in cooldowns}) != len(cooldowns):
                raise InvalidData('invalid restriction journal cooldowns')
            self.holds = holds
            self.deadlines = {item.name:item.deadline_utc for item in cooldowns}
        self._expire()

    def _expire(self):
        now = float(self.clock())
        self.deadlines = {name:deadline for name,deadline in self.deadlines.items()
                          if deadline > now}

    def _save(self):
        save_result(self.path, dict(version=1, holds=list(self.holds),
            cooldowns=[FenceCooldown(name, deadline).to_dict()
                       for name,deadline in sorted(self.deadlines.items())]))

    def snapshot(self):
        with self.lock:
            self._expire()
            return self.holds, tuple(FenceCooldown(name, deadline)
                for name,deadline in sorted(self.deadlines.items()))

    def cooldown(self, name, seconds):
        name = identity(name)
        if type(seconds) not in (int, float) or not 0 < seconds <= 86400:
            raise InvalidData('invalid durable cooldown')
        with self.lock:
            self._expire()
            self.deadlines[name] = max(self.deadlines.get(name, 0),
                                       float(self.clock())+seconds)
            self._save()

    def hold(self, name, seconds=0):
        name = identity(name)
        with self.lock:
            self._expire()
            self.holds = tuple(dict.fromkeys(self.holds+(name,)))
            if seconds:
                if type(seconds) not in (int, float) or not 0 < seconds <= 86400:
                    raise InvalidData('invalid durable hold cooldown')
                self.deadlines['quota_refresh'] = max(
                    self.deadlines.get('quota_refresh', 0),
                    float(self.clock())+seconds)
            self._save()

    def replace(self, holds, cooldowns):
        holds = tuple(identity(value) for value in holds)
        cooldowns = tuple(cooldowns)
        if (len(set(holds)) != len(holds) or len(holds) > 32
                or len(cooldowns) > 8
                or any(not isinstance(item, FenceCooldown) for item in cooldowns)
                or len({item.name for item in cooldowns}) != len(cooldowns)):
            raise InvalidData('invalid durable restriction replacement')
        with self.lock:
            self._expire()
            replacement = {item.name:item.deadline_utc for item in cooldowns
                           if item.deadline_utc > float(self.clock())}
            if self.holds == holds and self.deadlines == replacement:
                return False
            self.holds = holds
            self.deadlines = replacement
            self._save()
            return True
