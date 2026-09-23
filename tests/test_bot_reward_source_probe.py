"""Synthetic tests only: importing the explicit live probe performs no I/O."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

from kalshi_bot.rest import WireResponse
from kalshi_bot.quoting import Program
from kalshi_bot.transport import Subscription
from kalshi_bot.values import InvalidData
from test_bot_feeds import snapshot, delta

spec = importlib.util.spec_from_file_location('source_probe',
    Path(__file__).resolve().parents[1]/'scripts'/'probe_reward_sources.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class ComparisonTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_feed_baseline_ignores_only_refresh_snapshot_age(self):
        comparison = probe.Comparison((Subscription('book-0', ('orderbook_delta',), ('A',)),))
        await comparison.consume('book-0', snapshot() | {'_received_mono':100.})
        self.assertEqual(comparison.sample(104)['baseline_fresh'], 1)
        await comparison.consume('book-0', snapshot(2) | {'id':2, '_received_mono':106.})
        sample = comparison.sample(106)
        self.assertEqual((sample['baseline_fresh'], sample['refreshed_fresh']), (0,1))
        await comparison.consume('book-0', delta(3) | {'_received_mono':107.})
        sample = comparison.sample(107)
        self.assertEqual((sample['baseline_fresh'], sample['refreshed_fresh']), (1,1))
        self.assertEqual(comparison.counts['correlated_refresh_snapshots'], 1)

    async def test_sequence_failure_cannot_be_counted_as_valid(self):
        comparison = probe.Comparison((Subscription('book-0', ('orderbook_delta',), ('A',)),))
        await comparison.consume('book-0', snapshot() | {'_received_mono':100.})
        with self.assertRaises(InvalidData):
            await comparison.consume('book-0', snapshot(3) | {'_received_mono':101.})
        self.assertEqual(comparison.sample(101)['valid_books'], 0)

    async def test_reference_check_uses_requested_unified_yes_price_scale(self):
        from datetime import datetime, timedelta, timezone
        from decimal import Decimal
        now = datetime.now(timezone.utc)
        program = Program('P', 'A', now-timedelta(hours=1), now+timedelta(hours=1),
                          Decimal(200), 5000, 10000, False)
        comparison = probe.Comparison(
            (Subscription('book-0', ('orderbook_delta',), ('A',)),),
            {'A': (program,)})
        event = snapshot() | {'_received_mono': 100.}
        event['msg'] = dict(event['msg'],
            yes_dollars_fp=[['.50','20'],['.49','20'],['.48','200']],
            no_dollars_fp=[['.60','20'],['.61','20'],['.62','200']])
        await comparison.consume('book-0', event)
        book = comparison.feeds['book-0'].books['A']
        self.assertEqual(book.asks.levels[Decimal('.60')], Decimal(20))
        self.assertEqual(comparison.counts['reference_program_snapshots'], 1)
        self.assertEqual(comparison.counts['reference_sides_with_depth'], 2)
        self.assertEqual(comparison.counts['reference_mismatches'], 0)


class WireTests(unittest.TestCase):
    def test_only_public_reward_get_is_permitted(self):
        good = 'https://external-api.kalshi.com/trade-api/v2/incentive_programs?limit=1000'
        with patch.object(probe, 'get_wire', return_value=WireResponse(200,b'{}')) as wire:
            probe.public_wire(good, {'Accept':'application/json'}, 1024)
            for url, headers in ((good, {'Authorization':'fixture'}),
                    (good, {'KALSHI-ACCESS-KEY':'fixture'}),
                    ('https://external-api.kalshi.com/trade-api/v2/portfolio/orders', {})):
                with self.assertRaises(InvalidData): probe.public_wire(url,headers,1024)
            self.assertEqual(wire.call_count, 1)

    def test_throttle_stops_without_retry(self):
        with patch.object(probe, 'get_wire', return_value=WireResponse(429,b'{}')) as wire:
            with self.assertRaises(InvalidData):
                probe.public_wire('https://external-api.kalshi.com/trade-api/v2/incentive_programs?limit=1000',{},1024)
            self.assertEqual(wire.call_count, 1)
