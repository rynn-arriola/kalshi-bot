"""Public census tests: synthetic responses only, no credentials/network."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from kalshi_bot.rest import WireResponse
from test_bot_selection import book, program, terms, NOW

spec = importlib.util.spec_from_file_location('market_gate_census',
    Path(__file__).resolve().parents[1]/'scripts'/'check_live_market_gates.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class CensusTests(unittest.TestCase):
    def test_actual_selector_accepts_economic_fixture_and_rejects_small_reward(self):
        result = SimpleNamespace(terms=terms(),blockers=())
        good = probe.evaluate(book(),(program(pool_centicents=5000000),),result,NOW)
        self.assertTrue(good['passed'])
        self.assertEqual(len(good['retained_values']),2)
        bad = probe.evaluate(book(),(program(pool_centicents=1),),result,NOW)
        self.assertFalse(bad['passed'])
        self.assertIn('projected_reward_below_minimum',bad['reasons'])

    def test_missing_timing_evidence_never_passes(self):
        result = SimpleNamespace(terms=terms(),blockers=('timing_review_conflict',))
        row = probe.evaluate(book(),(program(pool_centicents=5000000),),result,NOW)
        self.assertFalse(row['passed'])
        self.assertIn('timing_review_conflict',row['reasons'])

    def test_private_and_unrelated_urls_and_headers_never_reach_network(self):
        base = 'https://external-api.kalshi.com/trade-api/v2/'
        for url, headers in ((base+'portfolio/orders',{}),
                (base+'markets/A/orderbook',{}),
                ('https://example.com/trade-api/v2/markets/A',{}),
                (base+'markets/A',{'KALSHI-ACCESS-KEY':'fixture'})):
            with patch.object(probe,'get_wire') as wire:
                with self.assertRaises(probe.InvalidData):
                    probe.PublicWire()(url,headers,1024)
                wire.assert_not_called()

    def test_429_latches_without_further_requests(self):
        reader = probe.PublicWire()
        with patch.object(probe,'get_wire',return_value=WireResponse(429,b'{}')) as wire:
            for _ in range(2):
                with self.assertRaises(probe.InvalidData):
                    reader('https://external-api.kalshi.com/trade-api/v2/incentive_programs',{},1024)
            self.assertEqual(wire.call_count,1)

    def test_public_metadata_passes_through_and_counts_bytes(self):
        reader = probe.PublicWire()
        response = WireResponse(200,b'{}')
        with patch.object(probe,'get_wire',return_value=response):
            self.assertIs(reader('https://external-api.kalshi.com/trade-api/v2/events/fee_changes?event_ticker=A',
                                 {'Accept':'application/json'},1024),response)
        self.assertEqual((reader.calls,reader.bytes),(1,2))


if __name__=='__main__':
    unittest.main()
