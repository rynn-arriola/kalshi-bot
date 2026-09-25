"""D-026 injected engine/recovery integration; no credentials or sockets."""
import asyncio
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from kalshi_bot.ledger import Fill, Ledger
from kalshi_bot.orders import parse_order
from kalshi_bot.rest import PageSet, ReadResult, ReadTransportUnavailable
from kalshi_bot.runtime import RecoveryRuntime
from kalshi_bot.values import InvalidData
from kalshi_bot.writer import LedgerWriter
from test_bot_auto_recovery import NOW, EXEC, Reads, history, wire_order
from test_bot_engine import snapshot


def event(key="o", **changes):
    return dict(type="fill", msg=dict(trade_id="f-"+key, order_id=key, market_ticker="A",
        book_side="bid", count_fp="10", yes_price_dollars="0.5", fee_cost="0.01",
        subaccount=0, exchange_index=0, **changes))


class AccountReads(Reads):
    def __init__(self, *args, quantity="0", **kwargs):
        super().__init__(*args, **kwargs)
        self.quantity = quantity
        self.resting_orders = ()
        self.before_collect = None

    async def read(self, name, **kwargs):
        if name == "balance":
            self.calls.append((name, kwargs))
            return ReadResult(dict(balance_dollars="500", updated_ts=1), 50)
        return await super().read(name, **kwargs)

    async def collect(self, name, **kwargs):
        if self.before_collect:
            await self.before_collect(name)
        if name in {"orders", "positions"}:
            self.calls.append((name, kwargs))
            rows = self.resting_orders if name == "orders" else ()
            if name == "positions" and self.quantity != "0":
                rows = (dict(ticker="A", position_fp=self.quantity,
                             market_exposure_dollars=str(abs(D(self.quantity))*D(".5")), exchange_index=0),)
            return PageSet(rows, 1, 100)
        return await super().collect(name, **kwargs)


class FakeReader:
    def __init__(self, spec):
        self.spec = spec
        self.queue = asyncio.Queue(maxsize=256)
        self.started = asyncio.Event()
        self.closed = False

    async def run(self, consume):
        try:
            for sid, channel in enumerate(self.spec.channels, 1):
                await consume(self.spec.name, dict(type="subscribed", id=1, msg=dict(channel=channel, sid=sid)))
            self.started.set()
            while True:
                item = await self.queue.get()
                if isinstance(item, Exception):
                    raise item
                await consume(self.spec.name, item)
        finally:
            self.closed = True


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name)/"runtime.db"
        self.writer = await LedgerWriter(self.path).start()
        self.reads = AccountReads()
        self.connections = {}
        self.delays, self.evaluated, self.deadlines = [], [], []
        self.tasks = []
        self.runtime = self.make_runtime()

    async def asyncTearDown(self):
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await self.writer.close()
        self.temp.cleanup()

    def make_runtime(self):
        def factory(spec):
            reader = FakeReader(spec)
            self.connections.setdefault(spec.name, []).append(reader)
            return reader
        async def sleep(delay):
            self.delays.append(delay)
            await asyncio.sleep(.001)
        async def evaluate(ticker, *_):
            self.evaluated.append(ticker)
        async def deadline(ticker):
            self.deadlines.append(ticker)
        async def lifecycle(event):
            pass
        return RecoveryRuntime(self.writer, self.reads, factory, tickers=("A", "B"), subaccount=0,
            history_start=EXEC-timedelta(seconds=1), now=lambda: NOW, evaluate=evaluate,
            deadline_handler=deadline, lifecycle_handler=lifecycle, sleep=sleep, jitter=lambda: 1)

    async def eventually(self, predicate):
        async with asyncio.timeout(4):
            while not predicate():
                await asyncio.sleep(.001)

    async def reserve(self, key="o", bind=False, **changes):
        row = wire_order(key, **changes)
        await self.writer.reserve_intent("c-"+key, dict(ticker="A", side=row["book_side"],
            price=row["yes_price_dollars"], count=row["initial_count_fp"], subaccount=0, exchange_index=0), EXEC)
        await self.writer.transition_intent("c-"+key, "SENDING")
        if bind:
            await self.writer.order(parse_order(row), EXEC)
        return row

    async def connected(self):
        self.runtime.account.connect_generation()
        self.runtime.engine.begin_private_epoch()
        self.runtime.account_subscribed = True

    async def ingest(self, payload=None):
        spec = next(s for s in self.runtime.specs if s.name == "account")
        await self.runtime._consume(spec, payload or event(), self.runtime.account.generation, set())
        await self.runtime.engine.step()

    async def launch(self):
        task = asyncio.create_task(self.runtime.run())
        self.tasks.append(task)
        await self.eventually(lambda: self.runtime.account_subscribed)
        return task

    async def steady_scope(self):
        """Install exact synthetic full-cap/flat evidence; grants no authority."""
        await self.connected()
        runtime = self.runtime
        runtime.broad_discovery = True
        gate = SimpleNamespace(reason='coverage_complete')
        runtime.selection = SimpleNamespace(initial_ranking=gate, refresh=Mock())
        order = SimpleNamespace(order_id='o', client_id='c', ticker='A',
            exchange_index=0, book_side='bid', yes_price=D('.5'), remaining=D(10))
        snapshot = SimpleNamespace(positions=(), orders=(order,),
            available_balance=D(500), balance_updated_ts=1, subaccount=0)
        audit = SimpleNamespace(blockers=(), consistent=True)
        report = SimpleNamespace(snapshot=snapshot, audit=audit,
            positions_match=True, unresolved_intents=1, observed_at=NOW)
        current = [report]
        runtime.account.current_report = lambda _now: current[0]
        runtime.current_entry_orders = lambda: current[0].snapshot.orders
        runtime.accounting_result = SimpleNamespace(window=SimpleNamespace(
            start=NOW-timedelta(hours=1), end=NOW+timedelta(hours=1), held=False, cap=1))
        runtime._refresh_continuity = Mock()
        self.assertEqual(runtime._record_steady_account_scope(report), frozenset(('A',)))
        return current, report

    async def test_full_cap_scope_suppresses_optional_market_evaluation(self):
        await self.steady_scope()
        runtime = self.runtime
        runtime.management.refresh = AsyncMock(return_value=None)
        await runtime._evaluate('B', object(), 1)
        runtime.management.refresh.assert_not_awaited()
        self.assertEqual((self.evaluated, runtime.suppressed_market_evaluations), ([], 1))
        await runtime._evaluate('A', object(), 1)
        runtime.management.refresh.assert_awaited_once_with('A', background=True)
        self.assertEqual(self.evaluated, ['A'])
        runtime.request_recovery()
        await runtime._evaluate('B', object(), 1)
        self.assertEqual(self.evaluated, ['A', 'B'])

    async def test_steady_scope_requires_full_cap_and_exact_source_revision(self):
        current, report = await self.steady_scope()
        runtime = self.runtime
        runtime.accounting_result.window.cap = 2
        self.assertIsNone(runtime._record_steady_account_scope(report))
        runtime.accounting_result.window.cap = 1
        self.assertEqual(runtime._record_steady_account_scope(report), frozenset(('A',)))
        await runtime.writer.observe(NOW)
        self.assertIsNone(runtime._current_steady_account_scope())
        self.assertIs(current[0], report)

    async def test_successful_full_recovery_marks_only_proven_owner_scope_at_cap(self):
        await self.steady_scope()
        runtime = self.runtime
        runtime.recover_once = AsyncMock(return_value=True)
        runtime.request_recovery()
        task = asyncio.create_task(runtime._recover())
        self.tasks.append(task)
        await self.eventually(lambda: runtime.recovery_state == 'repaired_entries_blocked')
        self.assertEqual(runtime.engine.dirty._dirty, {'A'})
        self.assertEqual(runtime._current_steady_account_scope(), frozenset(('A',)))

    async def test_steady_refresh_uses_one_snapshot_and_only_owned_scope(self):
        current, prior = await self.steady_scope()
        runtime = self.runtime
        refreshed_snapshot = SimpleNamespace(positions=prior.snapshot.positions,
            orders=prior.snapshot.orders, available_balance=prior.snapshot.available_balance,
            balance_updated_ts=2, subaccount=prior.snapshot.subaccount)
        refreshed = SimpleNamespace(snapshot=refreshed_snapshot, audit=prior.audit,
            positions_match=True, unresolved_intents=0, observed_at=NOW)
        async def reconcile(*_args, **_kwargs):
            current[0] = refreshed
            return refreshed
        runtime.account.reconcile = AsyncMock(side_effect=reconcile)
        runtime.management.refresh = AsyncMock(return_value=None)
        runtime.last_reports = ('history', prior)
        runtime.rewards = SimpleNamespace(refresh=Mock(), request_reflection=Mock())
        self.assertTrue(await runtime._refresh_steady_account())
        runtime.account.reconcile.assert_awaited_once()
        runtime.management.refresh.assert_awaited_once_with('A')
        runtime.selection.refresh.assert_called_once_with('A')
        runtime.rewards.refresh.assert_called_once_with('A')
        runtime.rewards.request_reflection.assert_called_once_with()
        self.assertFalse(runtime.recovery_requested.is_set())
        self.assertEqual((runtime.steady_refresh_attempts,
                          runtime.steady_refresh_completed,
                          runtime.steady_refresh_escalations), (1, 1, 0))
        self.assertIs(runtime.last_reports[1], refreshed)

    async def test_steady_refresh_changed_snapshot_escalates_to_full_recovery(self):
        current, prior = await self.steady_scope()
        runtime = self.runtime
        changed_snapshot = SimpleNamespace(positions=(), orders=(),
            available_balance=D(499), balance_updated_ts=2, subaccount=0)
        changed = SimpleNamespace(snapshot=changed_snapshot, audit=prior.audit,
            positions_match=True, unresolved_intents=0, observed_at=NOW)
        async def reconcile(*_args, **_kwargs):
            current[0] = changed
            return changed
        runtime.account.reconcile = AsyncMock(side_effect=reconcile)
        self.assertFalse(await runtime._refresh_steady_account())
        self.assertTrue(runtime.recovery_requested.is_set())
        self.assertIsNone(runtime._steady_account_scope)
        self.assertEqual((runtime.steady_refresh_attempts,
                          runtime.steady_refresh_completed,
                          runtime.steady_refresh_escalations), (1, 0, 1))

    async def test_steady_refresh_with_real_account_and_writer_keeps_exact_scope(self):
        await self.connected()
        runtime = self.runtime
        row = wire_order('steady', fill_count_fp='0', remaining_count_fp='10',
                         status='resting', last_update_time=NOW.isoformat())
        await self.writer.reserve_intent('c-steady', dict(ticker='A', side='bid',
            price='0.5', count='10', subaccount=0, exchange_index=0), EXEC)
        await self.writer.transition_intent('c-steady', 'SENDING')
        await self.writer.order(parse_order(row), NOW)
        self.reads.resting_orders = (row,)
        report = await runtime.account.reconcile(self.reads, now=lambda: NOW)
        self.assertIsNotNone(report)
        runtime.broad_discovery = True
        runtime.selection = SimpleNamespace(
            initial_ranking=SimpleNamespace(reason='coverage_complete'), refresh=Mock())
        runtime.accounting_result = SimpleNamespace(window=SimpleNamespace(
            start=NOW-timedelta(hours=1), end=NOW+timedelta(hours=1), held=False, cap=1))
        runtime.management.refresh = AsyncMock(return_value=None)
        self.assertEqual(runtime._record_steady_account_scope(report), frozenset(('A',)))
        self.assertTrue(await runtime._refresh_steady_account())
        self.assertEqual(runtime._current_steady_account_scope(), frozenset(('A',)))
        self.assertEqual(runtime.steady_refresh_completed, 1)

    async def test_unbound_fill_is_durable_and_later_recovered_via_order(self):
        row = await self.reserve()
        self.reads.orders = {"o": row}
        self.reads.quantity = "10"
        await self.connected()
        await self.ingest()
        self.assertEqual(len(await self.writer.pending_fills(0)), 1)
        self.assertEqual((await self.writer.inventory()).positions, ())
        self.assertTrue(await self.runtime.recover_once())
        self.assertEqual(await self.writer.pending_fills(0), ())
        self.assertEqual((await self.writer.inventory()).positions, (("A", D(10)),))
        self.assertFalse(self.runtime.entry_allowed)

    async def test_startup_history_repairs_missed_fill(self):
        self.reads.orders = {"o": await self.reserve()}
        self.reads.rows = (history(),)
        self.reads.quantity = "10"
        await self.connected()
        self.assertTrue(await self.runtime.recover_once())
        self.assertEqual((await self.writer.observe(NOW)).realized_pnl, D("-.01"))
        self.assertFalse(self.runtime.last_reports[1].ready_for_entry)

    async def test_missing_terminal_order_update_is_recovered_after_history(self):
        await self.reserve(bind=True, status="resting", fill_count_fp="0", remaining_count_fp="10")
        self.reads.orders = {"o": wire_order(last_update_time=NOW.isoformat())}
        self.reads.rows = (history(),)
        self.reads.quantity = "10"
        await self.connected()
        self.assertTrue(await self.runtime.recover_once())
        self.assertEqual(self.runtime.account.order_states["o"].intent_state, "TERMINAL")

    async def test_no_id_ambiguous_send_is_not_reported_repaired(self):
        await self.reserve()
        await self.connected()
        self.assertFalse(await self.runtime.recover_once())
        self.assertFalse(self.runtime.entry_allowed)

    async def test_pending_inbox_survives_restart_without_resetting_risk_hold(self):
        self.reads.orders = {"o": await self.reserve()}
        await self.connected()
        await self.ingest()
        await self.writer.fill(Fill("old", "old-order", "B", "bid", D(1), D(".5"), D(25)), EXEC)
        await self.writer.close()
        self.writer = await LedgerWriter(self.path).start()
        self.runtime = self.make_runtime()
        await self.connected()
        self.reads.quantity = "10"
        await self.runtime.recover_once()  # B mismatch remains blocked, A repair still positive.
        self.assertEqual(await self.writer.pending_fills(0), ())
        self.assertTrue((await self.writer.observe(NOW)).held)
        self.assertFalse(self.runtime.entry_allowed)

    async def test_known_stream_fill_applies_without_rest(self):
        await self.reserve(bind=True)
        await self.connected()
        await self.ingest()
        self.assertEqual(await self.writer.pending_fills(0), ())
        self.assertEqual(self.reads.calls, [])
        self.assertFalse(self.runtime.recovery_requested.is_set())

    async def test_later_stream_order_drains_pending_without_rest(self):
        row = await self.reserve()
        await self.connected()
        await self.ingest()
        await self.ingest(dict(type="user_order", msg=row))
        self.assertEqual(await self.writer.pending_fills(0), ())
        self.assertEqual((await self.writer.inventory()).positions, (("A", D(10)),))
        self.assertEqual(self.reads.calls, [])

    async def test_duplicate_stream_delivery_does_not_repeat_fee(self):
        await self.reserve(bind=True)
        await self.connected()
        await self.ingest()
        await self.ingest()
        self.assertEqual((await self.writer.observe(NOW)).realized_pnl, D("-.01"))

    async def test_pending_and_history_same_fill_apply_once(self):
        self.reads.orders = {"o": await self.reserve()}
        self.reads.rows = (history(),)
        self.reads.quantity = "10"
        await self.connected()
        await self.ingest()
        self.assertTrue(await self.runtime.recover_once())
        self.assertEqual((await self.writer.observe(NOW)).realized_pnl, D("-.01"))

    async def test_private_ingress_revokes_before_dispatch(self):
        await self.connected()
        await self.runtime.recover_once()
        self.assertIsNotNone(self.runtime.account.report)
        spec = next(s for s in self.runtime.specs if s.name == "account")
        await self.runtime._consume(spec, event(), 1, set())
        self.assertIsNone(self.runtime.account.report)
        self.assertIsNone(self.runtime.last_reports)
        self.assertEqual(len(self.runtime.engine.private), 1)

    async def test_rest_response_overtaken_by_private_revision_not_published(self):
        await self.connected()
        async def overtaken(name):
            self.runtime._revoke()
        self.reads.before_collect = overtaken
        self.assertFalse(await self.runtime.recover_once())
        self.assertIsNone(self.runtime.last_reports)

    async def test_only_one_recovery_pass_can_be_in_flight(self):
        await self.connected()
        started, release = asyncio.Event(), asyncio.Event()
        async def blocked(name):
            started.set()
            await release.wait()
        self.reads.before_collect = blocked
        task = asyncio.create_task(self.runtime.recover_once())
        self.tasks.append(task)
        await started.wait()
        with self.assertRaisesRegex(InvalidData, "already in flight"):
            await self.runtime.recover_once()
        release.set()
        await task

    async def test_foreign_order_keeps_inbox_and_blocks(self):
        self.reads.orders = {"o": wire_order(client_order_id="foreign")}
        await self.connected()
        await self.ingest()
        self.assertFalse(await self.runtime.recover_once())
        self.assertEqual(len(await self.writer.pending_fills(0)), 1)

    async def test_missing_scope_not_assumed_primary(self):
        self.reads.orders = {"o": await self.reserve()}
        self.reads.orders["o"].pop("subaccount_number")
        payload = event()
        payload["msg"].pop("subaccount")
        await self.connected()
        await self.ingest(payload)
        with self.assertRaises(InvalidData):
            await self.runtime.recover_once()
        self.assertEqual(len(await self.writer.pending_fills(0)), 1)

    async def test_actual_404_falls_back_to_archive_for_pending_fill(self):
        self.reads.archive = (await self.reserve(),)
        self.reads.quantity = "10"
        await self.connected()
        await self.ingest()
        self.assertTrue(await self.runtime.recover_once())
        self.assertTrue(any(n == "historical_orders" for n, _ in self.reads.calls))

    async def test_unknown_fill_disconnect_before_dispatch_is_not_lost(self):
        self.reads.orders = {"o": await self.reserve()}
        await self.connected()
        spec = next(s for s in self.runtime.specs if s.name == "account")
        await self.runtime._consume(spec, event(), 1, set())
        self.runtime.account.disconnect()
        await self.runtime.engine.step()
        self.assertEqual(len(await self.writer.pending_fills(0)), 1)
        self.runtime.account.connect_generation()
        self.runtime.engine.begin_private_epoch()
        self.reads.quantity = "10"
        self.assertTrue(await self.runtime.recover_once())

    async def test_inbox_conflicting_duplicate_poisoned_without_pnl(self):
        await self.connected()
        await self.ingest()
        with self.assertRaises(InvalidData):
            payload = event()
            payload["msg"]["fee_cost"] = "1"
            await self.ingest(payload)
        self.assertTrue(self.writer.failed)
        db = Ledger(self.path)
        try:
            self.assertEqual(db.connection.execute("SELECT COUNT(*) FROM pending_fills").fetchone()[0], 1)
            self.assertEqual(db.connection.execute("SELECT COUNT(*) FROM fills").fetchone()[0], 0)
        finally:
            db.close()

    async def test_inbox_apply_failure_does_not_delete_evidence(self):
        await self.reserve(bind=True)
        await self.connected()
        with patch("kalshi_bot.writer.WindowRisk.observe", side_effect=RuntimeError("crash")):
            with self.assertRaises(InvalidData):
                await self.ingest()
        db = Ledger(self.path)
        try:
            self.assertEqual(db.connection.execute("SELECT COUNT(*) FROM pending_fills").fetchone()[0], 1)
            self.assertEqual(db.position("A"), 0)
        finally:
            db.close()

    async def test_pending_fill_above_terminal_filled_rolls_back(self):
        await self.reserve(bind=True, fill_count_fp="5", status="canceled")
        await self.connected()
        with self.assertRaises(InvalidData):
            await self.ingest()
        db = Ledger(self.path)
        try:
            self.assertEqual(db.position("A"), 0)
            self.assertEqual(db.connection.execute("SELECT COUNT(*) FROM pending_fills").fetchone()[0], 1)
        finally:
            db.close()

    async def test_wrong_shard_cannot_apply_pending(self):
        await self.reserve(bind=True)
        await self.connected()
        payload = event()
        payload["msg"]["exchange_index"] = 9
        with self.assertRaises(InvalidData):
            await self.ingest(payload)

    async def test_inbox_capacity_never_silently_drops_old_fill(self):
        for i in range(256):
            f = Fill(str(i), str(i), "A", "bid", D(1), D(".5"), D(0))
            await self.writer.stage_fill(f, owner=0, now=NOW)
        with self.assertRaises(InvalidData):
            await self.writer.stage_fill(replace(f, trade_id="overflow"), owner=0, now=NOW)
        db = Ledger(self.path)
        try:
            self.assertEqual(db.connection.execute("SELECT COUNT(*) FROM pending_fills").fetchone()[0], 256)
        finally:
            db.close()

    async def test_engine_queue_overflow_retains_both_staged_fills(self):
        await self.connected()
        self.runtime.engine.capacity = 1
        spec = next(s for s in self.runtime.specs if s.name == "account")
        await self.runtime._consume(spec, event("a"), 1, set())
        with self.assertRaises(InvalidData):
            await self.runtime._consume(spec, event("b"), 1, set())
        self.assertTrue(self.runtime.engine.failed)
        self.assertEqual(len(await self.writer.pending_fills(0)), 2)

    async def test_run_starts_recovery_then_does_not_poll_healthy_streams(self):
        task = await self.launch()
        await self.eventually(lambda: self.runtime.recovery_state == "repaired_entries_blocked")
        calls = len(self.reads.calls)
        await asyncio.sleep(.03)
        self.assertEqual(len(self.reads.calls), calls)
        self.assertFalse(self.runtime.entry_allowed)
        self.runtime.stop()
        await task
        self.assertTrue(all(r.closed for group in self.connections.values() for r in group))
        self.assertTrue(all(state == "stopped" for state in self.runtime.reader_states.values()))

    async def test_account_reconnect_does_not_restart_book_readers(self):
        await self.launch()
        await self.eventually(lambda: self.runtime.recovery_passes == 1)
        await self.connections["account"][0].queue.put(OSError("offline"))
        await self.eventually(lambda: len(self.connections["account"]) == 2)
        await self.eventually(lambda: self.runtime.recovery_passes == 2)
        self.assertTrue(all(len(group) == 1 for name, group in self.connections.items() if name != "account"))
        self.assertEqual(self.runtime.account.generation, 2)

    async def test_book_sequence_loss_reconnects_only_affected_shard(self):
        await self.launch()
        name = self.runtime.engine.market_shard["A"]
        reader = self.connections[name][0]
        await reader.queue.put(snapshot())
        await self.eventually(lambda: "A" in self.evaluated)
        bad = dict(type="orderbook_delta", sid=1, seq=9, msg=dict(market_ticker="A", side="yes",
                   price_dollars=".4", delta_fp="1"))
        await reader.queue.put(bad)
        await self.eventually(lambda: len(self.connections[name]) == 2)
        self.assertEqual(len(self.connections["account"]), 1)
        self.assertFalse(self.runtime.engine.shards[name].books)

    async def test_recovery_network_wait_does_not_block_book_or_deadline(self):
        hold = asyncio.Event()
        async def blocked(name):
            await hold.wait()
        self.reads.before_collect = blocked
        await self.launch()
        name = self.runtime.engine.market_shard["A"]
        self.runtime.engine.schedule("A", self.runtime.clock())
        await self.connections[name][0].queue.put(snapshot())
        await self.eventually(lambda: self.evaluated and self.deadlines)
        self.assertEqual(self.runtime.recovery_state, "recovering")
        hold.set()

    async def test_connection_attempt_rounds_persist_with_capped_backoff(self):
        await self.launch()
        for number in range(3):
            await self.eventually(lambda: len(self.connections["account"]) > number)
            await self.connections["account"][number].queue.put(OSError("offline"))
        await self.eventually(lambda: len(self.connections["account"]) == 4)
        self.assertGreaterEqual(self.runtime.connection_attempts["account"], 4)
        self.assertIn(1, self.delays)
        self.assertIn(2, self.delays)
        self.assertIn(30, self.delays)
        self.assertEqual(self.runtime.reader_retry_rounds['account'], 1)
        self.assertTrue(self.runtime.account.connected)

    async def test_only_a_stable_subscription_resets_consecutive_failures(self):
        task = await self.launch()
        self.runtime.reader_healthy_seconds = .02
        self.delays.clear()
        await asyncio.sleep(.05)
        await self.connections["account"][0].queue.put(OSError("stable disconnect"))
        await self.eventually(lambda: len(self.connections["account"]) == 2)
        await self.connections["account"][1].queue.put(OSError("rapid disconnect 1"))
        await self.eventually(lambda: len(self.connections["account"]) == 3)
        await self.connections["account"][2].queue.put(OSError("rapid disconnect 2"))
        await self.eventually(lambda: len(self.connections["account"]) == 4)
        self.assertNotIn(30, self.delays)
        self.assertEqual(self.runtime.reader_retry_rounds["account"], 0)
        self.runtime.stop()
        await task

    async def test_missing_ack_times_out_and_exhausts_without_recovery_reads(self):
        class Silent(FakeReader):
            async def run(self, consume):
                try:
                    await asyncio.Event().wait()
                finally:
                    self.closed = True
        readers = []
        def factory(spec):
            readers.append(Silent(spec))
            return readers[-1]
        async def timeout(tasks, *, timeout, return_when):
            self.assertEqual(timeout, 10)
            await asyncio.sleep(0)
            return set(), set(tasks)
        self.runtime.reader_factory = factory
        spec = next(s for s in self.runtime.specs if s.name == "account")
        with patch("kalshi_bot.runtime.asyncio.wait", side_effect=timeout):
            await self.runtime._connection_round(spec)
        self.assertEqual(len(readers), 3)
        self.assertTrue(all(r.closed for r in readers))
        self.assertEqual(self.reads.calls, [])
        self.assertFalse(self.runtime.account_subscribed)

    async def test_order_lookup_budget_shared_across_recovery_phases(self):
        from kalshi_bot.runtime import RecoveryReads
        self.reads.orders = {"o": wire_order()}
        limited = RecoveryReads(self.reads)
        for _ in range(32):
            await limited.read("order", order_id="o", reason="reconcile")
        with self.assertRaisesRegex(InvalidData, "budget"):
            await limited.read("order", order_id="o", reason="reconcile")
        self.assertEqual(len(self.reads.calls), 32)

    async def test_recovery_attempts_bounded_on_unowned_fill(self):
        await self.connected()
        await self.ingest()
        task = asyncio.create_task(self.runtime._recover())
        self.tasks.append(task)
        await self.eventually(lambda: self.runtime.recovery_state == "blocked_retry_exhausted")
        self.assertEqual(self.runtime.recovery_attempts, 3)
        self.assertEqual(len(await self.writer.pending_fills(0)), 1)
        self.assertEqual(self.delays, [1, 2])

    async def test_transient_recovery_outage_retries_after_cooldown_and_repairs(self):
        await self.connected()
        calls = 0
        async def repair():
            nonlocal calls
            calls += 1
            if calls <= 3:
                raise ReadTransportUnavailable('synthetic transient outage')
            return True
        self.runtime.recover_once = repair
        self.runtime.request_recovery()
        task = asyncio.create_task(self.runtime._recover())
        self.tasks.append(task)
        await self.eventually(lambda: self.runtime.recovery_state == 'repaired_entries_blocked')
        self.assertEqual((calls, self.runtime.recovery_attempts), (4, 4))
        self.assertEqual(self.runtime.recovery_retry_rounds, 0)
        self.assertIn(30, self.delays)

    async def test_successful_drain_progress_gets_a_fresh_failure_budget(self):
        await self.connected()
        calls = 0
        async def progressive_repair():
            nonlocal calls
            calls += 1
            if calls <= 5:
                self.runtime.recovery_passes += 1
                self.runtime.request_recovery()
                return False
            return True
        self.runtime.recover_once = progressive_repair
        self.runtime.request_recovery()
        task = asyncio.create_task(self.runtime._recover())
        self.tasks.append(task)
        await self.eventually(
            lambda: self.runtime.recovery_state == 'repaired_entries_blocked')
        self.assertEqual(calls, 6)
        self.assertEqual(self.runtime.recovery_attempts, 6)
        self.assertEqual(self.runtime.recovery_passes, 5)
        self.assertNotEqual(self.runtime.recovery_state, 'blocked_retry_exhausted')
        self.assertEqual(self.delays, [])

    async def test_durable_cancel_during_incomplete_pass_is_progress(self):
        await self.connected()
        self.runtime.recovery_action_progress = 0
        calls = 0
        async def repair():
            nonlocal calls
            calls += 1
            if calls <= 5:
                self.runtime.recovery_action_progress += 1
                self.runtime.request_recovery('mutation_persisted')
                return False
            return True
        self.runtime.recover_once = repair
        self.runtime.request_recovery()
        self.tasks.append(asyncio.create_task(self.runtime._recover()))
        await self.eventually(lambda: self.runtime.recovery_state == 'repaired_entries_blocked')
        self.assertEqual(calls, 6)
        self.assertEqual(self.runtime.recovery_passes, 0)
        self.assertEqual(self.delays, [])

    async def test_cancel_progress_does_not_hide_subsequent_real_failure(self):
        await self.connected()
        self.runtime.recovery_action_progress = 0
        calls = 0
        async def repair():
            nonlocal calls
            calls += 1
            if calls == 1:
                self.runtime.recovery_action_progress += 1
                self.runtime.request_recovery('mutation_persisted')
            return False
        self.runtime.recover_once = repair
        self.runtime.request_recovery()
        self.tasks.append(asyncio.create_task(self.runtime._recover()))
        await self.eventually(lambda: self.runtime.recovery_state == 'blocked_retry_exhausted')
        self.assertEqual(calls, 4)
        self.assertEqual(self.delays, [1, 2])

    async def test_source_notifications_alone_do_not_reset_failure_budget(self):
        await self.connected()
        async def repair():
            self.runtime.request_recovery('mutation_observed')
            return False
        self.runtime.recover_once = repair
        self.runtime.request_recovery()
        self.tasks.append(asyncio.create_task(self.runtime._recover()))
        await self.eventually(lambda: self.runtime.recovery_state == 'blocked_retry_exhausted')
        self.assertEqual(self.runtime.recovery_attempts, 3)

    async def test_successful_recovery_wakes_reward_reflection(self):
        await self.connected()
        calls = []
        self.runtime.rewards = type('Rewards', (), {
            'request_reflection': lambda _self: calls.append('reflection')})()
        self.runtime.recover_once = lambda: asyncio.sleep(0, result=True)
        self.runtime.request_recovery()
        task = asyncio.create_task(self.runtime._recover())
        self.tasks.append(task)
        await self.eventually(
            lambda: self.runtime.recovery_state == 'repaired_entries_blocked')
        self.assertEqual(calls, ['reflection'])

    async def test_coalesces_many_recovery_requests(self):
        await self.connected()
        for _ in range(1000):
            self.runtime.request_recovery()
        task = asyncio.create_task(self.runtime._recover())
        self.tasks.append(task)
        await self.eventually(lambda: self.runtime.recovery_state == "repaired_entries_blocked")
        self.assertEqual(self.runtime.recovery_attempts, 1)

    async def test_old_account_epoch_frame_cannot_revoke_or_enqueue_current(self):
        await self.connected()
        spec = next(s for s in self.runtime.specs if s.name == "account")
        revision = self.runtime.account.revision
        await self.runtime._consume(spec, event(), 0, set())
        self.assertEqual(self.runtime.account.revision, revision)
        self.assertEqual(self.runtime.engine.backlog, 0)

    async def test_cancel_runtime_joins_readers_and_retains_durable_inbox(self):
        task = await self.launch()
        await self.connections["account"][0].queue.put(event())
        await self.eventually(lambda: self.runtime.recovery_attempts >= 1)
        # Stage explicitly to avoid relying on whether transport dispatch won cancellation.
        await self.runtime._stage(event())
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        self.assertFalse(self.runtime.running)
        self.assertTrue(all(r.closed for group in self.connections.values() for r in group))
        self.assertEqual(len(await self.writer.pending_fills(0)), 1)

    async def test_runtime_is_single_use(self):
        task = await self.launch()
        self.runtime.stop()
        await task
        with self.assertRaises(InvalidData):
            await self.runtime.run()

    async def test_wrong_ack_does_not_claim_subscribed(self):
        await self.connected()
        spec = next(s for s in self.runtime.specs if s.name == "account")
        with self.assertRaises(InvalidData):
            await self.runtime._consume(spec, dict(type="subscribed", id=2,
                msg=dict(channel="fill", sid=1)), 1, set())

    async def test_stale_ack_cannot_mark_new_account_subscribed(self):
        await self.connected()
        self.runtime.account_subscribed = False
        spec = next(s for s in self.runtime.specs if s.name == "account")
        acknowledged = set()
        for channel in spec.channels:
            await self.runtime._consume(spec, dict(type="subscribed", id=1,
                msg=dict(channel=channel, sid=1)), 0, acknowledged)
        self.assertFalse(self.runtime.account_subscribed)
        self.assertFalse(self.runtime.recovery_requested.is_set())

    async def test_partial_subscription_does_not_start_account_recovery(self):
        await self.connected()
        self.runtime.account_subscribed = False
        spec = next(s for s in self.runtime.specs if s.name == "account")
        await self.runtime._consume(spec, dict(type="subscribed", id=1,
            msg=dict(channel="fill", sid=1)), 1, set())
        self.assertFalse(self.runtime.account_subscribed)
        self.assertFalse(self.runtime.recovery_requested.is_set())


class InboxUnitTests(unittest.TestCase):
    def test_precision_enrichment_retains_first_seen_and_unknown_scope(self):
        from kalshi_bot.inbox import stage, pending
        db = Ledger(":memory:")
        try:
            f = Fill("t", "o", "A", "bid", D(1), D(".5"), D(0), 1000000, 1000000)
            stage(db, f, 0, None, None, EXEC)
            stage(db, replace(f, executed_us=1001000, execution_precision_us=1000), 0, 0, 2, NOW)
            item = pending(db, 0)[0]
            self.assertEqual((item.fill.executed_us, item.first_seen_at, item.scope, item.exchange_index),
                             (1001000, EXEC, 0, 2))
        finally:
            db.close()

    def test_conflicting_execution_timestamp_retains_original(self):
        from kalshi_bot.inbox import stage, pending
        db = Ledger(":memory:")
        try:
            f = Fill("t", "o", "A", "bid", D(1), D(".5"), D(0), 1000000)
            stage(db, f, 0, None, None, NOW)
            with self.assertRaises(InvalidData):
                stage(db, replace(f, executed_us=2000000), 0, None, None, NOW)
            self.assertEqual(pending(db, 0)[0].fill.executed_us, 1000000)
        finally:
            db.close()
