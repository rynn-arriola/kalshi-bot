"""Bounded catalog exploration plans, never venue subscription/order mutations."""
from dataclasses import replace
from datetime import timedelta
from types import MappingProxyType
import unittest

from kalshi_bot.discovery_candidates import CandidateDiscovery
from kalshi_bot.incentive_discovery import IncentiveCatalog
from kalshi_bot.selection_runtime import ProgramObservation
from kalshi_bot.values import InvalidData
from test_bot_engine import NOW, program
import test_bot_incentive_discovery as fixtures


def catalog(count=50):
    observations = {}
    for i in range(count):
        ticker = f'M{i:03}'
        p = program(ticker=ticker,program_id=f'p{i}',pool_centicents=1000000-i)
        observations[ticker] = ProgramObservation((p,),NOW,NOW+timedelta(seconds=60))
    return IncentiveCatalog(1,MappingProxyType(observations),frozenset(),NOW,
                            NOW+timedelta(seconds=60),100,160,1,count,100)


class CandidateTests(unittest.TestCase):
    def setUp(self): self.d = CandidateDiscovery()

    def test_eligibility_filters_candidates_and_incumbents_but_never_owners(self):
        result = self.choose(eligible=frozenset(('M002','M003')),
                             protected=('M000',), incumbents=('M001',))
        self.assertEqual(result.tickers, ('M000','M002','M003'))
        self.assertEqual(result.protected, ('M000',))
        self.assertEqual(result.deferred, 0)
        with self.assertRaises(InvalidData):
            self.choose(eligible={'M000'})

    def choose(self, data=None, **kwargs):
        args = dict(now=NOW,budget=10)
        args.update(kwargs)
        return self.d.choose(data if data is not None else catalog(),**args)

    def test_head_is_retained_and_tail_eventually_covers_universe(self):
        seen = set()
        data = catalog()
        for _ in range(10):
            result = self.choose(data)
            self.assertEqual(result.tickers[:2],('M000','M001'))
            self.assertEqual(len(result.tickers),10)
            self.assertEqual(len(set(result.tickers)),10)
            seen.update(result.tickers)
        self.assertEqual(seen,set(data.observations))
        self.assertFalse(result.authorized)

    def test_protected_outside_catalog_never_evicted(self):
        result = self.choose(protected=('OWNED',),incumbents=('M045',))
        self.assertEqual(result.tickers[:2],('OWNED','M045'))
        self.assertEqual(result.protected,('OWNED',))

    def test_budget_is_not_a_fixed_sixty_or_order_target(self):
        self.assertEqual(len(self.choose(catalog(100),budget=3).tickers),3)
        self.assertEqual(len(self.choose(catalog(100),budget=75).tickers),75)
        self.assertEqual(len(self.choose(catalog(2),budget=75).tickers),2)

    def test_saturation_preserves_owners_or_fails_no_truncation(self):
        owners = tuple(f'O{i}' for i in range(10))
        self.assertEqual(self.choose(protected=owners).tickers,owners)
        with self.assertRaises(InvalidData): self.choose(protected=owners,budget=9)

    def test_stale_catalog_retains_only_owners(self):
        result = self.choose(now=NOW+timedelta(seconds=60),protected=('OWNED',))
        self.assertEqual(result.tickers,('OWNED',))
        self.assertIsNone(result.source)

    def test_unsupported_or_ended_programs_are_not_candidates(self):
        data = catalog(3)
        values = dict(data.observations)
        for ticker, field in (('M000',dict(paid_out=True)),
                              ('M001',dict(max_reward_centicents=10000)),
                              ('M002',dict(end=NOW))):
            o = values[ticker]
            values[ticker] = replace(o,programs=(replace(o.programs[0],**field),))
        self.assertFalse(self.choose(replace(data,observations=MappingProxyType(values))).tickers)

    def test_invalid_scopes_and_duplicate_owners_fail(self):
        for args in (dict(budget=0),dict(budget=1025),dict(protected=('A','A')),
                     dict(incumbents=['A'])):
            with self.assertRaises(InvalidData): self.choose(**args)
        with self.assertRaises(InvalidData): self.d.choose({},now=NOW,budget=10)


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.f = fixtures.DiscoveryTests()
        await self.f.asyncSetUp()

    async def asyncTearDown(self): await self.f.asyncTearDown()

    async def test_catalog_to_candidate_plan_does_not_change_subscriptions(self):
        self.f.pages[0]['incentive_programs'] += [fixtures.row('B','b')]
        await self.f.refresh()
        result = await self.f.s.discovery_candidates()
        self.assertEqual(set(result.tickers),{'A','B'})
        self.assertEqual(set(self.f.r.engine.market_shard),{'A'})
        self.assertFalse(result.authorized)

    async def test_account_or_catalog_change_during_await_keeps_old_scope(self):
        await self.f.refresh()
        original = self.f.r.risk_view
        async def changed():
            result = await original()
            self.f.d.request()
            return result
        self.f.r.risk_view = changed
        result = await self.f.s.discovery_candidates()
        self.assertEqual(result.protected,('A',))
        self.assertIsNone(result.source)

    async def test_missing_account_report_preserves_every_existing_scope(self):
        await self.f.refresh()
        self.f.r.account._invalidate()
        result = await self.f.s.discovery_candidates()
        self.assertEqual(result.protected,('A',))
        self.assertIsNone(result.source)


if __name__ == '__main__': unittest.main()
