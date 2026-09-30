import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, get_ident
import unittest
from unittest.mock import patch

from kalshi_bot.account import AccountCoordinator, normalize_snapshot
from kalshi_bot.ledger import Fill, Ledger
from kalshi_bot.orders import OrderUpdate
from kalshi_bot.rest import (NoRedirect, RestReads, TokenBudget, WireResponse, decode,
                             get_wire, request_path)
from kalshi_bot.risk import WindowRisk
from kalshi_bot.values import InvalidData
from kalshi_bot.writer import LedgerWriter


NOW = datetime(2026, 9, 19, 5, tzinfo=timezone.utc)


def fill(key="1", side="bid", p="0.9", ticker="A"):
    return Fill(key, "o-"+key, ticker, side, D(10), D(p), D(0))


def event(key="1", side="bid", p="0.9"):
    return {"type": "fill", "sid": 1, "msg": {"trade_id": key, "order_id": "o-"+key,
        "market_ticker": "A", "book_side": side, "count_fp": "10.00",
        "yes_price_dollars": p, "fee_cost": "0", "subaccount": 0}}


def snapshot(q=None, orders=()):
    positions = [] if q is None else [{"ticker": "A", "exchange_index": 0,
                                     "position_fp": q, "market_exposure_dollars": "9"}]
    return normalize_snapshot(orders, positions, {"balance_dollars": "500", "updated_ts": 1}, subaccount=0)


class TransactionTests(unittest.TestCase):
    def test_outer_failure_rolls_back_fill_and_window(self):
        db = Ledger(":memory:")
        try:
            with self.assertRaises(RuntimeError), db.transaction():
                db.record_fill(fill(), NOW)
                WindowRisk(db).observe(NOW)
                raise RuntimeError("offline injected crash")
            self.assertEqual(db.position("A"), 0)
            self.assertEqual(db.connection.execute("SELECT COUNT(*) FROM fills").fetchone()[0], 0)
            self.assertEqual(db.connection.execute("SELECT COUNT(*) FROM risk_windows").fetchone()[0], 0)
        finally:
            db.close()

    def test_caught_inner_failure_uses_savepoint(self):
        db = Ledger(":memory:")
        try:
            with db.transaction():
                db.record_fill(fill(), NOW)
                with self.assertRaises(RuntimeError), db.transaction():
                    db.record_fill(fill("2"), NOW)
                    raise RuntimeError()
                WindowRisk(db).observe(NOW)
            self.assertEqual(db.position("A"), 10)
        finally:
            db.close()


class WriterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name)/"ledger.db"
        self.writer = await LedgerWriter(self.path).start()

    async def asyncTearDown(self):
        await self.writer.close()
        self.temp.cleanup()

    async def test_fill_ack_is_committed_and_duplicate_idempotent(self):
        ack = await self.writer.fill(fill(), NOW)
        self.assertTrue(ack.inserted)
        self.assertEqual(ack.position, 10)
        self.assertFalse((await self.writer.fill(fill(), NOW)).inserted)
        db = Ledger(self.path)
        try:
            self.assertEqual(db.position("A"), 10)
        finally:
            db.close()

    async def test_fills_count_net_toward_the_24_hour_limit_across_restart(self):
        for f in (fill(), fill("2", "ask", "0.3"), fill("3", "bid", "0.1"),
                  fill("4", "ask", "0.9")):
            ack = await self.writer.fill(f, NOW)
        self.assertEqual(ack.window.realized_pnl, 2)
        self.assertEqual(ack.window.cap, 50)       # D-162: net result, $60 limit
        await self.writer.close()
        self.writer = await LedgerWriter(self.path).start()
        self.assertEqual((await self.writer.observe(NOW)).realized_pnl, 2)

    async def test_risk_failure_rolls_back_close_and_poisons_writer(self):
        await self.writer.fill(fill(), NOW)
        with patch("kalshi_bot.writer.WindowRisk.observe", side_effect=RuntimeError("offline fault")):
            with self.assertRaises(InvalidData):
                await self.writer.fill(fill("2", "ask", "0.3"), NOW)
        self.assertTrue(self.writer.failed)
        with self.assertRaises(InvalidData):
            await self.writer.observe(NOW)
        db = Ledger(self.path)
        try:
            self.assertEqual(db.position("A"), 10)
            self.assertEqual(db.connection.execute("SELECT COUNT(*) FROM fills").fetchone()[0], 1)
        finally:
            db.close()

    async def test_one_thread_owns_all_sqlite_work(self):
        ids = []
        original = self.writer._execute
        def tracked(*args):
            ids.append(get_ident())
            return original(*args)
        with patch.object(self.writer, "_execute", side_effect=tracked):
            await self.writer.fill(fill(), NOW)
            await self.writer.inventory()
            await self.writer.observe(NOW)
        self.assertEqual(len(set(ids)), 1)
        self.assertNotEqual(ids[0], get_ident())

    async def test_caller_cancellation_does_not_discard_accepted_fill(self):
        entered, release = Event(), Event()
        original = self.writer._execute
        def delayed(*args):
            entered.set()
            if not release.wait(3):
                raise RuntimeError("test release missing")
            return original(*args)
        with patch.object(self.writer, "_execute", side_effect=delayed):
            task = asyncio.create_task(self.writer.fill(fill(), NOW))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 2))
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            finally:
                release.set()
        self.assertEqual(dict((await self.writer.inventory()).positions), {"A": D(10)})

    async def test_overflow_fails_closed_without_unbounded_queue(self):
        await self.writer.close()
        self.writer = await LedgerWriter(self.path, capacity=1).start()
        entered, release = Event(), Event()
        original = self.writer._execute
        def delayed(*args):
            entered.set()
            release.wait(3)
            return original(*args)
        with patch.object(self.writer, "_execute", side_effect=delayed):
            first = asyncio.create_task(self.writer.fill(fill(), NOW))
            self.assertTrue(await asyncio.to_thread(entered.wait, 2))
            second = asyncio.create_task(self.writer.observe(NOW))
            await asyncio.sleep(0)
            try:
                with self.assertRaises(InvalidData):
                    await self.writer.inventory()
                self.assertLessEqual(self.writer.backlog, 1)
                self.assertTrue(self.writer.failed)
            finally:
                release.set()
                results = await asyncio.gather(first, second, return_exceptions=True)
            self.assertIsInstance(results[1], InvalidData)

    async def test_conflicting_duplicate_poison_and_close_rejects_work(self):
        await self.writer.fill(fill(), NOW)
        with self.assertRaises(InvalidData):
            await self.writer.fill(fill(p="0.8"), NOW)
        await self.writer.close()
        with self.assertRaises(InvalidData):
            await self.writer.inventory()

    async def test_failed_start_is_reported_and_closes(self):
        other = LedgerWriter(Path(self.temp.name)/"missing"/"no.db")
        try:
            with self.assertRaises(InvalidData):
                await other.start()
        finally:
            await other.close()

    async def test_durable_intent_lifecycle_and_ambiguity_cannot_resend(self):
        await self.writer.reserve_intent("client-1", {"ticker": "A"}, NOW)
        self.assertEqual((await self.writer.inventory()).unresolved_intents, 1)
        await self.writer.transition_intent("client-1", "SENDING")
        await self.writer.transition_intent("client-1", "UNKNOWN")
        with self.assertRaises(InvalidData):
            await self.writer.transition_intent("client-1", "SENDING")
        db = Ledger(self.path)
        try:
            self.assertEqual(db.connection.execute("SELECT state FROM intents").fetchone()[0], "UNKNOWN")
        finally:
            db.close()

    async def test_inventory_capacity_failure_rolls_back_new_market(self):
        await self.writer.close()
        self.writer = await LedgerWriter(self.path, market_capacity=1).start()
        await self.writer.fill(fill(), NOW)
        with self.assertRaises(InvalidData):
            await self.writer.fill(fill("2", ticker="B"), NOW)
        db = Ledger(self.path)
        try:
            self.assertEqual(db.position("A"), 10)
            self.assertEqual(db.position("B"), 0)
        finally:
            db.close()

    async def test_concurrent_close_waits_for_same_worker(self):
        await asyncio.gather(self.writer.close(), self.writer.close())
        self.assertFalse(self.writer._thread.is_alive())

    async def test_cancelled_start_does_not_leave_non_daemon_thread_running(self):
        entered, release = Event(), Event()
        original = Ledger
        other = LedgerWriter(Path(self.temp.name)/"cancelled-start.db")
        def delayed(*args):
            entered.set()
            release.wait(3)
            return original(*args)
        with patch("kalshi_bot.writer.Ledger", side_effect=delayed):
            task = asyncio.create_task(other.start())
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 2))
                task.cancel()
            finally:
                release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertFalse(other._thread.is_alive())

    async def test_unexpected_worker_exit_resolves_active_and_queued_callers(self):
        with patch.object(self.writer, "_execute", side_effect=SystemExit()):
            with self.assertRaises(InvalidData):
                await asyncio.wait_for(self.writer.fill(fill(), NOW), 2)
        self.assertTrue(self.writer.failed)


class FakeClock:
    def __init__(self):
        self.now = 10.0
        self.sleeps = []

    def __call__(self):
        return self.now

    async def sleep(self, delay):
        self.sleeps.append(delay)
        self.now += delay
        await asyncio.sleep(0)


def wire(payload, status=200):
    return WireResponse(status, json.dumps(payload).encode())


class RestTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clock = FakeClock()
        self.budget = TokenBudget(rate=100, capacity=100, default_cost=10,
                                  clock=self.clock, sleep=self.clock.sleep)
        self.clients = []

    def client(self, fn, **kwargs):
        client = RestReads(self.budget, wire=fn, jitter=lambda: 0, **kwargs)
        self.clients.append(client)
        return client

    async def asyncTearDown(self):
        for client in self.clients:
            await client.close()

    async def test_default_and_route_token_costs_and_refill(self):
        budget = TokenBudget.from_documents({"read": {"refill_rate": 10, "bucket_capacity": 20}},
            {"default_cost": 10, "endpoint_costs": [
                {"method": "GET", "path": "/trade-api/v2/markets/{ticker}", "cost": 20},
                {"method": "POST", "path": "/portfolio/events/orders", "cost": 99}]},
            clock=self.clock, sleep=self.clock.sleep, initial_tokens=20)
        await budget.acquire("/markets/{ticker}", 20)
        await budget.acquire("/incentive_programs", 20)
        self.assertEqual(budget.spent, 30)
        self.assertEqual(self.clock.sleeps, [1])

    async def test_budget_rejects_impossible_cost_or_deadline(self):
        self.budget.costs["/costly"] = 101
        with self.assertRaises(InvalidData):
            await self.budget.acquire("/costly", 20)
        self.budget.tokens = 0
        with self.assertRaises(InvalidData):
            await self.budget.acquire("/normal", 10.01)

    async def test_only_allowlisted_reads_and_justified_sources(self):
        for name, params, reason in (("POST", {}, "metadata"), ("orders", {}, "poll"),
                                     ("market", {"ticker": "../secrets"}, "metadata"),
                                     ("positions", {"bad": 1}, "bootstrap"),
                                     ("historical_fills", {"bad": 0}, "history"),
                                     ("incentives", {"limit": True}, "incentives")):
            with self.subTest(name=name, reason=reason), self.assertRaises(InvalidData):
                request_path(name, params, reason)

    async def test_incentive_next_cursor_is_exhausted(self):
        calls = []
        def get(url, *_):
            calls.append(url)
            return wire({"incentive_programs": [{"id": len(calls)}],
                         "next_cursor": "a+b" if len(calls) == 1 else ""})
        result = await self.client(get).collect("incentives", reason="incentives", type="liquidity")
        self.assertEqual(result.pages, 2)
        self.assertEqual(len(result.rows), 2)
        self.assertIn("cursor=a%2Bb", calls[1])
        self.assertIn("type=liquidity", calls[1])
        self.assertEqual(result.source, 'incentives')
        self.assertEqual(result.query, (('type', 'liquidity'),))
        self.assertTrue(result.exhausted)

    async def test_cash_history_accepts_documented_short_terminal_omission_only(self):
        class Signer:
            def headers(self, *_):
                return {}
        client = self.client(lambda *_: wire({'settlements': []}), signer=Signer())
        with self.assertRaisesRegex(InvalidData, 'cursor missing'):
            await client.collect('settlements', reason='cash')
        for name, field in (('subaccount_transfers', 'transfers'),
                            ('intra_exchange_transfers', 'transfers'),
                            ('deposits', 'deposits'), ('withdrawals', 'withdrawals')):
            with self.subTest(name=name):
                client = self.client(lambda *_, key=field: wire({key: []}),
                                     signer=Signer())
                result = await client.collect(name, reason='cash')
                self.assertTrue(result.exhausted)
                self.assertEqual(result.rows, ())
                client = self.client(lambda *_, key=field: wire({key: [{}]*100}),
                                     signer=Signer())
                with self.assertRaisesRegex(InvalidData, 'cursor missing'):
                    await client.collect(name, reason='cash')

    async def test_cursor_cycles_never_return_partial_success(self):
        client = self.client(lambda *_: wire({"incentive_programs": [], "next_cursor": "repeat"}))
        with self.assertRaisesRegex(InvalidData, "cycle"):
            await client.collect("incentives", reason="incentives")

    async def test_page_row_and_byte_caps(self):
        client = self.client(lambda *_: wire({"incentive_programs": [{}, {}], "next_cursor": "next"}))
        for args in ({"max_pages": 1}, {"max_rows": 1}, {"byte_limit": 1}):
            with self.subTest(args=args), self.assertRaises(InvalidData):
                await client.collect("incentives", reason="incentives", **args)

    async def test_malformed_pages_and_supplied_cursor_fail(self):
        for payload in ({}, {"incentive_programs": [1]}, {"incentive_programs": [], "next_cursor": None}):
            client = self.client(lambda *_, p=payload: wire(p))
            with self.assertRaises(InvalidData):
                await client.collect("incentives", reason="incentives")
        with self.assertRaises(InvalidData):
            await client.collect("incentives", reason="incentives", cursor="middle")

    async def test_429_backoff_is_bounded_and_charged_per_attempt(self):
        calls = []
        def get(*_):
            calls.append(1)
            return wire({}, 429 if len(calls) < 3 else 200)
        await self.client(get).read("costs", reason="budget")
        self.assertEqual(len(calls), 3)
        self.assertEqual(self.budget.spent, 30)
        self.assertGreaterEqual(sum(self.clock.sleeps), 1.5)

    async def test_retry_exhaustion_and_auth_error(self):
        for status, expected in ((503, 3), (429, 3), (401, 1), (302, 1)):
            calls = []
            def get(*_):
                calls.append(1)
                return wire({}, status)
            with self.assertRaises(InvalidData):
                await self.client(get).read("costs", reason="budget")
            self.assertEqual(len(calls), expected)

    async def test_transport_error_does_not_echo_sensitive_details(self):
        def get(*_):
            raise RuntimeError("secret-test-marker")
        with self.assertRaises(InvalidData) as raised:
            await self.client(get).read("costs", reason="budget")
        self.assertNotIn("secret-test-marker", str(raised.exception))

    async def test_cancelled_consumer_preserves_shared_request_and_result_isolation(self):
        entered, release = Event(), Event()
        calls = []
        def get(*_):
            calls.append(1)
            entered.set()
            release.wait(3)
            return wire({"rows": ["original"]})
        client = self.client(get)
        first = asyncio.create_task(client.read("costs", reason="budget"))
        self.assertTrue(await asyncio.to_thread(entered.wait, 2))
        second = asyncio.create_task(client.read("costs", reason="budget"))
        third = asyncio.create_task(client.read("costs", reason="budget"))
        await asyncio.sleep(0)
        first.cancel()
        try:
            with self.assertRaises(asyncio.CancelledError):
                await first
        finally:
            release.set()
        a, b = await asyncio.gather(second, third)
        a.payload["rows"].append("changed")
        self.assertEqual(b.payload["rows"], ["original"])
        self.assertEqual(len(calls), 1)

    async def test_inflight_and_wire_response_caps(self):
        entered, release = Event(), Event()
        def get(*_):
            entered.set()
            release.wait(3)
            return wire({})
        client = self.client(get, inflight_limit=1)
        first = asyncio.create_task(client.read("costs", reason="budget"))
        self.assertTrue(await asyncio.to_thread(entered.wait, 2))
        try:
            with self.assertRaises(InvalidData):
                await client.read("market", reason="metadata", ticker="A")
        finally:
            release.set()
            await first
        with self.assertRaises(InvalidData):
            await self.client(lambda *_: wire({"x": "long"}), max_bytes=2).read("costs", reason="budget")

    async def test_read_signing_fixed_host_and_exact_path(self):
        calls = []
        class FakeSigner:
            def headers(self, method, path):
                calls.append((method, path))
                return {"X-Test": "not-a-real-key"}
        def get(url, headers, _):
            self.assertTrue(url.startswith("https://external-api.kalshi.com/trade-api/v2/portfolio/orders?"))
            self.assertEqual(headers["X-Test"], "not-a-real-key")
            return wire({"orders": []})
        client = self.client(get, signer=FakeSigner())
        await client.read("orders", reason="bootstrap", subaccount=0, status="resting")
        self.assertEqual(calls, [("GET", "/trade-api/v2/portfolio/orders?status=resting&subaccount=0")])

    async def test_missing_signer_and_closed_client_fail(self):
        client = self.client(lambda *_: self.fail("should not reach wire"))
        with self.assertRaises(InvalidData):
            await client.read("limits", reason="budget")
        await client.close()
        with self.assertRaises(InvalidData):
            await client.read("costs", reason="budget")

    async def test_whole_enumeration_deadline_not_renewed_each_page(self):
        def get(*_):
            self.clock.now += 16
            return wire({"incentive_programs": [], "next_cursor": str(self.clock.now)})
        with self.assertRaisesRegex(InvalidData, "enumeration deadline"):
            await self.client(get).collect("incentives", reason="incentives")

    async def test_json_decoding_runs_off_event_loop(self):
        ids = []
        original = decode
        def tracked(body):
            ids.append(get_ident())
            return original(body)
        with patch("kalshi_bot.rest.decode", side_effect=tracked):
            await self.client(lambda *_: wire({})).read("costs", reason="budget")
        self.assertNotEqual(ids[0], get_ident())

    async def test_rest_concurrency_never_exceeds_configured_slots(self):
        from threading import Lock
        entered, release, lock = Event(), Event(), Lock()
        active = peak = 0
        def get(*_):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
                if active == 2:
                    entered.set()
            release.wait(3)
            with lock:
                active -= 1
            return wire({})
        client = self.client(get, concurrency=2)
        tasks = [asyncio.create_task(client.read("market", reason="metadata", ticker=f"A-{n}"))
                 for n in range(6)]
        tasks.append(asyncio.create_task(client.read('costs', reason='budget')))
        try:
            self.assertTrue(await asyncio.to_thread(entered.wait, 2))
            self.assertEqual(peak, 2)
        finally:
            release.set()
            await asyncio.gather(*tasks)
        self.assertLessEqual(peak, 2)


class DecodeTests(unittest.TestCase):
    def test_exact_decimal_and_malformed_json(self):
        self.assertEqual(decode(b'{"n":0.123456}')['n'], D("0.123456"))
        for body in (b'{"x":1,"x":2}', b'{"x":NaN}', b'[]', b'bad', b'\xff'):
            with self.subTest(body=body), self.assertRaises(InvalidData):
                decode(body)

    def test_redirects_disabled(self):
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.example"))

    def test_wire_body_cap_without_network(self):
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def read1(self, n): return b"x"*n
        with patch("kalshi_bot.rest.build_opener") as opener:
            opener.return_value.open.return_value = Response()
            with self.assertRaises(InvalidData):
                get_wire("https://external-api.kalshi.com/trade-api/v2/account/endpoint_costs", {}, 3)


class AccountTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        self.writer = await LedgerWriter(Path(self.temp.name)/"ledger.db").start()
        self.owner = AccountCoordinator(self.writer, subaccount=0)
        self.generation = self.owner.connect_generation()
        # Private accounting now requires an exact, durable owned-order binding.
        await self.writer.reserve_intent("owned-1", {"ticker": "A", "side": "bid", "price": "0.9",
            "count": "10", "subaccount": 0, "exchange_index": 0}, NOW)
        await self.writer.transition_intent("owned-1", "SENDING")
        await self.writer.order(OrderUpdate("o-1", "owned-1", "A", "bid", D("0.9"),
            D(10), D(0), D(10), "resting", 0, 0, 1), NOW)

    async def asyncTearDown(self):
        await self.writer.close()
        self.temp.cleanup()

    async def test_flat_agreement_is_not_live_or_history_proof(self):
        token = self.owner.begin_reconciliation(NOW)
        result = await self.owner.finish_reconciliation(token, snapshot(), NOW)
        self.assertTrue(result.positions_match)
        self.assertFalse(result.ready_for_entry)
        self.assertIn("execution_history_not_proven", result.blockers)
        self.assertIsNone(await self.owner.finish_reconciliation(token, snapshot(), NOW))

    async def test_rest_cannot_overwrite_fill_during_fetch(self):
        token = self.owner.begin_reconciliation(NOW)
        await self.owner.on_event(event(), generation=self.generation, received_at=NOW)
        self.assertIsNone(await self.owner.finish_reconciliation(token, snapshot(), NOW))
        self.assertEqual(self.owner.latest_fill.position, 10)
        self.assertIsNone(self.owner.report)

    async def test_reconnect_and_disconnect_reject_old_rest_generation(self):
        token = self.owner.begin_reconciliation(NOW)
        self.owner.disconnect()
        self.owner.connect_generation()
        self.assertIsNone(await self.owner.finish_reconciliation(token, snapshot(), NOW))
        self.assertIsNone(await self.owner.on_event(event(), generation=self.generation, received_at=NOW))
        self.assertEqual((await self.writer.inventory()).positions, ())

    async def test_position_disagreement_does_not_import_fake_lots(self):
        token = self.owner.begin_reconciliation(NOW)
        result = await self.owner.finish_reconciliation(token, snapshot("10"), NOW)
        self.assertFalse(result.positions_match)
        self.assertIn("position_ledger_mismatch", result.blockers)
        self.assertEqual((await self.writer.inventory()).positions, ())

    async def test_matching_fill_and_rest_inventory(self):
        await self.owner.on_event(event(), generation=self.generation, received_at=NOW)
        token = self.owner.begin_reconciliation(NOW)
        result = await self.owner.finish_reconciliation(token, snapshot("10"), NOW)
        self.assertTrue(result.positions_match)
        self.assertFalse(result.ready_for_entry)

    async def test_stale_or_backward_snapshot_clock_is_rejected(self):
        for seconds in (-1, 6):
            token = self.owner.begin_reconciliation(NOW)
            with self.assertRaises(InvalidData):
                await self.owner.finish_reconciliation(token, snapshot(), NOW+timedelta(seconds=seconds))
            self.assertIsNone(self.owner.report)

    async def test_new_order_invalidates_even_matching_rest_snapshot(self):
        token = self.owner.begin_reconciliation(NOW)
        # A group event also invalidates account evidence; order events now
        # require full canonical data for the durable order projection.
        await self.owner.on_event({"type": "order_group_updates"}, generation=self.generation, received_at=NOW)
        self.assertIsNone(await self.owner.finish_reconciliation(token, snapshot(), NOW))

    async def test_missing_or_different_fill_subaccount_fails_closed(self):
        message = event()
        message["msg"]["order_id"] = "unknown-order"
        del message["msg"]["subaccount"]
        with self.assertRaises(InvalidData):
            await self.owner.on_event(message, generation=self.generation, received_at=NOW)
        self.assertFalse(self.owner.connected)
        self.assertEqual((await self.writer.inventory()).positions, ())
        gen = self.owner.connect_generation()
        message["msg"]["order_id"] = "o-1"
        message["msg"]["subaccount"] = 3
        with self.assertRaises(InvalidData):
            await self.owner.on_event(message, generation=gen, received_at=NOW)

    async def test_disconnect_during_ledger_read_cannot_publish_proof(self):
        token = self.owner.begin_reconciliation(NOW)
        original = self.writer.reconcile_snapshot
        async def interrupted(*args, **kwargs):
            result = await original(*args, **kwargs)
            self.owner.disconnect()
            return result
        with patch.object(self.writer, "reconcile_snapshot", side_effect=interrupted):
            self.assertIsNone(await self.owner.finish_reconciliation(token, snapshot(), NOW))
        self.assertIsNone(self.owner.report)

    async def test_slow_disk_cannot_publish_expired_snapshot(self):
        clock = FakeClock()
        self.owner.clock = clock
        token = self.owner.begin_reconciliation(NOW)
        original = self.writer.reconcile_snapshot
        async def delayed(*args, **kwargs):
            result = await original(*args, **kwargs)
            clock.now += 6
            return result
        with patch.object(self.writer, "reconcile_snapshot", side_effect=delayed):
            self.assertIsNone(await self.owner.finish_reconciliation(token, snapshot(), NOW))

    async def test_unresolved_intent_remains_a_blocker_even_when_flat(self):
        await self.writer.reserve_intent("unknown", {"ticker": "A"}, NOW)
        token = self.owner.begin_reconciliation(NOW)
        result = await self.owner.finish_reconciliation(token, snapshot(), NOW)
        self.assertIn("unbound_order_intents", result.blockers)
        self.assertFalse(result.ready_for_entry)

    async def test_integrated_injected_rest_reads_explicit_subaccount_all_shards(self):
        calls = []
        class FakeSigner:
            def headers(self, *_): return {}
        def get(url, *_):
            calls.append(url)
            self.assertIn("subaccount=0", url)
            self.assertNotIn("exchange_index", url)
            if "/orders?" in url:
                return wire({"orders": [], "cursor": ""})
            if "/positions?" in url:
                return wire({"market_positions": [], "event_positions": [], "cursor": ""})
            return wire({"balance_dollars": "500", "updated_ts": 1})
        client = RestReads(TokenBudget(rate=100, capacity=100, default_cost=10), FakeSigner(), wire=get)
        try:
            result = await self.owner.reconcile(client, now=lambda: NOW)
            self.assertTrue(result.positions_match)
            self.assertEqual(len(calls), 3)
            self.assertFalse(result.ready_for_entry)
        finally:
            await client.close()


class SnapshotTests(unittest.TestCase):
    def test_ambiguous_duplicate_position_rejected(self):
        p = {"ticker": "A", "exchange_index": 0, "position_fp": "10", "market_exposure_dollars": "9"}
        with self.assertRaises(InvalidData):
            normalize_snapshot([], [p, p], {"balance_dollars": "500", "updated_ts": 1}, subaccount=0)

    def test_canonical_order_and_exact_cash(self):
        order = {"order_id": "o", "client_order_id": "client", "ticker": "A", "exchange_index": 0,
                 "book_side": "ask", "yes_price_dollars": "0.6", "remaining_count_fp": "0.01",
                 "status": "resting", "subaccount_number": 0}
        result = snapshot(orders=[order])
        self.assertEqual(result.orders[0].remaining, D("0.01"))
        self.assertEqual(result.available_balance, 500)
        for update in ({"book_side": "no"}, {"remaining_count_fp": "0"}, {"status": "unknown"},
                       {"subaccount_number": 1}):
            with self.assertRaises(InvalidData):
                snapshot(orders=[{**order, **update}])
        with self.assertRaises(InvalidData):
            snapshot(orders=[order, order])
