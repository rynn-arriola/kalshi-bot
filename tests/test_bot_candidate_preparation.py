"""Credential-free candidate preparation with synthetic public documents."""
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal as D
import unittest

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


if __name__ == '__main__':
    unittest.main()
