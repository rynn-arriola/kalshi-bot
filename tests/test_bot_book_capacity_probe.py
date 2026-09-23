"""Capacity instrument regressions; no network or credentials."""
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from kalshi_bot.transport import Subscription
from test_bot_feeds import snapshot

scripts = Path(__file__).resolve().parents[1]/'scripts'
with patch.object(sys,'path',[str(scripts)]+sys.path):
    spec = importlib.util.spec_from_file_location('book_capacity_probe',scripts/'probe_book_capacity.py')
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)


class CapacityTests(unittest.IsolatedAsyncioTestCase):
    async def test_reader_failure_returns_failed_and_joins(self):
        class BrokenReader:
            def __init__(self,*args):
                self.queue = probe.asyncio.Queue()
                self.queued_bytes = 0
            async def run(self,consume):
                raise probe.InvalidData('fixture reader failure')
        with patch.object(probe,'WebSocketReaders',BrokenReader):
            row = await probe.stage(None,('A',),{'A':()},12)
        self.assertEqual(row['state'],'FAILED')
        self.assertTrue(row['reader_joined'])
        self.assertIn('errors',row)

    async def test_coverage_only_follows_valid_book_events(self):
        m = probe.Measurement((Subscription('b',('orderbook_delta',),('A','B'),True),),{})
        self.assertIsNone(m.full_snapshot)
        await m.consume('b',snapshot() | {'_received_mono':probe.time.monotonic()})
        self.assertIsNotNone(m.first_snapshot)
        self.assertIsNone(m.full_snapshot)
        await m.consume('b',snapshot(2,'B') | {'_received_mono':probe.time.monotonic()})
        self.assertIsNotNone(m.full_snapshot)
        self.assertEqual(m.sample(probe.time.monotonic())['refreshed_fresh'],2)

    async def test_sequence_gap_is_not_success(self):
        m = probe.Measurement((Subscription('b',('orderbook_delta',),('A','B'),True),),{})
        await m.consume('b',snapshot() | {'_received_mono':probe.time.monotonic()})
        with self.assertRaises(probe.InvalidData):
            await m.consume('b',snapshot(3,'B') | {'_received_mono':probe.time.monotonic()})
        self.assertIsNone(m.full_snapshot)
        self.assertEqual(m.sample(probe.time.monotonic())['valid_books'],0)

    def test_targets_fail_closed_for_missing_coverage_and_samples(self):
        row = dict(unique_books=1,markets=2,full_snapshot_seconds=None,
            steady_samples=0,minimum_fresh_fraction=0,cpu_percent_one_core=0,
            peak_sampled_working_set_bytes=0,event_loop_lag_ms={'p99':None},
            ingress_to_callback_ms={'p99':None},counts={})
        failures = probe.assess(row)
        self.assertIn('incomplete_snapshot_coverage',failures)
        self.assertIn('no_reference_checks',failures)
        row.update(unique_books=2,full_snapshot_seconds=1,steady_samples=2,
            minimum_fresh_fraction=1,event_loop_lag_ms={'p99':2},
            ingress_to_callback_ms={'p99':1},counts={'reference_program_snapshots':2})
        self.assertEqual(probe.assess(row),[])
        row['cpu_percent_one_core']=51
        self.assertEqual(probe.assess(row),['cpu_over_half_core'])

    async def test_stage_records_one_reasoned_outcome_per_market(self):
        class OneShotReader:
            def __init__(self,*args):
                self.queue = probe.asyncio.Queue()
                self.queued_bytes = 0
            async def run(self,consume):
                await consume('book-0',snapshot() | {'_received_mono':probe.time.monotonic()})
                await probe.asyncio.Event().wait()
        with patch.object(probe,'WebSocketReaders',OneShotReader):
            row = await probe.stage(None,('A',),{'A':()},12)
        self.assertEqual(len(row['market_outcomes']),1)
        self.assertEqual(row['market_outcomes'][0]['reasons'],['book_stale_over_5_seconds'])

    def test_percentiles_empty_and_small_samples(self):
        self.assertIsNone(probe.percentile([], .99))
        self.assertEqual(probe.percentile([3,1,2],.5),2)
        self.assertEqual(probe.percentile([3,1,2],.99),3)


if __name__=='__main__':
    unittest.main()
