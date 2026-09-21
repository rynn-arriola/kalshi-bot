"""D-027 disposable, offline risk reservations and advisory inventory plans."""
import asyncio
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from kalshi_bot.account import normalize_snapshot
from kalshi_bot.config import BotConfig
from kalshi_bot.ledger import Fill, Ledger
from kalshi_bot.orders import OrderUpdate
from kalshi_bot.position_basis import VenueCost
from kalshi_bot.runtime import RecoveryRuntime
from kalshi_bot.values import InvalidData
from kalshi_bot.writer import LedgerWriter
from test_bot_engine import NOW, snapshot


def request(key="candidate", ticker="A", side="bid", p=".5", reduce=False, quantity="10"):
    return dict(ticker=ticker, client_order_id=key, side=side, count=quantity, price=p,
        time_in_force="good_till_canceled", self_trade_prevention_type="taker_at_cross",
        post_only=True, reduce_only=reduce, cancel_order_on_pause=True, subaccount=0, exchange_index=0)


class RiskTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name)/"risk.db"
        self.writer = await LedgerWriter(self.path).start()

    async def asyncTearDown(self):
        await self.writer.close()
        self.temp.cleanup()

    async def view(self):
        return await self.writer.portfolio(subaccount=0, now=NOW)

    async def reserve(self, req=None, view=None, config=None, cash="500", known=True, fixture=True, now=NOW):
        req = req or request()
        return await self.writer.reserve_entry(req,
            attempt_id='attempt-'+req['client_order_id'], view=view or await self.view(),
            config=config or BotConfig(managed_market_slots=30), now=now, free_cash=D(cash),
            account_known=known, offline_fixture=fixture)

    async def order(self, key="o", side="bid", p=".5", qty="10", filled="0", remaining="10",
                    status="resting", reducing=False, ticker="A"):
        req = request(key, ticker, side, p, reducing, qty)
        await self.writer.reserve_intent(key, req, NOW)
        await self.writer.transition_intent(key, "SENDING")
        order = OrderUpdate("venue-"+key, key, ticker, side, D(p), D(qty), D(filled), D(remaining),
                            status, 0, 0, 1)
        await self.writer.order(order, NOW)
        return order

    async def fill(self, order, qty="10", side=None, p=None, fee="0", key="f", now=NOW):
        return await self.writer.fill(Fill(key, order.order_id, order.ticker, side or order.side,
            D(qty), D(p) if p else order.yes_price, D(fee)), now)

    async def test_intent_and_bound_order_are_counted_once(self):
        await self.order()
        view = await self.view()
        self.assertEqual((view.total, view.entry_count, view.working_risk), (5, 1, 5))

    async def test_reducer_excluded_from_count_not_dollars(self):
        await self.order("reduce", side="ask", p=".6", reducing=True)
        view = await self.view()
        self.assertEqual((view.total, view.entry_count, view.working_risk), (4, 0, 4))

    async def test_partial_fill_inventory_and_remaining_no_double_count(self):
        order = await self.order(filled="4", remaining="6")
        await self.fill(order, qty="4")
        view = await self.view()
        self.assertEqual((view.total, view.working_risk, dict(view.positions)["A"]), (5, 3, 4))

    async def test_terminal_missing_fills_retains_risk_and_blocks(self):
        order = await self.order(filled="4", remaining="0", status="canceled")
        view = await self.view()
        self.assertEqual(view.total, 5)
        self.assertIn("terminal_or_fill_proof_pending", view.blockers)
        await self.fill(order, qty="4")
        view = await self.view()
        self.assertEqual((view.total, view.working_risk, view.entry_count), (2, 0, 0))

    async def test_canceled_unfilled_order_releases_only_positive_terminal(self):
        order = await self.order()
        before = await self.view()
        await self.writer.order(replace(order, status="canceled", remaining=D(0), version_us=2), NOW)
        after = await self.view()
        self.assertEqual((before.total, after.total), (5, 0))

    async def test_unknown_send_is_reserved_and_blocks(self):
        await self.writer.reserve_intent("u", request("u"), NOW)
        await self.writer.transition_intent("u", "SENDING")
        await self.writer.transition_intent("u", "UNKNOWN")
        view = await self.view()
        self.assertEqual((view.total, view.entry_count), (5, 1))
        self.assertIn("ambiguous_send", view.blockers)
        self.assertFalse((await self.reserve(view=view)).reserved)

    async def test_no_inventory_cost_and_venue_cost_are_net_added(self):
        order = await self.order(filled="10", remaining="0", status="executed")
        await self.fill(order)
        await self.writer.venue_snapshot((VenueCost("A", 0, 0, D(10), D(5), "rest"),), subaccount=0, now=NOW)
        self.assertEqual((await self.view()).total, 5)

    async def test_mismatched_venue_inventory_blocks_and_never_lowers_risk(self):
        order = await self.order(filled="10", remaining="0", status="executed")
        await self.fill(order)
        await self.writer.venue_snapshot((VenueCost("A", 0, 0, D(2), D(1), "rest"),), subaccount=0, now=NOW)
        view = await self.view()
        self.assertEqual(view.total, 5)
        self.assertIn("venue_inventory_mismatch", view.blockers)

    async def test_no_position_uses_one_minus_yes_basis(self):
        order = await self.order(side="ask", p=".7", filled="10", remaining="0", status="executed")
        await self.fill(order)
        view = await self.view()
        self.assertEqual((view.total, dict(view.positions)["A"]), (3, -10))

    async def test_historical_flat_venue_rows_do_not_consume_active_capacity(self):
        for i in range(130):
            await self.writer.stream_cost("OLD"+str(i), D(0), D(0), subaccount=0, now=NOW)
        view = await self.view()
        self.assertEqual(view.exposure, ())
        self.assertFalse(self.writer.failed)

    async def test_concurrent_candidates_only_one_same_view_reserves(self):
        view = await self.view()
        a, b = await asyncio.gather(self.reserve(request("a"), view), self.reserve(request("b"), view))
        self.assertEqual(sum(r.reserved for r in (a, b)), 1)
        self.assertIn("stale_writer_evidence", a.blockers+b.blockers)
        self.assertEqual((await self.view()).entry_count, 1)

    async def test_cash_is_not_reused_by_consecutive_reservations(self):
        self.assertTrue((await self.reserve(request("a"), cash="9")).reserved)
        second = await self.reserve(request("b"), cash="9")
        self.assertFalse(second.reserved)
        self.assertIn("capital", second.blockers)

    async def test_entry_count_ratchet_rejects_31st(self):
        for i in range(30):
            await self.writer.reserve_intent(str(i), request(str(i), "M"+str(i)), NOW)
        result = await self.reserve()
        self.assertIn("entry_cap", result.blockers)
        self.assertFalse(result.reserved)

    async def test_market_exposure_limit_enforced(self):
        for i in range(18):
            await self.writer.reserve_intent(str(i), request(str(i)), NOW)
        result = await self.reserve()
        self.assertIn("market_exposure", result.blockers)

    async def test_portfolio_exposure_limit_enforced_without_new_default(self):
        for i in range(29):
            await self.writer.reserve_intent(str(i), request(str(i), "M"+str(i), p=".99"), NOW)
        result = await self.reserve(config=BotConfig(managed_market_slots=19))
        self.assertIn("portfolio_exposure", result.blockers)
        result = await self.reserve(config=BotConfig(managed_market_slots=None))
        self.assertIn("market_capacity_undecided", result.blockers)

    async def test_default_call_never_authorizes_live_reservation(self):
        result = await self.reserve(fixture=False)
        self.assertIn("live_authorization_missing", result.blockers)
        self.assertFalse(result.live_authorized)
        self.assertEqual((await self.view()).entry_count, 0)

    async def test_poly_default_cap_includes_inventory_and_reducing_orders(self):
        # Four markets each hold $45 inventory and a $30 exact-size reducer.
        # Zero entry orders, but the shared $300 exposure budget is exhausted.
        for i in range(4):
            ticker = 'held-' + str(i)
            opening = await self.order('open-' + str(i), ticker=ticker,
                qty='90', filled='90', remaining='0', status='executed')
            await self.fill(opening, qty='90', key='fill-' + str(i))
            await self.order('reduce-' + str(i), ticker=ticker, side='ask',
                p='.5', qty='60', remaining='60', reducing=True)
        view = await self.view()
        self.assertEqual((view.total, view.entry_count), (300, 0))
        result = await self.reserve(config=BotConfig())
        self.assertFalse(result.reserved)
        self.assertIn('portfolio_exposure', result.blockers)
        self.assertEqual((await self.view()).entry_count, 0)

    async def test_unknown_account_and_stale_view_are_rejected(self):
        self.assertIn("unknown_account", (await self.reserve(known=False)).blockers)
        self.assertIn("stale_account_evidence", (await self.reserve(now=NOW+timedelta(seconds=6))).blockers)

    async def test_writer_restart_revokes_old_view(self):
        view = await self.view()
        await self.writer.close()
        self.writer = await LedgerWriter(self.path).start()
        self.assertIn("stale_writer_evidence", (await self.reserve(view=view)).blockers)

    async def test_pending_ingress_revokes_view_before_accounting(self):
        view = await self.view()
        await self.writer.stage_fill(Fill("f", "o", "A", "bid", D(1), D(".5"), D(0)), owner=0, now=NOW)
        result = await self.reserve(view=view)
        self.assertIn("stale_writer_evidence", result.blockers)
        self.assertIn("pending_fills", result.blockers)

    async def test_mutated_caller_totals_do_not_bypass_transactional_recompute(self):
        for i in range(18):
            await self.writer.reserve_intent(str(i), request(str(i)), NOW)
        view = replace(await self.view(), exposure=(), entry_count=0)
        self.assertIn("market_exposure", (await self.reserve(view=view)).blockers)

    async def test_filled_market_cannot_receive_another_entry(self):
        order = await self.order(filled="10", remaining="0", status="executed")
        await self.fill(order)
        self.assertIn("position_is_reduce_only", (await self.reserve()).blockers)

    async def test_loss_hold_survives_restart_and_blocks_other_market(self):
        order = await self.order(filled="10", remaining="0", status="executed")
        await self.fill(order, fee="25")
        await self.writer.close()
        self.writer = await LedgerWriter(self.path).start()
        self.assertIn("entry_cap", (await self.reserve(request(ticker="B"))).blockers)

    async def test_duplicate_client_rejected_without_poisoning_writer(self):
        self.assertTrue((await self.reserve()).reserved)
        self.assertIn("client_identity_already_reserved", (await self.reserve()).blockers)
        self.assertFalse(self.writer.failed)

    async def test_position_age_survives_partial_close_restart_and_resets_flip(self):
        order = await self.order(filled="10", remaining="0", status="executed")
        await self.fill(order)
        close = await self.order("close", side="ask", qty="4", filled="4", remaining="0", status="executed", reducing=True)
        await self.fill(close, qty="4", key="close-fill", now=NOW+timedelta(seconds=10))
        await self.writer.close()
        self.writer = await LedgerWriter(self.path).start()
        first = await self.writer.market_inventory("A", subaccount=0)
        self.assertEqual((first.position, first.first_seen_at), (6, NOW))
        flip = await self.order("flip", side="ask", filled="10", remaining="0", status="executed")
        await self.fill(flip, key="flip", now=NOW+timedelta(seconds=20))
        self.assertEqual((await self.writer.market_inventory("A", subaccount=0)).first_seen_at, NOW+timedelta(seconds=20))

    async def test_old_missing_position_clock_is_not_reset_by_addition(self):
        order = await self.order(filled="10", remaining="0", status="executed")
        await self.fill(order)
        await self.writer.close()
        db = Ledger(self.path)
        with db.connection:
            db.connection.execute("DELETE FROM position_clocks")
        db.close()
        self.writer = await LedgerWriter(self.path).start()
        extra = await self.order("extra", filled="10", remaining="0", status="executed")
        await self.fill(extra, key="extra")
        self.assertIsNone((await self.writer.market_inventory("A", subaccount=0)).first_seen_at)


class ManagementTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        self.writer = await LedgerWriter(Path(self.temp.name)/"manage.db").start()
        self.now = NOW
        self.monotonic = 100.0
        self.deadlines = []
        async def ignore(*args):
            pass
        async def deadline(ticker):
            self.deadlines.append(ticker)
        self.runtime = RecoveryRuntime(self.writer, None, None, tickers=("A", "B"), subaccount=0,
            history_start=NOW-timedelta(hours=1), now=lambda: self.now, clock=lambda: self.monotonic,
            evaluate=ignore, deadline_handler=deadline, lifecycle_handler=ignore)
        self.runtime.account.connect_generation()
        self.runtime.engine.begin_private_epoch()
        for name, shard in self.runtime.engine.shards.items():
            generation = self.runtime.engine.begin_book_epoch(name)
            for seq, ticker in enumerate(sorted(shard.tickers), 1):
                self.runtime.engine.submit_book(name, snapshot(ticker, seq), generation=generation)
        while self.runtime.engine.backlog:
            await self.runtime.engine.step()

    async def asyncTearDown(self):
        await self.writer.close()
        self.temp.cleanup()

    async def order(self, key, side="bid", filled="0", remaining="10", reducing=False, qty="10", p=".5", terminal=False):
        req = request(key, side=side, p=p, reduce=reducing, quantity=qty)
        await self.writer.reserve_intent(key, req, self.now)
        await self.writer.transition_intent(key, "SENDING")
        order = OrderUpdate(key, key, "A", side, D(p), D(qty), D(filled), D(remaining),
                            "executed" if terminal else "resting", 0, 0, 1)
        await self.writer.order(order, self.now)
        self.runtime.account._store_order((await self.writer.orders())[-1])
        return order

    async def position(self, quantity="10"):
        req = request('open')
        prepared = await self.writer.reserve_entry(req, attempt_id='open-attempt',
            view=await self.writer.portfolio(subaccount=0, now=self.now),
            config=BotConfig(), now=self.now, free_cash=D(500),
            account_known=True, offline_fixture=True)
        self.assertTrue(prepared.reserved, prepared.blockers)
        sent = await self.writer.begin_send(prepared.receipt)
        self.assertTrue(sent.dispatch_allowed, sent.blockers)
        order = OrderUpdate('open', 'open', 'A', 'bid', D('.5'), D(10), D(quantity), D(0),
            'executed' if quantity == '10' else 'canceled', 0, 0, 1)
        await self.writer.order(order, self.now)
        self.runtime.account._store_order((await self.writer.orders())[-1])
        await self.writer.fill(Fill("f", "open", "A", "bid", D(quantity), D(".5"), D(0)), self.now)
        return order

    async def report(self, quantity="10", orders=()):
        position = () if quantity == "0" else (dict(ticker="A", exchange_index=0,
            position_fp=quantity, market_exposure_dollars=str(D(quantity)*D(".5"))),)
        rows = tuple(dict(order_id=o.order_id, client_order_id=o.client_id, ticker=o.ticker,
            status="resting", exchange_index=o.exchange_index, book_side=o.side,
            yes_price_dollars=str(o.yes_price), remaining_count_fp=str(o.remaining)) for o in orders)
        snapshot = normalize_snapshot(rows, position, dict(balance_dollars="500", updated_ts=1), subaccount=0)
        token = self.runtime.account.begin_reconciliation(self.now)
        await self.runtime.account.finish_reconciliation(token, snapshot, self.now)

    async def test_complete_market_proposes_exact_reducer_but_never_authorizes(self):
        await self.position("4")
        await self.report("4")
        plan = await self.runtime.management.refresh("A")
        self.assertEqual((plan.passive.reduce_side, plan.passive.reduce_quantity), ("ask", 4))
        self.assertFalse(plan.authorized)
        self.assertIn("live_authorization_missing", plan.blockers)

    async def test_existing_exact_touch_reducer_is_kept(self):
        await self.position()
        order = await self.order("reduce", side="ask", reducing=True, p=".6")
        await self.report(orders=(order,))
        plan = await self.runtime.management.refresh("A")
        self.assertEqual(plan.passive.keep_id, "reduce")
        self.assertIsNone(plan.passive.reduce_side)

    async def test_building_orders_cancel_plan_precedes_reducer(self):
        await self.position()
        order = await self.order("building")
        await self.report(orders=(order,))
        plan = await self.runtime.management.refresh("A")
        self.assertEqual(plan.passive.cancel_ids, ("building",))
        self.assertIsNone(plan.passive.reduce_side)

    async def test_wrong_reducer_size_requires_cancel_confirmation(self):
        await self.position("4")
        order = await self.order("reduce", side="ask", reducing=True, p=".6")
        await self.report("4", orders=(order,))
        plan = await self.runtime.management.refresh("A")
        self.assertEqual(plan.passive.cancel_ids, ("reduce",))
        self.assertIn("await_terminal_cancellation_and_fill_proof", plan.blockers)

    async def test_no_current_account_scope_blocks_replacement(self):
        await self.position()
        plan = await self.runtime.management.refresh("A")
        self.assertIsNone(plan.passive.reduce_side)
        self.assertIn("incomplete_order_scope", plan.blockers)

    async def test_foreign_resting_order_blocks_replacement(self):
        await self.position()
        foreign = OrderUpdate("foreign", "foreign", "A", "bid", D(".4"), D(10), D(0), D(10), "resting", 0, 0, 1)
        await self.report(orders=(foreign,))
        plan = await self.runtime.management.refresh("A")
        self.assertIsNone(plan.passive.reduce_side)

    async def test_new_ingress_or_disconnect_revokes_published_plan(self):
        await self.position()
        await self.report()
        await self.runtime.management.refresh("A")
        self.assertIsNotNone(self.runtime.management.current("A"))
        self.runtime._revoke()
        self.assertIsNone(self.runtime.management.current("A"))
        await self.runtime.management.refresh("A")
        self.runtime.account.disconnect()
        self.assertIsNone(self.runtime.management.current("A"))

    async def test_book_delta_queued_revokes_prior_price_plan(self):
        await self.position()
        await self.report()
        await self.runtime.management.refresh("A")
        name = self.runtime.engine.market_shard["A"]
        shard = self.runtime.engine.shards[name]
        self.runtime.engine.submit_book(name, dict(type="orderbook_delta", sid=1,
            seq=shard.sequences[1]+1, msg=dict(market_ticker="A", side="no", price_dollars=".6", delta_fp="1")),
            generation=shard.generation)
        self.assertIsNone(self.runtime.management.current("A"))

    async def test_inventory_age_timer_fires_without_market_updates(self):
        await self.position()
        await self.runtime.management.refresh("A")
        self.assertEqual(self.runtime.engine.deadlines.due_for("A"), 1000)
        self.now += timedelta(seconds=900)
        self.monotonic += 900
        await self.runtime.engine.step()
        self.assertIn("A", self.deadlines)
        self.assertIn("exit_terms_missing", self.runtime.management.current("A").blockers)
        self.assertIsNone(self.runtime.engine.deadlines.due_for("A"))

    async def test_inventory_timer_does_not_postpone_earlier_safety_deadline(self):
        await self.position()
        self.runtime.engine.schedule("A", 110)
        await self.runtime.management.refresh("A")
        self.assertEqual(self.runtime.engine.deadlines.due_for("A"), 110)
        self.monotonic = 110
        self.now += timedelta(seconds=10)
        await self.runtime.engine.step()
        self.assertEqual(self.runtime.engine.deadlines.due_for("A"), 1000)

    async def test_read_overtaken_by_private_revision_not_published(self):
        await self.position()
        original = self.writer.market_inventory
        async def changed(*args, **kwargs):
            result = await original(*args, **kwargs)
            self.runtime._revoke()
            return result
        self.writer.market_inventory = changed
        self.assertIsNone(await self.runtime.management.refresh("A"))

    async def test_local_writer_mutation_revokes_published_plan(self):
        await self.position()
        await self.report()
        await self.runtime.management.refresh("A")
        self.assertIsNotNone(self.runtime.management.current("A"))
        await self.writer.reserve_intent("new", request("new"), self.now)
        self.assertIsNone(self.runtime.management.current("A"))

    async def test_read_overtaken_by_writer_revision_not_published(self):
        original = self.writer.market_inventory
        async def changed(*args, **kwargs):
            result = await original(*args, **kwargs)
            await self.writer.reserve_intent("new", request("new"), self.now)
            return result
        self.writer.market_inventory = changed
        self.assertIsNone(await self.runtime.management.refresh("A"))

    async def test_runtime_entry_inspection_cannot_reserve(self):
        result = await self.runtime.inspect_entry(request())
        self.assertFalse(result.reserved)
        self.assertIn("live_authorization_missing", result.blockers)
        self.assertNotIn("market_capacity_undecided", result.blockers)

    async def test_unsubscribed_inventory_is_explicit_not_guessed_book(self):
        self.assertIsNone(await self.runtime.management.refresh("UNSUBSCRIBED"))
        self.assertIn("UNSUBSCRIBED", self.runtime.management.unmanaged)
