from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from portfolio_exit import (  # noqa: E402
    fee, maximum_loss, merged_ticker_intervals, parse_settlement_overrides,
    replay_interval,
)


class PortfolioExitTests(unittest.TestCase):
    def test_maximum_loss_uses_yes_equivalent_direction(self):
        self.assertAlmostEqual(maximum_loss(1.0, 0.30, 10), -3.0)
        self.assertAlmostEqual(maximum_loss(-1.0, 0.30, 10), -7.0)

    def test_fee_uses_requested_rate_and_four_decimal_ceiling(self):
        self.assertEqual(fee(1, 0.5, 0.07), 0.0175)
        self.assertEqual(fee(1, 0.5, 0.0175), 0.0044)

    def test_adjacent_equal_ticker_intervals_merge(self):
        schedule = [
            {"start": "2026-09-01T00:00:00Z", "end": "2026-09-02T00:00:00Z",
             "tickers": ["A"], "items": [{"ticker": "A", "per_day": 2.0,
               "programs": [{"id": "p", "target_size": 100,
                             "discount_factor": 0.5}]}]},
            {"start": "2026-09-02T00:00:00Z", "end": "2026-09-03T00:00:00Z",
             "tickers": ["A"], "items": [{"ticker": "A", "per_day": 2.0,
               "programs": [{"id": "p", "target_size": 100,
                             "discount_factor": 0.5}]}]},
        ]
        intervals = merged_ticker_intervals(schedule)
        self.assertEqual(len(intervals["A"]), 1)
        self.assertEqual(intervals["A"][0][2], 2.0)

    def test_settlement_overrides_parse_yes_and_no(self):
        self.assertEqual(
            parse_settlement_overrides(["A=yes", "B=NO"]),
            {"A": 1.0, "B": 0.0})

    def test_invalid_settlement_override_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_settlement_overrides(["A=maybe"])

    def test_nonqualifying_book_cannot_create_a_fill(self):
        def snapshot(ts):
            return {
                "ts": ts, "bid": 0.40, "bid_size": 1.0,
                "offer": 0.60, "offer_size": 1.0,
                "ladders": {"yes": [(0.40, 1.0)], "no": [(0.40, 1.0)]},
            }
        args = SimpleNamespace(
            policy="touch", size=10.0, reward_rule="july-2026-one-fifth",
            max_book_gap=300.0, book_tolerance=90.0, exit_deadline=10.0,
            maker_rate=0.0, settlements={}, ticker="A")
        fills, _, _ = replay_interval(
            [snapshot(0.0), snapshot(60.0)], 0.01,
            [(30.0, 0.40, 100.0, "no")], 0.0, 60.0, 1.0,
            (("p", 100.0, 0.5),), args)
        self.assertEqual(fills, [])


if __name__ == "__main__":
    unittest.main()
