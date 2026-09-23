import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D, localcontext
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from kalshi_bot.adapters import PriceBand, create_payload
from kalshi_bot.account import AccountCoordinator
from kalshi_bot.books import Book, BookConnection, Ladder, ProofLost
from kalshi_bot.command_types import CommandDenied
from kalshi_bot.config import BotConfig
from kalshi_bot.engine import EventEngine
from kalshi_bot.execution import InjectedExecutor, acknowledgement
from kalshi_bot.ledger import Ledger
from kalshi_bot.metadata import MetadataCache
from kalshi_bot.orders import OrderUpdate, inventory_plan
from kalshi_bot.quoting import Program, Quote, parse_program, reference_plan, snapshot_score
from kalshi_bot.ranking import RankingBoard
from kalshi_bot.values import InvalidData
from kalshi_bot.writer import LedgerWriter
from kalshi_bot.windows import WindowsStopEvent

NOW = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)
BANDS = (PriceBand(D(0), D(1), D("0.01")),)


def program(**kw):
    return replace(Program("P", "A", NOW-timedelta(hours=1), NOW+timedelta(hours=1), D(1000), 5000, 1000000, False), **kw)


def book(bids=(("0.50", "100"), ("0.49", "100"), ("0.48", "1000")),
         asks=(("0.60", "100"), ("0.61", "100"), ("0.62", "1000"))):
    result = Book("A", Ladder(4096), Ladder(4096), True)
    for rows, ladder in ((bids, result.bids), (asks, result.asks)):
        for p, q in rows:
            ladder.set(D(p), D(q))
    return result


def snapshot(ticker="A", seq=1):
    return {"type": "orderbook_snapshot", "sid": 1, "seq": seq, "msg": {
        "market_ticker": ticker, "yes_dollars_fp": [["0.4", "1000"]],
        "no_dollars_fp": [["0.6", "1000"]]}}


def delta(seq=2, ticker="A"):
    return {"type": "orderbook_delta", "sid": 1, "seq": seq, "msg": {
        "market_ticker": ticker, "side": "yes", "price_dollars": "0.4", "delta_fp": "1"}}


def request(client="client"):
    return create_payload(ticker="A", client_id=client, outcome="yes", outcome_price=D("0.4"),
                          quantity=D(10), bands=BANDS) | {"subaccount": 0, "exchange_index": 1}


def ack(**kw):
    return dict(order_id="order", client_order_id="client", fill_count="0", remaining_count="10", ts_ms=1) | kw


class QuoteTests(unittest.TestCase):
    def test_unified_yes_price_wire_produces_reference_quotes(self):
        feed = BookConnection(("A",))
        generation = feed.reconnect()
        feed.apply({"type": "orderbook_snapshot", "sid": 1, "seq": 1, "msg": {
            "market_ticker": "A",
            "yes_dollars_fp": [[".50", "100"], [".49", "100"], [".48", "1000"]],
            "no_dollars_fp": [[".60", "100"], [".61", "100"], [".62", "1000"]],
        }}, generation=generation)
        plan = reference_plan(feed.books["A"], program(), BANDS,
                              now=NOW, market_open=True)
        self.assertEqual([(q.side, q.yes_price) for q in plan.quotes],
                         [("bid", D(".49")), ("ask", D(".61"))])
        self.assertEqual((plan.bid.reference, plan.ask.reference),
                         (D(".49"), D(".61")))

    def test_reference_is_target_fifth_not_best_bid(self):
        p = reference_plan(book(), program(), BANDS, now=NOW, market_open=True)
        self.assertEqual([(q.side, q.yes_price, q.quantity) for q in p.quotes],
                         [("bid", D(".49"), 10), ("ask", D(".61"), 10)])
        self.assertFalse(p.blockers)

    def test_entire_cutoff_level_and_own_denominator(self):
        b, a, share = snapshot_score(book(), program(), BANDS, (Quote("bid", ".49", 10), Quote("ask", ".61", 10)))
        self.assertEqual(b.total, 710)  # 100 + 110 + 1000*0.5, not truncated 790*0.5.
        self.assertEqual(a.total, 710)
        self.assertEqual(b.own, 10)
        self.assertEqual(share, b.share)

    def test_own_order_is_removed_then_readded_once(self):
        existing = (Quote("bid", ".49", 10),)
        b = book(bids=((".50", 100), (".49", 110), (".48", 1000)))
        actual = snapshot_score(b, program(), BANDS, existing, reflected=existing)
        expected = snapshot_score(book(), program(), BANDS, existing)
        self.assertEqual(actual, expected)
        self.assertEqual(b.bids.levels[D(".49")], 110)

    def test_reflected_quantity_mismatch_is_not_guessed(self):
        with self.assertRaises(InvalidData):
            snapshot_score(book(), program(), BANDS, (), reflected=(Quote("bid", ".49", 101),))

    def test_thin_opposite_side_excludes_whole_snapshot(self):
        p = reference_plan(book(asks=((".6", "999"),)), program(), BANDS, now=NOW, market_open=True)
        self.assertFalse(p.blockers)  # Our ten may complete two-sided target depth.
        p = reference_plan(book(asks=((".6", "989"),)), program(), BANDS, now=NOW, market_open=True)
        self.assertEqual(p.snapshot_share, 0)
        self.assertFalse(p.quotes)

    def test_target_300_uses_60_not_200(self):
        p = reference_plan(book(), program(target=D(300)), BANDS, now=NOW, market_open=True)
        self.assertEqual(p.bid.reference, D(".50"))

    def test_one_side_can_earn_but_not_whole_pool(self):
        b, a, s = snapshot_score(book(), program(), BANDS, (Quote("bid", ".49", 10),))
        self.assertEqual(a.share, 0)
        with localcontext() as ctx:
            ctx.prec = 40
            self.assertEqual(s, b.share/2)

    def test_one_tick_worse_is_discounted(self):
        b, _, _ = snapshot_score(book(), program(), BANDS, (Quote("bid", ".48", 10),))
        self.assertEqual(b.own, 5)

    def test_better_price_never_gets_above_full_weight(self):
        b, _, _ = snapshot_score(book(), program(), BANDS, (Quote("bid", ".51", 10),))
        self.assertEqual(b.own, 10)

    def test_cutoff_excludes_deeper_orders(self):
        b, _, _ = snapshot_score(book(), program(), BANDS, (Quote("bid", ".47", 10),))
        self.assertEqual(b.own, 0)

    def test_discount_zero_and_one(self):
        for factor, own in ((0, 0), (10000, 10)):
            b, _, _ = snapshot_score(book(), program(discount_bps=factor), BANDS, (Quote("bid", ".48", 10),))
            self.assertEqual(b.own, own)

    def test_program_end_exclusive_closed_paid_out(self):
        for p, now, opened in ((program(), NOW, False), (program(), program().end, True),
                               (program(paid_out=True), NOW, True)):
            self.assertFalse(reference_plan(book(), p, BANDS, now=now, market_open=opened).quotes)

    def test_variable_bands_block_reward_arithmetic(self):
        bands = (PriceBand(D(0), D(".5"), D(".01")), PriceBand(D(".5"), D(1), D(".02")))
        with self.assertRaises(InvalidData):
            reference_plan(book(), program(), bands, now=NOW, market_open=True)

    def test_off_grid_price_rejected(self):
        with self.assertRaises(InvalidData):
            snapshot_score(book(), program(), BANDS, (Quote("bid", ".491", 10),))

    def test_crossing_proposal_rejected(self):
        with self.assertRaises(InvalidData):
            snapshot_score(book(), program(), BANDS, (Quote("bid", ".60", 10),))

    def test_invalid_book_or_wrong_market_rejected(self):
        for b in (replace(book(), valid=False), replace(book(), ticker="B")):
            with self.assertRaises(InvalidData):
                reference_plan(b, program(), BANDS, now=NOW, market_open=True)

    def test_api_program_parsing_does_not_default_missing_terms(self):
        row = dict(id="P", market_ticker="A", start_date=program().start.isoformat(), end_date=program().end.isoformat(),
                   incentive_type="liquidity", target_size_fp="1000", discount_factor_bps=5000, period_reward=1000000, paid_out=False)
        self.assertEqual(parse_program(row), program())
        for key in ("target_size_fp", "discount_factor_bps"):
            with self.assertRaises(InvalidData):
                parse_program(row | {key: None})


class RankingTests(unittest.TestCase):
    def setUp(self):
        self.board = RankingBoard(2)

    def add(self, ticker="A", reward=1000000, **kwargs):
        b = replace(book(), ticker=ticker)
        programs = kwargs.pop("programs", (program(ticker=ticker, pool_centicents=reward),))
        self.board.update(b, programs, BANDS, now=NOW, valid_until=NOW+timedelta(seconds=10),
                          market_open=True, **kwargs)

    def test_ranked_by_remaining_gross_not_claimed_profit(self):
        self.add("A")
        self.add("B", reward=2000000)
        rows = self.board.ranked(now=NOW, by="remaining_reward")
        self.assertEqual([r.ticker for r in rows], ["B", "A"])
        self.assertGreater(rows[0].gross_remaining_usd, rows[1].gross_remaining_usd)
        self.assertEqual(rows[0].capital_usd, D("8.80"))
        self.assertIsNone(rows[0].net_profit_usd)
        self.assertFalse(rows[0].trade_ready)

    def test_each_view_is_explicit_and_deterministic(self):
        self.add("B")
        self.add("A")
        for view in ("remaining_reward", "reward_rate", "capital_efficiency"):
            self.assertEqual([r.ticker for r in self.board.ranked(now=NOW, by=view)], ["A", "B"])
        with self.assertRaises(InvalidData): self.board.ranked(now=NOW, by="profit")

    def test_inventory_blocked_market_is_last(self):
        self.add("A", reward=100000000, position=D(1))
        self.add("B")
        rows = self.board.ranked(now=NOW, by="remaining_reward")
        self.assertEqual(rows[0].ticker, "B")
        self.assertIn("open_inventory_no_new_entries", rows[1].blockers)
        self.assertIsNone(rows[1].gross_remaining_usd)

    def test_expiry_revokes_ranking_even_without_events(self):
        self.add()
        row = self.board.ranked(now=NOW+timedelta(seconds=10), by="remaining_reward")[0]
        self.assertIn("ranking_evidence_expired", row.blockers)
        self.assertFalse(row.quotes)
        self.assertIsNone(row.gross_remaining_usd)

    def test_remaining_reward_decays_with_remaining_period(self):
        self.add()
        first = self.board.ranked(now=NOW, by="remaining_reward")[0]
        later = self.board.ranked(now=NOW+timedelta(seconds=5), by="remaining_reward")[0]
        self.assertLess(later.gross_remaining_usd, first.gross_remaining_usd)
        self.assertEqual(later.gross_hourly_usd, first.gross_hourly_usd)

    def test_overlap_not_double_counted_or_duplicate_market(self):
        self.add(programs=(program(), program(program_id="P2", target=D(300), pool_centicents=2000000)))
        rows = self.board.ranked(now=NOW, by="remaining_reward")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].program_id, "P2")

    def test_invalid_new_data_drops_old_ranking(self):
        self.add()
        with self.assertRaises(InvalidData):
            self.board.update(replace(book(), valid=False), (program(),), BANDS, now=NOW,
                              valid_until=NOW+timedelta(seconds=10), market_open=True)
        self.assertEqual(self.board.ranked(now=NOW, by="remaining_reward"), ())

    def test_capacity_and_invalidation(self):
        self.add("A")
        self.add("B")
        with self.assertRaises(InvalidData): self.add("C")
        self.board.invalidate("A")
        self.add("C")
        self.assertEqual(len(self.board.ranked(now=NOW, by="reward_rate")), 2)

    def test_account_cap_is_not_silently_ignored(self):
        self.add(programs=(program(max_reward_centicents=10000),))
        row = self.board.ranked(now=NOW, by="remaining_reward")[0]
        self.assertTrue(row.blockers)
        self.assertIsNone(row.gross_remaining_usd)

    def test_malformed_metadata_revokes_existing_ranking(self):
        self.add()
        with self.assertRaises(InvalidData): self.add(programs=())
        self.assertEqual(self.board.ranked(now=NOW, by="reward_rate"), ())


class CacheTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.time = 100.0
        self.cache = MetadataCache(capacity=2, entry_bytes=100, clock=lambda: self.time)

    async def asyncTearDown(self):
        await self.cache.close()

    async def fetch(self):
        return {"target": "1000"}

    async def test_cache_freezes_and_expires(self):
        _, value = await self.cache.refresh("P", self.fetch, ttl=10)
        value["target"] = "bad"
        self.assertEqual(self.cache.get("P")[1]["target"], "1000")
        self.time = 110
        with self.assertRaises(InvalidData): self.cache.get("P")

    async def test_deduplicates_inflight(self):
        entered, release = asyncio.Event(), asyncio.Event()
        calls = []
        async def fetch():
            calls.append(1)
            entered.set()
            await release.wait()
            return {}
        a = asyncio.create_task(self.cache.refresh("P", fetch, ttl=10))
        await entered.wait()
        b = asyncio.create_task(self.cache.refresh("P", fetch, ttl=10))
        await asyncio.sleep(0)
        release.set()
        self.assertEqual(*(await asyncio.gather(a, b)))
        self.assertEqual(len(calls), 1)

    async def test_revocation_wins_over_late_response(self):
        async def fetch():
            self.cache.revoke("P")
            return {}
        with self.assertRaises(InvalidData): await self.cache.refresh("P", fetch, ttl=10)
        with self.assertRaises(InvalidData): self.cache.get("P")

    async def test_slow_response_not_given_fresh_ttl(self):
        async def fetch():
            self.time += 10
            return {}
        with self.assertRaises(InvalidData): await self.cache.refresh("P", fetch, ttl=10)

    async def test_clock_regression_rejected(self):
        async def fetch():
            self.time -= 1
            return {}
        with self.assertRaises(InvalidData): await self.cache.refresh("P", fetch, ttl=10)

    async def test_cached_read_rejects_clock_before_observation(self):
        await self.cache.refresh("P", self.fetch, ttl=10)
        self.time = 99
        with self.assertRaises(InvalidData): self.cache.get("P")

    async def test_key_and_byte_bounds(self):
        self.cache.revoke("A")
        self.cache.revoke("B")
        with self.assertRaises(InvalidData): self.cache.revoke("C")
        async def large(): return {"x": "x"*101}
        with self.assertRaises(InvalidData): await self.cache.refresh("A", large, ttl=10)

    async def test_cancelled_waiter_does_not_cancel_shared_fetch(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def fetch():
            entered.set()
            await release.wait()
            return {}
        task = asyncio.create_task(self.cache.refresh("A", fetch, ttl=10))
        await entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        release.set()
        await self.cache.pending["A"]
        self.assertEqual(self.cache.get("A")[1], {})


class EngineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.calls = []
        async def private(event, generation): self.calls.append(("private", event["id"]))
        async def evaluate(ticker, book, generation): self.calls.append(("quote", ticker))
        async def deadline(ticker): self.calls.append(("deadline", ticker))
        self.engine = EventEngine({"a": BookConnection(("A",)), "b": BookConnection(("B",))},
                                 private_handler=private, evaluate=evaluate, deadline_handler=deadline, capacity=128)
        self.pa = self.engine.begin_private_epoch()
        self.ga = self.engine.begin_book_epoch("a")
        self.gb = self.engine.begin_book_epoch("b")

    def submit(self):
        self.engine.submit_book("a", snapshot(), generation=self.ga)

    async def test_deadline_private_then_quote(self):
        self.submit()
        self.engine.submit_private({"id": 1}, generation=self.pa)
        self.engine.schedule("A", self.engine.clock())
        await self.engine.step()
        self.assertEqual(self.calls, [("deadline", "A"), ("private", 1), ("quote", "A")])

    async def test_all_deltas_apply_only_decisions_coalesce(self):
        self.submit()
        for seq in range(2, 12): self.engine.submit_book("a", delta(seq), generation=self.ga)
        await self.engine.step()
        self.assertEqual(self.engine.shards["a"].books["A"].bids.levels[D(".4")], 1010)
        self.assertEqual(self.calls, [("quote", "A")])

    async def test_pending_deltas_block_quote(self):
        self.submit()
        for seq in range(2, 80): self.engine.submit_book("a", delta(seq), generation=self.ga)
        await self.engine.step()
        self.assertFalse(self.calls)
        await self.engine.step()
        await self.engine.step()
        self.assertEqual(self.calls, [("quote", "A")])

    async def test_failure_isolated_and_reconnect_independent(self):
        self.submit()
        self.engine.submit_book("a", delta(3), generation=self.ga)
        self.engine.submit_book("b", snapshot("B"), generation=self.gb)
        await self.engine.step()
        await self.engine.step()
        self.assertTrue(self.engine.shards["a"].failed)
        self.assertFalse(self.engine.shards["b"].failed)
        self.assertEqual(self.calls, [("quote", "B")])
        epoch = self.engine.begin_book_epoch("a")
        self.assertFalse(self.engine.submit_book("a", delta(), generation=self.ga))
        self.engine.submit_book("a", snapshot(), generation=epoch)
        await self.engine.step()
        self.assertEqual(self.calls[-1], ("quote", "A"))

    async def test_public_overflow_does_not_use_private_capacity(self):
        self.engine.capacity = 1
        self.submit()
        with self.assertRaises(ProofLost): self.engine.submit_book("a", delta(), generation=self.ga)
        self.engine.submit_private({"id": 1}, generation=self.pa)
        await self.engine.step()
        self.assertEqual(self.calls, [("private", 1)])

    async def test_private_overflow_halts_owner(self):
        self.engine.capacity = 1
        self.engine.submit_private({"id": 1}, generation=self.pa)
        with self.assertRaises(InvalidData): self.engine.submit_private({"id": 2}, generation=self.pa)
        with self.assertRaises(InvalidData): await self.engine.step()
        self.assertTrue(self.engine.failed)

    async def test_private_reconnect_never_discards_buffered_fill(self):
        self.engine.submit_private({"id": 1}, generation=self.pa)
        with self.assertRaises(InvalidData): self.engine.begin_private_epoch()
        self.assertEqual(len(self.engine.private), 1)

    async def test_events_frozen_at_enqueue(self):
        event = {"id": 1}
        self.engine.submit_private(event, generation=self.pa)
        event["id"] = 2
        await self.engine.step()
        self.assertEqual(self.calls, [("private", 1)])

    async def test_private_failure_blocks_decisions(self):
        async def fail(*_): raise InvalidData("fixture")
        self.engine.private_handler = fail
        self.submit()
        self.engine.submit_private({"id": 1}, generation=self.pa)
        with self.assertRaises(InvalidData): await self.engine.step()
        self.assertTrue(all(b.failed for b in self.engine.shards.values()))
        self.assertFalse(self.calls)

    async def test_timer_wakes_without_book_events(self):
        self.engine.schedule("A", self.engine.clock()+0.01)
        task = asyncio.create_task(self.engine.run())
        async with asyncio.timeout(2):
            while not self.calls: await asyncio.sleep(0.001)
        self.engine.stop()
        await task
        self.assertEqual(self.calls, [("deadline", "A")])
        self.assertFalse(self.engine.status()["live_ready"])

    async def test_deadlines_survive_private_flood(self):
        for i in range(100): self.engine.submit_private({"id": i}, generation=self.pa)
        self.engine.schedule("A", self.engine.clock())
        await self.engine.step()
        self.assertEqual(self.calls[0], ("deadline", "A"))
        self.assertEqual(len(self.engine.private), 68)

    async def test_dirty_decisions_drain_without_new_input(self):
        tickers = tuple("A"+str(i) for i in range(40))
        quotes = []
        async def noop(*_): pass
        async def evaluate(ticker, *_): quotes.append(ticker)
        engine = EventEngine({"a": BookConnection(tickers)}, private_handler=noop, evaluate=evaluate, deadline_handler=noop)
        generation = engine.begin_book_epoch("a")
        for seq, ticker in enumerate(tickers, 1):
            engine.submit_book("a", snapshot(ticker, seq), generation=generation)
        task = asyncio.create_task(engine.run())
        async with asyncio.timeout(2):
            while len(quotes) < 40: await asyncio.sleep(0.001)
        engine.stop()
        await task
        self.assertEqual(len(set(quotes)), 40)

    async def test_ranking_batch_yields_to_arriving_private_event(self):
        calls = []
        async def evaluate(ticker, *_):
            calls.append(ticker)
            self.engine.submit_private({"id": 9}, generation=self.pa)
        self.engine.evaluate = evaluate
        self.submit()
        await self.engine.step()
        self.assertEqual(calls, ["A"])
        self.assertEqual(len(self.engine.private), 1)
        await self.engine.step()
        self.assertEqual(self.calls, [("private", 9)])

    async def test_book_gap_revokes_downstream_rankings(self):
        revoked = []
        self.engine.invalidate = revoked.append
        self.submit()
        self.engine.submit_book("a", delta(3), generation=self.ga)
        await self.engine.step()
        self.assertEqual(revoked, ["A"])


class ExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name)/"test.db"
        self.writer = await LedgerWriter(self.path).start()
        self.calls = []
        async def invoke(kind, req):
            self.calls.append((kind, req))
            rows = await self.writer.mutations()
            self.assertEqual(rows[-1]["phase"], "SENDING")
            return ack()
        self.executor = InjectedExecutor(self.writer, invoke=invoke, validate_proof=lambda *_: True,
                                         offline_fixture=True, now=lambda: NOW)

    async def prepare(self, attempt="attempt", req=None):
        req = req or request()
        result = await self.writer.reserve_entry(req, attempt_id=attempt,
            view=await self.writer.portfolio(subaccount=0, now=NOW),
            config=BotConfig(), now=NOW, free_cash=D(500), account_known=True,
            offline_fixture=True)
        self.assertTrue(result.reserved, result.blockers)
        return result.receipt

    async def asyncTearDown(self):
        await self.writer.close()
        self.temp.cleanup()

    async def test_create_durable_before_invoke_ack_not_order(self):
        result = await self.executor.execute_prepared(await self.prepare())
        self.assertEqual(result.order_id, "order")
        self.assertTrue(result.reconciliation_required)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(await self.writer.orders(), ())
        self.assertEqual((await self.writer.inventory()).unresolved_intents, 1)
        rows = await self.writer.mutations()
        self.assertEqual(rows[0]["phase"], "ACK")

    async def test_duplicate_attempt_cannot_send_twice(self):
        receipt = await self.prepare()
        await self.executor.execute_prepared(receipt)
        with self.assertRaises(CommandDenied): await self.executor.execute_prepared(receipt)
        self.assertEqual(len(self.calls), 1)

    async def test_timeout_persists_unknown_and_never_retries(self):
        async def timeout(*_):
            self.calls.append(1)
            raise TimeoutError()
        self.executor.invoke = timeout
        receipt = await self.prepare()
        with self.assertRaises(TimeoutError): await self.executor.execute_prepared(receipt)
        self.assertEqual((await self.writer.mutations())[0]["phase"], "UNKNOWN")
        with self.assertRaises(CommandDenied): await self.executor.execute_prepared(receipt)
        self.assertEqual(len(self.calls), 1)

    async def test_bad_ack_persists_unknown(self):
        async def invoke(*_): return ack(client_order_id="wrong")
        self.executor.invoke = invoke
        with self.assertRaises(InvalidData): await self.executor.execute_prepared(await self.prepare())
        self.assertEqual((await self.writer.mutations())[0]["phase"], "UNKNOWN")

    async def test_gate_false_does_not_prepare_or_send(self):
        self.executor.validate_proof = lambda *_: False
        with self.assertRaises(CommandDenied): await self.executor.execute_prepared(await self.prepare())
        self.assertEqual((await self.writer.mutations())[0]["phase"], "PREPARED")
        self.assertFalse(self.calls)

    async def test_gate_rechecked_after_durable_await(self):
        checks = iter([True, False])
        self.executor.validate_proof = lambda *_: next(checks)
        with self.assertRaises(CommandDenied): await self.executor.execute_prepared(await self.prepare())
        self.assertFalse(self.calls)
        self.assertEqual((await self.writer.mutations())[0]["phase"], "UNKNOWN")

    async def test_restart_retains_ack_and_unresolved_reservation(self):
        await self.executor.execute_prepared(await self.prepare())
        await self.writer.close()
        self.writer = await LedgerWriter(self.path).start()
        self.assertEqual(json.loads((await self.writer.mutations())[0]["response"])["order_id"], "order")
        self.assertEqual((await self.writer.inventory()).unresolved_intents, 1)

    async def test_ack_fill_count_does_not_post_pnl(self):
        async def invoke(*_): return ack(fill_count="10", remaining_count="0")
        self.executor.invoke = invoke
        await self.executor.execute_prepared(await self.prepare())
        self.assertEqual((await self.writer.inventory()).positions, ())

    async def test_cancel_ack_does_not_release_order(self):
        await self.executor.execute_prepared(await self.prepare())
        await self.writer.order(OrderUpdate("order", "client", "A", "bid", D(".4"), D(10), D(0), D(10), "resting", 0, 1, 1000), NOW)
        async def invoke(*_): return {"order_id": "order", "ts_ms": 2, "reduced_by": "10"}
        self.executor.invoke = invoke
        req = dict(order_id="order", market_ticker="A", subaccount=0, exchange_index=1)
        prepared = await self.writer.prepare_cancel('cancel', req,
            evidence=await self.writer.cancel_evidence('order'), now=NOW)
        self.assertTrue(prepared.reserved, prepared.blockers)
        await self.executor.execute_prepared(prepared.receipt)
        self.assertFalse((await self.writer.orders())[0].order.terminal)
        self.assertEqual((await self.writer.inventory()).unresolved_intents, 1)

    async def test_unowned_cancel_never_invokes_gateway(self):
        req = dict(order_id="foreign", market_ticker="A", subaccount=0, exchange_index=1)
        with self.assertRaises(InvalidData):
            await self.writer.prepare_cancel('cancel', req, evidence=None, now=NOW)
        self.assertFalse(self.calls)

    async def test_cancelled_send_retains_unknown(self):
        entered = asyncio.Event()
        async def invoke(*_):
            entered.set()
            await asyncio.Event().wait()
        self.executor.invoke = invoke
        receipt = await self.prepare()
        task = asyncio.create_task(self.executor.execute_prepared(receipt))
        await entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertEqual((await self.writer.mutations())[0]["phase"], "UNKNOWN")

    async def test_concurrent_mutation_rejected_not_queued(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def invoke(*_):
            entered.set()
            await release.wait()
            return ack()
        self.executor.invoke = invoke
        receipt = await self.prepare()
        task = asyncio.create_task(self.executor.execute_prepared(receipt))
        await entered.wait()
        with self.assertRaises(CommandDenied): await self.executor.execute_prepared(receipt)
        release.set()
        await task

    async def test_live_constructor_rejected(self):
        with self.assertRaises(InvalidData):
            InjectedExecutor(self.writer, invoke=None, validate_proof=None, offline_fixture=False)

    async def test_v2_ack_does_not_accept_legacy_wrapper(self):
        with self.assertRaises(InvalidData): acknowledgement("create", request(), {"order": ack()})

    async def test_combined_book_rank_command_fill_and_exact_reducer(self):
        owner = AccountCoordinator(self.writer, subaccount=0)
        owner.connect_generation()
        ranks = RankingBoard()
        async def private(event, generation):
            await owner.on_event(event, generation=generation, received_at=NOW)
            ranks.invalidate("A")
        async def evaluate(ticker, book, generation):
            inventory = dict((await self.writer.inventory()).positions)
            ranks.update(book, (program(),), BANDS, now=NOW, valid_until=NOW+timedelta(seconds=5),
                         market_open=True, position=inventory.get(ticker, D(0)))
        async def deadline(ticker): await self.writer.observe(NOW)
        engine = EventEngine({"a": BookConnection(("A",))}, private_handler=private,
                             evaluate=evaluate, deadline_handler=deadline, invalidate=ranks.invalidate)
        private_epoch = engine.begin_private_epoch()
        epoch = engine.begin_book_epoch("a")
        engine.submit_book("a", snapshot(), generation=epoch)
        await engine.step()
        ranked = ranks.ranked(now=NOW, by="remaining_reward")[0]
        self.assertEqual(ranked.quotes[0].yes_price, D(".4"))
        # Explicit offline fixture gate only; ranking is not trading permission.
        await self.executor.execute_prepared(await self.prepare())
        engine.submit_private(dict(type="user_order", msg=dict(order_id="order", client_order_id="client",
            ticker="A", book_side="bid", yes_price_dollars=".4", initial_count_fp="10", fill_count_fp="0",
            remaining_count_fp="10", status="resting", subaccount_number=0, exchange_index=1,
            last_updated_ts_ms=1)), generation=private_epoch)
        engine.submit_private(dict(type="fill", msg=dict(trade_id="trade", order_id="order", market_ticker="A",
            book_side="bid", count_fp="3", yes_price_dollars=".4", fee_cost=".01", subaccount=0)), generation=private_epoch)
        engine.submit_book("a", delta(), generation=epoch)
        await engine.step()
        self.assertEqual(dict((await self.writer.inventory()).positions)["A"], 3)
        self.assertIn("open_inventory_no_new_entries", ranks.ranked(now=NOW, by="remaining_reward")[0].blockers)
        plan = inventory_plan(D(3), await self.writer.orders(), ticker="A", touch=D(".6"), complete_scope=True)
        self.assertEqual(plan.cancel_ids, ("order",))
        self.assertIsNone(plan.reduce_side)
        # A terminal update confirming the three fills permits the exact reducer.
        await self.writer.order(OrderUpdate("order", "client", "A", "bid", D(".4"), D(10), D(3), D(0), "canceled", 0, 1, 2000), NOW)
        plan = inventory_plan(D(3), await self.writer.orders(), ticker="A", touch=D(".6"), complete_scope=True)
        self.assertEqual((plan.reduce_side, plan.reduce_quantity), ("ask", 3))
        self.assertEqual(len(self.calls), 1)  # Only one fake create; no real writes.
        self.assertFalse(engine.status()["live_ready"])


@unittest.skipUnless(os.name == "nt", "native Windows primitive")
class StopControlTests(unittest.TestCase):
    def test_absent_runtime_request_does_not_create_stale_event(self):
        identity = str(uuid4())
        self.assertFalse(WindowsStopEvent(identity).request())
        with WindowsStopEvent(identity) as control:
            self.assertFalse(control.requested)

    def test_request_is_sticky_until_owner_closes(self):
        identity = str(uuid4())
        with WindowsStopEvent(identity) as control:
            self.assertTrue(WindowsStopEvent(identity).request())
            self.assertTrue(control.requested)
            self.assertTrue(control.requested)
        with WindowsStopEvent(identity) as control:
            self.assertFalse(control.requested)

    def test_duplicate_stop_owner_rejected(self):
        identity = str(uuid4())
        with WindowsStopEvent(identity):
            with self.assertRaises(InvalidData):
                with WindowsStopEvent(identity): pass

    def test_separate_process_can_request_stop(self):
        identity = str(uuid4())
        with WindowsStopEvent(identity) as control:
            result = subprocess.run([sys.executable, "-B", "-c",
                "from kalshi_bot.windows import WindowsStopEvent; import sys; sys.exit(0 if WindowsStopEvent(sys.argv[1]).request() else 2)",
                identity], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(control.requested)


if __name__ == "__main__":
    unittest.main()
