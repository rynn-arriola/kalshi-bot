"""D-133 full-recovery final re-audit; real owners, temporary ledger, no network."""
from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tests import test_bot_account_release as baseline
from tests import test_bot_routine_refresh as routine


class RecoveryReauditTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = baseline.AccountReleaseTests.asyncSetUp
    asyncTearDown = baseline.AccountReleaseTests.asyncTearDown
    open_epoch = baseline.AccountReleaseTests.open_epoch
    refresh = baseline.AccountReleaseTests.refresh
    reserve = baseline.AccountReleaseTests.reserve
    runtime = routine.RoutineRefreshTests.runtime
    advance = routine.RoutineRefreshTests.advance

    async def recover(self, runtime, after_history=None):
        """One full pass; history takes real time, as it does live."""
        snapshots, history = runtime.account.reconcile, runtime.account.recover_history
        calls = []
        async def snapshot(*args, **kwargs):
            calls.append('prepared' if kwargs.get('prepare_accounting_boundary') else 'plain')
            return await snapshots(*args, **kwargs)
        async def enumerate_history(*args, **kwargs):
            result = await history(*args, **kwargs)
            self.advance(.5)
            if after_history is not None:
                after_history()
            return result
        runtime.request_recovery()
        runtime.recovery_requested.clear()
        with (patch.object(runtime.account, 'reconcile', snapshot),
              patch.object(runtime.account, 'recover_history', enumerate_history)):
            repaired = await runtime.recover_once()
        return repaired, calls

    async def test_unchanged_first_snapshot_replaces_middle_venue_read(self):
        runtime = await self.runtime()
        repaired, calls = await self.recover(runtime)
        self.assertTrue(repaired)
        self.assertEqual(calls, ['plain', 'prepared'])  # first + tail only
        self.assertEqual(runtime.recovery_final_reaudits, 1)
        self.assertTrue(runtime.accounting_result.released)
        self.assertIsNotNone(runtime._current_routine_proof())
        self.assertLessEqual({'first_snapshot', 'history', 'final_snapshot', 'tail_snapshot'},
                             set(runtime.recovery_phase_ms))
        self.assertEqual(runtime.status()['recovery_final_reaudits'], 1)

    async def test_private_event_since_first_snapshot_reads_venue_again(self):
        runtime = await self.runtime()
        def private_event():
            runtime.account.revision += 1
        repaired, calls = await self.recover(runtime, private_event)
        self.assertEqual(runtime.recovery_final_reaudits, 0)
        self.assertEqual(calls[:2], ['plain', 'plain'])

    async def test_snapshot_past_five_seconds_reads_venue_again(self):
        runtime = await self.runtime()
        repaired, calls = await self.recover(runtime, lambda: self.advance(5))
        self.assertEqual(runtime.recovery_final_reaudits, 0)
        self.assertEqual(calls, ['plain', 'plain', 'prepared'])
        self.assertTrue(repaired)

    async def test_repaired_ledger_disagreeing_with_snapshot_reads_venue_again(self):
        runtime = await self.runtime()
        original = self.writer.reaudit
        async def blocked(snapshot):
            return replace(await original(snapshot), blockers=('owned_order_fill_gap',))
        with patch.object(self.writer, 'reaudit', blocked):
            repaired, calls = await self.recover(runtime)
        self.assertEqual(runtime.recovery_final_reaudits, 0)
        self.assertEqual(calls, ['plain', 'plain', 'prepared'])
        self.assertTrue(repaired)

    async def test_venue_change_before_tail_never_releases(self):
        runtime = await self.runtime()
        def cash_moves():
            runtime.reads.cash = dict(runtime.reads.cash, balance=49000, balance_dollars='490')
        repaired, calls = await self.recover(runtime, cash_moves)
        self.assertEqual(runtime.recovery_final_reaudits, 1)
        self.assertEqual(calls, ['plain', 'prepared'])
        self.assertFalse(repaired)
        self.assertIsNone(runtime._current_routine_proof())

    async def test_missing_order_lookup_keeps_ordinary_final_read(self):
        runtime = await self.runtime()
        missing = SimpleNamespace(awaiting_fills=True,
                                  order=SimpleNamespace(order_id='gone', terminal=True))
        async def lookup(reads, order_id, *, now):
            reads.order_lookups += 1  # The real read's budget accounting.
        async def once():
            del self.writer.orders  # Later snapshots use the real ledger.
            return (missing,)
        def missing_order():
            self.writer.orders = once
        with patch.object(runtime.account, 'recover_order', lookup):
            repaired, calls = await self.recover(runtime, missing_order)
        self.assertEqual(runtime.recovery_final_reaudits, 0)
        self.assertEqual(calls, ['plain', 'plain', 'prepared'])
        self.assertTrue(repaired)

if __name__ == '__main__':
    unittest.main()
