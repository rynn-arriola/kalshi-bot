import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import AsyncMock, patch

from kalshi_bot.account import AccountCoordinator, normalize_snapshot
from kalshi_bot.ledger import Fill, Ledger
from kalshi_bot.orders import (OrderReceipt, OrderUpdate, inventory_plan, parse_order,
                               record_order, timestamp_us)
from kalshi_bot.recovery import (HistoricalFill, HistoryEvidence, fetch_history,
                                 parse_history_fill, stage_history)
from kalshi_bot.rest import PageSet, ReadResult, RestReads, TokenBudget, request_path
from kalshi_bot.values import InvalidData
from kalshi_bot.writer import LedgerWriter

NOW = datetime(2026, 9, 20, 5, tzinfo=timezone.utc)
START = NOW-timedelta(hours=1)
END = NOW+timedelta(hours=1)


def update(**kwargs):
    fields = dict(order_id="order-1", client_id="client-1", ticker="A", side="bid",
                  yes_price=D("0.5"), initial=D(10), filled=D(0), remaining=D(10),
                  status="resting", subaccount=0, exchange_index=0, version_us=1000)
    return OrderUpdate(**(fields | kwargs))


def payload(**kwargs):
    return dict(ticker="A", side="bid", price="0.5", count="10", subaccount=0,
                exchange_index=0, reduce_only=False) | kwargs


def wire_order(**kwargs):
    return dict(order_id="order-1", client_order_id="client-1", ticker="A", book_side="bid",
                yes_price_dollars="0.5", initial_count_fp="10", fill_count_fp="0",
                remaining_count_fp="10", status="resting", subaccount_number=0,
                exchange_index=0, last_updated_ts_ms=1) | kwargs


def execution(key="trade-1", qty="10", **kwargs):
    return Fill(key, kwargs.get("order_id", "order-1"), kwargs.get("ticker", "A"),
                kwargs.get("side", "bid"), D(qty), D("0.5"), D("0.01"))


def history_row(key="trade-1", when=NOW, **kwargs):
    return dict(fill_id=key, trade_id=key, order_id="order-1", ticker="A", market_ticker="A",
                book_side="bid", count_fp="10", yes_price_dollars="0.5", fee_cost="0.01",
                created_time=when.isoformat(), subaccount_number=0, exchange_index=0) | kwargs


class FakeReads:
    def __init__(self, *, historical=(), current=(), cutoff=NOW, changed_cutoff=None, order=None):
        self.historical, self.current = tuple(historical), tuple(current)
        self.cutoff, self.changed_cutoff, self.order = cutoff, changed_cutoff, order
        self.calls, self.cutoff_calls = [], 0
        self.hook = None

    async def read(self, name, **kwargs):
        self.calls.append((name, kwargs))
        if self.hook:
            self.hook()
        if name == "order":
            if self.order is None:
                raise InvalidData("read failed with HTTP 404; no proof obtained")
            return ReadResult({"order": self.order}, 100)
        self.cutoff_calls += 1
        cutoff = self.changed_cutoff if self.cutoff_calls > 1 and self.changed_cutoff else self.cutoff
        return ReadResult({"trades_created_ts": cutoff.isoformat()}, 100)

    async def collect(self, name, **kwargs):
        self.calls.append((name, kwargs))
        rows = self.historical if name == "historical_fills" else self.current
        return PageSet(rows, 1, 100)


class OrderTests(unittest.TestCase):
    def setUp(self):
        self.db = Ledger(":memory:")
        self.db.reserve_intent("client-1", payload(), NOW)
        self.db.transition_intent("client-1", "SENDING")

    def tearDown(self):
        self.db.close()

    def test_exact_owned_order_binds_and_acknowledges(self):
        receipt = record_order(self.db, update(), NOW)
        self.assertTrue(receipt.owned)
        self.assertEqual(receipt.intent_state, "ACKNOWLEDGED")

    def test_foreign_order_is_not_adopted_by_prefix(self):
        result = record_order(self.db, update(client_id="client-foreign"), NOW)
        self.assertFalse(result.owned)
        self.assertEqual(self.db.connection.execute("SELECT COUNT(*) FROM order_evidence").fetchone()[0], 0)

    def test_term_mismatches_and_wrong_account_rejected(self):
        for kwargs in ({"ticker": "B"}, {"yes_price": "0.6"}, {"side": "ask"},
                       {"subaccount": 1}, {"exchange_index": 2}, {"initial": D(11)}):
            with self.subTest(kwargs=kwargs), self.assertRaises(InvalidData):
                record_order(self.db, update(**kwargs), NOW)

    def test_same_client_cannot_bind_two_venue_orders(self):
        record_order(self.db, update(), NOW)
        with self.assertRaises(InvalidData):
            record_order(self.db, update(order_id="duplicate"), NOW)

    def test_stale_order_cannot_revive_terminal(self):
        result = record_order(self.db, update(status="canceled", remaining=D(0), version_us=2000), NOW)
        self.assertEqual(result.intent_state, "TERMINAL")
        result = record_order(self.db, update(version_us=1000), NOW)
        self.assertFalse(result.applied)
        self.assertEqual(result.order.status, "canceled")

    def test_newer_order_cannot_revive_terminal(self):
        record_order(self.db, update(status="canceled", remaining=D(0)), NOW)
        with self.assertRaises(InvalidData):
            record_order(self.db, update(version_us=2000), NOW)

    def test_equal_version_conflict_or_missing_version_is_not_guessed(self):
        record_order(self.db, update(), NOW)
        for version in (1000, None):
            with self.assertRaises(InvalidData):
                record_order(self.db, update(filled=D(1), remaining=D(9), version_us=version), NOW)

    def test_duplicate_is_idempotent(self):
        record_order(self.db, update(), NOW)
        self.assertFalse(record_order(self.db, update(), NOW).applied)

    def test_terminal_waits_for_fill_accounting(self):
        receipt = record_order(self.db, update(status="executed", filled=D(10), remaining=D(0)), NOW)
        self.assertTrue(receipt.awaiting_fills)
        self.assertEqual(receipt.intent_state, "ACKNOWLEDGED")
        self.assertEqual(self.db.unresolved_intents(), 1)

    def test_terminal_with_accounted_fills_resolves_intent(self):
        self.db.record_fill(execution(), NOW)
        result = record_order(self.db, update(status="executed", filled=D(10), remaining=D(0)), NOW)
        self.assertFalse(result.awaiting_fills)
        self.assertEqual(result.intent_state, "TERMINAL")

    def test_filled_quantity_cannot_decrease(self):
        record_order(self.db, update(filled=D(2), remaining=D(8)), NOW)
        with self.assertRaises(InvalidData):
            record_order(self.db, update(filled=D(1), remaining=D(9), version_us=2000), NOW)

    def test_reserved_or_rejected_intent_cannot_claim_order(self):
        self.db.reserve_intent("reserved", payload(), NOW)
        with self.assertRaises(InvalidData):
            record_order(self.db, update(client_id="reserved"), NOW)

    def test_unknown_create_reconciles_by_exact_client_terms(self):
        self.db.transition_intent("client-1", "UNKNOWN")
        self.assertEqual(record_order(self.db, update(), NOW).intent_state, "ACKNOWLEDGED")

    def test_capacity_failure_is_atomic(self):
        with self.assertRaises(InvalidData):
            record_order(self.db, update(), NOW, capacity=0)
        self.assertEqual(self.db.connection.execute("SELECT state FROM intents").fetchone()[0], "SENDING")

    def test_order_parser_timestamp_variants_and_scope(self):
        self.assertEqual(parse_order(wire_order()).version_us, 1000)
        row = wire_order(last_updated_ts_ms=None, last_update_time=NOW.isoformat())
        self.assertEqual(parse_order(row).version_us, timestamp_us(NOW.isoformat()))
        row["subaccount_number"] = None
        with self.assertRaises(InvalidData):
            parse_order(row)
        self.assertEqual(parse_order(row, scope=0).subaccount, 0)
        snapshot = normalize_snapshot([row], [], {"balance_dollars": "500", "updated_ts": 1}, subaccount=0)
        self.assertEqual(snapshot.subaccount, 0)

    def test_unknown_status_bool_account_invalid_quantities(self):
        for kwargs in ({"status": "unknown"}, {"subaccount": True}, {"filled": "11"},
                       {"remaining": "0"}, {"status": "executed"}):
            with self.assertRaises(InvalidData):
                update(**kwargs)

    def test_single_order_get_path_cannot_escape(self):
        _, path = request_path("order", {"order_id": "order-1"}, "reconcile")
        self.assertEqual(path, "/portfolio/orders/order-1")
        with self.assertRaises(InvalidData):
            request_path("order", {"order_id": "../keys"}, "reconcile")


class InventoryPlanTests(unittest.TestCase):
    def receipt(self, **kwargs):
        reducing = kwargs.pop("reducing", False)
        return OrderReceipt(update(**kwargs), True, True, False, "ACKNOWLEDGED", reducing)

    def test_position_cancels_building_before_new_reducer(self):
        plan = inventory_plan(D(3), (self.receipt(),), ticker="A", touch=D("0.6"), complete_scope=True)
        self.assertEqual(plan.cancel_ids, ("order-1",))
        self.assertIsNone(plan.reduce_side)

    def test_exact_fractional_reducer_is_kept(self):
        order = self.receipt(side="ask", remaining=D("0.37"), yes_price=D("0.6"), reducing=True)
        plan = inventory_plan(D("0.37"), (order,), ticker="A", touch=D("0.6"), complete_scope=True)
        self.assertEqual(plan.keep_id, "order-1")
        self.assertEqual(plan.cancel_ids, ())
        self.assertEqual(plan.reduce_quantity, 0)

    def test_wrong_quantity_cancels_before_replacement(self):
        order = self.receipt(side="ask", reducing=True)
        plan = inventory_plan(D(3), (order,), ticker="A", touch=D("0.5"), complete_scope=True)
        self.assertEqual(plan.cancel_ids, ("order-1",))
        self.assertEqual(plan.reduce_quantity, 0)

    def test_no_order_plans_exact_qty_and_correct_yes_frame_side(self):
        for pos, side in ((D("0.37"), "ask"), (D("-2.5"), "bid")):
            plan = inventory_plan(pos, (), ticker="A", touch=D("0.5"), complete_scope=True)
            self.assertEqual(plan.reduce_side, side)
            self.assertEqual(plan.reduce_quantity, abs(pos))

    def test_unknown_scope_no_touch_foreign_or_unaccounted_fill_blocks(self):
        cases = [((), False, D("0.5")), ((), True, None),
                 ((replace(self.receipt(), owned=False),), True, D("0.5")),
                 ((replace(self.receipt(), awaiting_fills=True),), True, D("0.5"))]
        for orders, scope, touch in cases:
            plan = inventory_plan(D(2), orders, ticker="A", touch=touch, complete_scope=scope)
            self.assertIsNone(plan.reduce_side)
            self.assertTrue(plan.blockers)

    def test_duplicate_reducers_keep_only_one_and_cancel_other(self):
        one = self.receipt(side="ask", reducing=True)
        two = replace(one, order=replace(one.order, order_id="order-2", client_id="client-2"))
        plan = inventory_plan(D(10), (one, two), ticker="A", touch=D("0.5"), complete_scope=True)
        self.assertEqual(plan.keep_id, "order-1")
        self.assertEqual(plan.cancel_ids, ("order-2",))

    def test_flat_only_cancels_reducers_and_never_plans_entry(self):
        plan = inventory_plan(D(0), (self.receipt(reducing=True),), ticker="A", touch=D("0.5"), complete_scope=True)
        self.assertEqual(plan.cancel_ids, ("order-1",))
        self.assertIsNone(plan.reduce_side)

    def test_missing_touch_preserves_existing_reducer(self):
        reducer = self.receipt(side="ask", reducing=True)
        plan = inventory_plan(D(10), (reducer,), ticker="A", touch=None, complete_scope=True)
        self.assertEqual(plan.cancel_ids, ())
        self.assertIsNone(plan.reduce_side)
        self.assertIn("no_passive_touch", plan.blockers)


class HistoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_required_missing_cursor_does_not_mean_complete_page(self):
        client = RestReads(TokenBudget(rate=100, capacity=100, default_cost=10))
        try:
            for name, rows, reason in (("orders", "orders", "reconcile"), ("fills", "fills", "history"),
                                       ("historical_fills", "fills", "history")):
                with patch.object(client, "read", AsyncMock(return_value=ReadResult({rows: []}, 20))):
                    with self.assertRaisesRegex(InvalidData, "required pagination cursor"):
                        await client.collect(name, reason=reason)
            with patch.object(client, "read", AsyncMock(return_value=ReadResult({"market_positions": []}, 20))):
                with self.assertRaisesRegex(InvalidData, "required pagination cursor"):
                    await client.collect("positions", reason="reconcile")
            with patch.object(client, "read", AsyncMock(return_value=ReadResult({"market_positions": [],
                                                                                "cursor": ""}, 20))):
                self.assertEqual((await client.collect("positions", reason="reconcile")).rows, ())
        finally:
            await client.close()

    async def test_live_archive_overlap_deduplicates_exact_executions(self):
        row = history_row()
        reads = FakeReads(historical=[row], current=[row])
        result = await fetch_history(reads, start=START, end=END, subaccount=0)
        self.assertEqual(len(result.records), 1)
        self.assertEqual(result.pages, 2)
        historic = next(args for name, args in reads.calls if name == "historical_fills")
        current = next(args for name, args in reads.calls if name == "fills")
        self.assertEqual(historic["subaccount"], 0)
        self.assertEqual(current["subaccount"], 0)
        self.assertLess(current["min_ts"], int(NOW.timestamp()))
        self.assertGreater(historic["max_ts"], int(NOW.timestamp()))

    async def test_recent_only_avoids_unneeded_archive(self):
        reads = FakeReads(current=[history_row()], cutoff=START-timedelta(hours=1))
        result = await fetch_history(reads, start=START, end=END, subaccount=0)
        self.assertEqual(result.pages, 1)
        self.assertNotIn("historical_fills", [n for n, _ in reads.calls])

    async def test_archive_only_uses_documented_subaccount_query(self):
        reads = FakeReads(historical=[history_row()], cutoff=END+timedelta(hours=1))
        await fetch_history(reads, start=START, end=END, subaccount=0)
        self.assertNotIn("fills", [n for n, _ in reads.calls])
        historic = next(args for name, args in reads.calls if name == "historical_fills")
        self.assertEqual(historic["subaccount"], 0)

    async def test_archive_missing_row_scope_uses_documented_request_filter(self):
        reads = FakeReads(historical=[history_row(subaccount_number=None)])
        result = await fetch_history(reads, start=START, end=END, subaccount=0)
        self.assertEqual((len(result.records), result.records[0].subaccount), (1, 0))

    async def test_explicit_foreign_archive_row_conflicts_with_filter(self):
        reads = FakeReads(historical=[history_row(subaccount_number=1)])
        with self.assertRaisesRegex(InvalidData, 'differs from filtered request'):
            await fetch_history(reads, start=START, end=END, subaccount=0)

    async def test_moving_archive_boundary_rejects_collection(self):
        reads = FakeReads(changed_cutoff=NOW+timedelta(seconds=1))
        with self.assertRaisesRegex(InvalidData, "boundary moved"):
            await fetch_history(reads, start=START, end=END, subaccount=0)

    async def test_conflicting_overlap_is_rejected(self):
        reads = FakeReads(historical=[history_row()], current=[history_row(fee_cost="0.02")])
        with self.assertRaisesRegex(InvalidData, "conflicting"):
            await fetch_history(reads, start=START, end=END, subaccount=0)

    async def test_query_overlap_does_not_leak_outside_requested_interval(self):
        reads = FakeReads(current=[history_row("start", START), history_row("end", END),
                                   history_row("prior", START-timedelta(microseconds=1))])
        result = await fetch_history(reads, start=START, end=END, subaccount=0)
        self.assertEqual([r.fill.trade_id for r in result.records], ["start"])

    async def test_combined_budgets_apply_across_both_sources(self):
        reads = FakeReads(historical=[history_row("a")], current=[history_row("b")])
        with self.assertRaises(InvalidData):
            await fetch_history(reads, start=START, end=END, subaccount=0, max_rows=1)
        with self.assertRaises(InvalidData):
            await fetch_history(reads, start=START, end=END, subaccount=0, max_bytes=100)

    async def test_alias_timestamp_and_scope_conflicts_are_rejected(self):
        for changes in ({"trade_id": "different"}, {"market_ticker": "B"}, {"ts": 1},
                        {"subaccount_number": True}, {"created_time": "2026-09-20"}):
            with self.assertRaises(InvalidData):
                parse_history_fill(history_row(**changes))

    async def test_staging_missing_fill_never_changes_positions_or_loss_clock(self):
        evidence = await fetch_history(FakeReads(current=[history_row()]), start=START, end=END, subaccount=0)
        db = Ledger(":memory:")
        try:
            result = stage_history(db, evidence, NOW)
            self.assertEqual(len(result.missing_fill_keys), 1)
            self.assertEqual(db.position("A"), 0)
            self.assertEqual(db.connection.execute("SELECT COUNT(*) FROM fills").fetchone()[0], 0)
            self.assertEqual(db.connection.execute("SELECT COUNT(*) FROM risk_windows").fetchone()[0], 0)
            stage_history(db, evidence, NOW)
            self.assertEqual(db.connection.execute("SELECT COUNT(*) FROM recovery_fills").fetchone()[0], 1)
        finally:
            db.close()

    async def test_staging_existing_fill_matches_without_duplicate_accounting(self):
        evidence = await fetch_history(FakeReads(current=[history_row()]), start=START, end=END, subaccount=0)
        db = Ledger(":memory:")
        try:
            db.record_fill(execution(), NOW)
            audit = stage_history(db, evidence, NOW)
            self.assertEqual(audit.already_recorded, 1)
            self.assertEqual(audit.missing_fill_keys, ())
            self.assertEqual(db.position("A"), 10)
        finally:
            db.close()

    async def test_correction_rolls_back_entire_evidence_batch(self):
        evidence = await fetch_history(FakeReads(current=[history_row()]), start=START, end=END, subaccount=0)
        db = Ledger(":memory:")
        try:
            stage_history(db, evidence, NOW)
            changed = await fetch_history(FakeReads(current=[history_row("first"), history_row(fee_cost="0.02")]),
                                          start=START, end=END, subaccount=0)
            with self.assertRaises(InvalidData):
                stage_history(db, changed, NOW)
            self.assertEqual(db.connection.execute("SELECT COUNT(*) FROM recovery_fills").fetchone()[0], 1)
        finally:
            db.close()


class OwnerRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name)/"ledger.db"
        self.writer = await LedgerWriter(self.path).start()
        await self.writer.reserve_intent("client-1", payload(), NOW)
        await self.writer.transition_intent("client-1", "SENDING")
        self.owner = AccountCoordinator(self.writer, subaccount=0)
        self.generation = self.owner.connect_generation()

    async def asyncTearDown(self):
        await self.writer.close()
        self.temp.cleanup()

    async def observe_order(self, **kwargs):
        return await self.owner.on_event({"type": "user_order", "msg": wire_order(**kwargs)},
                                         generation=self.generation, received_at=NOW)

    async def observe_fill(self, **kwargs):
        row = dict(trade_id="trade-1", order_id="order-1", market_ticker="A", book_side="bid",
                   count_fp="10", yes_price_dollars="0.5", fee_cost="0.01") | kwargs
        return await self.owner.on_event({"type": "fill", "msg": row}, generation=self.generation, received_at=NOW)

    async def test_order_stream_binds_then_missing_fill_scope_uses_durable_identity(self):
        await self.observe_order()
        result = await self.observe_fill()
        self.assertEqual(result.position, 10)
        self.assertTrue(self.owner.order_states["order-1"].awaiting_fills)

    async def test_terminal_order_before_fill_waits_then_resolves_atomically(self):
        receipt = await self.observe_order(status="executed", remaining_count_fp="0", fill_count_fp="10")
        self.assertTrue(receipt.awaiting_fills)
        result = await self.observe_fill()
        self.assertEqual(result.order.intent_state, "TERMINAL")
        self.assertEqual((await self.writer.inventory()).unresolved_intents, 0)

    async def test_fill_before_terminal_order_is_not_double_counted(self):
        await self.observe_order()
        await self.observe_fill()
        receipt = await self.observe_order(status="executed", remaining_count_fp="0", fill_count_fp="10", last_updated_ts_ms=2)
        self.assertEqual(receipt.intent_state, "TERMINAL")
        self.assertEqual(dict((await self.writer.inventory()).positions), {"A": D(10)})

    async def test_foreign_or_unbound_fill_never_enters_bot_loss_ledger(self):
        with self.assertRaises(InvalidData):
            await self.observe_fill(subaccount=0)
        self.assertFalse(self.owner.connected)
        self.assertEqual((await self.writer.inventory()).positions, ())

    async def test_known_order_with_conflicting_fill_identity_fails_closed(self):
        await self.observe_order()
        with self.assertRaises(InvalidData):
            await self.observe_fill(market_ticker="OTHER")
        self.assertTrue(self.writer.failed)

    async def test_position_update_is_informational_not_ledger_or_loss(self):
        result = await self.owner.on_event({"type": "market_position", "msg": {
            "market_ticker": "A", "position_fp": "-2.5", "position_cost_dollars": "1", "subaccount": 0}},
            generation=self.generation, received_at=NOW)
        self.assertEqual(result.quantity, D("-2.5"))
        self.assertEqual((await self.writer.inventory()).positions, ())

    async def test_position_missing_scope_is_rejected(self):
        with self.assertRaises(InvalidData):
            await self.owner.on_event({"type": "market_position", "msg": {}},
                                      generation=self.generation, received_at=NOW)

    async def test_rest_404_does_not_confirm_cancel_or_release_reservation(self):
        await self.observe_order()
        with self.assertRaises(InvalidData):
            await self.owner.recover_order(FakeReads(), "order-1", now=lambda: NOW)
        self.assertEqual((await self.writer.inventory()).unresolved_intents, 1)

    async def test_direct_rest_terminal_proof_survives_restart(self):
        await self.observe_order()
        reads = FakeReads(order=wire_order(status="canceled", remaining_count_fp="0", last_updated_ts_ms=2))
        result = await self.owner.recover_order(reads, "order-1", now=lambda: NOW)
        self.assertEqual(result.intent_state, "TERMINAL")
        await self.writer.close()
        self.writer = await LedgerWriter(self.path).start()
        orders = await self.writer.orders()
        self.assertEqual(orders[0].order.status, "canceled")
        self.assertEqual(orders[0].intent_state, "TERMINAL")

    async def test_disconnect_during_order_fetch_rejects_result(self):
        reads = FakeReads(order=wire_order())
        reads.hook = self.owner.disconnect
        self.assertIsNone(await self.owner.recover_order(reads, "order-1", now=lambda: NOW))
        self.assertEqual(await self.writer.orders(), ())

    async def test_history_recovery_leaves_unbound_fill_staged_without_pnl_replay(self):
        result = await self.owner.recover_history(FakeReads(current=[history_row()]),
                    start=START, end=END, now=lambda: NOW)
        self.assertEqual(result.seen, 1)
        self.assertEqual((await self.writer.inventory()).positions, ())
        self.assertIn("unbound_fills_not_imported", result.blockers)

    async def test_exact_incident_import_is_not_reblocked_as_unbound(self):
        # A stopped-owner incident repair is the only path that may explicitly
        # account for an external close.  Once the exact fill is durable,
        # ordinary history recovery must validate it as a duplicate rather
        # than require a fabricated bot-owned order binding.
        await self.writer.fill(execution(), NOW)
        before = await self.writer.observe(NOW)
        result = await self.owner.recover_history(FakeReads(current=[history_row()]),
                    start=START, end=END, now=lambda: NOW)
        after = await self.writer.observe(NOW)
        self.assertEqual((result.imported, result.already_recorded), (0, 1))
        self.assertEqual(result.missing_fill_keys, ())
        self.assertNotIn("unbound_fills_not_imported", result.blockers)
        self.assertEqual(after.realized_pnl, before.realized_pnl)
        self.assertEqual((await self.writer.inventory()).positions, (("A", D(10)),))

    async def test_bootstrap_binds_orders_but_absence_never_cancels_them(self):
        class AccountReads:
            rows = (wire_order(),)
            async def collect(self, name, **kwargs):
                return PageSet(self.rows if name == "orders" else (), 1, 100)
            async def read(self, *args, **kwargs):
                return ReadResult({"balance_dollars": "500", "updated_ts": 1}, 100)
        reads = AccountReads()
        await self.owner.reconcile(reads, now=lambda: NOW)
        self.assertTrue(self.owner.order_states["order-1"].owned)
        self.owner.disconnect()
        self.owner.connect_generation()
        reads.rows = ()
        report = await self.owner.reconcile(reads, now=lambda: NOW)
        self.assertFalse(report.ready_for_entry)
        self.assertEqual(self.owner.order_states["order-1"].order.status, "resting")
        self.assertEqual((await self.writer.inventory()).unresolved_intents, 1)

    async def test_order_batch_conflict_rolls_back_prior_binding(self):
        await self.writer.reserve_intent("client-2", payload(), NOW)
        await self.writer.transition_intent("client-2", "SENDING")
        bad = update(order_id="order-2", client_id="client-2", yes_price=D("0.9"))
        with self.assertRaises(InvalidData):
            await self.writer.order_batch((update(), bad), NOW)
        db = Ledger(self.path)
        try:
            self.assertEqual(db.connection.execute("SELECT COUNT(*) FROM order_evidence").fetchone()[0], 0)
            self.assertEqual(db.connection.execute("SELECT state FROM intents WHERE client_id='client-1'").fetchone()[0], "SENDING")
        finally:
            db.close()

    async def test_history_chunks_yield_to_risk_commands(self):
        rows = [history_row(str(n)) for n in range(300)]
        evidence = await fetch_history(FakeReads(current=rows), start=START, end=END, subaccount=0)
        entered, release = Event(), Event()
        original, commands, sizes = self.writer._execute, [], []
        def tracked(ledger, command, args):
            commands.append(command)
            if command == "history":
                sizes.append(len(args[0].records))
                if len(sizes) == 1:
                    entered.set()
                    release.wait(3)
            return original(ledger, command, args)
        with patch.object(self.writer, "_execute", side_effect=tracked):
            audit = asyncio.create_task(self.writer.audit_history(evidence, NOW))
            self.assertTrue(await asyncio.to_thread(entered.wait, 2))
            risk = asyncio.create_task(self.writer.observe(NOW))
            await asyncio.sleep(0)
            release.set()
            result, _ = await asyncio.gather(audit, risk)
        self.assertEqual(sizes, [256, 44])
        self.assertEqual(commands, ["history", "observe", "history", "history_complete"])
        self.assertEqual(result.seen, 300)
