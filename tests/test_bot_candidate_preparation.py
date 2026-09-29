"""Credential-free candidate preparation with synthetic public documents."""
import asyncio
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal as D
import unittest
from unittest.mock import patch

import kalshi_bot.candidate_preparation as candidate_preparation
from kalshi_bot.candidate_preparation import INCENTIVE_QUERY, prepare_candidates
from kalshi_bot.market_inputs import (SCHEDULED_RELEASE_CONDITION,
    SCHEDULED_RELEASE_REVIEW)
from kalshi_bot.rest import PageSet, ReadResult
from kalshi_bot.values import InvalidData
from test_bot_engine import NOW
from test_bot_incentive_discovery import row as program
from test_bot_market_inputs import market


class Reads:
    def __init__(self, programs, markets, milestones):
        self.programs = programs
        self.markets = {row['ticker']:row for row in markets}
        self.milestones = milestones
        self.calls = []

    async def collect(self, name, **params):
        self.calls.append((name, params))
        if name == 'incentives':
            return PageSet(tuple(deepcopy(self.programs)), 1, 100, name,
                           INCENTIVE_QUERY, True)
        if name == 'milestones':
            return PageSet(tuple(deepcopy(self.milestones)), 1, 100, name,
                           tuple(sorted((k,v) for k,v in params.items()
                                        if k not in {'max_pages','max_rows','byte_limit','coalesce_scope'})), True)
        raise AssertionError(name)

    async def read(self, name, **params):
        self.calls.append((name, params))
        requested = params['tickers'].split(',')
        return ReadResult({'markets':[deepcopy(self.markets[t]) for t in requested
                                      if t in self.markets]}, 100)


def milestone(event, name, hours=1):
    return dict(id=name, type='sports_game', start_date=(NOW+timedelta(hours=hours)).isoformat(),
                primary_event_tickers=[event])


class CandidatePreparationTests(unittest.IsolatedAsyncioTestCase):
    async def test_builds_exact_broad_scope_and_diverse_seed(self):
        markets = [{**market('A'), 'event_ticker':'E1', 'exchange_index':2,
                    'can_close_early':False},
                   {**market('B'), 'event_ticker':'E1'},
                   {**market('C'), 'event_ticker':'E2'}]
        programs = [program('A','pa',period_reward=3000000),
                    program('B','pb',period_reward=2000000),
                    program('C','pc',period_reward=1000000)]
        reads = Reads(programs, markets, [milestone('E1','M1'), milestone('E2','M2')])
        result = await prepare_candidates(reads, now=NOW, max_reviews=2, seed_capacity=2)
        self.assertEqual(tuple(r.ticker for r in result.reviews), ('A','C'))
        self.assertEqual(result.initial_tickers, ('A','C'))
        self.assertEqual(result.exchange_indices, (0,2))
        self.assertFalse(any(r.early_close_reviewed for r in result.reviews))
        self.assertEqual(result.reviews[0].review_reference, 'automatic-primary-milestone-v1')
        self.assertEqual(result.reviews[0].valid_until, NOW+timedelta(hours=3))
        self.assertEqual({name for name,_ in reads.calls}, {'incentives','markets','milestones'})

    async def test_requires_one_future_primary_milestone_and_supported_market(self):
        markets = [{**market('A'),'event_ticker':'E1'},
                   {**market('B'),'event_ticker':'E2','market_type':'scalar'}]
        reads = Reads([program('A','pa'),program('B','pb')], markets,
            [milestone('E1','M1'), milestone('E1','M2',hours=2), milestone('E2','M3')])
        with self.assertRaisesRegex(InvalidData, 'no current reward market'):
            await prepare_candidates(reads, now=NOW)

    async def test_rejects_duplicate_market_identity_from_public_scope(self):
        class DuplicateReads(Reads):
            async def read(self, name, **params):
                value = {**market('A'),'event_ticker':'E1'}
                return ReadResult({'markets':[value,value]},100)
        reads = DuplicateReads([program('A','pa')], [], [milestone('E1','M1')])
        with self.assertRaisesRegex(InvalidData, 'response scope'):
            await prepare_candidates(reads, now=NOW)

    async def test_automatic_scope_rejects_unreviewed_early_close(self):
        early = {**market('A'), 'event_ticker':'E1', 'can_close_early':True,
                 'early_close_condition':'Threshold can be reached before the milestone.'}
        regular = {**market('B'), 'event_ticker':'E2'}
        reads = Reads([program('A','pa'),program('B','pb')], [early,regular],
                      [milestone('E1','M1'), milestone('E2','M2')])
        result = await prepare_candidates(reads, now=NOW)
        self.assertEqual(tuple(r.ticker for r in result.reviews), ('B',))
        self.assertIn(('early_close_unreviewed',1), result.excluded)

    async def test_reviews_exact_scheduled_release_family(self):
        release = {**market('A'), 'event_ticker':'E1', 'can_close_early':True,
            'early_close_condition':SCHEDULED_RELEASE_CONDITION,
            'occurrence_datetime':(NOW+timedelta(hours=2)).isoformat()}
        binding = milestone('E1','M1') | {'type':'company_report'}
        result = await prepare_candidates(Reads([program('A','pa')], [release],
            [binding]), now=NOW)
        review = result.reviews[0]
        self.assertTrue(review.early_close_reviewed)
        self.assertEqual(review.review_reference, SCHEDULED_RELEASE_REVIEW)

    async def test_scheduled_release_requires_reviewed_type_and_safe_clock(self):
        release = {**market('A'), 'event_ticker':'E1', 'can_close_early':True,
            'early_close_condition':SCHEDULED_RELEASE_CONDITION,
            'occurrence_datetime':(NOW+timedelta(hours=2)).isoformat()}
        regular = {**market('B'), 'event_ticker':'E2'}
        programs = [program('A','pa'), program('B','pb')]
        unsupported = milestone('E1','M1') | {'type':'sports_game'}
        result = await prepare_candidates(Reads(programs, [release,regular],
            [unsupported,milestone('E2','M2')]), now=NOW)
        self.assertEqual(tuple(r.ticker for r in result.reviews), ('B',))
        self.assertIn(('early_close_unreviewed',1), result.excluded)

        conflicting = milestone('E1','M1',hours=3) | {'type':'company_report'}
        result = await prepare_candidates(Reads(programs, [release,regular],
            [conflicting,milestone('E2','M2')]), now=NOW)
        self.assertEqual(tuple(r.ticker for r in result.reviews), ('B',))
        self.assertIn(('scheduled_release_timing_conflict',1), result.excluded)

    async def test_imminent_binding_is_not_discarded_before_ambiguity_check(self):
        reads = Reads([program('A','pa')], [{**market('A'),'event_ticker':'E1'}],
                      [milestone('E1','IMMINENT',hours=.05),
                       milestone('E1','LATER',hours=2)])
        with self.assertRaisesRegex(InvalidData, 'no current reward market'):
            await prepare_candidates(reads, now=NOW)

    async def test_single_imminent_binding_is_excluded_explicitly(self):
        reads = Reads([program('A','pa')], [{**market('A'),'event_ticker':'E1'}],
                      [milestone('E1','IMMINENT',hours=.05)])
        with self.assertRaisesRegex(InvalidData, 'no current reward market'):
            await prepare_candidates(reads, now=NOW)

    async def test_market_batches_overlap_independent_milestone_census(self):
        class ConcurrentReads(Reads):
            def __init__(self, *args):
                super().__init__(*args)
                self.active = self.high_water = 0
            async def _turn(self, call):
                self.active += 1
                self.high_water = max(self.high_water, self.active)
                try:
                    await asyncio.sleep(.01)
                    return await call()
                finally:
                    self.active -= 1
            async def collect(self, name, **params):
                return await self._turn(lambda:super(ConcurrentReads,self).collect(
                    name, **params))
            async def read(self, name, **params):
                return await self._turn(lambda:super(ConcurrentReads,self).read(
                    name, **params))
        rows = [{**market(ticker),'event_ticker':'E'+ticker} for ticker in ('A','B')]
        reads = ConcurrentReads([program('A','pa'),program('B','pb')], rows,
            [milestone('EA','MA'),milestone('EB','MB')])
        with patch.object(candidate_preparation,'_chunks',
                          return_value=(('A',),('B',))):
            result = await prepare_candidates(reads, now=NOW)
        self.assertEqual(len(result.reviews),2)
        self.assertGreaterEqual(reads.high_water,2)
        self.assertLessEqual(reads.high_water,3)


class SavedScanLaunchTests(unittest.IsolatedAsyncioTestCase):
    """D-159: a fresh saved full-market scan chooses most of the launch scope."""
    def reads(self, tickers, pools, events=None):
        events = events or {t: 'E'+t for t in tickers}
        rows = [{**market(t), 'event_ticker': events[t]} for t in tickers]
        programs = [program(t, 'p'+t, period_reward=pools[t]) for t in tickers]
        return Reads(programs, rows, [milestone(e, 'M'+e) for e in sorted(set(events.values()))])

    async def test_scanned_markets_come_first_by_reward_left_even_within_one_event(self):
        pools = dict(A=1000000, B=2000000, C=3000000, D=4000000)
        reads = self.reads('ABCD', pools, events=dict(A='E1', B='E1', C='E2', D='E3'))
        result = await prepare_candidates(reads, now=NOW, max_reviews=4, seed_capacity=2,
                                          scan_scores={'A': D(3), 'B': D(5), 'C': D(0)})
        self.assertEqual(tuple(r.ticker for r in result.reviews), ('B', 'A', 'D', 'C'))
        self.assertEqual(result.initial_tickers, ('B', 'A'))
        self.assertEqual(result.scanned, 2)

    async def test_one_eighth_of_the_scope_stays_on_the_old_order(self):
        tickers = 'ABCDEFGHI'
        pools = {t: 1000000*(i+1) for i, t in enumerate(tickers)}  # I has the best hint.
        scan = {t: D(100-i) for i, t in enumerate(tickers)}         # I scores lowest.
        result = await prepare_candidates(self.reads(tickers, pools), now=NOW,
                                          max_reviews=8, scan_scores=scan)
        self.assertEqual(result.scanned, 7)
        self.assertEqual(tuple(r.ticker for r in result.reviews), tuple('ABCDEFG')+('I',))

    async def test_scanned_markets_still_pass_every_eligibility_check(self):
        early = {**market('A'), 'event_ticker': 'E1', 'can_close_early': True,
                 'early_close_condition': 'Threshold can be reached before the milestone.'}
        reads = Reads([program('A', 'pa'), program('B', 'pb')],
                      [early, {**market('B'), 'event_ticker': 'E2'}],
                      [milestone('E1', 'M1'), milestone('E2', 'M2')])
        result = await prepare_candidates(reads, now=NOW, scan_scores={'A': D(9), 'X': D(8)})
        self.assertEqual(tuple(r.ticker for r in result.reviews), ('B',))
        self.assertEqual(result.scanned, 0)

    async def test_project_contracts_stay_in_scope_and_are_seeded_first(self):
        """D-161: projects survive restarts even when the scan or hint ranks
        them low; the rest of the scope is chosen as before."""
        tickers = 'ABCDEFGHI'
        pools = {t: 1000000*(i+1) for i, t in enumerate(tickers)}   # A has the worst hint
        scan = {t: D(100-i) for i, t in enumerate(tickers)}         # A scores best, B second
        result = await prepare_candidates(self.reads(tickers, pools), now=NOW, max_reviews=4,
                                          seed_capacity=2, scan_scores=scan, pinned=('I', 'H', 'Z'))
        self.assertEqual(tuple(r.ticker for r in result.reviews)[:2], ('I', 'H'))   # usual order
        self.assertEqual(result.initial_tickers, ('I', 'H'))
        self.assertEqual((result.pinned, len(result.reviews)), (2, 4))
        self.assertEqual(tuple(r.ticker for r in result.reviews)[2:], ('A', 'B'))
        plain = await prepare_candidates(self.reads(tickers, pools), now=NOW, max_reviews=2,
                                         pinned=('I', 'H', 'G'))
        self.assertEqual((tuple(r.ticker for r in plain.reviews), plain.pinned), (('I', 'H'), 2))
        hint = await prepare_candidates(self.reads(tickers, pools), now=NOW, max_reviews=3,
                                        pinned=('A',))
        self.assertEqual(tuple(r.ticker for r in hint.reviews)[0], 'A')
        self.assertEqual(len(hint.reviews), 3)

    async def test_without_scan_scores_the_scope_is_unchanged(self):
        pools = dict(A=1000000, B=2000000, C=3000000)
        plain = await prepare_candidates(self.reads('ABC', pools), now=NOW, max_reviews=2)
        empty = await prepare_candidates(self.reads('ABC', pools), now=NOW, max_reviews=2,
                                         scan_scores={})
        self.assertEqual(plain, empty)
        self.assertEqual(plain.scanned, 0)


if __name__ == '__main__':
    unittest.main()
