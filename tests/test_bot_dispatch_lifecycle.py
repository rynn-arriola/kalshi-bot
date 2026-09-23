"""Offline task supervision with disposable ledger and synthetic transport."""
import asyncio
from contextlib import closing
from pathlib import Path
import sqlite3
import unittest

from kalshi_bot.dispatch import PASSIVE_REDUCER, SAFETY_CANCEL
from kalshi_bot.dispatch_supervisor import DispatchSupervisor
from kalshi_bot.mutation_outcomes import MutationHTTPFailure
from kalshi_bot.values import InvalidData
from kalshi_bot.writer import LedgerWriter
import test_bot_dispatch_sources as fixtures


async def until(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(.001)


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.f = fixtures.DispatchSourceTests()
        await self.f.asyncSetUp()
        self.service = self.f.runtime.attach_dispatch(self.f.source, self.f.dispatcher,
                                                      offline_fixture=True)
        self.tasks = []
        self.release = asyncio.Event()
        self.closed_peers = []

    async def asyncTearDown(self):
        self.release.set()
        self.f.runtime.stop()
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await self.f.asyncTearDown()

    async def start(self, *, runtime=False):
        if runtime:
            # Park external readers/recovery at injected boundaries. The actual
            # runtime, engine, writer, source, service and dispatcher still run.
            async def connection(spec):
                try:
                    await asyncio.Event().wait()
                finally:
                    self.closed_peers.append(spec.name)
            async def recovery():
                await asyncio.Event().wait()
            self.f.runtime._connection = connection
            self.f.runtime._recover = recovery
            task = asyncio.create_task(self.f.runtime.run())
        else:
            task = asyncio.create_task(self.service.run())
        self.tasks.append(task)
        await until(lambda: self.service.running or task.done())
        if task.done():
            task.result()
        await self.f.ready()
        return task

    def request(self):
        return self.f.runtime.request_dispatch('A', PASSIVE_REDUCER)

    async def held_transport(self):
        entered = asyncio.Event()
        original = self.service.dispatcher.executor.invoke.invoke
        async def held(kind, request):
            entered.set()
            await self.release.wait()
            return await original(kind, request)
        self.service.dispatcher.executor.invoke.invoke = held
        self.request()
        await asyncio.wait_for(entered.wait(), 2)

    async def test_idle_no_poll_then_single_ack(self):
        task = await self.start()
        turns = self.service.turns
        await asyncio.sleep(.05)
        self.assertEqual(self.service.turns, turns)
        self.assertTrue(self.request())
        self.assertFalse(self.request())
        await until(lambda: len(self.f.calls) == 1 and self.service.last_state == 'IDLE')
        self.assertEqual((await self.f.writer.mutations())[-1]['phase'], 'ACK')
        retained = self.service.status()['last_outcome']
        self.assertEqual(retained['ticker'], 'A')
        self.assertNotEqual(retained['state'], 'IDLE')
        self.assertTrue(retained['historical_only'])
        self.service.stop()
        await task
        self.assertFalse(self.service.running)

    async def test_runtime_stop_joins_outcome_before_reader_and_writer_release(self):
        task = await self.start(runtime=True)
        await self.held_transport()
        self.f.runtime.stop()
        self.assertFalse(self.request())
        await asyncio.sleep(.02)
        self.assertFalse(task.done())
        self.assertFalse(self.closed_peers)
        self.assertEqual((await self.f.writer.mutations())[-1]['phase'], 'SENDING')
        self.release.set()
        await task
        self.assertEqual((await self.f.writer.mutations())[-1]['phase'], 'ACK')
        self.assertEqual(len(self.closed_peers), len(self.f.runtime.specs))
        self.assertFalse(self.f.writer.failed)
        self.assertFalse(self.f.runtime.running)
        self.assertFalse(self.service.running)

    async def test_repeated_runtime_cancellation_retains_inflight_outcome(self):
        task = await self.start(runtime=True)
        await self.held_transport()
        task.cancel()
        await until(lambda: self.service.stopping)
        task.cancel()
        await asyncio.sleep(.01)
        self.assertFalse(task.done())
        self.assertFalse(self.request())
        self.release.set()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual((await self.f.writer.mutations())[-1]['phase'], 'ACK')
        self.assertFalse(self.service.running)

    async def test_runtime_fault_stops_dispatch_and_drains_accepted_outcome(self):
        task = await self.start(runtime=True)
        await self.held_transport()
        self.f.runtime.engine.failed = True
        self.f.runtime.engine.stop()
        await until(lambda: self.service.stopping)
        self.assertFalse(task.done())
        self.release.set()
        await task
        self.assertEqual((await self.f.writer.mutations())[-1]['phase'], 'ACK')

    async def test_dispatch_failure_propagates_and_stops_runtime(self):
        task = await self.start(runtime=True)
        async def fail(*args):
            raise MutationHTTPFailure(429)
        self.f.dispatcher.executor.invoke.invoke = fail
        self.request()
        with self.assertRaises(MutationHTTPFailure):
            await task
        self.assertTrue(self.service.failed)
        self.assertTrue(self.f.runtime.stop_requested.is_set())
        self.assertEqual((await self.f.writer.mutations())[-1]['phase'], 'UNKNOWN')
        self.assertFalse(self.request())
        self.assertEqual(len(self.closed_peers), len(self.f.runtime.specs))

    async def test_create_400_rejection_does_not_crash_runtime(self):
        task = await self.start(runtime=True)
        async def fail(*args):
            raise MutationHTTPFailure(400)
        self.f.dispatcher.executor.invoke.invoke = fail
        self.request()
        await until(lambda: self.service.last_outcome is not None
                    and self.service.last_outcome['state'] == 'REJECTED')
        self.assertFalse(task.done())
        self.assertFalse(self.service.failed)
        self.assertFalse(self.f.dispatcher.executor.failed)
        self.assertEqual((await self.f.writer.mutations())[-1]['phase'], 'REJECTED')
        self.f.runtime.stop()
        await task

    async def test_late_failure_during_stop_is_not_reported_healthy(self):
        task = await self.start(runtime=True)
        entered = asyncio.Event()
        async def fail(*args):
            entered.set()
            await self.release.wait()
            raise MutationHTTPFailure(503)
        self.f.dispatcher.executor.invoke.invoke = fail
        self.request()
        await asyncio.wait_for(entered.wait(), 2)
        self.f.runtime.stop()
        self.release.set()
        with self.assertRaises(InvalidData):
            await task
        self.assertTrue(self.service.failed)
        self.assertEqual((await self.f.writer.mutations())[-1]['phase'], 'UNKNOWN')

    async def test_cancelled_runtime_with_late_error_does_not_leak_loop_logging(self):
        task = await self.start(runtime=True)
        entered = asyncio.Event()
        async def fail(*args):
            entered.set()
            await self.release.wait()
            raise MutationHTTPFailure(429)
        self.f.dispatcher.executor.invoke.invoke = fail
        loop = asyncio.get_running_loop()
        previous, errors = loop.get_exception_handler(), []
        loop.set_exception_handler(lambda _loop, context: errors.append(context))
        self.addCleanup(loop.set_exception_handler, previous)
        self.request()
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        await until(lambda: self.service.stopping)
        task.cancel()
        self.release.set()
        with self.assertRaises((InvalidData, asyncio.CancelledError)):
            await task
        await asyncio.sleep(0)
        self.assertFalse(errors)
        self.assertTrue(self.service.failed)
        self.assertEqual((await self.f.writer.mutations())[-1]['phase'], 'UNKNOWN')

    async def test_stop_during_prepare_aborts_unsent_receipt(self):
        task = await self.start(runtime=True)
        original = self.f.writer.prepare_reduction
        async def prepare(*args, **kwargs):
            result = await original(*args, **kwargs)
            self.f.runtime.stop()
            return result
        self.f.writer.prepare_reduction = prepare
        self.request()
        await task
        self.assertFalse(self.f.calls)
        self.assertEqual((await self.f.writer.mutations())[-1]['phase'], 'NOT_SENT')

    async def test_stop_during_sending_aborts_proven_unsent_without_transport(self):
        task = await self.start(runtime=True)
        original = self.f.writer.begin_send
        async def sending(*args):
            result = await original(*args)
            self.f.runtime.stop()
            return result
        self.f.writer.begin_send = sending
        self.request()
        await task
        self.assertFalse(self.f.calls)
        self.assertEqual((await self.f.writer.mutations())[-1]['phase'], 'NOT_SENT')

    async def test_stop_during_outcome_commit_keeps_writer_open(self):
        task = await self.start(runtime=True)
        entered = asyncio.Event()
        original = self.f.writer.record_outcome
        async def record(*args):
            entered.set()
            await self.release.wait()
            return await original(*args)
        self.f.writer.record_outcome = record
        self.request()
        await asyncio.wait_for(entered.wait(), 2)
        self.f.runtime.stop()
        await asyncio.sleep(.01)
        self.assertFalse(task.done())
        self.release.set()
        await task
        self.assertEqual((await self.f.writer.mutations())[-1]['phase'], 'ACK')

    async def test_writer_persistence_fault_blocks_shutdown_success(self):
        task = await self.start(runtime=True)
        async def broken(*args):
            raise OSError('synthetic failed persistence')
        self.f.writer.record_outcome = broken
        self.request()
        with self.assertRaises(OSError):
            await task
        self.assertTrue(self.service.failed)
        self.assertEqual((await self.f.writer.mutations())[-1]['phase'], 'SENDING')

    async def test_quota_wait_does_not_spin_and_wakes_on_explicit_change(self):
        task = await self.start()
        from test_bot_write_budget import now
        self.f.budget.pause_429(shard=0, seconds=60, now=now(1))
        self.request()
        await until(lambda: self.service.last_state == 'WAITING')
        turns = self.service.turns
        for _ in range(10000):
            self.assertFalse(self.request())
        await asyncio.sleep(.04)
        self.assertEqual(self.service.turns, turns)
        self.assertFalse(self.f.calls)
        pair = lambda: now(62)
        self.f.dispatcher.clock_pair = pair
        self.f.dispatcher.executor.invoke.clock_pair = pair
        self.service.changed()
        await until(lambda: self.service.last_state == 'IDLE' and len(self.f.calls) == 1)
        self.assertEqual((await self.f.writer.mutations())[-1]['phase'], 'ACK')
        self.f.runtime.stop()
        await task

    async def test_none_delay_waits_for_notification_not_poll(self):
        task = await self.start()
        self.f.budget.try_reserve = lambda *a, **k: None
        self.f.budget.ready_delay = lambda *a, **k: None
        self.request()
        await until(lambda: self.service.last_state == 'WAITING')
        turns = self.service.turns
        await asyncio.sleep(.03)
        self.assertEqual(self.service.turns, turns)
        self.service.changed()
        await until(lambda: self.service.turns > turns)
        self.service.stop()
        await task

    async def test_queue_priority_is_preserved(self):
        # Only ordering is inspected here; actual cancel/reducer eligibility is
        # covered by source tests and rechecked again at dispatch.
        self.assertTrue(self.request())
        self.assertTrue(self.f.runtime.request_dispatch('B', SAFETY_CANCEL))
        self.assertEqual(self.f.dispatcher.status().queued[0], (SAFETY_CANCEL, 'B'))

    async def test_overflow_stops_supervision_without_background_exception_loss(self):
        task = await self.start()
        self.f.dispatcher.capacity = 1
        self.request()
        with self.assertRaises(InvalidData):
            self.f.runtime.request_dispatch('B', SAFETY_CANCEL)
        with self.assertRaises(InvalidData):
            await task
        self.assertTrue(self.service.failed)
        self.assertFalse(self.f.calls)

    async def test_closed_owner_cannot_restart_or_accept_work(self):
        task = await self.start()
        self.service.stop()
        await task
        self.assertFalse(self.request())
        with self.assertRaises(InvalidData):
            await self.service.run()
        with self.assertRaises(InvalidData):
            self.f.runtime.attach_dispatch(self.f.source, self.f.dispatcher, offline_fixture=True)

    async def test_stopped_before_first_service_turn_does_not_invoke(self):
        self.request()
        self.f.runtime.stop()
        await self.service.run()
        self.assertFalse(self.f.calls)
        self.assertFalse(self.service.running)
        with self.assertRaises(InvalidData):
            await self.service.run()

    async def test_unexpected_service_stop_is_not_ignored_as_reader_exhaustion(self):
        task = await self.start(runtime=True)
        self.service.stop()
        with self.assertRaisesRegex(InvalidData, 'ended without runtime stop'):
            await task
        self.assertTrue(self.f.runtime.stop_requested.is_set())

    async def test_cancelled_close_waits_for_owned_task(self):
        task = await self.start()
        await self.held_transport()
        close = asyncio.create_task(self.service.close())
        self.tasks.append(close)
        await until(lambda: self.service.stopping)
        close.cancel()
        await asyncio.sleep(.005)
        close.cancel()
        self.assertFalse(close.done())
        self.release.set()
        with self.assertRaises(asyncio.CancelledError):
            await close
        await task
        self.assertEqual((await self.f.writer.mutations())[-1]['phase'], 'ACK')

    async def test_invalid_wait_delay_fails_instead_of_busy_looping(self):
        task = await self.start()
        self.f.budget.try_reserve = lambda *a, **k: None
        self.f.budget.ready_delay = lambda *a, **k: float('nan')
        self.request()
        with self.assertRaisesRegex(InvalidData, 'wait delay'):
            await task
        self.assertTrue(self.service.failed)

    async def test_zero_wait_is_throttled_and_does_not_spin(self):
        task = await self.start()
        self.f.budget.try_reserve = lambda *a, **k: None
        self.f.budget.ready_delay = lambda *a, **k: 0.
        self.request()
        await until(lambda: self.service.last_state == 'WAITING')
        turns = self.service.turns
        await asyncio.sleep(.035)
        self.assertLess(self.service.turns-turns, 8)
        self.service.stop()
        await task

    async def test_unknown_survives_new_writer_without_replay(self):
        task = await self.start()
        async def fail(*args):
            raise MutationHTTPFailure(429)
        self.f.dispatcher.executor.invoke.invoke = fail
        self.request()
        with self.assertRaises(MutationHTTPFailure):
            await task
        await self.f.writer.close()
        path = Path(self.f.temp.name)/'fixture.db'
        writer = await LedgerWriter(path).start()
        try:
            self.assertEqual((await writer.mutations())[-1]['phase'], 'UNKNOWN')
            self.assertNotEqual(writer.epoch, self.f.writer.epoch)
            from datetime import timedelta
            from kalshi_bot.runtime import RecoveryRuntime
            from kalshi_bot.dispatch_sources import InventoryDispatchSource
            from test_bot_write_budget import budget, now
            async def ignore(*args):
                pass
            calls = []
            async def forbidden(*args):
                calls.append(args)
                raise AssertionError('restart must not replay')
            fresh = RecoveryRuntime(writer, None, None, tickers=('A', 'B'), subaccount=0,
                history_start=self.f.now-timedelta(hours=1), now=lambda: self.f.now,
                clock=lambda: self.f.mono, evaluate=ignore,
                deadline_handler=ignore, lifecycle_handler=ignore)
            source = InventoryDispatchSource(fresh, offline_fixture=True)
            dispatcher = source.dispatcher(budget(), invoke=forbidden, clock_pair=lambda: now(1))
            supervisor = fresh.attach_dispatch(source, dispatcher, offline_fixture=True)
            self.assertEqual(supervisor.status()['queued'], 0)
            # Even restored fresh account/book/terms evidence cannot replay the
            # unresolved command. This is stronger than merely lacking sources.
            from kalshi_bot.account import normalize_snapshot
            from test_bot_engine import snapshot
            fresh.account.connect_generation()
            fresh.engine.begin_private_epoch()
            for receipt in await writer.orders():
                fresh.account._store_order(receipt)
            evidence = normalize_snapshot((), (dict(ticker='A', exchange_index=0,
                position_fp='10', market_exposure_dollars='5'),),
                dict(balance_dollars='500', updated_ts=1), subaccount=0)
            await fresh.account.finish_reconciliation(
                fresh.account.begin_reconciliation(self.f.now), evidence, self.f.now)
            fresh.management.set_terms(self.f.runtime.management.terms['A'])
            for name, shard in fresh.engine.shards.items():
                generation = fresh.engine.begin_book_epoch(name)
                for seq, ticker in enumerate(sorted(shard.tickers), 1):
                    fresh.engine.submit_book(name, snapshot(ticker, seq), generation=generation)
            while fresh.engine.backlog:
                await fresh.engine.step()
            self.assertIsNotNone(fresh.account.current_report(self.f.now))
            runner = asyncio.create_task(supervisor.run())
            try:
                fresh.request_dispatch('A', PASSIVE_REDUCER)
                await until(lambda: supervisor.last_state == 'IDLE')
                self.assertFalse(calls)
                self.assertFalse(fresh.entry_allowed)
                self.assertEqual((await writer.mutations())[-1]['phase'], 'UNKNOWN')
            finally:
                supervisor.stop()
                await runner
            with closing(sqlite3.connect(path.as_uri()+'?mode=ro', uri=True)) as db:
                self.assertGreater(db.execute("SELECT count(*) FROM command_credits WHERE state='HELD'").fetchone()[0], 0)
        finally:
            await writer.close()
        self.assertFalse(self.request())


class AttachmentTests(unittest.IsolatedAsyncioTestCase):
    async def test_requires_explicit_matching_unused_owners(self):
        fixture = fixtures.DispatchSourceTests()
        await fixture.asyncSetUp()
        try:
            for flag in (False, None, 1):
                with self.assertRaises(InvalidData):
                    fixture.runtime.attach_dispatch(fixture.source, fixture.dispatcher,
                                                    offline_fixture=flag)
            with self.assertRaises(InvalidData):
                fixture.runtime.attach_dispatch(object(), fixture.dispatcher, offline_fixture=True)
            fixture.runtime.used = True
            with self.assertRaises(InvalidData):
                fixture.runtime.attach_dispatch(fixture.source, fixture.dispatcher, offline_fixture=True)
            fixture.runtime.used = False
            original = fixture.dispatcher.executor.after_outcome
            fixture.dispatcher.executor.after_outcome = None
            with self.assertRaises(InvalidData):
                DispatchSupervisor(fixture.source, fixture.dispatcher, offline_fixture=True)
            fixture.dispatcher.executor.after_outcome = original
            with self.assertRaises(InvalidData):
                fixture.runtime.request_dispatch('A', PASSIVE_REDUCER)
        finally:
            await fixture.asyncTearDown()
