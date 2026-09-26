"""D-141 safety pause when recovery cannot prove the account, and self-recovery."""
import unittest
from unittest.mock import patch

from tests import test_bot_account_release as baseline
from tests import test_bot_routine_refresh as routine


class SafetyPauseTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = baseline.AccountReleaseTests.asyncSetUp
    asyncTearDown = baseline.AccountReleaseTests.asyncTearDown
    open_epoch = baseline.AccountReleaseTests.open_epoch
    refresh = baseline.AccountReleaseTests.refresh
    reserve = baseline.AccountReleaseTests.reserve
    runtime = routine.RoutineRefreshTests.runtime
    advance = routine.RoutineRefreshTests.advance

    async def test_blocked_recovery_pulls_entries_until_a_repair(self):
        runtime = await self.runtime()
        events = []
        runtime.diagnostics.emit = lambda name, **context: events.append(name)
        with patch.object(runtime, 'request_entry_drain') as drain:
            self.assertFalse(runtime.entry_pause_active)
            runtime.recovery_state = 'blocked_retry_exhausted'
            self.assertTrue(runtime.entry_pause_active)
            self.assertFalse(runtime.entry_allowed)
            runtime._safety_tick()  # The live refresh loop's half-second tick.
            drain.assert_called_once()
            self.assertEqual(events.count('recovery_safety_pause'), 1)
            runtime.recovery_state = 'recovering'       # Retrying: still paused.
            runtime.recovery_state = 'blocked_retry_exhausted'
            self.assertTrue(runtime.entry_pause_active)
            self.assertEqual(events.count('recovery_safety_pause'), 1)  # One per episode.
            runtime.recovery_state = 'repaired_entries_blocked'
            self.assertFalse(runtime.entry_pause_active)
        self.assertEqual(runtime.status()['recovery_safety_pauses'], 1)

    async def test_self_recovery_retries_quickly_then_every_five_minutes(self):
        runtime = await self.runtime()
        with patch.object(runtime, 'request_entry_drain'):
            runtime.recovery_state = 'blocked_retry_exhausted'
        fired = []
        for step in range(1, 12*60):  # Twelve minutes in one-second ticks.
            self.advance(1)
            if runtime._retry_exhausted_recovery():
                fired.append(step)
                runtime.recovery_requested.clear()  # The pass failed again.
                with patch.object(runtime, 'request_entry_drain'):
                    runtime.recovery_state = 'blocked_retry_exhausted'
        self.assertEqual(fired[:5], [30, 90, 210, 510, 810][:len(fired[:5])])
        self.assertEqual([b-a for a, b in zip(fired, fired[1:])][:3], [60, 120, 300])

    async def test_successful_retry_resets_the_schedule_and_resumes(self):
        runtime = await self.runtime()
        with patch.object(runtime, 'request_entry_drain'):
            runtime.recovery_state = 'blocked_retry_exhausted'
        self.advance(30)
        self.assertTrue(runtime._retry_exhausted_recovery())
        runtime.recovery_requested.clear()
        self.assertTrue(await runtime.recover_once())
        runtime.recovery_state = 'repaired_entries_blocked'
        self.assertFalse(runtime.entry_pause_active)
        self.assertEqual(runtime.status()['exhausted_retries'], 0)

    async def test_no_retry_while_stopping(self):
        runtime = await self.runtime()
        with patch.object(runtime, 'request_entry_drain'):
            runtime.recovery_state = 'blocked_retry_exhausted'
        runtime.stop_requested.set()
        self.advance(600)
        self.assertFalse(runtime._retry_exhausted_recovery())


if __name__ == '__main__':
    unittest.main()
