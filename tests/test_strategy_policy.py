from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from strategy_policy import polymarket_entry_quotes  # noqa: E402
from net_sizing import target_quote  # noqa: E402


class PolymarketStrategyPolicyTests(unittest.TestCase):
    def test_wide_book_joins_both_touches(self) -> None:
        quotes = polymarket_entry_quotes(0.43, 0.50, 0.01)
        self.assertIsNotNone(quotes)
        assert quotes is not None
        self.assertEqual((quotes.yes_bid, quotes.yes_offer), (0.43, 0.50))
        self.assertTrue(quotes.joined_touch)

    def test_one_cent_book_is_backed_out_to_exactly_two_cents(self) -> None:
        quotes = polymarket_entry_quotes(0.49, 0.50, 0.01)
        self.assertIsNotNone(quotes)
        assert quotes is not None
        self.assertEqual((quotes.yes_bid, quotes.yes_offer), (0.49, 0.51))
        self.assertFalse(quotes.joined_touch)

    def test_locked_book_is_backed_out_around_the_midpoint(self) -> None:
        quotes = polymarket_entry_quotes(0.50, 0.50, 0.01)
        self.assertIsNotNone(quotes)
        assert quotes is not None
        self.assertEqual((quotes.yes_bid, quotes.yes_offer), (0.49, 0.51))

    def test_crossed_book_is_rejected(self) -> None:
        self.assertIsNone(polymarket_entry_quotes(0.51, 0.50, 0.01))

    def test_non_cent_grid_preserves_minimum_gap(self) -> None:
        quotes = polymarket_entry_quotes(0.49, 0.50, 0.005)
        self.assertIsNotNone(quotes)
        assert quotes is not None
        self.assertAlmostEqual(quotes.yes_offer - quotes.yes_bid, 0.02)

    def test_replay_joins_displayed_queue_on_a_wide_book(self) -> None:
        book = {
            "bid": 0.43, "bid_size": 12.0,
            "offer": 0.50, "offer_size": 18.0,
        }
        self.assertEqual(
            target_quote("polymarket-current", book, 0.01),
            (0.43, 12.0, 0.50, 18.0))

    def test_replay_tracks_queue_only_on_touch_side_of_tight_book(self) -> None:
        book = {
            "bid": 0.49, "bid_size": 12.0,
            "offer": 0.50, "offer_size": 18.0,
        }
        self.assertEqual(
            target_quote("polymarket-current", book, 0.01),
            (0.49, 12.0, 0.51, 0.0))


if __name__ == "__main__":
    unittest.main()
