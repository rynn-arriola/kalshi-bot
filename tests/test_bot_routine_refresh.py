"""Routine refresh through real owners; temporary ledgers, no network."""
import asyncio
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from kalshi_bot.rest import PageSet, ReadResult
from kalshi_bot.runtime import RecoveryRuntime
from kalshi_bot.orders import OrderUpdate
from tests import test_bot_account_release as baseline


class RoutineRefreshTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = baseline.AccountReleaseTests.asyncSetUp
    asyncTearDown = baseline.AccountReleaseTests.asyncTearDown
    open_epoch = baseline.AccountReleaseTests.open_epoch
    refresh = baseline.AccountReleaseTests.refresh
    reserve = baseline.AccountReleaseTests.reserve

    async def runtime(self):
        class Reads(baseline.Reads):
            async def read(inner, name, **kwargs):
                inner.calls.append(name)
                if name == 'cutoff':
                    return ReadResult(dict(trades_created_ts=baseline.BOUNDARY.isoformat()), 1)
                return await super().read(name, **kwargs)

            async def collect(inner, name, **kwargs):
                inner.calls.append(name)
                if name == 'orders':
                    return PageSet(inner.orders, 1, 20)
                if name in {'positions', 'fills', 'historical_fills'}:
                    return PageSet((), 1, 20)
                return await super().collect(name, **kwargs)

        async def no_op(*args):
            pass
        reads = Reads()
        reads.calls, reads.orders = [], ()
        runtime = RecoveryRuntime(self.writer, reads, lambda spec: None,
            tickers=('A',), subaccount=0, history_start=baseline.BOUNDARY,
            now=lambda: self.now, clock=lambda: self.tick,
            evaluate=no_op, deadline_handler=no_op, lifecycle_handler=no_op,
            accounting_boundary=baseline.BOUNDARY, broad_discovery=True)
        runtime.account = self.account
        runtime._epoch = self.epoch
        runtime._persisted_epoch_gaps = 0
        runtime.account_subscribed = True
        runtime.engine.begin_private_epoch()
        self.assertTrue(await runtime.recover_once())
        runtime.recovery_state = 'repaired_entries_blocked'
        return runtime

    def advance(self, seconds=3):
        self.now += timedelta(seconds=seconds)
        self.tick += seconds

    async def test_renews_real_lease_before_cap_and_can_fund_refill(self):
        runtime = await self.runtime()
        first = runtime._current_routine_proof()
        self.assertIsNotNone(first)  # No ranking and zero orders is supported.
        old = self.writer._accounting_lease
        for seconds in (3, 3, 17):
            self.advance(seconds)
            runtime.reads.calls.clear()
            self.assertTrue(await runtime._refresh_routine_account())
            self.assertFalse(runtime.recovery_requested.is_set())
            self.assertTrue(self.writer._accounting_lease.fence.current())
            self.assertEqual(runtime.reads.calls.count('orders'), 1)
            self.assertEqual(runtime.reads.calls.count('positions'), 1)
            self.assertEqual(runtime.reads.calls.count('deposits'), 1)
        self.assertFalse(old.fence.current())
        self.assertEqual(runtime.routine_refresh_completed, 3)
        self.assertEqual(len(runtime._routine_account_proof.receipt_ids), len(first.receipt_ids)+3)
        self.assertTrue((await self.reserve('refill')).reserved)

    async def test_snapshot_and_accounting_sources_start_concurrently(self):
        runtime = await self.runtime()
        self.advance()
        expected = {'orders', 'positions', 'balance', 'settlements',
                    'subaccount_transfers', 'intra_exchange_transfers',
                    'deposits', 'withdrawals'}
        started = set()
        starts = {}
        all_started = asyncio.Event()
        original_read, original_collect = runtime.reads.read, runtime.reads.collect

        async def wait_for_peers(name, invoke, **kwargs):
            if name in expected:
                started.add(name)
                starts[name] = starts.get(name, 0)+1
                if expected <= started:
                    all_started.set()
                await all_started.wait()
            return await invoke(name, **kwargs)

        async def read(name, **kwargs):
            return await wait_for_peers(name, original_read, **kwargs)

        async def collect(name, **kwargs):
            return await wait_for_peers(name, original_collect, **kwargs)

        runtime.reads.read, runtime.reads.collect = read, collect
        self.assertTrue(await asyncio.wait_for(runtime._refresh_routine_account(), 2))
        self.assertEqual(started, expected)
        # The account balance is also the cash snapshot; do not spend a second
        # serialized request after the source-fenced snapshot completes.
        self.assertEqual(starts['balance'], 1)
        self.assertFalse(runtime.recovery_requested.is_set())

    async def test_changed_cash_private_revision_or_writer_escalates(self):
        runtime = await self.runtime()
        for kind in ('cash', 'private', 'writer'):
            with self.subTest(kind=kind):
                runtime.recovery_requested.clear()
                self.assertTrue(await runtime.recover_once())
                self.advance()
                original = runtime.reads.read
                changed = False
                async def racing(name, **kwargs):
                    nonlocal changed
                    result = await original(name, **kwargs)
                    if name == 'balance' and not changed:
                        changed = True
                        if kind == 'private':
                            runtime.account._invalidate()
                        elif kind == 'writer':
                            await self.writer.observe(self.now)
                        else:
                            result = ReadResult(dict(result.payload, balance_dollars='499.99'), 1)
                    return result
                runtime.reads.read = racing
                self.assertFalse(await runtime._refresh_routine_account())
                self.assertTrue(runtime.recovery_requested.is_set())
                self.assertIsNone(runtime._routine_account_proof)
                self.assertFalse(self.writer._accounting_lease is not None
                    and self.writer._accounting_lease.fence.current())
                runtime.reads.read = original

    async def test_history_chain_is_bounded_and_source_fenced(self):
        runtime = await self.runtime()
        proof = runtime._routine_account_proof
        runtime._record_routine_proof(proof.receipt_ids*128, runtime.last_reports[0])
        self.assertIsNone(runtime._routine_account_proof)
        runtime._routine_account_proof = proof
        runtime.ingress_revision += 1
        self.assertIsNone(runtime._current_routine_proof())

    async def test_nonempty_or_omitted_tail_escalates(self):
        runtime = await self.runtime()
        for omitted in (False, True):
            with self.subTest(omitted=omitted):
                runtime.recovery_requested.clear()
                self.assertTrue(await runtime.recover_once())
                history = runtime.last_reports[0]
                self.advance()
                fake = (replace(history, enumeration=replace(history.enumeration,
                    remembered_count=history.enumeration.row_count+1)) if omitted else None)
                with patch.object(runtime.account, 'extend_empty_history', AsyncMock(return_value=fake)):
                    self.assertFalse(await runtime._refresh_routine_account())
                self.assertTrue(runtime.recovery_requested.is_set())

    async def test_timer_routes_to_renewal_without_full_recovery(self):
        runtime = await self.runtime()
        self.advance()
        original = runtime._refresh_routine_account
        async def once():
            value = await original()
            runtime.stop_requested.set()
            return value
        with patch.object(runtime, '_refresh_routine_account', once):
            await asyncio.wait_for(runtime._live_refresh(), 2)
        self.assertEqual(runtime.routine_refresh_completed, 1)
        self.assertFalse(runtime.recovery_requested.is_set())

    async def test_full_cap_timer_renews_accounting_instead_of_snapshot_only(self):
        runtime = await self.runtime()
        old = self.writer._accounting_lease
        self.advance()
        original = runtime._refresh_routine_account
        async def once():
            result = await original()
            runtime.stop_requested.set()
            return result
        # Full-cap scope is a scheduling hint. It cannot take precedence over
        # renewal of the real accounting lease created by the fixture owners.
        with (patch.object(runtime, '_current_steady_account_scope', return_value=frozenset(('A',))),
              patch.object(runtime, '_refresh_steady_account',
                  AsyncMock(side_effect=AssertionError('snapshot-only path revokes lease'))),
              patch.object(runtime, '_refresh_routine_account', once)):
            await asyncio.wait_for(runtime._live_refresh(), 2)
        self.assertEqual(runtime.routine_refresh_completed, 1)
        self.assertFalse(runtime.recovery_requested.is_set())
        self.assertIsNot(self.writer._accounting_lease, old)

    async def test_timer_counts_snapshot_read_time_not_only_publication_age(self):
        runtime = await self.runtime()
        # The report can be newly published after two seconds spent reading.
        # Its accounting fence still starts at read start, not publication.
        runtime.account._report_monotonic = self.tick-2
        self.advance(1)
        async def once():
            runtime.stop_requested.set()
            return True
        with patch.object(runtime, '_refresh_routine_account', AsyncMock(side_effect=once)) as refresh:
            await asyncio.wait_for(runtime._live_refresh(), 2)
            refresh.assert_awaited_once()

    async def test_paused_slow_recovery_leaves_flat_report_for_supervisor(self):
        from kalshi_bot.live import verified_flat
        runtime = await self.runtime()
        runtime.live_session = SimpleNamespace(entries_paused=True)
        runtime.account._report_monotonic = self.tick-4.5
        task = asyncio.create_task(runtime._live_refresh())
        try:
            await asyncio.sleep(.02)
            self.assertEqual(runtime.routine_refresh_attempts, 0)
            self.assertFalse(runtime.recovery_requested.is_set())
            self.assertTrue(await verified_flat(runtime))
        finally:
            runtime.stop_requested.set()
            await task

    async def test_full_recovery_collects_financial_sources_with_final_snapshot(self):
        runtime = await self.runtime()
        original = runtime.account.reconcile
        calls = 0
        async def snapshot(*args, **kwargs):
            nonlocal calls
            calls += 1
            # Time advances through the first repair stages so the elapsed
            # tail and final source refresh are required, as in production.
            self.advance(.1)
            return await original(*args, **kwargs)
        with (patch.object(runtime.account, 'reconcile', snapshot),
              patch.object(runtime.account, 'reconcile_accounting',
                  AsyncMock(side_effect=AssertionError('serial financial reads')))):
            self.assertTrue(await runtime.recover_once())
        # D-133/D-134: the unchanged first snapshot is re-audited; the tail
        # snapshot still collects every financial source concurrently.
        self.assertEqual(calls, 2)
        self.assertEqual(runtime.recovery_final_reaudits, 1)
        self.assertTrue(runtime.accounting_result.released)

    async def test_slow_snapshot_fails_freshness_without_widening_lease(self):
        runtime = await self.runtime()
        self.advance()
        original = runtime.reads.collect
        async def slow(name, **kwargs):
            if name == 'positions':
                self.advance(17)
            return await original(name, **kwargs)
        runtime.reads.collect = slow
        self.assertFalse(await runtime._refresh_routine_account())
        self.assertTrue(runtime.recovery_requested.is_set())
        self.assertFalse(self.writer._accounting_lease is not None
            and self.writer._accounting_lease.fence.current())

    async def test_real_owned_orders_renew_at_two_twenty_eight_and_full_cap(self):
        runtime = await self.runtime()
        for index in range(30):
            client, order_id = f'owned-{index}', f'order-{index}'
            req = dict(baseline.request(client), price='0.01')
            reserved = await self.reserve(client, req=req)
            self.assertTrue(reserved.reserved, reserved.blockers)
            prepared = reserved.receipt
            self.assertTrue((await self.writer.begin_send(prepared)).dispatch_allowed)
            await self.writer.record_outcome('ack', prepared, dict(order_id=order_id,
                client_order_id=client, fill_count='0', remaining_count='10', ts_ms=1), self.now)
            await self.writer.order(OrderUpdate(order_id, client, 'A', 'bid', D('.01'),
                D(10), D(0), D(10), 'resting', 0, 1, 1), self.now)
            runtime.reads.orders += (dict(order_id=order_id, client_order_id=client,
                ticker='A', book_side='bid', yes_price_dollars='.01',
                initial_count_fp='10', fill_count_fp='0', remaining_count_fp='10',
                status='resting', subaccount=0, exchange_index=1,
                last_update_time='1970-01-01T00:00:00.000001Z'),)
            runtime.request_recovery()
            runtime.recovery_requested.clear()
            self.assertTrue(await runtime.recover_once())
            if index in (1, 27, 29):
                for reason in ('priority_capacity_met', 'coverage_complete'):
                    runtime.selection = SimpleNamespace(initial_ranking=SimpleNamespace(reason=reason))
                    self.advance()
                    self.assertTrue(await runtime._refresh_routine_account())
                    self.assertEqual(len(runtime.account.report.snapshot.orders), index+1)
                    self.assertIsNotNone(runtime._current_routine_proof())
        self.assertEqual(runtime._current_steady_account_scope(), frozenset(('A',)))
        self.advance()
        original = runtime._refresh_routine_account
        calls = 0
        async def twice():
            nonlocal calls
            self.assertTrue(await original())
            self.assertTrue(self.writer._accounting_lease.fence.current())
            calls += 1
            self.advance(3 if calls == 1 else 0)
            if calls == 2:
                runtime.stop_requested.set()
            return True
        with (patch.object(runtime, '_refresh_routine_account', twice),
              patch.object(runtime, '_refresh_steady_account',
                  AsyncMock(side_effect=AssertionError('lost full-cap renewal')))):
            await asyncio.wait_for(runtime._live_refresh(), 3)
        self.assertEqual(calls, 2)
        self.assertFalse(runtime.recovery_requested.is_set())

    async def test_new_funding_cannot_renew(self):
        runtime = await self.runtime()
        runtime.reads.deposits = (dict(self.deposit, id='new-deposit',
            created_ts=int(self.now.timestamp())),)
        self.advance()
        self.assertFalse(await runtime._refresh_routine_account())
        self.assertTrue(runtime.recovery_requested.is_set())
        self.assertFalse(self.writer._accounting_lease is not None
            and self.writer._accounting_lease.fence.current())

    async def test_slow_full_repair_then_routine_does_not_replay_startup(self):
        runtime = await self.runtime()
        original = runtime.account.reconcile
        calls = 0
        async def slow(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                self.advance(17)
            return await original(*args, **kwargs)
        with patch.object(runtime.account, 'reconcile', slow):
            self.assertTrue(await runtime.recover_once())
        self.assertEqual(calls, 3)
        self.advance()
        with patch.object(runtime, 'recover_once', AsyncMock(side_effect=AssertionError('full replay'))):
            self.assertTrue(await runtime._refresh_routine_account())
        self.assertTrue(self.writer._accounting_lease.fence.current())

    async def test_stop_during_cash_reads_revokes_renewal(self):
        runtime = await self.runtime()
        self.advance()
        original = runtime.reads.collect
        async def stop(name, **kwargs):
            result = await original(name, **kwargs)
            if name == 'deposits':
                runtime.stop()
            return result
        runtime.reads.collect = stop
        self.assertFalse(await runtime._refresh_routine_account())
        self.assertTrue(runtime.stop_requested.is_set())
        self.assertFalse(self.writer._accounting_lease is not None
            and self.writer._accounting_lease.fence.current())

    async def test_cancellation_revokes_and_requests_recovery(self):
        runtime = await self.runtime()
        self.advance()
        waiting = asyncio.Event()
        async def wait(*args, **kwargs):
            waiting.set()
            await asyncio.Event().wait()
        with patch.object(runtime.account, 'extend_empty_history', wait):
            task = asyncio.create_task(runtime._refresh_routine_account())
            await waiting.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertTrue(runtime.recovery_requested.is_set())
        self.assertFalse(runtime.recovery_lock.locked())
        self.assertFalse(self.writer._accounting_lease is not None
            and self.writer._accounting_lease.fence.current())

    async def test_recovery_waits_for_refresh_owner_without_spending_retries(self):
        runtime = await self.runtime()
        await runtime.recovery_lock.acquire()
        held = True
        runtime.request_recovery()
        task = asyncio.create_task(runtime._recover())
        try:
            await asyncio.sleep(.01)
            self.assertEqual(runtime.recovery_attempts, 0)
            runtime.recovery_lock.release()
            held = False
            async with asyncio.timeout(3):
                while (runtime.recovery_attempts == 0
                        or runtime.recovery_state != 'repaired_entries_blocked'):
                    if task.done(): task.result()
                    await asyncio.sleep(.001)
            self.assertEqual(runtime.recovery_attempts, 1)
        finally:
            if held:
                runtime.recovery_lock.release()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
