"""D-024 accounting regressions. Local disposable ledgers; no trading calls."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from kalshi_bot.adapters import parse_fill
from kalshi_bot.ledger import Fill, Ledger
from kalshi_bot.recovery import parse_history_fill
from kalshi_bot.risk import WindowRisk
from kalshi_bot.values import InvalidData
from kalshi_bot.writer import LedgerWriter

NOW = datetime(2026, 9, 20, 9, tzinfo=timezone.utc)
BOUNDARY = NOW+timedelta(hours=1)  # 06:00 Eastern
EXECUTED = 1789800000000000


def fill(key, side="bid", qty="10", price="0.5", fee="0", **kwargs):
    return Fill(key, "order-"+key, "A", side, D(qty), D(price), D(fee), **kwargs)


class AccountingTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/"ledger.db"
        self.db = Ledger(self.path)
        self.addCleanup(lambda: self.db.close())

    def pnl(self):
        return self.db.realized(NOW, NOW+timedelta(days=1))

    def basis(self):
        row = self.db.connection.execute("SELECT yes_price FROM lots WHERE ticker='A'").fetchone()
        return D(row[0]) if row else None

    def restart(self):
        self.db.close()
        self.db = Ledger(self.path)

    def test_long_weighted_average_not_fifo(self):
        for f in (fill("1", qty="2", price="0.2"), fill("2", qty="6", price="0.6"),
                  fill("3", "ask", "3", "0.4")):
            self.db.record_fill(f, NOW)
        self.assertEqual(self.db.position("A"), 5)
        self.assertEqual(self.basis(), D("0.5"))
        self.assertEqual(self.pnl(), D("-0.3"))
        self.assertEqual(self.db.connection.execute("SELECT COUNT(*) FROM lots").fetchone()[0], 1)

    def test_short_weighted_average_not_fifo(self):
        for f in (fill("1", "ask", "2", "0.2"), fill("2", "ask", "6", "0.6"),
                  fill("3", "bid", "3", "0.4")):
            self.db.record_fill(f, NOW)
        self.assertEqual(self.db.position("A"), -5)
        self.assertEqual(self.basis(), D("0.5"))
        self.assertEqual(self.pnl(), D("0.3"))

    def test_average_basis_and_partial_close_survive_restart(self):
        self.db.record_fill(fill("1", qty="2", price="0.2", fee="0.02"), NOW)
        self.db.record_fill(fill("2", qty="6", price="0.6", fee="0.06"), NOW)
        self.restart()
        self.db.record_fill(fill("3", "ask", "3", "0.4", "0.03"), NOW)
        self.restart()
        self.assertEqual(self.basis(), D("0.5"))
        self.assertEqual(self.pnl(), D("-0.41"))

    def test_flip_uses_new_fill_basis_and_charges_entire_fee(self):
        self.db.record_fill(fill("1", qty="4", price="0.6", fee="0.04"), NOW)
        self.db.record_fill(fill("2", "ask", "10", "0.4", "0.10"), NOW)
        self.assertEqual(self.pnl(), D("-0.94"))
        self.assertEqual(self.db.position("A"), -6)
        self.assertEqual(self.basis(), D("0.4"))
        self.db.record_fill(fill("3", "bid", "6", "0.3", "0.06"), NOW)
        self.assertEqual(self.pnl(), D("-0.40"))
        self.assertIsNone(self.basis())

    def test_flat_reopening_has_no_old_basis_or_deferred_fees(self):
        for f in (fill("1", fee="0.1"), fill("2", "ask", fee="0.2"),
                  fill("3", price="0.8", fee="0.3")):
            self.db.record_fill(f, NOW)
        self.assertEqual(self.basis(), D("0.8"))
        self.assertEqual(self.pnl(), D("-0.6"))
        self.assertEqual(self.db.connection.execute("SELECT fee FROM lots").fetchone()[0], "0")

    def test_opening_fees_stay_in_original_receipt_window(self):
        self.db.record_fill(fill("1", fee="0.10"), NOW)
        self.db.record_fill(fill("2", "ask", "4", "0.4", "0.04"), BOUNDARY)
        self.assertEqual(self.db.realized(NOW, BOUNDARY), D("-0.10"))
        self.assertEqual(WindowRisk(self.db).observe(BOUNDARY).realized_pnl, D("-0.44"))
        self.assertEqual(self.db.position("A"), 6)

    def test_late_fill_counts_now_once_not_execution_window(self):
        self.db.record_fill(fill("1", price="0.6"), NOW)
        delayed = fill("2", "ask", price="0.4", fee="0.10", executed_us=EXECUTED)
        self.db.record_fill(delayed, BOUNDARY)
        self.assertEqual(self.db.realized(NOW, BOUNDARY), 0)
        self.assertEqual(WindowRisk(self.db).observe(BOUNDARY).realized_pnl, D("-2.10"))
        self.restart()
        self.assertFalse(self.db.record_fill(delayed, BOUNDARY+timedelta(hours=6)))
        row = self.db.connection.execute("SELECT received_at,executed_us FROM fills WHERE id=?", (delayed.key,)).fetchone()
        self.assertEqual(tuple(row), (BOUNDARY.isoformat(), EXECUTED))
        self.assertEqual(self.pnl(), D("-2.10"))

    def test_receipt_order_not_execution_order_determines_basis(self):
        # Late opening-like bid is learned after the close; do not replay/rewrite.
        self.db.record_fill(fill("1", price="0.2", executed_us=EXECUTED), NOW)
        self.db.record_fill(fill("2", "ask", price="0.5", executed_us=EXECUTED+2), NOW)
        self.db.record_fill(fill("3", price="0.8", executed_us=EXECUTED+1), NOW)
        self.assertEqual(self.pnl(), 3)
        self.assertEqual(self.basis(), D("0.8"))

    def test_reporting_timestamp_enrichment_never_moves_receipt_or_charges_fee(self):
        f = fill("1", fee="0.1")
        self.db.record_fill(f, NOW)
        self.assertFalse(self.db.record_fill(replace(f, executed_us=EXECUTED), BOUNDARY))
        self.assertFalse(self.db.record_fill(f, BOUNDARY))
        row = self.db.connection.execute("SELECT received_at,executed_us FROM fills").fetchone()
        self.assertEqual(tuple(row), (NOW.isoformat(), EXECUTED))
        self.assertEqual(self.pnl(), D("-0.1"))

    def test_coarse_timestamp_can_be_refined_not_downgraded(self):
        f = fill("1", executed_us=EXECUTED, execution_precision_us=1000000)
        self.db.record_fill(f, NOW)
        self.db.record_fill(replace(f, executed_us=EXECUTED+123456, execution_precision_us=1), NOW)
        self.db.record_fill(f, NOW)
        row = self.db.connection.execute("SELECT executed_us,execution_precision_us FROM fills").fetchone()
        self.assertEqual(tuple(row), (EXECUTED+123456, 1))

    def test_conflicting_timestamp_duplicate_fails_without_accounting_change(self):
        f = fill("1", fee="0.1", executed_us=EXECUTED)
        self.db.record_fill(f, NOW)
        with self.assertRaisesRegex(InvalidData, "execution time"):
            self.db.record_fill(replace(f, executed_us=EXECUTED+1), NOW)
        self.assertEqual(self.pnl(), D("-0.1"))
        self.assertEqual(self.db.position("A"), 10)

    def test_duplicate_changed_fee_requires_correction_policy(self):
        f = fill("1", fee="0.1")
        self.db.record_fill(f, NOW)
        with self.assertRaisesRegex(InvalidData, "economics"):
            self.db.record_fill(replace(f, fee=D("0.2")), NOW)
        self.assertEqual(self.pnl(), D("-0.1"))

    def test_separate_market_basis_and_fee_journal(self):
        self.db.record_fill(fill("1", price="0.8", fee="0.1"), NOW)
        self.db.record_fill(replace(fill("2", "ask", price="0.2", fee="0.1"), ticker="B"), NOW)
        self.assertEqual(self.pnl(), D("-0.2"))
        self.assertEqual(self.db.position("A"), 10)
        self.assertEqual(self.db.position("B"), -10)

    def test_fractional_contracts_weighted_average(self):
        for f in (fill("1", qty="0.01", price="0.2"), fill("2", qty="0.03", price="0.6"),
                  fill("3", "ask", "0.02", "0.4", "0.00001")):
            self.db.record_fill(f, NOW)
        self.assertEqual(self.basis(), D("0.5"))
        self.assertEqual(self.pnl(), D("-0.00201"))

    def test_outer_crash_rolls_back_basis_fee_and_execution_metadata(self):
        self.db.record_fill(fill("1", price="0.2", fee="0.1"), NOW)
        with self.assertRaises(RuntimeError), self.db.transaction():
            self.db.record_fill(fill("2", price="0.6", fee="0.2", executed_us=EXECUTED), NOW)
            raise RuntimeError("injected crash")
        self.restart()
        self.assertEqual(self.basis(), D("0.2"))
        self.assertEqual(self.pnl(), D("-0.1"))
        self.assertEqual(self.db.connection.execute("SELECT COUNT(*) FROM realized_events").fetchone()[0], 1)

    def test_many_same_side_fills_keep_one_indexed_position_row(self):
        with self.db.transaction():
            for i in range(1000):
                self.db.record_fill(fill(str(i), qty="0.01"), NOW)
        self.assertEqual(self.db.position("A"), 10)
        self.assertEqual(self.db.connection.execute("SELECT COUNT(*) FROM lots").fetchone()[0], 1)
        plan = self.db.connection.execute("EXPLAIN QUERY PLAN SELECT * FROM lots WHERE ticker='A'").fetchone()[3]
        self.assertIn("INDEX", plan)

    def test_negative_fee_still_requires_explicit_rebate_contract(self):
        with self.assertRaises(InvalidData):
            fill("1", fee="-0.1")


class SchemaGuardTests(unittest.TestCase):
    def test_old_or_unversioned_databases_are_refused_without_rewriting(self):
        for version in (None, "1", "99"):
            with self.subTest(version=version), TemporaryDirectory() as folder:
                path = Path(folder)/"old.db"
                db = sqlite3.connect(path)
                db.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT)")
                if version is not None:
                    db.execute("INSERT INTO meta VALUES('schema',?)", (version,))
                db.commit()
                db.close()
                before = path.read_bytes()
                with self.assertRaisesRegex(InvalidData, "migration required"):
                    Ledger(path)
                self.assertEqual(path.read_bytes(), before)
                self.assertFalse(Path(str(path)+"-wal").exists())


class TimestampTests(unittest.TestCase):
    def message(self, **kwargs):
        return {"type": "fill", "msg": dict(trade_id="t", order_id="o", market_ticker="A",
                book_side="bid", count_fp="10", yes_price_dollars="0.5", fee_cost="0.1", **kwargs)}

    def test_ms_preferred_and_seconds_must_agree(self):
        f = parse_fill(self.message(ts=1789800000, ts_ms=1789800000123))
        self.assertEqual((f.executed_us, f.execution_precision_us), (EXECUTED+123000, 1000))
        with self.assertRaises(InvalidData):
            parse_fill(self.message(ts=1789800001, ts_ms=1789800000123))

    def test_missing_time_stays_unknown_seconds_stays_coarse(self):
        self.assertIsNone(parse_fill(self.message()).executed_us)
        f = parse_fill(self.message(ts=1789800000))
        self.assertEqual((f.executed_us, f.execution_precision_us), (EXECUTED, 1000000))

    def test_malformed_timestamps_not_silently_ignored(self):
        for value in (None, True, "1790000000", 1.5, -1, 2**63):
            for field in ("ts", "ts_ms"):
                with self.subTest(value=value, field=field), self.assertRaises(InvalidData):
                    parse_fill(self.message(**{field: value}))

    def test_historical_timestamp_kept_inside_normalized_fill(self):
        row = dict(fill_id="t", trade_id="t", order_id="o", ticker="A", market_ticker="A",
                   book_side="bid", count_fp="10", yes_price_dollars="0.5", fee_cost="0.1",
                   created_time="2026-09-20T09:00:00.123456Z", subaccount_number=0, exchange_index=0)
        parsed = parse_history_fill(row)
        self.assertEqual(parsed.fill.executed_us, parsed.executed_us)
        self.assertEqual(parsed.fill.executed_us % 1000000, 123456)


class WriterAccountingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name)/"writer.db"
        self.writer = await LedgerWriter(self.path).start()

    async def asyncTearDown(self):
        await self.writer.close()
        self.temp.cleanup()

    async def test_open_fee_ratchets_atomically_profit_and_restart_cannot_widen(self):
        # Large synthetic fee tests the boundary, not a venue-fee estimate.
        ack = await self.writer.fill(fill("1", fee="5"), NOW)
        self.assertEqual((ack.window.realized_pnl, ack.window.cap), (D(-5), 25))
        ack = await self.writer.fill(fill("2", "ask", price="0.9"), NOW)
        self.assertEqual((ack.window.realized_pnl, ack.window.cap), (D(-1), 25))
        await self.writer.close()
        self.writer = await LedgerWriter(self.path).start()
        self.assertEqual((await self.writer.observe(NOW)).cap, 25)

    async def test_fee_triggered_hold_survives_restart_and_next_window(self):
        ack = await self.writer.fill(fill("1", fee="25"), NOW)
        self.assertTrue(ack.window.held)
        await self.writer.close()
        self.writer = await LedgerWriter(self.path).start()
        self.assertEqual((await self.writer.observe(BOUNDARY)).cap, 0)

    async def test_duplicate_next_window_does_not_repeat_fee(self):
        f = fill("1", fee="0.1")
        await self.writer.fill(f, NOW)
        ack = await self.writer.fill(f, BOUNDARY)
        self.assertFalse(ack.inserted)
        self.assertEqual(ack.window.realized_pnl, 0)

    async def test_risk_failure_rolls_back_entire_fee_journal(self):
        with patch("kalshi_bot.writer.WindowRisk.observe", side_effect=RuntimeError("fault")):
            with self.assertRaises(InvalidData):
                await self.writer.fill(fill("1", fee="5"), NOW)
        self.assertTrue(self.writer.failed)
        await self.writer.close()
        db = Ledger(self.path)
        try:
            self.assertEqual(db.position("A"), 0)
            self.assertEqual(db.connection.execute("SELECT COUNT(*) FROM realized_events").fetchone()[0], 0)
        finally:
            db.close()
