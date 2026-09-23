"""Bounded missing-field batches; never a book, fee schedule or authority source.

Owned by ExitInputService. Its existing parsers and publication fences remain
authoritative. Original query timestamps are retained on every cache hit.
"""
import asyncio
from dataclasses import dataclass
from datetime import datetime

from .values import InvalidData, utc


@dataclass(frozen=True)
class Batch:
    documents: dict
    observed: datetime
    mono: float


class BulkEventInputs:
    def __init__(self, owner):
        self.owner = owner
        self.groups, self.targets, self.cache, self.locks = {}, {}, {}, {}
        self.serial = 0
        self.reset()

    def reset(self):
        self.serial += 1
        self.cache.clear()
        self.groups, self.targets, self.locks, self.versions = {}, {}, {}, {}
        events = sorted({r.event for r in self.owner.reviews.values()})
        group = []
        for event in events:
            if group and (len(group) >= 50 or len(','.join((*group, event))) > 2048):
                self._group(tuple(group))
                group = []
            group.append(event)
        if group:
            self._group(tuple(group))

    def _group(self, events):
        index = len(self.groups)
        self.groups[index] = events
        self.locks[index] = asyncio.Lock()
        self.versions[index] = 0
        for event in events:
            self.targets['event', event] = index
        for review in self.owner.reviews.values():
            if review.event in events:
                self.targets['market', review.ticker] = index
                # A milestone shared by groups needs only one authoritative row.
                self.targets.setdefault(('milestone', review.milestone_id), index)

    def invalidate(self, target):
        index = self.targets.get(target)
        if index is not None:
            self.cache.pop(index, None)
            # Fence even an in-flight group response. No stale batch can enter
            # the cache after a lifecycle observation or review replacement.
            self.versions[index] += 1

    async def get(self, target):
        index = self.targets[target]
        serial, version = self.serial, self.versions[index]
        lock = self.locks[index]
        async with lock:
            if serial != self.serial or version != self.versions.get(index):
                raise InvalidData('bulk metadata scope superseded')
            owner = self.owner
            batch = self.cache.get(index)
            if batch is None or not self._fresh(batch):
                observed, mono = utc(owner.now()), owner.clock()
                result = await owner.reads.read('events', reason='metadata',
                    tickers=','.join(self.groups[index]), limit=200,
                    with_nested_markets='true', with_milestones='true',
                    coalesce_scope=(owner.read_scope, owner.generation, serial, index, version))
                if serial != self.serial or version != self.versions.get(index):
                    raise InvalidData('bulk metadata scope superseded during read')
                docs = self._documents(result.payload, index)
                batch = Batch(docs, observed, mono)
                if (serial != self.serial or version != self.versions.get(index)
                        or owner.closed or not owner.connected
                        or not self._fresh(batch)):
                    raise InvalidData('bulk metadata response stale or superseded')
                self.cache[index] = batch
            if target not in batch.documents:
                raise InvalidData('reviewed metadata missing from bulk response')
            return batch.documents[target], batch.observed, batch.mono

    def _fresh(self, batch):
        owner = self.owner
        return (0 <= (utc(owner.now())-batch.observed).total_seconds() < owner.ttl
                and 0 <= owner.clock()-batch.mono < owner.ttl)

    def _documents(self, payload, index):
        # A filtered <=50-event request must be complete. Never silently accept
        # an unexhausted cursor, duplicate identities or an unexpected event.
        if (type(payload) is not dict or payload.get('cursor') != ''
                or type(payload.get('events')) is not list
                or type(payload.get('milestones')) is not list
                or len(payload['events']) > 50 or len(payload['milestones']) > 4096):
            raise InvalidData('incomplete or unbounded bulk metadata')
        docs, seen, markets = {}, set(), set()
        for event in payload['events']:
            key = event['event_ticker']
            if key not in self.groups[index] or key in seen:
                raise InvalidData('bulk event identity conflict')
            seen.add(key)
            docs['event', key] = {'event': {k: v for k, v in event.items() if k != 'markets'}}
            rows = event.get('markets')
            if type(rows) is not list or len(rows) > 4096:
                raise InvalidData('bounded nested markets required')
            for row in rows:
                ticker = row['ticker']
                if row['event_ticker'] != key or ticker in markets:
                    raise InvalidData('bulk market identity conflict')
                markets.add(ticker)
                if self.targets.get(('market', ticker)) == index:
                    docs['market', ticker] = {'market': row}
        if seen != set(self.groups[index]):
            raise InvalidData('bulk event coverage incomplete')
        seen = set()
        for row in payload['milestones']:
            key = row['id']
            if key in seen:
                raise InvalidData('duplicate bulk milestone')
            seen.add(key)
            if self.targets.get(('milestone', key)) == index:
                docs['milestone', key] = {'milestone': row}
        return docs
