"""Offline-only priority, durable handoff and recovery fixtures."""
import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from kalshi_bot.command_types import CommandDenied
from kalshi_bot.config import BotConfig
from kalshi_bot.dispatch import (DispatchCandidate, MutationDispatcher,
    SAFETY_CANCEL, PASSIVE_REDUCER, DUE_IOC)
from kalshi_bot.execution import InjectedExecutor
from kalshi_bot.ledger import Fill
from kalshi_bot.orders import OrderUpdate
from kalshi_bot.quota import QuotaUnavailable
from kalshi_bot.values import InvalidData
from kalshi_bot.write_budget import WriteBudget
from kalshi_bot.writer import LedgerWriter
from test_bot_write_budget import snapshot, now as budget_now
from test_bot_command_handoff import request as entry_request
from quota_dispatch_fixture import ObservedQuotaFixture


NOW = datetime(2026, 9, 21, 12, tzinfo=timezone.utc)


class DispatcherTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        self.writer = await LedgerWriter(Path(self.temp.name)/'dispatch.db').start()
        self.invoked = []
        async def invoke(kind, request):
            self.invoked.append((kind, request))
            if kind == 'cancel':
                return dict(order_id=request['order_id'], ts_ms=1, reduced_by='10')
            return dict(order_id='reducer-order', ts_ms=1, fill_count='0',
                        remaining_count=request['count'])
        self.executor = InjectedExecutor(self.writer, invoke=invoke,
            validate_proof=lambda *_: True, offline_fixture=True, now=lambda: NOW)
        self.clock = 1
        self.budget = WriteBudget(snapshot(rate=100, capacity=100),
            shards=(0, 1), now=budget_now(), offline_fixture=True)
        self.candidates = {}
        self.refresh_count = 0
        async def refresh(ticker, priority):
            self.refresh_count += 1
            return self.candidates.get((ticker, priority))
        self.dispatcher = MutationDispatcher(self.writer, self.executor, self.budget,
            refresh=refresh, clock_pair=lambda: budget_now(self.clock), now=lambda: NOW,
            offline_fixture=True)

    async def asyncTearDown(self):
        await self.dispatcher.close()
        await self.writer.close()
        self.temp.cleanup()

    async def working_order(self, ticker='A', order_id='order-a'):
        req = entry_request(ticker+'-client')
        req['ticker'] = ticker
        reserved = await self.writer.reserve_entry(req, attempt_id=ticker+'-entry',
            view=await self.writer.portfolio(subaccount=0, now=NOW),
            config=BotConfig(), now=NOW, free_cash=D(500), account_known=True,
            offline_fixture=True)
        self.assertTrue(reserved.reserved, reserved.blockers)
        receipt = reserved.receipt
        self.assertTrue((await self.writer.begin_send(receipt)).dispatch_allowed)
        await self.writer.record_outcome('ack', receipt, dict(order_id=order_id,
            client_order_id=req['client_order_id'], fill_count='0',
            remaining_count='10', ts_ms=1), NOW)
        await self.writer.order(OrderUpdate(order_id, req['client_order_id'], ticker,
            'bid', D('.4'), D(10), D(0), D(10), 'resting', 0, 1, 1), NOW)
        evidence = await self.writer.cancel_evidence(order_id)
        request = dict(order_id=order_id, market_ticker=ticker,
                       subaccount=0, exchange_index=1)
        candidate = DispatchCandidate(ticker, SAFETY_CANCEL, ticker+'-cancel',
                                      request, evidence, 1)
        self.candidates[(ticker, SAFETY_CANCEL)] = candidate
        return candidate

    async def test_priority_coalescing_and_bounded_overflow(self):
        self.assertTrue(self.dispatcher.submit('A', PASSIVE_REDUCER))
        self.assertTrue(self.dispatcher.submit('B', SAFETY_CANCEL))
        self.assertTrue(self.dispatcher.submit('A', DUE_IOC))
        self.assertFalse(self.dispatcher.submit('A', PASSIVE_REDUCER))
        self.assertEqual(self.dispatcher.status().queued,
            ((SAFETY_CANCEL, 'B'), (DUE_IOC, 'A')))
        self.dispatcher.capacity = 2
        with self.assertRaises(InvalidData):
            self.dispatcher.submit('C', SAFETY_CANCEL)
        self.assertTrue(self.dispatcher.status().failed)

    async def test_one_dispatcher_owner_per_writer(self):
        with self.assertRaisesRegex(InvalidData, 'one mutation dispatcher'):
            MutationDispatcher(self.writer, self.executor, self.budget,
                refresh=lambda *_: None, clock_pair=lambda: budget_now(1),
                now=lambda: NOW, offline_fixture=True)

    async def test_cancel_handoff_is_durable_before_injected_invoke(self):
        await self.working_order()
        async def checked(kind, request):
            rows = await self.writer.mutations()
            self.assertEqual(rows[-1]['phase'], 'SENDING')
            self.invoked.append((kind, request))
            return dict(order_id=request['order_id'], ts_ms=1, reduced_by='10')
        self.executor.invoke = checked
        self.dispatcher.submit('A', SAFETY_CANCEL)
        outcome = await self.dispatcher.run_one()
        self.assertEqual((outcome.state, outcome.order_id), ('ACK', 'order-a'))
        self.assertEqual(len(self.invoked), 1)
        self.assertEqual(self.refresh_count, 2)
        self.assertFalse(self.dispatcher.status().live_ready)
        self.assertFalse((await self.writer.orders())[0].order.terminal)
        self.assertEqual((await self.dispatcher.run_one()).state, 'IDLE')

    async def test_urgent_cancel_precedes_older_passive_work(self):
        await self.working_order('A', 'order-a')
        await self.working_order('B', 'order-b')
        self.dispatcher.submit('A', PASSIVE_REDUCER)
        self.dispatcher.submit('B', SAFETY_CANCEL)
        first = await self.dispatcher.run_one()
        self.assertEqual((first.priority, first.state, first.ticker),
                         (SAFETY_CANCEL, 'ACK', 'B'))
        self.assertEqual(self.invoked[0][1]['order_id'], 'order-b')
        # A still needs a fresh reducer plan; there was no stale receipt.
        second = await self.dispatcher.run_one()
        self.assertEqual((second.priority, second.state),
                         (PASSIVE_REDUCER, 'BLOCKED'))

    async def test_waiting_retains_market_key_not_prepared_receipt(self):
        await self.working_order()
        self.clock = 0
        self.dispatcher.submit('A', SAFETY_CANCEL)
        waiting = await self.dispatcher.run_one()
        self.assertEqual(waiting.state, 'WAITING')
        self.assertEqual(self.dispatcher.status().queued, ((SAFETY_CANCEL, 'A'),))
        self.assertEqual(len(await self.writer.mutations()), 1)  # Entry only.
        self.clock = 1
        self.assertEqual((await self.dispatcher.run_one()).state, 'ACK')

    async def test_route_change_after_reservation_requeues_without_write(self):
        first = await self.working_order()
        calls = 0
        async def changed(ticker, priority):
            nonlocal calls
            calls += 1
            return first if calls == 1 else replace(first, request=dict(
                first.request, order_id='order-b'),
                evidence=replace(first.evidence, order_id='order-b'))
        self.dispatcher.refresh = changed
        self.dispatcher.submit('A', SAFETY_CANCEL)
        result = await self.dispatcher.run_one()
        self.assertEqual((result.state, result.blockers),
                         ('WAITING', ('candidate_route_changed',)))
        self.assertEqual(self.dispatcher.status().queued, ((SAFETY_CANCEL, 'A'),))
        self.assertEqual(len(await self.writer.mutations()), 1)  # Entry only.
        self.assertFalse(self.invoked)
        self.assertFalse(self.dispatcher.status().failed)

    async def test_executor_denial_aborts_unsent_preparation(self):
        await self.working_order()
        self.executor.validate_proof = lambda *_: False
        self.dispatcher.submit('A', SAFETY_CANCEL)
        result = await self.dispatcher.run_one()
        self.assertEqual(result.state, 'BLOCKED')
        rows = await self.writer.mutations()
        self.assertEqual(rows[-1]['phase'], 'NOT_SENT')
        self.assertFalse(self.invoked)
        self.assertEqual(self.budget.status(now=budget_now(self.clock)).outstanding, 0)

    async def test_post_sending_proof_loss_aborts_proven_unsent_command(self):
        await self.working_order()
        checks = iter((True, False))
        self.executor.validate_proof = lambda *_: next(checks)
        self.dispatcher.submit('A', SAFETY_CANCEL)
        result = await self.dispatcher.run_one()
        self.assertEqual((result.state, result.blockers),
                         ('BLOCKED', ('proof_changed_before_submission',)))
        self.assertEqual((await self.writer.mutations())[-1]['phase'], 'NOT_SENT')
        self.assertFalse(self.dispatcher.status().failed)
        self.assertFalse(self.executor.failed)
        self.assertFalse(self.invoked)

    async def test_quota_expiry_during_prepare_aborts(self):
        await self.working_order()
        original = self.writer.prepare_cancel
        async def stale(*args, **kwargs):
            result = await original(*args, **kwargs)
            self.clock = 300
            return result
        self.writer.prepare_cancel = stale
        self.dispatcher.submit('A', SAFETY_CANCEL)
        result = await self.dispatcher.run_one()
        self.assertEqual(result.state, 'WAITING')
        self.assertEqual(result.blockers, ('write_quota_expired',))
        self.assertEqual((await self.writer.mutations())[-1]['phase'], 'NOT_SENT')
        self.assertFalse(self.invoked)
        self.assertFalse(self.dispatcher.status().failed)
        self.assertEqual(self.dispatcher.status().queued, ((SAFETY_CANCEL, 'A'),))
        self.assertEqual(self.budget.status(now=budget_now(300)).outstanding, 0)
        # Fresh evidence and a new candidate, never retry the old receipt/id.
        self.writer.prepare_cancel = original
        self.budget.refresh(snapshot(scope=self.budget._snapshot.scope, sequence=2,
            start=budget_now(300), rate=100, capacity=100), now=budget_now(300))
        self.clock = 301
        old = self.candidates[('A', SAFETY_CANCEL)]
        self.candidates[('A', SAFETY_CANCEL)] = replace(old, attempt_id='after-quota',
            evidence=await self.writer.cancel_evidence('order-a'))
        result = await self.dispatcher.run_one()
        self.assertEqual(result.state, 'ACK', result.blockers)
        self.assertEqual(len(self.invoked), 1)
        self.assertFalse(self.dispatcher.status().failed)

    async def quota_refresh_during_prepare(self, *, complete=False):
        await self.working_order()
        fixture = ObservedQuotaFixture()
        self.addAsyncCleanup(fixture.close)
        self.budget = await fixture.attach(self.dispatcher)
        original = self.writer.prepare_cancel
        async def refreshing(*args, **kwargs):
            result = await original(*args, **kwargs)
            await fixture.begin_refresh()
            if complete:
                await fixture.finish_refresh()
            return result
        self.writer.prepare_cancel = refreshing
        self.dispatcher.submit('A', SAFETY_CANCEL)
        result = await self.dispatcher.run_one()
        reason = 'write_quota_replaced' if complete else 'write_quota_refreshing'
        self.assertEqual((result.state, result.blockers), ('WAITING', (reason,)))
        self.assertEqual((await self.writer.mutations())[-1]['phase'], 'NOT_SENT')
        self.assertFalse(self.invoked)
        self.assertFalse(self.dispatcher.status().failed)
        self.assertEqual(self.dispatcher.status().queued, ((SAFETY_CANCEL, 'A'),))
        self.writer.prepare_cancel = original
        if not complete:
            # An unfinished refresh cannot send or prepare another command.
            self.assertEqual((await self.dispatcher.run_one()).state, 'WAITING')
            self.assertEqual(len(await self.writer.mutations()), 2)
            await fixture.finish_refresh()
        old = self.candidates[('A', SAFETY_CANCEL)]
        self.candidates[('A', SAFETY_CANCEL)] = replace(old, attempt_id='fresh-quota',
            evidence=await self.writer.cancel_evidence('order-a'))
        self.assertEqual((await self.dispatcher.run_one()).state, 'ACK')
        self.assertEqual(len(self.invoked), 1)

    async def test_observed_quota_refresh_during_prepare_waits_then_recovers(self):
        await self.quota_refresh_during_prepare()

    async def test_completed_quota_refresh_during_prepare_replaces_revoked_permit(self):
        await self.quota_refresh_during_prepare(complete=True)

    async def observed_quota_loss_during_prepare(self, reason, *, fatal):
        await self.working_order()
        fixture = ObservedQuotaFixture()
        self.addAsyncCleanup(fixture.close)
        self.budget = await fixture.attach(self.dispatcher)
        original = self.writer.prepare_cancel
        async def unavailable(*args, **kwargs):
            result = await original(*args, **kwargs)
            if reason == 'write_quota_stale':
                fixture.clock.t += 301
            elif reason == 'write_quota_clock_fault':
                fixture.clock.offset += 3
            elif reason == 'write_quota_stopped':
                fixture.source.stop()
            else:
                fixture.source.invalidate(reason)
            return result
        self.writer.prepare_cancel = unavailable
        self.dispatcher.submit('A', SAFETY_CANCEL)
        if fatal:
            with self.assertRaises(QuotaUnavailable) as raised:
                await self.dispatcher.run_one()
            self.assertEqual(raised.exception.reason, reason)
            self.assertTrue(self.dispatcher.status().failed)
        else:
            result = await self.dispatcher.run_one()
            self.assertEqual((result.state, result.blockers), ('WAITING', (reason,)))
            self.assertIsNone(result.retry_after)
            self.assertFalse(self.dispatcher.status().failed)
        self.assertFalse(self.invoked)
        self.assertEqual((await self.writer.mutations())[-1]['phase'], 'NOT_SENT')

    async def test_observed_quota_stale_aborts_and_waits(self):
        await self.observed_quota_loss_during_prepare('write_quota_stale', fatal=False)

    async def test_failed_quota_refresh_aborts_and_waits(self):
        await self.observed_quota_loss_during_prepare('write_quota_refresh_failed', fatal=False)

    async def test_observed_quota_clock_fault_is_not_retried(self):
        await self.observed_quota_loss_during_prepare('write_quota_clock_fault', fatal=True)

    async def test_observed_quota_stop_is_not_retried(self):
        await self.observed_quota_loss_during_prepare('write_quota_stopped', fatal=True)

    async def test_refresh_after_sending_keeps_unknown_and_never_invokes(self):
        await self.working_order()
        fixture = ObservedQuotaFixture()
        self.addAsyncCleanup(fixture.close)
        self.budget = await fixture.attach(self.dispatcher)
        original = self.writer.begin_send
        async def refreshing(receipt):
            result = await original(receipt)
            await fixture.begin_refresh()
            return result
        self.writer.begin_send = refreshing
        self.dispatcher.submit('A', SAFETY_CANCEL)
        with self.assertRaises(QuotaUnavailable):
            await self.dispatcher.run_one()
        self.assertTrue(self.dispatcher.status().failed)
        self.assertTrue(self.executor.failed)
        self.assertFalse(self.invoked)
        self.assertEqual((await self.writer.mutations())[-1]['phase'], 'UNKNOWN')

    async def test_same_revision_discarded_permit_still_fails(self):
        await self.working_order()
        original = self.writer.prepare_cancel
        async def discarded(*args, **kwargs):
            result = await original(*args, **kwargs)
            permit = next(iter(self.budget._permits.values()))[0]
            self.budget.discard(permit, now=budget_now(self.clock))
            return result
        self.writer.prepare_cancel = discarded
        self.dispatcher.submit('A', SAFETY_CANCEL)
        with self.assertRaises(InvalidData):
            await self.dispatcher.run_one()
        self.assertTrue(self.dispatcher.status().failed)
        self.assertFalse(self.invoked)
        self.assertEqual((await self.writer.mutations())[-1]['phase'], 'NOT_SENT')

    async def test_altered_permit_cannot_hide_behind_completed_refresh(self):
        await self.working_order()
        fixture = ObservedQuotaFixture()
        self.addAsyncCleanup(fixture.close)
        self.budget = await fixture.attach(self.dispatcher)
        original = self.writer.prepare_cancel
        async def altered(*args, **kwargs):
            result = await original(*args, **kwargs)
            permit = next(iter(self.budget._permits.values()))[0]
            object.__setattr__(permit, 'route', '/portfolio/events/orders/another')
            await fixture.begin_refresh()
            await fixture.finish_refresh()
            return result
        self.writer.prepare_cancel = altered
        self.dispatcher.submit('A', SAFETY_CANCEL)
        with self.assertRaisesRegex(InvalidData, 'altered dispatch write permit'):
            await self.dispatcher.run_one()
        self.assertTrue(self.dispatcher.status().failed)
        self.assertFalse(self.invoked)
        self.assertEqual((await self.writer.mutations())[-1]['phase'], 'NOT_SENT')

    async def test_refresh_cannot_requeue_an_already_sending_receipt(self):
        await self.working_order()
        fixture = ObservedQuotaFixture()
        self.addAsyncCleanup(fixture.close)
        self.budget = await fixture.attach(self.dispatcher)
        original = self.writer.prepare_cancel
        async def advanced(*args, **kwargs):
            result = await original(*args, **kwargs)
            await self.writer.begin_send(result.receipt)
            await fixture.begin_refresh()
            return result
        self.writer.prepare_cancel = advanced
        self.dispatcher.submit('A', SAFETY_CANCEL)
        with self.assertRaises(QuotaUnavailable):
            await self.dispatcher.run_one()
        self.assertTrue(self.dispatcher.status().failed)
        self.assertFalse(self.invoked)
        self.assertEqual((await self.writer.mutations())[-1]['phase'], 'SENDING')

    async def test_quota_expiry_during_sending_never_invokes_transport(self):
        await self.working_order()
        original = self.writer.begin_send
        async def delayed(receipt):
            self.assertEqual(self.budget.status(now=budget_now(self.clock)).outstanding, 1)
            result = await original(receipt)
            self.clock = 300
            return result
        self.writer.begin_send = delayed
        self.dispatcher.submit('A', SAFETY_CANCEL)
        with self.assertRaises(QuotaUnavailable):
            await self.dispatcher.run_one()
        self.assertFalse(self.invoked)
        self.assertTrue(self.dispatcher.status().failed)
        self.assertTrue(self.executor.failed)
        self.assertEqual((await self.writer.mutations())[-1]['phase'], 'UNKNOWN')
        self.assertEqual(self.budget.status(now=budget_now(300)).outstanding, 0)

    async def test_pre_send_clock_fault_remains_fatal_after_abort(self):
        await self.working_order()
        original = self.writer.prepare_cancel
        async def regressed(*args, **kwargs):
            result = await original(*args, **kwargs)
            self.clock = 0
            return result
        self.writer.prepare_cancel = regressed
        self.dispatcher.submit('A', SAFETY_CANCEL)
        with self.assertRaises(QuotaUnavailable):
            await self.dispatcher.run_one()
        self.assertTrue(self.dispatcher.status().failed)
        self.assertFalse(self.invoked)
        self.assertEqual((await self.writer.mutations())[-1]['phase'], 'NOT_SENT')

    async def test_expired_permit_with_already_sending_receipt_remains_fatal(self):
        await self.working_order()
        original = self.writer.prepare_cancel
        async def advanced(*args, **kwargs):
            result = await original(*args, **kwargs)
            await self.writer.begin_send(result.receipt)
            self.clock = 300
            return result
        self.writer.prepare_cancel = advanced
        self.dispatcher.submit('A', SAFETY_CANCEL)
        with self.assertRaises(QuotaUnavailable):
            await self.dispatcher.run_one()
        self.assertTrue(self.dispatcher.status().failed)
        self.assertFalse(self.invoked)
        self.assertEqual((await self.writer.mutations())[-1]['phase'], 'SENDING')

    async def test_async_send_edge_callback_rejected_before_sending(self):
        candidate = await self.working_order()
        prepared = await self.writer.prepare_cancel(candidate.attempt_id,
            candidate.request, evidence=candidate.evidence, now=NOW)
        self.assertTrue(prepared.reserved)
        async def unsafe_callback():
            return None
        with self.assertRaisesRegex(InvalidData, 'synchronous send-edge'):
            await self.executor.execute_prepared(
                prepared.receipt, before_invoke=unsafe_callback)
        self.assertEqual((await self.writer.mutations())[-1]['phase'], 'PREPARED')
        self.assertFalse(self.invoked)

    async def test_cancellation_joins_one_worker_and_does_not_duplicate(self):
        await self.working_order()
        entered, release = asyncio.Event(), asyncio.Event()
        async def slow(kind, request):
            entered.set()
            await release.wait()
            self.invoked.append((kind, request))
            return dict(order_id=request['order_id'], ts_ms=1, reduced_by='10')
        self.executor.invoke = slow
        self.dispatcher.submit('A', SAFETY_CANCEL)
        task = asyncio.create_task(self.dispatcher.run_one())
        await entered.wait()
        self.assertEqual((await self.dispatcher.run_one()).blockers,
                         ('dispatcher_busy',))
        task.cancel()
        self.assertEqual(self.dispatcher.status().active, ('A', SAFETY_CANCEL))
        release.set()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(len(self.invoked), 1)
        self.assertIsNone(self.dispatcher.status().active)

    async def test_unknown_injected_send_latches_dispatcher_without_retry(self):
        await self.working_order()
        async def lost(*_):
            self.invoked.append('once')
            raise TimeoutError('synthetic transport uncertainty')
        self.executor.invoke = lost
        self.dispatcher.submit('A', SAFETY_CANCEL)
        with self.assertRaises(TimeoutError):
            await self.dispatcher.run_one()
        self.assertTrue(self.dispatcher.status().failed)
        self.assertEqual((await self.writer.mutations())[-1]['phase'], 'UNKNOWN')
        self.assertEqual((await self.dispatcher.run_one()).state, 'FAILED')
        self.assertEqual(self.invoked, ['once'])

    async def test_explicit_live_mode_rejected(self):
        with self.assertRaises(InvalidData):
            MutationDispatcher(self.writer, self.executor, self.budget,
                refresh=lambda *_: None, clock_pair=lambda: budget_now(),
                now=lambda: NOW)


if __name__ == '__main__':
    unittest.main()
