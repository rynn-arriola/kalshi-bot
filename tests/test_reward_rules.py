from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from reward_rules import (  # noqa: E402
    DEFAULT_RULE_MODE,
    RewardRuleMode,
    calculate_payout,
    qualify_side,
    rule_banner,
    share_with_order,
    snapshot_qualifies,
)


class RewardRuleTests(unittest.TestCase):
    def setUp(self) -> None:
        # Target 100. The best 10 contracts do not set the July reference;
        # cumulative size first reaches one fifth (20) at 0.59.
        self.ladder = [(0.60, 10), (0.59, 10), (0.58, 80)]

    def test_current_default_is_july_rule(self) -> None:
        self.assertEqual(DEFAULT_RULE_MODE, RewardRuleMode.JULY_2026)
        banner = rule_banner()
        self.assertIn("source 2026-07-15", banner)
        self.assertIn("CURRENT", banner)

    def test_one_fifth_reference_differs_from_legacy_best_bid(self) -> None:
        current = qualify_side(self.ladder, 100, 0.5)
        legacy = qualify_side(
            self.ladder, 100, 0.5,
            mode=RewardRuleMode.FEBRUARY_2026)

        self.assertEqual(current.reference_price, 0.59)
        self.assertAlmostEqual(current.total_score, 60.0)
        self.assertEqual(legacy.reference_price, 0.60)
        self.assertAlmostEqual(legacy.total_score, 35.0)

    def test_levels_better_than_reference_receive_full_credit(self) -> None:
        result = qualify_side(self.ladder, 100, 0.5)
        # 10 @ .60 + 10 @ .59 receive 1.0x; 80 @ .58 receive 0.5x.
        self.assertAlmostEqual(result.total_score, 10 + 10 + 40)

    def test_missing_target_clears_the_side(self) -> None:
        result = qualify_side([(0.60, 10), (0.59, 20)], 100, 0.5)
        self.assertFalse(result.reached_target)
        self.assertEqual(result.total_score, 0.0)
        self.assertEqual(result.qualifying_levels, ())

    def test_proposed_order_is_inserted_before_reference_and_cutoff(self) -> None:
        share = share_with_order(
            [(0.60, 10), (0.59, 10), (0.58, 70)],
            100, 0.5, 0.61, 10)
        # Reference becomes .60 after .61 + .60 reach 20. Our better order gets
        # full credit. Total = 10 + 10 + 5 + 17.5 = 42.5.
        self.assertAlmostEqual(share or 0.0, 10 / 42.5)

    def test_snapshot_requires_both_sides_to_reach_target(self) -> None:
        self.assertTrue(snapshot_qualifies(
            self.ladder, self.ladder, 100, 0.5))
        self.assertFalse(snapshot_qualifies(
            self.ladder, [(0.40, 99)], 100, 0.5))

    def test_current_payout_scales_for_excluded_snapshots(self) -> None:
        result = calculate_payout(0.20, 100, 8000, 10000)
        self.assertEqual(result.non_excluded_fraction, Decimal("0.8"))
        self.assertEqual(result.raw_payout, Decimal("16.000"))
        self.assertEqual(result.payable_payout, Decimal("16.00"))

    def test_legacy_payout_does_not_scale_pool(self) -> None:
        result = calculate_payout(
            0.20, 100, 8000, 10000,
            mode=RewardRuleMode.FEBRUARY_2026)
        self.assertEqual(result.raw_payout, Decimal("20.0"))
        self.assertEqual(result.payable_payout, Decimal("20.00"))

    def test_minimum_and_round_down_are_applied_in_filed_order(self) -> None:
        below = calculate_payout(0.00999, 100, 10, 10)
        above = calculate_payout(0.01009, 100, 10, 10)
        self.assertEqual(below.raw_payout, Decimal("0.99900"))
        self.assertEqual(below.payable_payout, Decimal("0.00"))
        self.assertEqual(above.raw_payout, Decimal("1.00900"))
        self.assertEqual(above.payable_payout, Decimal("1.00"))

    def test_invalid_snapshot_counts_fail_loudly(self) -> None:
        with self.assertRaises(ValueError):
            calculate_payout(0.1, 100, 11, 10)

    def test_impossible_order_price_fails_loudly(self) -> None:
        with self.assertRaises(ValueError):
            share_with_order(self.ladder, 100, 0.5, 1.0, 5)


if __name__ == "__main__":
    unittest.main()
