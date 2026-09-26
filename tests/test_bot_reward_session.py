"""D-137 reward session measurement: unknown-time reasons and size what-if."""
from datetime import timedelta
from decimal import Decimal as D
import unittest

from kalshi_bot.quoting import Quote, snapshot_score
from kalshi_bot.reward_tracker import RewardTracker
from kalshi_bot.values import InvalidData
from test_bot_engine import NOW, BANDS, book, program


class RewardSessionTests(unittest.TestCase):
    def setUp(self):
        self.t = RewardTracker(scope='fixture-account-0')
        self.p = program(pool_centicents=72000000)
        self.quotes = (Quote('bid', D('.5'), D(10)), Quote('ask', D('.6'), D(10)))
        self.book = book()

    def observe(self, offset, continuity=('epoch', 1), reflected=True):
        self.t.observe_many((self.p,), book=self.book, bands=BANDS, quotes=self.quotes,
            reflected_known=reflected, at=NOW+timedelta(seconds=offset),
            valid_until=NOW+timedelta(seconds=offset+5), continuity=continuity)

    def test_what_if_scores_larger_own_size_on_the_same_book(self):
        for offset in range(0, 5):
            self.observe(offset)
        s = self.t.session_status()
        base = D(s['estimate_usd'])
        two, three = D(s['whatif']['2x']['usd']), D(s['whatif']['3x']['usd'])
        self.assertGreater(base, 0)
        # Bigger own size raises our share, never more than proportionally.
        self.assertTrue(base < two <= 2*base)
        self.assertTrue(two < three <= 3*base)
        one = snapshot_score(self.book, self.p, BANDS, self.quotes, reflected=self.quotes)[2]
        doubled = tuple(Quote(q.side, q.yes_price, q.quantity*2) for q in self.quotes)
        expected = snapshot_score(self.book, self.p, BANDS, doubled, reflected=self.quotes)[2]
        self.assertEqual(two/base, expected/one)
        self.assertEqual(s['markets'][0]['ticker'], self.p.ticker)
        # The real estimate is unchanged by measuring counterfactuals.
        self.assertEqual(self.t.records[self.p.program_id].estimate, base)

    def test_unknown_time_is_labelled_by_cause(self):
        self.observe(0)
        self.observe(1, reflected=False)          # reflection could not be proven
        self.observe(2)                           # previous sample had no rate
        self.observe(3, continuity=('epoch', 2))  # source changed
        self.t.invalidate(self.p.ticker)
        self.observe(4)                           # sample dropped (e.g. recovery)
        self.observe(100)                         # long gap, e.g. stopped
        self.observe(101)
        self.observe(108)                         # beyond freshness window
        reasons = {k: D(v) for k, v in self.t.session_status()['unknown_by_reason'].items()}
        self.assertEqual(reasons, {'reflection_unverified': 2, 'continuity_changed': 1,
            'no_prior_sample': 1, 'not_running_or_long_gap': 96, 'stale_gap': 7})
        s = self.t.session_status()
        self.assertEqual(D(s['observed_seconds'])+D(s['unknown_seconds']), 108)

    def test_what_if_requires_a_qualified_rate(self):
        with self.assertRaises(InvalidData):
            self.t.record(self.p, at=NOW, valid_until=NOW, rate=None, whatif=(D(1), D(1)))
        with self.assertRaises(InvalidData):
            self.t.record(self.p, at=NOW, valid_until=NOW, rate=D('.1'), continuity=('e', 1),
                          qualified=True, whatif=(D(10**6), D(1)))


if __name__ == '__main__':
    unittest.main()
