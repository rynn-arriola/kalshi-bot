"""Production metadata adapter, fake public reads only."""
import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
import unittest

from kalshi_bot.market_inputs import ExitInputService, FeeProfile
from kalshi_bot.metadata_scheduler import MetadataScheduler
from kalshi_bot.rest import ReadResult, request_path
from kalshi_bot.values import InvalidData
from test_bot_market_inputs import Reads, review, NOW


class BulkReads(Reads):
    async def read(self, name, **params):
        if name != 'events':
            return await super().read(name, **params)
        self.calls.append((name, params))
        payload = deepcopy(dict(events=[{**self.event, 'markets':list(self.markets.values())}],
                                milestones=[self.milestone], cursor=''))
        if self.before:
            await self.before(name)
        if hasattr(self, 'transform'):
            payload = self.transform(payload)
        return ReadResult(payload, 100)


class BulkTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.reads = BulkReads(('A', 'B'))
        self.age = 0
        self.service = ExitInputService(self.reads, ('A','B'),
            now=lambda: NOW+timedelta(seconds=self.age), clock=lambda: self.age, ttl=60,
            timing_reviews=tuple(review(row) for row in self.reads.markets.values()),
            fee_profile=FeeProfile(D('.0001'), 'fixture', NOW+timedelta(hours=1)), bulk_events=True)
        self.service.bind(lambda terms: None, lambda ticker: None)
        self.service.begin(1)
        self.service.subscribed(1, 1)

    async def asyncTearDown(self):
        await self.service.close()

    async def test_shared_batch_keeps_fee_reads_and_original_timestamps(self):
        first = await self.service.refresh('A')
        self.age = 20
        second = await self.service.refresh('B')
        self.assertFalse(first.blockers+second.blockers)
        names = [name for name, _ in self.reads.calls]
        self.assertEqual(names.count('events'), 1)
        self.assertFalse(set(names) & {'market','event','milestone'})
        self.assertEqual(set(names), {'events','series','series_fees','event_fees'})
        self.assertEqual(self.service.values['market','B'].observed, NOW)
        self.assertEqual(self.service.values['market','B'].expires, NOW+timedelta(seconds=60))
        self.assertIn('events_bulk', self.service.values['market','B'].sources)

    async def test_concurrent_consumers_share_one_read(self):
        await asyncio.gather(self.service.refresh('A'), self.service.refresh('B'))
        self.assertEqual(sum(n == 'events' for n,_ in self.reads.calls), 1)

    async def test_expiry_and_reconnect_force_new_batch(self):
        await self.service.refresh('A')
        self.age = 60
        await self.service.refresh('B')
        self.service.begin(2)
        self.service.subscribed(2, 2)
        await self.service.refresh('A')
        self.assertEqual(sum(n == 'events' for n,_ in self.reads.calls), 3)

    async def test_missing_duplicate_extra_and_pagination_rejected(self):
        transforms = [lambda p: {**p,'cursor':'next'}, lambda p: {**p,'events':[]},
            lambda p: {**p,'events':p['events']*2},
            lambda p: {**p,'milestones':[]},
            lambda p: {**p,'events':[{**p['events'][0],'event_ticker':'OTHER'}]},
            lambda p: {**p,'events':[{**p['events'][0],'markets':[]}]},
            lambda p: {**p,'milestones':p['milestones']*2}]
        for transform in transforms:
            with self.subTest(transform=transform):
                self.service.begin(self.service.generation+1)
                self.service.subscribed(self.service.generation, 1)
                self.reads.transform = transform
                with self.assertRaises(InvalidData):
                    await self.service.refresh('A')
                self.assertNotIn('A', self.service.results)

    async def test_lifecycle_overtakes_batch_and_rejects_stale_response(self):
        started, release = asyncio.Event(), asyncio.Event()
        async def pause(name):
            if name == 'events':
                started.set()
                await release.wait()
        self.reads.before = pause
        task = asyncio.create_task(self.service.refresh('B'))
        await started.wait()
        self.service.ingest(dict(type='market_lifecycle_v2',sid=1,seq=1,
            msg=dict(market_ticker='A',event_type='deactivated')), generation=1)
        release.set()
        with self.assertRaises(InvalidData): await task
        self.assertFalse(self.service.bulk.cache)
        self.assertNotIn('B', self.service.results)

    async def test_stream_overlay_cannot_be_undone_by_bulk(self):
        self.service.ingest(dict(type='market_lifecycle_v2',sid=1,seq=1,
            msg=dict(market_ticker='A',event_type='deactivated')), generation=1)
        with self.assertRaises(InvalidData): await self.service.refresh('A')
        self.assertNotIn('A', self.service.results)

    async def test_changed_review_fences_old_scope_and_complete_fees_still_required(self):
        self.service.set_review('A', replace(review(self.reads.markets['A']), rules_hash='0'*64))
        result = await self.service.refresh('A')
        self.assertIn('timing_review_conflict', result.blockers)
        self.service.set_review('A', review(self.reads.markets['A']))
        self.reads.event_changes = [dict(id='f',event_ticker='E',series_ticker='WRONG',
            scheduled_ts=NOW.isoformat(),fee_type_override=None,fee_multiplier_override=None)]
        self.age = 60
        with self.assertRaises(InvalidData): await self.service.refresh('A')

    async def test_real_scheduler_recovers_expiry_during_fee_dependency(self):
        shifted = False
        async def shift(name):
            nonlocal shifted
            if name == 'series' and not shifted:
                self.age = 60
                shifted = True
        self.reads.before = shift
        scheduler = MetadataScheduler(self.service)
        scheduler.request('A')
        task = asyncio.create_task(scheduler.run())
        try:
            async with asyncio.timeout(5):
                while 'A' not in self.service.results:
                    if task.done(): task.result()
                    if shifted: self.age += 1
                    await asyncio.sleep(.01)
            self.assertFalse(self.service.results['A'].blockers)
            self.assertFalse(scheduler.exhausted)
            self.assertGreaterEqual(sum(n=='events' for n,_ in self.reads.calls),2)
        finally:
            scheduler.stop()
            await task

    async def test_close_joins_bulk_loader_and_does_not_publish_after_cancel(self):
        started = asyncio.Event()
        async def pause(name):
            if name == 'events':
                started.set()
                await asyncio.Event().wait()
        self.reads.before = pause
        task = asyncio.create_task(self.service.refresh('A'))
        await started.wait()
        await self.service.close()
        with self.assertRaises(InvalidData): await task
        self.assertFalse(self.service.bulk.cache or self.service.results or self.service.pending)

    def test_groups_respect_event_and_query_limits(self):
        reviews = tuple(replace(review(self.reads.markets['A']),ticker=f'M{i}',
            event=f'E{i}'+('X'*100),milestone_id=f'R{i}') for i in range(1024))
        service = ExitInputService(self.reads,tuple(r.ticker for r in reviews),
            now=lambda:NOW,ttl=60,timing_reviews=reviews,bulk_events=True)
        self.assertEqual(len(service.bulk.targets),3072)
        self.assertTrue(all(len(g)<=50 and len(','.join(g))<=2048
                            for g in service.bulk.groups.values()))

    def test_bulk_route_is_public_metadata_only(self):
        spec, path = request_path('events', dict(tickers='E,F',limit=200,
            with_nested_markets='true',with_milestones='true'), 'metadata')
        self.assertFalse(spec.authenticated)
        self.assertIn('tickers=E%2CF', path)
        with self.assertRaises(InvalidData): request_path('events', {}, 'bootstrap')
        with self.assertRaises(InvalidData): request_path('events', {'limit':201}, 'metadata')
        with self.assertRaises(InvalidData):
            request_path('events', {'with_nested_markets':'yes'}, 'metadata')
