from __future__ import annotations

import sys
import sqlite3
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from reference_policy import (  # noqa: E402
    reference_order_prices, reference_target_quote, snapshot_tick,
    tick_sizes_from_market_meta,
)


class ReferencePolicyTests(unittest.TestCase):
    def setUp(self):
        self.ladders = {
            "yes": [(0.60, 40), (0.59, 100), (0.58, 100), (0.57, 760)],
            "no": [(0.38, 50), (0.37, 150), (0.36, 800)],
        }

    def test_reference_is_level_reaching_one_fifth_target(self):
        prices = reference_order_prices(
            self.ladders, 1000, 0.5,
            reward_rule="july-2026-one-fifth", tick=0.01)
        self.assertEqual(prices, {"yes": 0.58, "no": 0.37})

    def test_one_tick_behind_widens_both_sides(self):
        prices = reference_order_prices(
            self.ladders, 1000, 0.5,
            reward_rule="july-2026-one-fifth", tick=0.01, behind_ticks=1)
        self.assertEqual(prices, {"yes": 0.57, "no": 0.36})

    def test_reference_quote_joins_displayed_reference_queue(self):
        snapshot = {"ladders": self.ladders}
        quote = reference_target_quote(
            snapshot, 0.01, (("p", 1000, 0.5),),
            reward_rule="july-2026-one-fifth")
        self.assertEqual(quote, (0.58, 100, 0.63, 150))

    def test_snapshot_tick_uses_observed_grid(self):
        self.assertEqual(snapshot_tick({"yes": [(0.501, 1), (0.502, 1)]}), 0.001)

    def test_market_metadata_tick_overrides_sparse_displayed_levels(self):
        connection = sqlite3.connect(":memory:")
        connection.execute(
            "CREATE TABLE market_meta (market_ticker TEXT, fetched_at TEXT,"
            " raw_json TEXT)")
        connection.execute(
            "INSERT INTO market_meta VALUES (?, ?, ?)",
            ("A", "2026-01-01T00:00:00Z",
             '{"market":{"ticker":"A","price_ranges":'
             '[{"start":"0","end":"1","step":"0.0100"}]}}'))
        self.assertEqual(tick_sizes_from_market_meta(connection), {"A": 0.01})


if __name__ == "__main__":
    unittest.main()
