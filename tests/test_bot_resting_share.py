"""Phase 3 measurement: per-market resting share (never order authority)."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS
import json
import unittest

from kalshi_bot.resting_share import RestingShare


def legs(*tickers):
    return tuple(NS(ticker=t) for t in tickers)


class RestingShareTests(unittest.TestCase):
    def test_share_is_leg_time_over_time_since_first_rested(self):
        r = RestingShare()
        r.sample(0, legs('A', 'A'))           # both legs resting
        for t in range(10, 610, 10):
            r.sample(t, legs('A', 'A') if t < 300 else legs('A') if t < 450 else legs())
        # 0-300 two legs, 300-450 one leg, 450-600 none: (300*2+150)/2/600
        self.assertAlmostEqual(r.share('A'), (600+150)/2/600)
        self.assertIsNone(r.share('B'))

    def test_a_market_counts_only_from_its_first_rest(self):
        r = RestingShare()
        for t in range(0, 610, 10):
            r.sample(t, legs('A', 'A') if t < 300 else legs('A', 'A', 'B', 'B'))
        for t in range(610, 1210, 10):
            r.sample(t, legs('B', 'B'))
        self.assertAlmostEqual(r.share('B'), 1.0)
        self.assertAlmostEqual(r.share('A'), 610/1200)  # the 600-610 interval began with A

    def test_unknown_views_and_long_gaps_count_neither_way(self):
        r = RestingShare()
        for t in range(0, 610, 10):
            r.sample(t, legs('A', 'A'))
        r.sample(620, None)                    # unverified: the next interval is skipped
        r.sample(630, legs())
        r.sample(5000, legs())                 # restart-sized gap: skipped
        for t in range(5010, 5610, 10):
            r.sample(t, legs())
        self.assertEqual(r.markets['A'][0], 600+600)
        self.assertAlmostEqual(r.share('A'), 600/1200)
        self.assertEqual(r.unknown, 1)

    def test_more_than_two_legs_count_as_a_full_pair(self):
        r = RestingShare()
        r.sample(0, legs('A', 'A', 'A'))
        r.sample(10, legs())
        self.assertEqual(r.markets['A'][1], 20)

    def test_too_little_time_gives_no_share(self):
        r = RestingShare()
        r.sample(0, legs('A', 'A'))
        r.sample(10, legs('A', 'A'))
        self.assertIsNone(r.share('A'))
        self.assertEqual(r.share('A', minimum_seconds=10), 1.0)
        self.assertIsNone(r.median_share())

    def test_least_recently_rested_markets_are_evicted_first(self):
        r = RestingShare()
        r.CAPACITY = 2
        r.sample(0, legs('A'))
        r.sample(10, legs('B'))
        r.sample(20, legs('A'))
        r.sample(30, legs('C'))
        self.assertEqual(set(r.markets), {'A', 'C'})

    def test_median_across_markets(self):
        r = RestingShare()
        for t in range(0, 1210, 10):
            r.sample(t, legs('A', 'A', 'B') if t < 600 else legs('C', 'C'))
        self.assertEqual(r.status()['markets'], 3)
        self.assertAlmostEqual(r.median_share(), r.share('A'))

    def test_saved_history_survives_a_restart(self):
        with TemporaryDirectory() as temp:
            path = Path(temp)/'resting_share.json'
            r = RestingShare(path)
            for t in range(0, 610, 10):
                r.sample(t, legs('B', 'B') if t < 20 else legs('A', 'A'))
            r.save()
            self.assertFalse(path.with_suffix('.tmp').exists())
            back = RestingShare(path).load()
            self.assertEqual(back.share('A'), r.share('A'))
            self.assertEqual(back.markets['A'][:2], r.markets['A'][:2])
            back.CAPACITY = 1
            back.sample(0, legs())             # eviction keeps the most recently rested
            self.assertEqual(set(back.markets), {'A'})

    def test_missing_corrupt_or_oversized_files_start_empty(self):
        with TemporaryDirectory() as temp:
            path = Path(temp)/'resting_share.json'
            self.assertEqual(RestingShare(path).load().markets, {})
            for text in ('{', '[]', '{"markets": {"A": [1]}}', '{"markets": {"A": ["x", 1]}}'):
                path.write_text(text, encoding='utf-8')
                self.assertEqual(RestingShare(path).load().markets, {}, text)
            path.write_text(json.dumps(dict(markets={'A': [100, -1], 'B': [100, 500]})),
                            encoding='utf-8')
            loaded = RestingShare(path).load()
            self.assertEqual(set(loaded.markets), {'B'})           # negative dropped
            self.assertEqual(loaded.markets['B'][:2], [100., 200.])  # clamped to 2 legs
            self.assertEqual(loaded.share('B', minimum_seconds=0), 1.0)
            loaded.BYTES_LIMIT = 5
            self.assertEqual(loaded.load().markets, {})
            self.assertIsNone(RestingShare().load().path)


if __name__ == '__main__':
    unittest.main()
