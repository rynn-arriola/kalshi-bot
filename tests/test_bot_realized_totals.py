"""Derived receipt totals must preserve D-024 accounting and rollback semantics."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from kalshi_bot.ledger import Fill, Ledger
from kalshi_bot.risk import WindowRisk, window_bounds
from kalshi_bot.values import InvalidData

NOW = datetime(2026, 9, 20, 9, tzinfo=timezone.utc)


def fill(key, side="bid", qty="10", price="0.5", fee="0.1"):
    return Fill(key, "o"+key, "A", side, D(qty), D(price), D(fee))


class TotalsTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/"ledger.db"
        self.db = Ledger(self.path)
        self.addCleanup(lambda: self.db.close())
        self.start, self.end = window_bounds(NOW)

    def total(self):
        return self.db.realized_incremental(self.start, self.end)

    def test_cold_then_incremental_partial_close_and_flip_match_full_scan(self):
        for item in (fill("1"), fill("2", price="0.3"),
                     fill("3", "ask", "7", "0.2"), fill("4", "ask", "20", "0.8"),
                     fill("5", "bid", "7", "0.6")):
            self.db.record_fill(item, NOW)
            self.assertEqual(self.total(), self.db.realized(self.start, self.end))

    def test_cold_schema_two_existing_fills_are_not_reset(self):
        self.db.record_fill(fill("1", fee="5"), NOW)
        self.db.connection.execute("DROP TABLE realized_totals")
        self.db.close()
        self.db = Ledger(self.path)
        state = WindowRisk(self.db).observe(NOW)
        self.assertEqual((state.realized_pnl, state.cap), (D(-5), 25))

    def test_restart_duplicate_and_timestamp_enrichment_do_not_charge_twice(self):
        item = fill("1")
        self.db.record_fill(item, NOW)
        self.assertEqual(self.total(), D("-0.1"))
        self.db.close()
        self.db = Ledger(self.path)
        self.db.record_fill(replace(item, executed_us=100), self.end)
        self.assertEqual(self.total(), D("-0.1"))

    def test_boundary_and_later_window_do_not_pollute_old_total(self):
        self.db.record_fill(fill("1"), NOW)
        self.total()
        self.db.record_fill(fill("2", "ask", price="0.4"), self.end)
        self.assertEqual(self.total(), D("-0.1"))
        state = WindowRisk(self.db).observe(self.end)
        self.assertEqual(state.realized_pnl, D("-1.1"))
        self.assertEqual(self.total(), D("-0.1"))

    def test_outer_rollback_restores_cursor_total_and_ratchet(self):
        self.db.record_fill(fill("1"), NOW)
        WindowRisk(self.db).observe(NOW)
        with self.assertRaises(RuntimeError), self.db.transaction():
            self.db.record_fill(fill("2", fee="25"), NOW)
            self.assertTrue(WindowRisk(self.db).observe(NOW).held)
            raise RuntimeError("crash")
        self.db.record_fill(fill("3", fee="0.2"), NOW)
        state = WindowRisk(self.db).observe(NOW)
        self.assertEqual((state.realized_pnl, state.cap, state.held), (D("-0.3"), 30, False))

    def test_cold_cache_created_inside_rollback_disappears(self):
        with self.assertRaises(RuntimeError), self.db.transaction():
            self.db.record_fill(fill("1"), NOW)
            self.total()
            raise RuntimeError("crash")
        self.assertEqual(self.db.connection.execute("SELECT COUNT(*) FROM realized_totals").fetchone()[0], 0)
        self.assertEqual(self.total(), 0)

    def test_query_plan_uses_new_rowid_range_not_full_time_window(self):
        plan = self.db.connection.execute(
            "EXPLAIN QUERY PLAN SELECT pnl FROM realized_events WHERE rowid>? AND rowid<=? "
            "AND received_at>=? AND received_at<? ORDER BY rowid",
            (100, 101, self.start.isoformat(), self.end.isoformat())).fetchone()[3]
        self.assertIn("INTEGER PRIMARY KEY", plan)
        self.assertIn("rowid>?", plan)

    def test_invalid_window_refused(self):
        with self.assertRaises(InvalidData):
            self.db.realized_incremental(self.end, self.start)

    def test_detects_journal_shrink_instead_of_returning_old_total(self):
        self.db.record_fill(fill("1"), NOW)
        self.total()
        with self.db.connection:
            self.db.connection.execute("DELETE FROM realized_events")
        with self.assertRaisesRegex(InvalidData, "shrank"):
            self.total()
