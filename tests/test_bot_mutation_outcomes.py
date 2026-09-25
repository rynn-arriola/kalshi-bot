"""Injected-only failures; actual disposable owners, never venue I/O."""
import asyncio
from contextlib import closing
from dataclasses import FrozenInstanceError
from pathlib import Path
import sqlite3
import unittest

from kalshi_bot.dispatch import SAFETY_CANCEL
from kalshi_bot.mutation_outcomes import MutationHTTPFailure, MutationOutcomeOwner
from kalshi_bot.values import InvalidData
from kalshi_bot.write_budget import ORDERS
import test_bot_dispatch_sources as fixtures
from test_bot_inventory_risk import request
from test_bot_write_budget import budget, now, snapshot


class OutcomeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.f = fixtures.DispatchSourceTests()
        await self.f.asyncSetUp()
        self.owner = self.f.dispatcher.executor.invoke

    async def asyncTearDown(self):
        await self.f.asyncTearDown()

    async def failure(self, exc):
        async def fail(kind, req):
            self.f.calls.append((kind, dict(req)))
            raise exc
        self.owner.invoke = fail
        with self.assertRaises(type(exc)):
            await self.f.run_priority()
        await self.assert_unknown()

    async def assert_unknown(self):
        self.assertEqual((await self.f.writer.mutations())[-1]['phase'], 'UNKNOWN')
        self.assertTrue(self.f.runtime.recovery_requested.is_set())
        self.assertIsNone(self.f.runtime.account.current_report(self.f.now))
        self.assertIsNone(self.f.source._proof)
        self.assertTrue(self.f.dispatcher.executor.failed)
        self.assertEqual((await self.f.dispatcher.run_one()).state, 'FAILED')
        self.assertEqual(len(self.f.calls), 1)
        self.assertFalse(self.owner.busy)

    async def test_429_pauses_only_original_shard_and_never_retries(self):
        await self.f.ready(route=1)
        await self.failure(MutationHTTPFailure(429))
        buckets = self.f.budget.status(now=now(1)).buckets
        self.assertEqual((buckets[0][-1], buckets[1][-1]), (0, 1))
        self.assertIsNotNone(self.f.budget.try_reserve('POST', ORDERS, shard=0, now=now(1)))
        self.assertIsNone(self.f.budget.try_reserve('POST', ORDERS, shard=1, now=now(1)))
        self.assertEqual((self.owner.last.http_status, self.owner.last.exchange_index), (429, 1))
        with self.assertRaises(FrozenInstanceError):
            self.owner.last.http_status = 200

    async def test_http_auth_failure_is_unknown_not_throttle(self):
        await self.f.ready()
        await self.failure(MutationHTTPFailure(401))
        self.assertEqual(self.owner.last.outcome, 'http_failure')
        self.assertEqual(self.f.budget.status(now=now(1)).buckets[0][-1], 0)

    async def test_http_conflict_is_not_rejection_proof(self):
        await self.f.ready()
        await self.failure(MutationHTTPFailure(409))

    async def test_create_http_400_is_durable_rejection_not_ambiguous_send(self):
        await self.f.ready()
        async def fail(kind, req):
            self.f.calls.append((kind, dict(req)))
            raise MutationHTTPFailure(400)
        self.owner.invoke = fail
        result = await self.f.run_priority()
        self.assertEqual(result.state, 'REJECTED')
        self.assertEqual((await self.f.writer.mutations())[-1]['phase'], 'REJECTED')
        self.assertEqual(self.owner.last.outcome, 'rejected')
        self.assertFalse(self.f.dispatcher.executor.failed)
        self.assertNotIn('ambiguous_send', (await self.f.writer.portfolio(
            subaccount=0, now=self.f.now)).blockers)

    async def test_cancel_http_400_remains_unknown_until_terminal_proof(self):
        await self.f.ready(filled='4', remaining='6')
        async def fail(kind, req):
            self.f.calls.append((kind, dict(req)))
            raise MutationHTTPFailure(400)
        self.owner.invoke = fail
        with self.assertRaises(MutationHTTPFailure):
            await self.f.run_priority(SAFETY_CANCEL)
        await self.assert_unknown()
        self.assertEqual(self.owner.last.outcome, 'http_failure')

    async def test_paused_cancel_404_is_rejected_and_requires_reconciliation(self):
        from types import SimpleNamespace
        await self.f.ready(filled='0', remaining='10')
        self.f.runtime.live_session = SimpleNamespace(entries_paused=True)
        async def missing(kind, req):
            self.f.calls.append((kind, dict(req)))
            raise MutationHTTPFailure(404, 'not_found')
        self.owner.invoke = missing
        result = await self.f.run_priority(SAFETY_CANCEL)
        self.assertEqual(result.state, 'REJECTED')
        mutation = (await self.f.writer.mutations())[-1]
        self.assertEqual(mutation['phase'], 'REJECTED')
        self.assertIn('"status":404', mutation['response'])
        self.assertEqual((await self.f.writer.orders())[0].order.remaining, 10)
        self.assertTrue(self.f.runtime.recovery_requested.is_set())
        self.assertIsNone(self.f.runtime.account.current_report(self.f.now))
        self.assertFalse(self.f.dispatcher.executor.failed)
        self.assertFalse(self.f.dispatcher.status().queued)
        self.assertEqual(self.owner.last.outcome, 'rejected')

    async def test_server_failure_is_unknown(self):
        await self.f.ready()
        await self.failure(MutationHTTPFailure(503))

    async def test_network_error_retains_no_raw_exception(self):
        await self.f.ready()
        await self.failure(OSError('sensitive fixture message'))
        self.assertNotIn('sensitive', repr(self.owner.last))
        self.assertEqual(self.owner.last.outcome, 'uncertain')

    async def test_transport_cancel_is_unknown_and_not_silently_dropped(self):
        await self.f.ready()
        await self.failure(asyncio.CancelledError())
        self.assertEqual(self.owner.last.outcome, 'interrupted')

    async def test_timeout_requests_recovery(self):
        await self.f.ready()
        self.f.dispatcher.executor.timeout = .02
        async def held(kind, req):
            self.f.calls.append((kind, req))
            await asyncio.Event().wait()
        self.owner.invoke = held
        with self.assertRaises(TimeoutError):
            await self.f.run_priority()
        await self.assert_unknown()

    async def test_malformed_ack_is_unknown(self):
        await self.f.ready()
        async def malformed(kind, req):
            self.f.calls.append((kind, req))
            return dict(order_id='reducer-order', raw='private fixture body')
        self.owner.invoke = malformed
        with self.assertRaises(InvalidData):
            await self.f.run_priority()
        await self.assert_unknown()
        self.assertNotIn('private', repr(self.owner.last))

    async def test_ack_revokes_old_account_proof_and_requests_recovery(self):
        await self.f.ready()
        self.assertEqual((await self.f.run_priority()).state, 'ACK')
        self.assertTrue(self.f.runtime.recovery_requested.is_set())
        self.assertIsNone(self.f.runtime.account.current_report(self.f.now))
        self.assertEqual(self.owner.last.outcome, 'ack')
        self.assertFalse(self.f.dispatcher.executor.failed)

    async def test_cancel_ack_is_not_terminal(self):
        await self.f.ready(filled='4', remaining='6')
        self.assertEqual((await self.f.run_priority(SAFETY_CANCEL)).state, 'ACK')
        self.assertEqual(self.owner.last.kind, 'cancel')
        self.assertEqual((await self.f.writer.orders())[0].order.remaining, 6)
        self.assertTrue(self.f.runtime.recovery_requested.is_set())

    async def test_transport_request_mutation_cannot_redirect_pause(self):
        await self.f.ready(route=1)
        async def fail(kind, req):
            req['exchange_index'] = 0
            raise MutationHTTPFailure(429)
        self.owner.invoke = fail
        with self.assertRaises(MutationHTTPFailure):
            await self.f.run_priority()
        self.assertEqual(self.owner.last.exchange_index, 1)
        self.assertEqual(self.f.budget.status(now=now(1)).buckets[0][-1], 0)

    async def test_early_recovery_consumption_is_signalled_again_after_persistence(self):
        await self.f.ready()
        original = self.f.writer.record_outcome
        async def record(*args):
            self.assertTrue(self.f.runtime.recovery_requested.is_set())
            self.f.runtime.recovery_requested.clear()  # Early worker wake-up.
            return await original(*args)
        self.f.writer.record_outcome = record
        await self.failure(MutationHTTPFailure(429))

    async def test_successful_ack_also_resignals_after_persistence(self):
        await self.f.ready()
        original = self.f.writer.record_outcome
        async def record(*args):
            self.f.runtime.recovery_requested.clear()
            return await original(*args)
        self.f.writer.record_outcome = record
        self.assertEqual((await self.f.run_priority()).state, 'ACK')
        self.assertTrue(self.f.runtime.recovery_requested.is_set())

    async def test_pause_failure_still_requests_recovery(self):
        await self.f.ready()
        def broken(**kwargs):
            raise InvalidData('synthetic quota failure')
        self.f.budget.pause_429 = broken
        async def fail(kind, req):
            self.f.calls.append((kind, req))
            raise MutationHTTPFailure(429)
        self.owner.invoke = fail
        with self.assertRaises(InvalidData):
            await self.f.run_priority()
        await self.assert_unknown()
        self.assertEqual(self.owner.last.http_status, 429)

    async def test_preinvoke_proof_failure_still_signals_recovery(self):
        await self.f.ready()
        original = self.f.writer.begin_send
        async def sending(receipt):
            result = await original(receipt)
            self.f.runtime._revoke()
            return result
        self.f.writer.begin_send = sending
        result = await self.f.run_priority()
        self.assertEqual((result.state, result.blockers),
                         ('BLOCKED', ('proof_changed_before_submission',)))
        self.assertEqual((await self.f.writer.mutations())[-1]['phase'], 'NOT_SENT')
        # D-130: the supervisor's post-turn step owns the fallback; a real
        # source change (revoke) cannot be re-audited, so recovery is requested.
        await self.f.source.after_turn(result)
        self.assertTrue(self.f.runtime.recovery_requested.is_set())
        self.assertEqual(self.f.runtime.unsent_rebases, 0)
        self.assertFalse(self.f.calls)

    async def test_failed_ack_persistence_does_not_leave_owner_healthy(self):
        await self.f.ready()
        async def broken(*args):
            self.f.runtime.recovery_requested.clear()
            raise OSError('synthetic persistence failure')
        self.f.writer.record_outcome = broken
        with self.assertRaises(OSError):
            await self.f.run_priority()
        self.assertEqual((await self.f.writer.mutations())[-1]['phase'], 'SENDING')
        self.assertTrue(self.f.dispatcher.executor.failed)
        self.assertTrue(self.f.runtime.recovery_requested.is_set())

    async def test_notification_failure_blocks_even_durable_ack(self):
        await self.f.ready()
        def broken():
            raise InvalidData('synthetic notification failure')
        self.f.dispatcher.executor.after_outcome = broken
        with self.assertRaises(InvalidData):
            await self.f.run_priority()
        self.assertEqual((await self.f.writer.mutations())[-1]['phase'], 'ACK')
        self.assertTrue(self.f.dispatcher.executor.failed)
        self.assertEqual((await self.f.dispatcher.run_one()).state, 'FAILED')

    async def test_consumer_cancel_waits_for_429_and_retains_unknown(self):
        await self.f.ready()
        entered, release = asyncio.Event(), asyncio.Event()
        async def held(kind, req):
            self.f.calls.append((kind, req))
            entered.set()
            await release.wait()
            raise MutationHTTPFailure(429)
        self.owner.invoke = held
        task = asyncio.create_task(self.f.run_priority())
        loop = asyncio.get_running_loop()
        previous, errors = loop.get_exception_handler(), []
        loop.set_exception_handler(lambda _loop, context: errors.append(context))
        self.addCleanup(loop.set_exception_handler, previous)
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        await asyncio.sleep(0)
        self.assertFalse(task.done())
        release.set()
        with self.assertRaises(MutationHTTPFailure):
            await task
        await self.assert_unknown()
        await asyncio.sleep(0)
        self.assertFalse(errors, 'retained failure must not leak to default loop logging')

    async def test_unknown_and_capacity_persist_in_closed_fixture(self):
        await self.f.ready()
        await self.failure(MutationHTTPFailure(429))
        await self.f.writer.close()
        path = Path(self.f.temp.name)/'fixture.db'
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro', uri=True)) as db:
            self.assertGreater(db.execute("SELECT count(*) FROM mutation_attempts WHERE phase='UNKNOWN'").fetchone()[0], 0)
            self.assertGreater(db.execute("SELECT count(*) FROM command_authorizations WHERE state='UNKNOWN'").fetchone()[0], 0)
            self.assertGreater(db.execute('SELECT count(*) FROM command_credits').fetchone()[0], 0)


class OwnerContractTests(unittest.IsolatedAsyncioTestCase):
    def owner(self, **kwargs):
        async def fail(*args):
            raise MutationHTTPFailure(429)
        options = dict(invoke=fail, clock_pair=lambda: now(1), notify=lambda n: None,
                       offline_fixture=True)
        options.update(kwargs)
        return MutationOutcomeOwner(budget(), **options)

    def test_strict_http_status_and_constant_exception_text(self):
        for status in (None, True, '429', 429., 200, 600):
            with self.assertRaises(InvalidData):
                MutationHTTPFailure(status)
        self.assertEqual(str(MutationHTTPFailure(429)), 'mutation_http_failure')
        with self.assertRaises(AttributeError):
            MutationHTTPFailure(429).status = 200
        for code in ('', 'has space', 'x'*101, '\u2603'):
            with self.assertRaises(InvalidData):
                MutationHTTPFailure(400, code)
        failure = MutationHTTPFailure(400, 'invalid_order')
        self.assertEqual(failure.error_code, 'invalid_order')
        with self.assertRaises(AttributeError):
            failure.error_code = 'changed'

    def test_explicit_fixture_and_bounded_pause(self):
        for flag in (False, None, 1):
            with self.assertRaises(InvalidData):
                self.owner(offline_fixture=flag)
        for pause in (0, -1, True, float('nan'), float('inf'), 61, '1'):
            with self.assertRaises(InvalidData):
                self.owner(pause_seconds=pause)

    async def test_async_notification_is_rejected_even_hidden_by_lambda(self):
        async def notify(*args):
            pass
        with self.assertRaises(InvalidData):
            self.owner(notify=notify)
        owner = self.owner(notify=lambda n: notify())
        with self.assertRaisesRegex(InvalidData, 'must not await'):
            await owner('create', request())
        self.assertFalse(owner.busy)

    async def test_one_inflight_owner(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def held(*args):
            entered.set()
            await release.wait()
            raise MutationHTTPFailure(429)
        owner = self.owner(invoke=held)
        task = asyncio.create_task(owner('create', request()))
        await asyncio.wait_for(entered.wait(), 2)
        with self.assertRaisesRegex(InvalidData, 'busy'):
            await owner('create', request())
        release.set()
        with self.assertRaises(MutationHTTPFailure):
            await task

    async def test_late_refresh_keeps_original_scope_and_current_pause(self):
        owner = self.owner()
        async def fail(*args):
            owner.budget.refresh(snapshot(scope=owner.budget._snapshot.scope,
                sequence=2, start=now(1)), now=now(1))
            raise MutationHTTPFailure(429)
        owner.invoke = fail
        with self.assertRaises(MutationHTTPFailure):
            await owner('create', request())
        self.assertEqual(owner.budget.status(now=now(1)).buckets[0][-1], 1)
