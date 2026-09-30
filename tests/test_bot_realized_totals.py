"""D-162: the rolling 24-hour realized total behind the $60 loss limit."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from kalshi_bot.ledger import Fill, Ledger
from kalshi_bot.risk import WindowRisk
from kalshi_bot.values import InvalidData

NOW = datetime(2026, 9, 20, 9, tzinfo=timezone.utc)


def fill(key, side="bid", qty="10", price="0.5", fee="0.1"):
    return Fill(key, "o"+key, "A", side, D(qty), D(price), D(fee))


class RollingTotalTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/"ledger.db"
        self.db = Ledger(self.path)
        self.addCleanup(lambda: self.db.close())

    def test_sums_receipts_inside_the_window_with_inclusive_ends(self):
        self.db.record_fill(fill("1", fee="0.1"), NOW-timedelta(hours=30))        # outside
        self.db.record_fill(fill("2", "ask", price="0.4", fee="0.2"), NOW-timedelta(hours=24))
        self.db.record_fill(fill("3", fee="0.3"), NOW)
        self.assertEqual(self.db.realized_since(NOW-timedelta(hours=24), NOW),
                         self.db.realized(NOW-timedelta(hours=24), NOW+timedelta(microseconds=1)))
        self.assertEqual(self.db.realized_since(NOW, NOW), D("-0.3"))
        self.assertEqual(self.db.realized_since(NOW+timedelta(seconds=1), NOW+timedelta(hours=1)), 0)

    def test_a_moving_window_adds_no_cached_rows(self):
        self.db.record_fill(fill("1"), NOW)
        before = self.db.connection.execute("SELECT COUNT(*) FROM realized_totals").fetchone()[0]
        risk = WindowRisk(self.db)
        for second in range(50):
            risk.observe(NOW+timedelta(seconds=second))
        after = self.db.connection.execute("SELECT COUNT(*) FROM realized_totals").fetchone()[0]
        self.assertEqual(before, after)

    def test_invalid_window_refused(self):
        with self.assertRaises(InvalidData):
            self.db.realized_since(NOW, NOW-timedelta(seconds=1))

    def test_same_total_after_restart(self):
        self.db.record_fill(fill("1", fee="0.25"), NOW)
        first = WindowRisk(self.db).observe(NOW).realized_pnl
        self.db.close()
        self.db = Ledger(self.path)
        self.assertEqual(WindowRisk(self.db).observe(NOW).realized_pnl, first)


if __name__ == '__main__':
    unittest.main()
