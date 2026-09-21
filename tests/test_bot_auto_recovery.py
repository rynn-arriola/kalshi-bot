"""D-025 automatic recovery, no network or trading side effects."""
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from kalshi_bot.account import AccountCoordinator, normalize_snapshot
from kalshi_bot.ledger import Fill, Ledger
from kalshi_bot.orders import OrderUpdate, timestamp_us
from kalshi_bot.position_basis import VenueCost
from kalshi_bot.recovery import HistoricalFill
from kalshi_bot.rest import ReadFailure, ReadResult, PageSet
from kalshi_bot.values import InvalidData
from kalshi_bot.writer import LedgerWriter

NOW = datetime(2026, 9, 20, 9, 59, 59, tzinfo=timezone.utc)
EXEC = NOW-timedelta(minutes=10)


def history(key="o", *, side="bid", qty="10", price="0.5", fee="0.01", when=EXEC, **changes):
    return dict(fill_id="f-"+key, trade_id="f-"+key, order_id=key, ticker="A", market_ticker="A",
        book_side=side, count_fp=qty, yes_price_dollars=price, fee_cost=fee,
        created_time=when.isoformat(), subaccount_number=0, exchange_index=0) | changes


def wire_order(key="o", **changes):
    return dict(order_id=key, client_order_id="c-"+key, ticker="A", book_side="bid",
        initial_count_fp="10", fill_count_fp="10", remaining_count_fp="0", status="executed",
        yes_price_dollars="0.5", subaccount_number=0, exchange_index=0,
        last_update_time=EXEC.isoformat()) | changes


class Reads:
    def __init__(self, rows=(), orders=None, archive=()):
        self.rows, self.orders, self.archive = tuple(rows), orders or {}, tuple(archive)
        self.calls, self.cutoff_count = [], 0
        self.hook = None

    async def read(self, name, **kwargs):
        self.calls.append((name, kwargs))
        if name == "order":
            value = self.orders.get(kwargs["order_id"])
            if value is None:
                raise ReadFailure(404)
            return ReadResult({"order": value}, 100)
        self.cutoff_count += 1
        if self.hook:
            self.hook(self.cutoff_count)
        stamp = (NOW-timedelta(days=1)).isoformat()
        return ReadResult({"trades_created_ts": stamp, "orders_updated_ts": stamp}, 100)

    async def collect(self, name, **kwargs):
        self.calls.append((name, kwargs))
        return PageSet(self.archive if name == "historical_orders" else self.rows, 1, 100)


class RecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name)/"ledger.db"
        self.writer = await LedgerWriter(self.path).start()
        self.owner = AccountCoordinator(self.writer, subaccount=0)
        self.owner.connect_generation()

    async def asyncTearDown(self):
        await self.writer.close()
        self.temp.cleanup()

    async def reserve(self, key="o", *, side="bid", price="0.5", qty="10", ticker="A"):
        await self.writer.reserve_intent("c-"+key, dict(ticker=ticker, side=side, price=price, count=qty,
            subaccount=0, exchange_index=0), EXEC)
        await self.writer.transition_intent("c-"+key, "SENDING")

    async def bind(self, key="o", *, side="bid", price="0.5", qty="10", filled="10", ticker="A"):
        await self.reserve(key, side=side, price=price, qty=qty, ticker=ticker)
        return await self.writer.order(OrderUpdate(key, "c-"+key, ticker, side, D(price), D(qty),
            D(filled), D(0), "executed", 0, 0, timestamp_us(EXEC.isoformat())), EXEC)

    async def recover(self, reads, now=lambda: NOW):
        return await self.owner.recover_history(reads, start=EXEC-timedelta(seconds=1),
                                               end=NOW+timedelta(seconds=10), now=now)

    async def test_owned_missing_fill_imports_and_releases_only_matching_terminal(self):
        await self.bind()
        result = await self.recover(Reads([history()]))
        self.assertEqual((result.seen, result.imported, result.already_recorded), (1, 1, 0))
        self.assertFalse(result.ready_for_entry)
        self.assertEqual((await self.writer.inventory()).positions, (("A", D(10)),))
        self.assertEqual((await self.writer.inventory()).unresolved_intents, 0)
        self.assertEqual((await self.writer.observe(NOW)).realized_pnl, D("-0.01"))

    async def test_duplicates_keep_original_receipt_across_restart_and_window(self):
        await self.bind()
        await self.recover(Reads([history()]))
        await self.writer.close()
        self.writer = await LedgerWriter(self.path).start()
        self.owner = AccountCoordinator(self.writer, subaccount=0)
        self.owner.connect_generation()
        result = await self.recover(Reads([history()]), now=lambda: NOW+timedelta(seconds=2))
        self.assertEqual((result.imported, result.already_recorded), (0, 1))
        self.assertEqual((await self.writer.observe(NOW+timedelta(seconds=2))).realized_pnl, 0)
        db = Ledger(self.path)
        try:
            self.assertEqual(db.connection.execute("SELECT received_at FROM fills").fetchone()[0], NOW.isoformat())
        finally:
            db.close()

    async def test_receipt_after_fetch_crosses_into_new_window(self):
        await self.bind()
        clock = [NOW]
        reads = Reads([history(fee="5")])
        reads.hook = lambda n: clock.__setitem__(0, NOW+timedelta(seconds=2)) if n == 2 else None
        await self.recover(reads, now=lambda: clock[0])
        self.assertEqual((await self.writer.observe(clock[0])).cap, 25)
        db = Ledger(self.path)
        try:
            self.assertEqual(db.realized(EXEC, NOW+timedelta(seconds=1)), 0)
        finally:
            db.close()

    async def test_unknown_send_binds_via_exact_rest_order_then_imports(self):
        await self.reserve()
        result = await self.recover(Reads([history()], {"o": wire_order()}))
        self.assertEqual(result.imported, 1)
        self.assertEqual(self.owner.order_states["o"].intent_state, "TERMINAL")

    async def test_archive_lookup_can_bind_missing_order_for_fill(self):
        await self.reserve()
        reads = Reads([history()], archive=[wire_order()])
        result = await self.recover(reads)
        self.assertEqual(result.imported, 1)
        self.assertEqual(sum(name == "historical_orders" for name, _ in reads.calls), 1)

    async def test_archive_fetch_shared_for_two_orders_same_market(self):
        await self.reserve("a")
        await self.reserve("b")
        reads = Reads([history("a"), history("b")], archive=[wire_order("a"), wire_order("b")])
        self.assertEqual((await self.recover(reads)).imported, 2)
        self.assertEqual(sum(name == "historical_orders" for name, _ in reads.calls), 1)

    async def test_foreign_or_absent_orders_never_import(self):
        for orders in ({"o": wire_order(client_order_id="other")}, {}):
            report = await self.recover(Reads([history()], orders))
            self.assertEqual(report.imported, 0)
            self.assertIn("unbound_fills_not_imported", report.blockers)
        self.assertEqual((await self.writer.inventory()).positions, ())

    async def test_unknown_identity_lookup_budget_is_32(self):
        reads = Reads([history(str(i)) for i in range(40)])
        report = await self.recover(reads)
        self.assertEqual(sum(name == "order" for name, _ in reads.calls), 32)
        self.assertEqual(sum(name == "historical_orders" for name, _ in reads.calls), 1)
        self.assertEqual(len(report.missing_fill_keys), 40)

    async def test_conflicting_order_terms_do_not_import(self):
        await self.reserve()
        with self.assertRaises(InvalidData):
            await self.recover(Reads([history()], {"o": wire_order(yes_price_dollars="0.9")}))
        db = Ledger(self.path)
        try:
            self.assertEqual(db.position("A"), 0)
        finally:
            db.close()

    async def test_duplicate_economics_conflict_preserves_original_pnl(self):
        await self.bind()
        await self.recover(Reads([history()]))
        with self.assertRaises(InvalidData):
            await self.recover(Reads([history(fee="0.02")]))
        self.assertTrue(self.writer.failed)
        db = Ledger(self.path)
        try:
            self.assertEqual(db.realized(EXEC, NOW+timedelta(seconds=5)), D("-0.01"))
        finally:
            db.close()

    async def test_each_fill_ratchets_even_if_later_profit_recovers_in_same_batch(self):
        await self.bind("open", price="0.1")
        await self.bind("close", side="ask", price="0.9")
        rows = [history("close", side="ask", price="0.9", fee="0", when=EXEC+timedelta(seconds=1)),
                history("open", price="0.1", fee="5")]
        report = await self.recover(Reads(rows))  # Newest-first endpoint; deterministic replay sorts it.
        self.assertEqual(report.imported, 2)
        state = await self.writer.observe(NOW)
        self.assertEqual((state.realized_pnl, state.cap), (D(3), 25))

    async def test_invalid_later_fill_rolls_back_whole_32_fill_chunk(self):
        await self.bind()
        records = tuple(HistoricalFill(Fill(str(i), "o", "A", "bid", D(6), D("0.5"), D(1),
            timestamp_us(EXEC.isoformat())+i), timestamp_us(EXEC.isoformat())+i, 0, 0) for i in range(2))
        with self.assertRaises(InvalidData):
            await self.writer.recover_fills(records, subaccount=0, now=NOW)
        db = Ledger(self.path)
        try:
            self.assertEqual(db.position("A"), 0)
            self.assertEqual(db.connection.execute("SELECT COUNT(*) FROM fills").fetchone()[0], 0)
            self.assertEqual(db.connection.execute("SELECT COUNT(*) FROM risk_windows").fetchone()[0], 0)
        finally:
            db.close()

    async def test_account_or_shard_conflict_rejected(self):
        await self.bind()
        record = HistoricalFill(Fill("x", "o", "A", "bid", D(10), D("0.5"), D(0)),
                                timestamp_us(EXEC.isoformat()), 0, 1)
        with self.assertRaises(InvalidData):
            await self.writer.recover_fills((record,), subaccount=0, now=NOW)

    async def test_disconnect_before_apply_imports_nothing(self):
        await self.bind()
        reads = Reads([history()])
        reads.hook = lambda _: self.owner.disconnect()
        self.assertIsNone(await self.recover(reads))
        self.assertEqual((await self.writer.inventory()).positions, ())

    async def test_interruption_between_batches_publishes_no_complete_report(self):
        await self.bind(qty="33", filled="33")
        rows = [history(trade_id=str(i), fill_id=str(i), qty="1", when=EXEC+timedelta(microseconds=i)) for i in range(33)]
        original, sizes = self.writer.recover_fills, []
        async def interrupted(records, **kwargs):
            sizes.append(len(records))
            result = await original(records, **kwargs)
            self.owner.disconnect()
            return result
        with patch.object(self.writer, "recover_fills", side_effect=interrupted):
            self.assertIsNone(await self.recover(Reads(rows)))
        self.assertEqual(sizes, [32])
        self.assertEqual((await self.writer.inventory()).positions, (("A", D(32)),))
        self.assertIsNone(self.owner.history_report)
        self.owner.connect_generation()
        result = await self.recover(Reads(rows))
        self.assertEqual((result.imported, result.already_recorded), (1, 32))


class VenueBasisTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = RecoveryTests.asyncSetUp
    asyncTearDown = RecoveryTests.asyncTearDown
    reserve = RecoveryTests.reserve
    bind = RecoveryTests.bind

    async def snapshot(self, qty="10", cost="5.98", *, now=NOW, orders=()):
        positions = [] if qty == "0" else [dict(ticker="A", exchange_index=0,
                                               position_fp=qty, market_exposure_dollars=cost)]
        snap = normalize_snapshot(orders, positions, {"balance_dollars": "500", "updated_ts": 1}, subaccount=0)
        return await self.owner.finish_reconciliation(self.owner.begin_reconciliation(now), snap, now)

    async def test_venue_cost_fallback_is_exit_only_not_fake_fill_or_pnl(self):
        await self.bind()
        report = await self.snapshot()
        self.assertFalse(report.positions_match)
        basis = await self.owner.exit_basis("A", now=NOW)
        self.assertEqual((basis.quantity, basis.yes_price, basis.source), (D(10), D("0.598"), "venue_cost_rest"))
        self.assertTrue(basis.exit_only)
        self.assertFalse(basis.complete_fill_history)
        self.assertEqual((await self.writer.inventory()).positions, ())
        self.assertEqual((await self.writer.observe(NOW)).realized_pnl, 0)

    async def test_no_position_uses_one_minus_economic_cost(self):
        await self.bind(side="ask")
        await self.snapshot("-10", "7.07")
        self.assertEqual((await self.owner.exit_basis("A", now=NOW)).yes_price, D("0.293"))

    async def test_no_owned_quantity_no_basis(self):
        await self.snapshot()
        self.assertIsNone(await self.owner.exit_basis("A", now=NOW))

    async def test_owned_quantity_mismatch_rejects_fallback(self):
        await self.bind(filled="8")
        await self.snapshot()
        self.assertIsNone(await self.owner.exit_basis("A", now=NOW))

    async def test_local_fill_basis_preferred_when_quantity_agrees(self):
        await self.bind()
        await self.writer.fill(Fill("f", "o", "A", "bid", D(10), D("0.5"), D(0)), NOW)
        await self.snapshot(cost="5")
        result = await self.owner.exit_basis("A", now=NOW)
        self.assertEqual((result.source, result.yes_price), ("local_fills", D("0.5")))

    async def test_stale_disconnected_or_private_event_invalidates_basis(self):
        await self.bind()
        await self.snapshot()
        self.assertIsNone(await self.owner.exit_basis("A", now=NOW+timedelta(seconds=6)))
        await self.owner.on_event({"type": "order_group_updates", "msg": {}},
                                 generation=self.owner.generation, received_at=NOW)
        self.assertIsNone(await self.owner.exit_basis("A", now=NOW))
        await self.snapshot()
        self.owner.disconnect()
        self.assertIsNone(await self.owner.exit_basis("A", now=NOW))

    async def test_first_seen_clock_survives_restart_but_requires_fresh_snapshot(self):
        await self.bind()
        await self.snapshot()
        await self.writer.close()
        self.writer = await LedgerWriter(self.path).start()
        self.owner = AccountCoordinator(self.writer, subaccount=0)
        self.owner.connect_generation()
        later = NOW+timedelta(minutes=20)
        self.assertIsNone(await self.owner.exit_basis("A", now=later))
        await self.snapshot(now=later)
        self.assertEqual((await self.owner.exit_basis("A", now=later)).first_seen_at, NOW)

    async def test_flat_observation_resets_clock_not_fill_ledger(self):
        await self.bind()
        await self.snapshot()
        await self.snapshot("0", "0", now=NOW+timedelta(seconds=1))
        await self.snapshot(now=NOW+timedelta(seconds=2))
        basis = await self.owner.exit_basis("A", now=NOW+timedelta(seconds=2))
        self.assertEqual(basis.first_seen_at, NOW+timedelta(seconds=2))

    async def test_fresh_matching_stream_cost_remains_primary(self):
        await self.bind()
        await self.owner.on_event({"type": "market_position", "msg": dict(subaccount=0,
            market_ticker="A", position_fp="10", position_cost_dollars="5.98")},
            generation=self.owner.generation, received_at=NOW)
        await self.snapshot(now=NOW+timedelta(seconds=1))
        result = await self.owner.exit_basis("A", now=NOW+timedelta(seconds=1))
        self.assertEqual(result.source, "venue_cost_websocket")
        self.assertEqual(result.first_seen_at, NOW)

    async def test_ambiguous_intent_blocks_fallback(self):
        await self.bind()
        await self.reserve("unknown")
        await self.snapshot()
        self.assertIsNone(await self.owner.exit_basis("A", now=NOW))

    async def test_zero_or_out_of_range_cost_not_guessed(self):
        await self.bind()
        for cost in ("0", "10", "15"):
            await self.snapshot(cost=cost)
            self.assertIsNone(await self.owner.exit_basis("A", now=NOW))

    async def test_backwards_snapshot_does_not_reset_absent_clock(self):
        await self.bind()
        await self.snapshot()
        with self.assertRaises(InvalidData):
            await self.writer.venue_snapshot((), subaccount=0, now=NOW-timedelta(seconds=1))
