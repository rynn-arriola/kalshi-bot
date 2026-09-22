"""Reviewed discovery/metadata boundaries; synthetic local inputs only."""
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
from types import SimpleNamespace
import unittest

from kalshi_bot.candidate_inputs import CandidateInputs
from kalshi_bot.market_inputs import ExitInputService, FeeProfile
from kalshi_bot.values import InvalidData
from test_bot_market_inputs import Reads, review, market, NOW
from test_bot_selection import terms


class CandidateInputTests(unittest.TestCase):
    def setUp(self):
        self.reviews = (review(market('A')), review(market('B')))
        self.metadata = ExitInputService(Reads(), ('A',), now=lambda: NOW, ttl=60,
            timing_reviews=self.reviews[:1], candidate_reviews=self.reviews,
            fee_profile=FeeProfile(D('.0001'), 'fixture', NOW+timedelta(hours=2)))
        self.runtime = SimpleNamespace(market_inputs=self.metadata,
            live_session=SimpleNamespace(tickers=frozenset(('A','B'))), metadata_scheduler=None)
        self.f = CandidateInputs(self.runtime, (0,1))

    def test_unreviewed_and_expired_bindings_are_not_eligible(self):
        self.assertEqual(self.f.blockers('B', NOW), ())
        self.assertEqual(self.f.blockers('C', NOW), ('timing_review_missing',))
        self.assertEqual(self.f.blockers('B', NOW+timedelta(hours=2)), ('timing_review_missing',))
        self.runtime.live_session.tickers = frozenset(('A',))
        self.assertEqual(self.f.blockers('B', NOW), ('timing_review_missing',))

    def test_review_registry_survives_removal_but_explicit_revocation_does_not(self):
        self.metadata.rebind_scope(('B',))
        self.assertEqual(self.metadata.reviews, {'B':self.reviews[1]})
        self.metadata.rebind_scope(('A',))
        self.assertEqual(self.metadata.reviews, {'A':self.reviews[0]})
        self.metadata.set_review('A', None)
        self.assertEqual(self.f.blockers('A', NOW), ('timing_review_missing',))
        self.metadata.rebind_scope(('B',))
        self.metadata.rebind_scope(('A',))
        self.assertNotIn('A', self.metadata.reviews)

    def test_fee_missing_conflicts_deadlines_and_exchange_report_reason(self):
        self.metadata.fee_profile = None
        self.assertEqual(self.f.blockers('B', NOW), ('fee_profile_missing',))
        self.metadata.fee_profile = FeeProfile(D('.0001'), 'fixture', NOW+timedelta(hours=2))
        term = replace(terms(), observed_at=NOW, valid_until=NOW+timedelta(seconds=30),
                       event_risk_at=NOW+timedelta(hours=1))
        self.metadata.results['B'] = SimpleNamespace(terms=term, blockers=('timing_review_conflict',))
        self.assertEqual(self.f.blockers('B', NOW), ('timing_review_conflict',))
        self.metadata.results['B'] = SimpleNamespace(terms=replace(term, event_risk_at=NOW), blockers=())
        self.assertEqual(self.f.blockers('B', NOW), ('entry_horizon_ended',))
        self.metadata.results.clear()
        self.metadata.values[('market','B')] = SimpleNamespace(value=SimpleNamespace(exchange=9))
        self.metadata._fresh = lambda _: True
        self.assertEqual(self.f.blockers('B', NOW), ('exchange_not_configured',))

    def test_exhaustion_remains_visible_after_scope_retirement(self):
        self.runtime.metadata_scheduler = SimpleNamespace(exhausted={'B'}, retired={})
        self.assertEqual(self.f.blockers('B', NOW), ('metadata_retry_exhausted',))
        self.runtime.metadata_scheduler = SimpleNamespace(exhausted=set(), retired={'B':(3,True,123)})
        self.assertEqual(self.f.blockers('B', NOW), ('metadata_retry_exhausted',))

    def test_registry_duplicate_and_conflicting_active_binding_rejected(self):
        for rows in ((self.reviews[0],self.reviews[0]),
                     (replace(self.reviews[0], rules_hash='a'*64),)):
            with self.assertRaises(InvalidData):
                ExitInputService(Reads(), ('A',), now=lambda:NOW, ttl=60,
                    timing_reviews=self.reviews[:1], candidate_reviews=rows)

    def test_catalog_skip_samples_bounded_without_dropping_counts(self):
        c = SimpleNamespace(observations={f'UNKNOWN{i}':None for i in range(10000)})
        self.assertEqual(self.f.eligible(c, NOW), frozenset())
        self.assertEqual(self.f.counts, {'timing_review_missing':10000})
        self.assertEqual(len(self.f.samples), 32)
        self.assertEqual(self.f.status()['observed_at'], NOW.isoformat())


if __name__ == '__main__':
    unittest.main()
