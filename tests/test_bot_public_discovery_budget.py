"""Deterministic local pacing against a synthetic throttled public service."""
import unittest

from kalshi_bot.rest import PublicDiscoveryBudget, TokenBudget


class PublicBudgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_cold_start_and_idle_do_not_bank_a_request_burst(self):
        tick = [0.]
        async def sleep(delay): tick[0] += delay
        budget = PublicDiscoveryBudget(clock=lambda: tick[0], sleep=sleep)
        stamps = []
        for i in range(20):
            if i == 10: tick[0] += 5
            await budget.acquire('/markets', tick[0]+30)
            stamps.append(tick[0])
        self.assertGreaterEqual(stamps[0], .02)
        self.assertTrue(all(b-a >= .01999 for a,b in zip(stamps,stamps[1:])))
        self.assertLessEqual(budget.tokens, 1)

    async def test_429_rate_is_shared_across_pages_and_concurrent_failures(self):
        tick = [0.]
        async def sleep(delay): tick[0] += delay
        budget = PublicDiscoveryBudget(clock=lambda: tick[0], sleep=sleep)
        budget.throttle(.5)
        budget.throttle(.5)
        self.assertEqual(budget.rate,25)
        await budget.acquire('/milestones', 30)
        self.assertGreaterEqual(tick[0],.5)
        budget.throttle(.5)
        self.assertEqual(budget.rate,12)
        self.assertEqual(budget.tokens,0)
        self.assertEqual(budget.throttles,3)

    async def test_simulated_service_converges_without_per_page_retry_storm(self):
        tick = [0.]
        async def sleep(delay): tick[0] += delay
        budget = PublicDiscoveryBudget(clock=lambda: tick[0], sleep=sleep)
        last = -1.
        failures = 0
        for page in range(30):
            for attempt in range(3):
                await budget.acquire('/markets' if page%2 else '/milestones',tick[0]+30)
                if tick[0]-last < .1-1e-9:  # Synthetic service: 10 requests/s.
                    failures += 1
                    budget.throttle(.5*2**attempt)
                else:
                    last=tick[0]
                    break
            else: self.fail('page exhausted retries')
        self.assertLessEqual(failures,3)
        self.assertLessEqual(budget.rate,10)
        self.assertGreaterEqual(budget.rate,1)

    async def test_authenticated_budget_keeps_verified_rate_after_429(self):
        budget=TokenBudget(rate=200,capacity=600,default_cost=10)
        budget.throttle(.5)
        self.assertEqual((budget.rate,budget.capacity),(200,600))
