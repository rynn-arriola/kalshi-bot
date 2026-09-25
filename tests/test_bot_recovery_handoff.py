"""Recovery must join the real dispatcher; synthetic wires and disposable ledgers."""
import asyncio
import unittest
from types import SimpleNamespace as NS

import test_bot_live_runtime as fixture
from kalshi_bot.dispatch import ENTRY_PAIR


class HandoffTests(unittest.IsolatedAsyncioTestCase):
    async def test_flat_maintenance_owner_is_prioritized_after_account_refresh(self):
        f = fixture.LiveEntryTests()
        await f.asyncSetUp()
        try:
            r = f.runtime
            # A flat owner may be absent from the account's active scope.
            r.engine.dirty.capacity = 4
            r.engine.dirty.register('B')
            r.engine.dirty.mark('B')
            r.maintenance = NS(cycle=NS(ticker='A'))
            r._schedule_account_refresh(('B',))
            self.assertEqual(r.engine.dirty.take(r.clock(),limit=1), ['A'])
            self.assertTrue(r.engine.wake.is_set())
        finally:
            await f.asyncTearDown()

    async def scenario(self, *, fails=False, stopped=False):
        f = fixture.LiveEntryTests()
        await f.asyncSetUp()
        r = f.runtime
        r.account_subscribed = True
        recording, release, recovered = asyncio.Event(), asyncio.Event(), asyncio.Event()
        original = f.f.writer.record_batch_outcome
        calls = []

        async def held(*args, **kwargs):
            recording.set()
            await release.wait()
            if fails:
                raise OSError('synthetic durable failure')
            return await original(*args, **kwargs)

        async def recover():
            calls.append(f.dispatcher.status().active)
            recovered.set()
            return True

        f.f.writer.record_batch_outcome = held
        r.recover_once = recover
        recovery = asyncio.create_task(r._recover())
        f.dispatcher.submit('A', ENTRY_PAIR)
        dispatch = asyncio.create_task(f.dispatcher.run_one())
        try:
            await asyncio.wait_for(recording.wait(), 2)
            self.assertIsNone(r.account.current_report(r.now()))
            # Let recovery run while the ACK is intentionally not durable.
            await asyncio.sleep(.03)
            self.assertFalse(calls, 'recovery read raced outstanding persistence')
            if stopped:
                r.stop_requested.set()
            release.set()
            if fails:
                with self.assertRaises(OSError): await dispatch
            else:
                self.assertEqual((await dispatch).state, 'ACK')
            if stopped:
                await asyncio.wait_for(recovery, 2)
                self.assertFalse(calls)
            else:
                await asyncio.wait_for(recovered.wait(), 2)
                self.assertEqual(calls, [None])
                self.assertEqual(r.recovery_attempts, 1)
        finally:
            release.set()
            recovery.cancel()
            await asyncio.gather(dispatch, recovery, return_exceptions=True)
            await f.asyncTearDown()

    async def test_recovery_waits_for_durable_batch_result(self):
        await self.scenario()

    async def test_failed_persistence_still_wakes_reconciliation(self):
        await self.scenario(fails=True)

    async def test_stop_during_join_does_not_start_recovery_reads(self):
        await self.scenario(stopped=True)
