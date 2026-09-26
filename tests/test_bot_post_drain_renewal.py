"""D-147: after a protective-cancel drain, renew the proof instead of a full pass."""
from unittest.mock import patch
import unittest

import test_bot_risk_dispatch_retry as retry_fixture


class PostDrainRenewalTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.b = retry_fixture.RiskDispatchRetryTests()
        await self.b.asyncSetUp()  # Market A is latched as a protective cycle.
        self.r = self.b.r
        # Drain both legs through the real dispatcher, as production does.
        await self.b.first_ack()
        self.b.advance()
        self.r._resume_risk_drain()
        await self.b.d.run_one()
        await self.b.d.run_one()
        self.assertFalse(self.b.source.risk_drain_pending)
        self.assertTrue(self.r._post_drain_recovery_pending)
        self.r.recovery_requested.clear()
        self.anchor = object()

    async def asyncTearDown(self):
        await self.b.asyncTearDown()

    def drain(self, anchor):
        with patch.object(type(self.r), '_current_own_order_anchor', lambda _self: anchor):
            return self.r._request_post_drain_recovery()

    async def test_own_cancels_only_renew_without_full_recovery(self):
        self.assertTrue(self.drain(self.anchor))
        self.assertFalse(self.r.recovery_requested.is_set())
        self.assertFalse(self.r._post_drain_recovery_pending)
        self.assertEqual(self.r.status()['post_drain_renewals'], 1)
        self.assertFalse(self.drain(self.anchor))  # One obligation, consumed once.

    async def test_economic_change_since_the_last_proof_still_fully_recovers(self):
        self.assertTrue(self.drain(None))  # e.g. a fill moved the history floor.
        self.assertTrue(self.r.recovery_requested.is_set())
        self.assertEqual(self.r._recovery_reason, 'post_drain')
        self.assertEqual(self.r.status()['post_drain_renewals'], 0)

    async def test_stop_or_pause_drain_still_fully_recovers(self):
        with patch.object(type(self.r), 'entry_pause_active', property(lambda _self: True)):
            self.assertTrue(self.drain(self.anchor))
        self.assertTrue(self.r.recovery_requested.is_set())

    async def test_safety_pause_still_fully_recovers(self):
        # Exhausted recovery sets the safety pause, which is an entry pause.
        self.r.recovery_state = 'blocked_retry_exhausted'
        self.assertTrue(self.drain(self.anchor))
        self.assertTrue(self.r.recovery_requested.is_set())


if __name__ == '__main__':
    unittest.main()
