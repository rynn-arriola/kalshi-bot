"""D-135 adaptive re-entry lockout after protective withdrawals; offline owners."""
import unittest

from kalshi_bot.fill_risk import FillRiskPolicy
from kalshi_bot.values import InvalidData
import test_bot_concurrent_withdrawals as concurrent


class CooldownScheduleTests(unittest.TestCase):
    def test_first_withdrawal_short_then_doubles_to_the_original_cap(self):
        policy = FillRiskPolicy()
        self.assertEqual([policy.cooldown_for(n) for n in range(1, 7)],
                         [60, 120, 240, 300, 300, 300])
        self.assertEqual(policy.cooldown_for(10**6), 300)  # No overflow.

    def test_invalid_schedule_rejected(self):
        for kwargs in (dict(cooldown_min_seconds=0), dict(cooldown_min_seconds=301),
                       dict(cooldown_min_seconds=float('inf'))):
            with self.subTest(**kwargs), self.assertRaises(InvalidData):
                FillRiskPolicy(**kwargs)


class AdaptiveCooldownTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = concurrent.ConcurrentWithdrawalTests.asyncSetUp
    asyncTearDown = concurrent.ConcurrentWithdrawalTests.asyncTearDown
    working = concurrent.ConcurrentWithdrawalTests.working
    latch_b = concurrent.ConcurrentWithdrawalTests.latch_b

    def lockout(self):
        return self.m._risk_cooldown['B']-self.r.clock()

    def withdraw_and_finish(self):
        self.assertTrue(self.latch_b())
        at_latch = self.lockout()
        self.m._finish_secondary('B')
        return at_latch, self.lockout()

    async def test_repeats_back_off_and_an_hour_of_calm_resets(self):
        self.assertEqual(self.withdraw_and_finish(), (60, 60))
        self.b.advance(61)
        self.assertTrue(self.m.entry_allowed('B', 'any'))  # Re-entry after 60 s.
        self.assertEqual(self.withdraw_and_finish(), (120, 120))
        self.b.advance(121)
        self.assertEqual(self.withdraw_and_finish(), (240, 240))
        self.b.advance(241)
        self.assertEqual(self.withdraw_and_finish(), (300, 300))
        self.b.advance(3601)
        self.assertEqual(self.withdraw_and_finish(), (60, 60))

    async def test_lockout_still_blocks_reentry_until_it_expires(self):
        self.withdraw_and_finish()
        self.b.advance(59)
        self.assertFalse(self.m.entry_allowed('B', 'any'))
        self.b.advance(2)
        self.assertTrue(self.m.entry_allowed('B', 'any'))


if __name__ == '__main__':
    unittest.main()
