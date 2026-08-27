from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from exit_cost import (  # noqa: E402
    book_at_or_after,
    crossed_exit,
    exit_quote_price,
    settlement_pnl,
    taker_fee,
)


def snapshot(ts: float, bid: float = 0.40, offer: float = 0.60) -> dict:
    return {
        "ts": ts,
        "bid": bid,
        "bid_size": 20.0,
        "offer": offer,
        "offer_size": 30.0,
        "ladders": {
            "yes": [(bid, 10.0), (round(bid - 0.01, 2), 20.0)],
            "no": [(round(1.0 - offer, 2), 10.0),
                   (round(1.0 - offer - 0.01, 2), 20.0)],
        },
    }


class ExitCostTests(unittest.TestCase):
    def test_timed_book_never_uses_a_pre_deadline_snapshot(self) -> None:
        series = [snapshot(100), snapshot(110), snapshot(121), snapshot(130)]
        found = book_at_or_after(series, 0, 120, 5)
        self.assertIsNotNone(found)
        assert found is not None
        self.assertEqual(found[0], 2)
        self.assertEqual(found[1]["ts"], 121)

    def test_timed_book_rejects_a_capture_gap(self) -> None:
        series = [snapshot(100), snapshot(150)]
        self.assertIsNone(book_at_or_after(series, 0, 120, 20))

    def test_long_yes_cross_walks_later_yes_bids_and_charges_fee(self) -> None:
        later = snapshot(120, bid=0.35, offer=0.55)
        result = crossed_exit(later, direction=1.0, size=15.0)
        self.assertIsNotNone(result)
        assert result is not None
        vwap, filled, fee = result
        self.assertAlmostEqual(vwap, (10 * 0.35 + 5 * 0.34) / 15)
        self.assertEqual(filled, 15.0)
        self.assertEqual(fee, taker_fee(filled, vwap))

    def test_short_yes_cross_uses_no_bids_as_yes_asks(self) -> None:
        later = snapshot(120, bid=0.35, offer=0.55)
        result = crossed_exit(later, direction=-1.0, size=15.0)
        self.assertIsNotNone(result)
        assert result is not None
        vwap, filled, _ = result
        self.assertAlmostEqual(vwap, (10 * 0.55 + 5 * 0.56) / 15)
        self.assertEqual(filled, 15.0)

    def test_settlement_uses_signed_yes_equivalent_economics(self) -> None:
        self.assertAlmostEqual(settlement_pnl(0.0, 1.0, 0.40, 10), -4.0)
        self.assertAlmostEqual(settlement_pnl(0.0, -1.0, 0.60, 10), 6.0)
        self.assertAlmostEqual(settlement_pnl(1.0, 1.0, 0.40, 10), 6.0)
        self.assertAlmostEqual(settlement_pnl(1.0, -1.0, 0.60, 10), -4.0)

    def test_passive_exit_quote_only_improves_without_locking_loss(self) -> None:
        book = snapshot(100, bid=0.40, offer=0.60)
        self.assertEqual(exit_quote_price(book, 1.0, 0.50, 0.01), 0.59)
        self.assertEqual(exit_quote_price(book, 1.0, 0.595, 0.01), 0.60)
        self.assertEqual(exit_quote_price(book, -1.0, 0.50, 0.01), 0.41)
        self.assertEqual(exit_quote_price(book, -1.0, 0.405, 0.01), 0.40)


if __name__ == "__main__":
    unittest.main()
