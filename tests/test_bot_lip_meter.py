"""D-161 step 1: real-time LIP meter per contract (measurement only)."""
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from kalshi_bot.lip_meter import LipMeter, MINIMUM_PAYOUT, payout_after_floor
from kalshi_bot.quoting import Quote, program_plans
from kalshi_bot.ranking import seconds
from test_bot_engine import NOW, BANDS, book, program

QUOTES = (Quote('bid', D('0.50'), D(30)), Quote('ask', D('0.60'), D(30)))


def rate(prog, quotes=QUOTES, b=None):
    from decimal import localcontext
    share = program_plans(b or book(), (prog,), BANDS, now=NOW, market_open=True,
                          reflected=quotes, proposed=quotes)[0].snapshot_share
    with localcontext() as ctx:
        ctx.prec = 40
        return D(prog.pool_centicents)/10000/seconds(prog.end-prog.start)*share


def close(test, a, b):
    test.assertLess(abs(a-b), D('1e-20'), (a, b))


class MeterTests(unittest.TestCase):
    def setUp(self):
        self.p = program()
        self.markets = [('A', book(), BANDS, (self.p,), QUOTES)]

    def test_rate_is_the_bots_kalshi_scoring_of_our_resting_orders(self):
        m = LipMeter()
        m.sample(0, NOW, self.markets)
        self.assertGreater(m.rates['P'], 0)
        self.assertEqual(m.rates['P'], rate(self.p))

    def test_each_interval_earns_the_rate_seen_at_its_start(self):
        m = LipMeter()
        m.sample(0, NOW, self.markets)
        m.sample(5, NOW+timedelta(seconds=5), self.markets)
        m.sample(10, NOW+timedelta(seconds=10), [])        # orders gone at 10 s
        m.sample(15, NOW+timedelta(seconds=15), [])
        row = m.programs['P']
        close(self, row['earned'], rate(self.p)*10)
        self.assertEqual((row['seconds'], row['ticker'], row['first_at']), (D(10), 'A', NOW))

    def test_long_gaps_and_unknown_views_are_not_credited(self):
        m = LipMeter()
        m.sample(0, NOW, self.markets)
        m.sample(16, NOW, self.markets)                    # gap over 15 s
        self.assertEqual(m.programs['P']['earned'], 0)
        self.assertEqual(m.gaps, 1)
        m.sample(21, NOW, None)                            # unknown: 16-21 not credited
        m.sample(26, NOW, self.markets)                    # 21-26 follows an unknown
        self.assertEqual(m.programs['P']['earned'], 0)
        m.sample(31, NOW, self.markets)
        close(self, m.programs['P']['earned'], rate(self.p)*5)
        self.assertEqual(m.unknown, 1)

    def test_missing_book_or_bands_and_unscoreable_books_are_counted(self):
        m = LipMeter()
        m.sample(0, NOW, [('A', None, BANDS, (self.p,), QUOTES), ('A', book(), None, (self.p,), QUOTES)])
        self.assertEqual((m.unscored, m.errors, m.rates), (2, 0, {}))
        # Our 500 at .50 is not in a book holding only 100 there: not scoreable.
        m.sample(5, NOW, [('A', book(), BANDS, (self.p,), (Quote('bid', D('0.50'), D(500)),))])
        self.assertEqual(m.errors, 1)
        m.sample(10, NOW, [('A', book(), BANDS, (), QUOTES), ('A', book(), BANDS, (self.p,), ())])
        self.assertEqual((m.unscored, m.errors, m.programs), (2, 1, {}))

    def test_a_one_sided_book_scores_zero(self):
        m = LipMeter()
        thin = book(asks=())
        m.sample(0, NOW, [('A', thin, BANDS, (self.p,), (Quote('bid', D('0.50'), D(30)),))])
        self.assertEqual(m.rates['P'], 0)

    def test_the_dollar_floor_is_per_program(self):
        self.assertEqual(payout_after_floor(D('0.99')), 0)
        self.assertEqual(payout_after_floor(MINIMUM_PAYOUT), D(1))
        m = LipMeter()
        m.programs = {'a': dict(ticker='A', end=NOW+timedelta(hours=2), first_at=NOW, earned=D('1.50'), seconds=D(1)),
                      'b': dict(ticker='B', end=NOW+timedelta(hours=2), first_at=NOW, earned=D('0.90'), seconds=D(1)),
                      'c': dict(ticker='C', end=NOW-timedelta(hours=1), first_at=NOW, earned=D('5'), seconds=D(1))}
        s = m.status(NOW)
        self.assertEqual((s['live'], s['cleared_live'], s['payable_live_usd'], s['earned_live_usd']),
                         (2, 1, '1.5000', '2.4000'))
        self.assertEqual([t['ticker'] for t in s['top']], ['A', 'B'])
        self.assertEqual((s['top'][0]['cleared'], s['top'][1]['cleared']), (True, False))

    def test_capacity_prunes_old_ended_programs_first(self):
        m = LipMeter()
        m.CAPACITY = 1
        m.programs = {'old': dict(ticker='Z', end=NOW-timedelta(days=15), first_at=NOW, earned=D(0), seconds=D(0))}
        m.sample(0, NOW, self.markets)
        self.assertEqual(set(m.programs), {'P'})
        m.programs['recent'] = dict(ticker='Y', end=NOW-timedelta(days=1), first_at=NOW, earned=D(0), seconds=D(0))
        m.sample(5, NOW, [('B', book(), BANDS, (replace(self.p, program_id='Q', ticker='A'),), QUOTES)])
        self.assertNotIn('Q', m.programs)
        self.assertEqual(m.errors, 1)


class PersistenceTests(unittest.TestCase):
    def test_totals_survive_a_restart_and_old_programs_are_dropped(self):
        with TemporaryDirectory() as temp:
            path = Path(temp)/'lip_meter.json'
            m = LipMeter(path)
            p = program()
            m.sample(0, NOW, [('A', book(), BANDS, (p,), QUOTES)])
            m.sample(5, NOW, [('A', book(), BANDS, (p,), QUOTES)])
            m.programs['old'] = dict(ticker='Z', end=NOW-timedelta(days=15), first_at=NOW, earned=D(3), seconds=D(9))
            m.save(NOW)
            self.assertFalse(path.with_suffix('.tmp').exists())
            back = LipMeter(path).load()
            self.assertEqual(set(back.programs), {'P'})
            self.assertEqual(back.programs['P'], m.programs['P'])

    def rows(self, **specs):
        m = LipMeter()
        for pid, (earned, hours) in specs.items():
            m.programs[pid] = dict(ticker='T'+pid, end=NOW+timedelta(hours=hours), first_at=NOW,
                                   earned=D(earned), seconds=D(3600))
        return m

    def test_ending_soon_lists_what_will_and_will_not_pay(self):
        # D-173: programs end before markets do; show the deadline, soonest first.
        m = self.rows(A=('1.19', 90), B=('0.78', 42), C=('0.04', 10), D=('0.30', 200), E=('0.50', -1))
        soon = m.ending_soon(NOW)
        self.assertEqual([r['ticker'] for r in soon], ['TB', 'TA'])          # C too small, D too far, E ended
        self.assertEqual((soon[0]['pays'], soon[1]['pays']), (False, True))
        self.assertEqual((soon[0]['hours_left'], soon[0]['earned_usd']), (42.0, '0.7800'))
        self.assertEqual(m.status(NOW)['ending_soon'], soon)

    def test_a_credit_is_matched_to_the_closest_just_ended_program(self):
        # D-173: the 10-02 $1.43 credit could not be traced to a market.
        m = self.rows(G=('1.40', -6), M=('2.10', -20), Y=('1.45', -40), Z=('0.50', -3), L=('1.44', 5))
        match = m.match_credit(D('1.43'), NOW)
        self.assertEqual(match['best']['ticker'], 'TG')                       # Y ended too long ago, L live
        self.assertEqual([c['ticker'] for c in match['candidates']], ['TG', 'TM'])
        self.assertIsNone(self.rows().match_credit(D('1'), NOW)['best'])
        for i in range(60):
            m.match_credit(D('1'), NOW)
        self.assertEqual(len(m.payouts), m.PAYOUTS_KEPT)
        with TemporaryDirectory() as temp:
            m.path = Path(temp)/'lip_meter.json'
            m.save(NOW)
            back = LipMeter(m.path).load()
            self.assertEqual(back.payouts, m.payouts)
            m.path.write_text(json.dumps(dict(programs={}, payouts='bad')), encoding='utf-8')
            self.assertEqual(LipMeter(m.path).load().payouts, [])

    def test_missing_corrupt_or_oversized_files_start_empty(self):
        with TemporaryDirectory() as temp:
            path = Path(temp)/'lip_meter.json'
            self.assertEqual(LipMeter(path).load().programs, {})
            good = dict(ticker='A', end=NOW.isoformat(), first_at=NOW.isoformat(), earned='1', seconds='2')
            for bad in ('{', '[]', json.dumps(dict(programs={'P': good | dict(earned='-1')})),
                        json.dumps(dict(programs={'P': good | dict(earned='NaN')})),
                        json.dumps(dict(programs={'P': good | dict(end='x')})),
                        json.dumps(dict(programs={'P': {k: v for k, v in good.items() if k != 'ticker'}}))):
                path.write_text(bad, encoding='utf-8')
                self.assertEqual(LipMeter(path).load().programs, {}, bad)
            path.write_text(json.dumps(dict(programs={'P': good})), encoding='utf-8')
            self.assertEqual(LipMeter(path).load().programs['P']['earned'], D(1))
            m = LipMeter(path)
            m.BYTES_LIMIT = 5
            self.assertEqual(m.load().programs, {})
            self.assertIsNone(LipMeter().load().path)


if __name__ == '__main__':
    unittest.main()
