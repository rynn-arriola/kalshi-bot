"""D-028 local proof boundaries. Disposable fixtures; no venue access."""
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from kalshi_bot.account import AccountCoordinator, normalize_snapshot
from kalshi_bot.ledger import Fill, Ledger
from kalshi_bot.orders import OrderUpdate
from kalshi_bot.position_basis import VenueCost, observe_costs
from kalshi_bot.runtime import RecoveryRuntime
from kalshi_bot.values import InvalidData
from kalshi_bot.writer import LedgerWriter
from test_bot_auto_recovery import NOW, EXEC, wire_order
from test_bot_recovery_runtime import AccountReads


def snapshot(orders=(), quantity=None, shard=0, scope=0):
    rows = tuple(dict(order_id=o.order_id, client_order_id=o.client_id, ticker=o.ticker,
        status="resting", exchange_index=o.exchange_index, book_side=o.side,
        yes_price_dollars=str(o.yes_price), remaining_count_fp=str(o.remaining)) for o in orders)
    positions = () if quantity is None else (dict(ticker="A", exchange_index=shard,
        position_fp=str(quantity), market_exposure_dollars=str(abs(D(quantity))*D(".5"))),)
    return normalize_snapshot(rows, positions, dict(balance_dollars="500", updated_ts=1), subaccount=scope)


class VerificationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name)/"verification.db"
        self.writer = await LedgerWriter(self.path).start()
        self.owner = AccountCoordinator(self.writer, subaccount=0)
        self.owner.connect_generation()

    async def asyncTearDown(self):
        await self.writer.close()
        self.temp.cleanup()

    async def order(self, key="o", *, filled="0", remaining="10", status="resting", side="bid", scope=0):
        await self.writer.reserve_intent(key, dict(ticker="A", side=side, price=".5", count="10",
            subaccount=scope, exchange_index=0), NOW)
        await self.writer.transition_intent(key, "SENDING")
        order = OrderUpdate(key, key, "A", side, D(".5"), D(10), D(filled), D(remaining), status, scope, 0, 1)
        await self.writer.order(order, NOW)
        return order

    async def fill(self, order, qty="10"):
        await self.writer.fill(Fill("f-"+order.order_id, order.order_id, "A", order.side, D(qty), D(".5"), D(0)), NOW)

    async def audit(self, snap=None):
        return await self.writer.reconcile_snapshot(snap or snapshot(), now=NOW)

    async def report(self, snap=None):
        token = self.owner.begin_reconciliation(NOW)
        return await self.owner.finish_reconciliation(token, snap or snapshot(), NOW)

    async def test_flat_empty_agreement_is_not_history_or_live_proof(self):
        report = await self.report()
        self.assertTrue(report.audit.consistent)
        self.assertFalse(report.ready_for_entry)
        for reason in ("execution_history_not_proven", "private_stream_continuity_not_proven",
                       "cash_snapshot_not_atomic", "starting_basis_not_proven"):
            self.assertIn(reason, report.blockers)

    async def test_exact_owned_resting_order_is_locally_reconciled(self):
        order = await self.order()
        report = await self.report(snapshot((order,)))
        self.assertTrue(report.audit.consistent)
        self.assertEqual(report.unresolved_intents, 1)
        self.assertNotIn("resting_order_ownership_not_reconciled", report.blockers)
        self.assertFalse(report.ready_for_entry)

    async def test_absent_owned_order_not_released(self):
        await self.order()
        audit = await self.audit()
        self.assertEqual(audit.missing_order_ids, ("o",))
        self.assertEqual((await self.writer.inventory()).unresolved_intents, 1)
        self.assertFalse(audit.consistent)

    async def test_foreign_order_blocks_even_with_same_order_count(self):
        order = await self.order()
        foreign = replace(order, order_id="foreign", client_id="foreign")
        audit = await self.audit(snapshot((foreign,)))
        self.assertEqual(audit.foreign_order_ids, ("foreign",))
        self.assertEqual(audit.missing_order_ids, ("o",))

    async def test_every_resting_identity_term_compared(self):
        order = await self.order()
        for change in (dict(client_id="wrong"), dict(ticker="B"), dict(exchange_index=1),
                       dict(side="ask"), dict(yes_price=D(".4")), dict(remaining=D(9))):
            with self.subTest(change=change):
                audit = await self.audit(snapshot((replace(order, **change),)))
                self.assertEqual(audit.mismatched_order_ids, ("o",))

    async def test_terminal_order_cannot_appear_resting(self):
        order = await self.order(remaining="0", status="canceled")
        audit = await self.audit(snapshot((replace(order, status="resting", remaining=D(10)),)))
        self.assertEqual(audit.mismatched_order_ids, ("o",))

    async def test_canceled_unfilled_terminal_is_consistent_without_releasing_other_work(self):
        await self.order(remaining="0", status="canceled")
        self.assertTrue((await self.audit()).consistent)

    async def test_matching_flat_net_does_not_hide_opposite_missing_fills(self):
        await self.order("buy", filled="10", remaining="0", status="executed")
        await self.order("sell", filled="10", remaining="0", status="executed", side="ask")
        audit = await self.audit()
        self.assertTrue(audit.positions_match)
        self.assertEqual(audit.awaiting_fill_ids, ("buy", "sell"))
        self.assertFalse(audit.consistent)

    async def test_partial_fill_agreement_needs_exact_accounted_quantity(self):
        order = await self.order(filled="4", remaining="6")
        self.assertIn("owned_order_fill_gap", (await self.audit(snapshot((order,)))).blockers)
        await self.fill(order, "4")
        self.assertTrue((await self.audit(snapshot((order,), "4"))).consistent)

    async def test_position_mismatch_cannot_be_fixed_by_cost_observation(self):
        order = await self.order(filled="10", remaining="0", status="executed")
        await self.fill(order)
        audit = await self.audit(snapshot(quantity="9"))
        self.assertIn("position_ledger_mismatch", audit.blockers)
        self.assertEqual(dict((await self.writer.inventory()).positions)["A"], 10)

    async def test_matching_quantity_wrong_exchange_is_not_scope_proof(self):
        order = await self.order(filled="10", remaining="0", status="executed")
        await self.fill(order)
        audit = await self.audit(snapshot(quantity="10", shard=1))
        self.assertTrue(audit.positions_match)
        self.assertIn("position_order_scope_unproven", audit.blockers)

    async def test_unowned_local_inventory_is_not_starting_basis_proof(self):
        await self.writer.fill(Fill("f", "unknown", "A", "bid", D(10), D(".5"), D(0)), NOW)
        self.assertIn("position_order_scope_unproven", (await self.audit(snapshot(quantity="10"))).blockers)

    async def test_different_account_owned_order_blocks(self):
        await self.order(scope=1)
        self.assertIn("account_scope_conflict", (await self.audit()).blockers)

    async def test_reserved_and_unknown_intents_remain_unbound(self):
        for key in ("reserved", "unknown"):
            await self.writer.reserve_intent(key, dict(ticker="A", subaccount=0), NOW)
        await self.writer.transition_intent("unknown", "SENDING")
        await self.writer.transition_intent("unknown", "UNKNOWN")
        audit = await self.audit()
        self.assertEqual(audit.unbound_client_ids, ("reserved", "unknown"))

    async def test_pending_inbox_blocks_even_when_positions_match(self):
        await self.writer.stage_fill(Fill("f", "o", "A", "bid", D(1), D(".5"), D(0)), owner=0, now=NOW)
        audit = await self.audit()
        self.assertEqual(audit.pending_fills, 1)
        self.assertTrue(audit.positions_match)
        self.assertIn("pending_fills", audit.blockers)

    async def test_new_local_intent_revokes_report(self):
        await self.report()
        self.assertIsNotNone(self.owner.current_report(NOW))
        await self.writer.reserve_intent("new", dict(ticker="A", subaccount=0), NOW)
        self.assertIsNone(self.owner.current_report(NOW))

    async def test_awaited_snapshot_overtaken_by_local_write_not_published(self):
        original = self.writer.reconcile_snapshot
        async def changed(*args, **kwargs):
            audit = await original(*args, **kwargs)
            await self.writer.reserve_intent("new", dict(ticker="A", subaccount=0), NOW)
            return audit
        with patch.object(self.writer, "reconcile_snapshot", side_effect=changed):
            self.assertIsNone(await self.report())

    async def test_current_report_expiration_and_clock_reversal(self):
        await self.report()
        self.assertIsNone(self.owner.current_report(NOW+timedelta(seconds=6)))
        self.assertIsNone(self.owner.current_report(NOW-timedelta(seconds=1)))

    async def test_reconnect_drops_report(self):
        await self.report()
        self.owner.disconnect()
        self.owner.connect_generation()
        self.assertIsNone(self.owner.current_report(NOW))

    async def test_writer_restart_rejects_old_report(self):
        await self.report()
        await self.writer.close()
        self.writer = await LedgerWriter(self.path).start()
        self.owner.writer = self.writer
        self.assertIsNone(self.owner.current_report(NOW))

    async def test_audit_failure_rolls_back_venue_observations(self):
        with patch("kalshi_bot.verification.audit_snapshot", side_effect=InvalidData("injected")):
            with self.assertRaises(InvalidData):
                await self.audit(snapshot(quantity="10"))
        await self.writer.close()
        db = Ledger(self.path)
        try:
            self.assertEqual(db.connection.execute("SELECT COUNT(*) FROM venue_costs").fetchone()[0], 0)
        finally:
            db.close()


class BatchCostTests(unittest.TestCase):
    def test_over_capacity_batch_rolls_back_every_observation(self):
        db = Ledger(":memory:")
        try:
            observations = tuple(VenueCost(t, 0, 0, D(1), D(".5"), "rest") for t in ("A", "B"))
            observe_costs(db, (observations[0],), NOW, capacity=1)
            with self.assertRaises(InvalidData):
                observe_costs(db, (observations[1],), NOW, capacity=1)
            rows = db.connection.execute("SELECT ticker FROM venue_costs").fetchall()
            self.assertEqual([r[0] for r in rows], ["A"])
        finally:
            db.close()

    def test_batch_preserves_age_and_exact_cost(self):
        db = Ledger(":memory:")
        try:
            first = VenueCost("A", 0, 0, D(10), D(5), "rest")
            observe_costs(db, (first,), NOW)
            observe_costs(db, (replace(first, quantity=D(4), cost=D(2)),), NOW+timedelta(seconds=10))
            row = db.connection.execute("SELECT * FROM venue_costs").fetchone()
            self.assertEqual((row["first_seen_at"], row["quantity"], row["cost"]), (NOW.isoformat(), "4", "2"))
        finally:
            db.close()


class RuntimeVerificationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        self.writer = await LedgerWriter(Path(self.temp.name)/"runtime.db").start()
        self.reads = AccountReads()
        async def ignore(*args):
            pass
        self.runtime = RecoveryRuntime(self.writer, self.reads, None, tickers=("A",), subaccount=0,
            history_start=EXEC-timedelta(seconds=1), now=lambda: NOW, evaluate=ignore,
            deadline_handler=ignore, lifecycle_handler=ignore)
        self.runtime.account.connect_generation()
        self.runtime.account_subscribed = True

    async def asyncTearDown(self):
        await self.writer.close()
        self.temp.cleanup()

    async def test_empty_repair_retains_requested_history_not_complete_history_claim(self):
        self.assertTrue(await self.runtime.recover_once())
        state = self.runtime.verification_status()
        self.assertTrue(state["local_snapshot_consistent"])
        self.assertEqual(state["history_interval_us"], [int((EXEC-timedelta(seconds=1)).timestamp()*1000000),
                                                       int(NOW.timestamp()*1000000)])
        self.assertIn("execution_history_not_proven", state["blockers"])
        self.assertFalse(state["live_ready"])

    async def test_private_ingress_clears_combined_assessment(self):
        await self.runtime.recover_once()
        self.runtime._revoke()
        state = self.runtime.verification_status()
        self.assertFalse(state["local_snapshot_consistent"])
        self.assertIsNone(state["history_interval_us"])

    async def test_history_source_revision_overtaken_between_stages_blocks_repair(self):
        original = self.runtime.account.recover_history
        async def changed(*args, **kwargs):
            result = await original(*args, **kwargs)
            self.runtime._revoke()
            return result
        with patch.object(self.runtime.account, "recover_history", side_effect=changed):
            self.assertFalse(await self.runtime.recover_once())
        self.assertIn("current_history_pass_missing", self.runtime.verification_status()["blockers"])

    async def test_foreign_resting_order_prevents_repaired_status(self):
        original = self.reads.collect
        async def collect(name, **kwargs):
            result = await original(name, **kwargs)
            if name == "orders":
                return replace(result, rows=(wire_order(client_order_id="foreign", status="resting",
                    fill_count_fp="0", remaining_count_fp="10"),))
            return result
        self.reads.collect = collect
        self.assertFalse(await self.runtime.recover_once())
        self.assertIn("foreign_resting_orders", self.runtime.verification_status()["blockers"])
        self.assertEqual(self.runtime.status()["completed_repair_passes"], 0)

    async def test_status_read_does_not_mutate_or_request_venue_data(self):
        await self.runtime.recover_once()
        calls, revision = len(self.reads.calls), self.writer.revision
        for _ in range(100):
            self.runtime.status()
        self.assertEqual((len(self.reads.calls), self.writer.revision), (calls, revision))

    async def test_successful_repairs_do_not_authorize_entry(self):
        await self.runtime.recover_once()
        self.assertFalse(self.runtime.entry_allowed)
        self.assertFalse(self.runtime.status()["live_ready"])
