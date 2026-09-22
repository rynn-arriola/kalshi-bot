"""Reviewed discovery scope, separate from current book subscriptions.

No venue I/O or inferred timing. The existing metadata owner revalidates each
binding, fee, grid and deadline after admission and before ranking/dispatch.
"""
from collections import Counter

from .values import utc


class CandidateInputs:
    def __init__(self, runtime, exchange_indices):
        self.runtime = runtime
        self.reviews = runtime.market_inputs.candidate_reviews
        self.exchanges = frozenset(exchange_indices)
        self.counts = {}
        self.samples = ()
        self.observed_at = None

    def blockers(self, ticker, now):
        r = self.runtime
        review = self.reviews.get(ticker)
        if ticker not in r.live_session.tickers:
            return ('timing_review_missing',)
        if review is None or utc(now) >= review.valid_until:
            return ('timing_review_missing',)
        inputs = r.market_inputs
        profile = inputs.fee_profile
        if profile is None or utc(now) >= profile.valid_until:
            return ('fee_profile_missing',)
        scheduler = r.metadata_scheduler
        if scheduler is not None and (ticker in scheduler.exhausted
                or scheduler.retired.get(ticker, (0, False, 0))[1]):
            return ('metadata_retry_exhausted',)
        result = inputs.results.get(ticker)
        if result is not None and result.terms.observed_at <= now < result.terms.valid_until:
            if result.blockers:
                return result.blockers
            if not result.terms.active:
                return ('market_inactive',)
            if result.terms.deadline <= now:
                return ('entry_horizon_ended',)
        market = inputs.values.get(('market', ticker))
        if market is not None and inputs._fresh(market) and market.value.exchange not in self.exchanges:
            return ('exchange_not_configured',)
        return ()

    def eligible(self, catalog, now):
        """Once per bounded discovery pass, not per book tick. Counts are diagnostic."""
        counts, samples, eligible = Counter(), [], set()
        for ticker in catalog.observations:
            reasons = self.blockers(ticker, now)
            if reasons:
                counts.update(reasons)
                if len(samples) < 32:
                    samples.append((ticker, reasons))
            else:
                eligible.add(ticker)
        self.counts, self.samples = dict(counts), tuple(samples)
        self.observed_at = utc(now).isoformat()
        return frozenset(eligible)

    def status(self):
        return dict(reviewed_candidates=len(self.reviews), skipped_counts=self.counts,
                    skipped_samples=self.samples, samples_limit=32,
                    observed_at=self.observed_at,
                    universal_timing_inference=False)
