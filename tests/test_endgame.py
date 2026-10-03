"""D-175 Endgame Trader: per-sport rules on real Kalshi live-data shapes,
entry choice, fees, paper fills and the dry-run process (no network)."""
import importlib.util
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))

from kalshi_bot import endgame as E  # noqa: E402

POLICY = E.load_policy(ROOT/'config'/'endgame_policy.json')


def rule(sport):
    return POLICY.rules[sport]


# Soccer trades only the 2-option cup 'advances' markets (operator: "Advances",
# "I dont want the one with 3 options"); the 90-minute rule stays testable.
SOCCER_90 = E.SportRule(kind='minute', types=('soccer_tournament_multi_leg',), min_minute=90)


def live(**kw):
    return dict(status='inprogress', widget_status='live', **kw)


def tennis(one, two):
    def rounds(scores):
        return [dict(outcome=o, score=s) for o, s in scores]
    return dict(status='live', widget_status='live', competitor1_round_scores=rounds(one),
                competitor2_round_scores=rounds(two))


def market(ticker, team, bid, ask, status='active'):
    return dict(ticker=ticker, yes_sub_title=team, yes_bid_dollars=bid, yes_ask_dollars=ask, status=status)


class PolicyTest(unittest.TestCase):
    def test_config_loads_dry_with_all_sports(self):
        self.assertTrue(POLICY.enabled)
        self.assertFalse(POLICY.live_orders)
        self.assertEqual((POLICY.data_min_price, POLICY.min_price, POLICY.max_price),
                         (D('0.90'), D('0.95'), D('0.99')))
        # Operator 10-03: "change the risk to 30 usd and stop loss to 90 usd a day".
        self.assertEqual((POLICY.risk_per_trade_usd, POLICY.daily_loss_stop_usd), (D(30), D(90)))
        self.assertEqual(E.contracts_for(POLICY.risk_per_trade_usd, POLICY.max_price), 30)
        self.assertEqual(set(POLICY.rules), {'soccer', 'soccer-3way', 'basketball', 'football', 'hockey', 'tennis',
                                             'table-tennis', 'esports', 'baseball', 'rugby', 'volleyball'})
        self.assertEqual({s for s, r in POLICY.rules.items() if r.experimental},
                         {'rugby', 'volleyball', 'soccer', 'soccer-3way'})
        self.assertEqual([s for s, _ in POLICY.rules_for('basketball_game')], ['basketball'])
        self.assertEqual(POLICY.rules_for('cricket_match'), [])
        # Soccer: the 2-option cup 'advances' markets; the 3-option 90-minute game
        # market is tracked on paper only, as its own sport (operator: "add it for paper").
        rules = dict(POLICY.rules_for('soccer_tournament_multi_leg'))
        soccer, three = rules['soccer'], rules['soccer-3way']
        self.assertEqual(set(rules), {'soccer', 'soccer-3way'})
        self.assertEqual((soccer.kind, soccer.events), ('advance', 'advance'))
        self.assertEqual((three.kind, three.events, three.experimental), ('minute', 'winner', True))
        self.assertEqual(E.rule_events(soccer, ['KXCOPADELREYADVANCE-26OCT03BAZATL', 'KXCOPADELREYGAME-26OCT03BAZATL',
                                                'KXCOPADELREYSPREAD-26OCT03BAZATL']),
                         ['KXCOPADELREYADVANCE-26OCT03BAZATL'])

    def test_bad_policy_rejected(self):
        with self.assertRaises(ValueError):
            E.Policy(min_price=D('0.95'), data_min_price=D('0.96'))
        with self.assertRaises(ValueError):
            E.Policy(max_price=D('1.00'))
        with self.assertRaises(ValueError):
            E.SportRule(kind='cricket', types=('cricket_match',))


class AlmostOverTest(unittest.TestCase):
    def test_soccer_minute_and_tie(self):
        game = dict(status='live', widget_status='live', time="90+6'",
                    home_same_game_score=2, away_same_game_score=5)
        self.assertTrue(E.almost_over(SOCCER_90, 'soccer_tournament_multi_leg', game))
        self.assertFalse(E.almost_over(SOCCER_90, 'soccer_tournament_multi_leg', dict(game, time="89'")))
        self.assertFalse(E.almost_over(SOCCER_90, 'soccer_tournament_multi_leg',
                                       dict(game, home_same_game_score=5)))

    def test_soccer_same_game_score_not_aggregate(self):
        game = dict(status='live', widget_status='live', time="91'", home_same_game_score=1,
                    away_same_game_score=1, home_aggregate_score=3, away_aggregate_score=1)
        self.assertFalse(E.almost_over(SOCCER_90, 'soccer_tournament_multi_leg', game))

    def test_soccer_advance_normal_time_extra_time_penalties(self):
        r = rule('soccer')
        game = dict(status='live', widget_status='live', time="90+3'", home_same_game_score=1,
                    away_same_game_score=0, home_aggregate_score=1, away_aggregate_score=0)
        self.assertTrue(E.almost_over(r, 'soccer_tournament_multi_leg', game))
        self.assertFalse(E.almost_over(r, 'soccer_tournament_multi_leg', dict(game, time="89'")))
        # Extra time: 91'-119' has up to half an hour left; 120'+ counts.
        self.assertFalse(E.almost_over(r, 'soccer_tournament_multi_leg', dict(game, time="105'")))
        self.assertFalse(E.almost_over(r, 'soccer_tournament_multi_leg', dict(game, time="119'")))
        self.assertTrue(E.almost_over(r, 'soccer_tournament_multi_leg', dict(game, time="120+1'")))
        # Penalties never.
        self.assertFalse(E.almost_over(r, 'soccer_tournament_multi_leg', dict(game, show_penalties=True)))
        self.assertFalse(E.almost_over(r, 'soccer_tournament_multi_leg', dict(game, match_status='penalties')))
        # Two legs: the aggregate decides. 1-0 tonight but 1-2 on aggregate is still a lead (for the away side).
        two_leg = dict(game, home_aggregate_score=1, away_aggregate_score=2)
        self.assertTrue(E.almost_over(r, 'soccer_tournament_multi_leg', two_leg))
        level = dict(game, home_aggregate_score=2, away_aggregate_score=2)
        self.assertFalse(E.almost_over(r, 'soccer_tournament_multi_leg', level))
        # No aggregate: the same-game score.
        single = {k: v for k, v in game.items() if 'aggregate' not in k}
        self.assertTrue(E.almost_over(r, 'soccer_tournament_multi_leg', single))
        self.assertFalse(E.almost_over(r, 'soccer_tournament_multi_leg', dict(single, away_same_game_score=1)))

    def test_advance_market_must_settle_soon(self):
        r = rule('soccer')
        now = datetime(2026, 10, 3, 17, 30, tzinfo=timezone.utc)
        soon = dict(market('EV-BAZ', 'CD Baztan advances', '0.96', '0.97'), expected_expiration_time='2026-10-03T18:30:00Z')
        later = dict(soon, expected_expiration_time='2026-10-10T18:30:00Z')     # a first leg
        self.assertEqual(E.pick_entry('EV', [soon], POLICY, r, data_band=False, now=now).ticker, 'EV-BAZ')
        self.assertIsNone(E.pick_entry('EV', [later], POLICY, r, data_band=False, now=now))
        self.assertIsNone(E.pick_entry('EV', [dict(soon, expected_expiration_time=None)], POLICY, r,
                                       data_band=False, now=now))
        self.assertIsNone(E.pick_entry('EV', [soon], POLICY, r, data_band=False, now=None))

    def test_basketball_quarters_halves_and_halftime(self):
        game = live(period=4, period_type='quarter', period_remaining_time='01:59',
                    home_points=80, away_points=77)
        self.assertTrue(E.almost_over(rule('basketball'), 'basketball_game', game))
        self.assertTrue(E.almost_over(rule('basketball'), 'basketball_game', dict(game, period=5)))
        self.assertFalse(E.almost_over(rule('basketball'), 'basketball_game', dict(game, period=3)))
        self.assertFalse(E.almost_over(rule('basketball'), 'basketball_game',
                                       dict(game, period_remaining_time='02:01')))
        self.assertFalse(E.almost_over(rule('basketball'), 'basketball_game', dict(game, home_points=77)))
        self.assertFalse(E.almost_over(rule('basketball'), 'basketball_game', dict(game, status='halftime')))
        college = dict(game, period=2, period_type='half')
        self.assertTrue(E.almost_over(rule('basketball'), 'basketball_game', college))
        self.assertFalse(E.almost_over(rule('basketball'), 'basketball_game', dict(college, period=1)))

    def test_football_and_hockey(self):
        # Polymarket 10-03 (after Villanova 35-31 lost to a late touchdown):
        # last 4 minutes of Q4/OT with a 9+ point lead.
        game = live(quarter=4, clock='3:59', home_points=26, away_points=17)
        self.assertTrue(E.almost_over(rule('football'), 'football_game', game))
        self.assertTrue(E.almost_over(rule('football'), 'football_game', dict(game, clock='4:00')))
        self.assertFalse(E.almost_over(rule('football'), 'football_game', dict(game, clock='4:01')))
        self.assertFalse(E.almost_over(rule('football'), 'football_game', dict(game, home_points=25)))
        self.assertFalse(E.almost_over(rule('football'), 'football_game', dict(game, quarter=3)))
        self.assertFalse(E.almost_over(rule('football'), 'football_game', dict(game, clock='13:12')))
        puck = live(period=3, period_remaining_time='00:45', home_points=3, away_points=1)
        self.assertTrue(E.almost_over(rule('hockey'), 'hockey_tournament', puck))
        self.assertFalse(E.almost_over(rule('hockey'), 'hockey_tournament', dict(puck, period=2)))
        self.assertFalse(E.almost_over(rule('hockey'), 'hockey_tournament', dict(puck, home_points=1)))

    def test_rugby_needs_eight(self):
        game = live(period=2, period_remaining_time='01:00', home_points=14, away_points=26)
        self.assertTrue(E.almost_over(rule('rugby'), 'rugby_match', game))
        self.assertFalse(E.almost_over(rule('rugby'), 'rugby_match', dict(game, home_points=19)))

    def test_baseball_ninth_two_run_lead(self):
        # Polymarket rule: 9th inning or later, 2+ run lead, any half, any outs.
        game = live(inning=9, inning_half=1, outs=0, home_points=5, away_points=3)
        self.assertTrue(E.almost_over(rule('baseball'), 'baseball_game', game))
        self.assertTrue(E.almost_over(rule('baseball'), 'baseball_game', dict(game, inning=11)))
        self.assertFalse(E.almost_over(rule('baseball'), 'baseball_game', dict(game, inning=8)))
        self.assertFalse(E.almost_over(rule('baseball'), 'baseball_game', dict(game, away_points=4)))
        self.assertFalse(E.almost_over(rule('baseball'), 'baseball_game', dict(game, away_points=5)))

    def test_tennis_current_set(self):
        r = rule('tennis')
        self.assertTrue(E.almost_over(r, 'tennis_tournament_singles', tennis(
            [('winner', 6), ('ongoing', 5)], [('loser', 4), ('ongoing', 3)])))
        # Leader in sets but behind in the current set.
        self.assertFalse(E.almost_over(r, 'tennis_tournament_singles', tennis(
            [('winner', 6), ('ongoing', 3)], [('loser', 4), ('ongoing', 5)])))
        # Not enough games yet.
        self.assertFalse(E.almost_over(r, 'tennis_tournament_singles', tennis(
            [('winner', 6), ('ongoing', 4)], [('loser', 4), ('ongoing', 1)])))
        # One set all: both are a set away; the second player's 5-4 in the decider counts.
        self.assertTrue(E.almost_over(r, 'tennis_tournament_doubles', tennis(
            [('winner', 6), ('loser', 3), ('ongoing', 4)], [('loser', 4), ('winner', 6), ('ongoing', 5)])))
        # Finished match (two sets won) is not "almost over".
        self.assertFalse(E.almost_over(r, 'tennis_tournament_singles', tennis(
            [('winner', 7), ('winner', 6)], [('loser', 5), ('loser', 2)])))

    def test_table_tennis_best_of_and_lead(self):
        game = dict(status='live', widget_status='live', best_of_sets=5, period_scores=[
            dict(number=1, competitor1_score=11, competitor2_score=4),
            dict(number=2, competitor1_score=11, competitor2_score=3),
            dict(number=3, competitor1_score=7, competitor2_score=11),
            dict(number=4, competitor1_score=8, competitor2_score=2)])
        self.assertTrue(E.almost_over(rule('table-tennis'), 'table_tennis_match', game))
        close = dict(game, period_scores=game['period_scores'][:3]+[
            dict(number=4, competitor1_score=8, competitor2_score=5)])
        self.assertFalse(E.almost_over(rule('table-tennis'), 'table_tennis_match', close))
        self.assertFalse(E.almost_over(rule('table-tennis'), 'table_tennis_match', dict(game, best_of_sets=7)))
        # Already three games won (decided, or the best-of was misread): never.
        won = dict(game, period_scores=[dict(number=i, competitor1_score=11, competitor2_score=2) for i in (1, 2, 3)]
                   + [dict(number=4, competitor1_score=8, competitor2_score=1)])
        self.assertFalse(E.almost_over(rule('table-tennis'), 'table_tennis_match', won))
        lost = dict(game, period_scores=[dict(number=i, competitor1_score=s1, competitor2_score=s2)
                                         for i, (s1, s2) in enumerate(((11, 2), (2, 11), (11, 3), (3, 11), (2, 11), (8, 1)), 1)])
        self.assertFalse(E.almost_over(rule('table-tennis'), 'table_tennis_match', lost))

    def test_volleyball_one_set_away(self):
        game = dict(status='live', widget_status='live', best_of=5, period_scores=[
            dict(number=1, home_score=15, away_score=25), dict(number=2, home_score=20, away_score=25),
            dict(number=3, home_score=14, away_score=21)])
        self.assertTrue(E.almost_over(rule('volleyball'), 'volleyball_match', game))
        early = dict(game, period_scores=game['period_scores'][:2]+[dict(number=3, home_score=10, away_score=16)])
        self.assertFalse(E.almost_over(rule('volleyball'), 'volleyball_match', early))

    def test_esports_map_point(self):
        game = dict(status='live', widget_status='live', home_score=1, away_score=0)
        self.assertTrue(E.almost_over(rule('esports'), 'esports_match', game))
        self.assertFalse(E.almost_over(rule('esports'), 'esports_match', dict(game, home_score=0)))
        self.assertFalse(E.almost_over(rule('esports'), 'esports_match', dict(game, home_score=2)))

    def test_finished_or_not_started_never(self):
        game = live(quarter=4, clock='0:10', home_points=27, away_points=17)
        for status, widget in (('closed', 'finished'), ('not_started', 'pre'), ('inprogress', 'pre')):
            self.assertFalse(E.almost_over(rule('football'), 'football_game',
                                           dict(game, status=status, widget_status=widget)))
        self.assertFalse(E.almost_over(None, 'football_game', game))


class EntryTest(unittest.TestCase):
    def test_winner_events(self):
        self.assertEqual(E.winner_events([
            'KXMLBGAME-26OCT031300CWSCLE', 'KXMLBSPREAD-26OCT031300CWSCLE', 'KXMLBTOTAL-X',
            'KXMLBEXTRAS-X', 'KXMLBDELAY-X', 'KXNCAAF1H-X', 'KXARGPREMDIVBTTS-X', 'KXNBA1HGAME-X',
            'KXEPLTOTALMATCH-X',
            'KXITFDOUBLES-26OCT03FRAKUHSHESWE', 'KXT20MATCH-26OCT031330TLYRGSREDXI']),
            ['KXMLBGAME-26OCT031300CWSCLE', 'KXITFDOUBLES-26OCT03FRAKUHSHESWE',
             'KXT20MATCH-26OCT031330TLYRGSREDXI'])

    def test_middle_price_trigger_and_cap(self):
        r = rule('basketball')
        pick = lambda ms, data=False: E.pick_entry('EV', ms, POLICY, r, data_band=data)
        self.assertEqual(pick([market('EV-A', 'A', '0.95', '0.97'), market('EV-B', 'B', '0.02', '0.04')]).ticker, 'EV-A')
        self.assertIsNone(pick([market('EV-A', 'A', '0.89', '0.99')]))        # 94c middle
        self.assertIsNone(pick([market('EV-A', 'A', '0.98', '1.00')]))        # ask over the cap
        self.assertIsNone(pick([market('EV-A', 'A', '0.85', '0.99')]))        # wide and low
        self.assertIsNone(pick([market('EV-A', 'A', '0.96', '0.97', status='closed')]))
        self.assertIsNone(pick([market('EV-A', 'A', '0', '0.97')]))           # one-sided
        cand = pick([market('EV-A', 'A', '0.95', '0.96')])
        self.assertEqual((cand.mid, cand.ask, cand.band), (D('0.955'), D('0.96'), 'rule'))

    def test_data_band_only_in_dry(self):
        r = rule('hockey')
        ms = [market('EV-A', 'A', '0.91', '0.93')]
        self.assertIsNone(E.pick_entry('EV', ms, POLICY, r, data_band=False))
        self.assertEqual(E.pick_entry('EV', ms, POLICY, r, data_band=True).band, 'data')
        self.assertIsNone(E.pick_entry('EV', [market('EV-A', 'A', '0.88', '0.91')], POLICY, r, data_band=True))
        # 90.5c middle but a 17c spread: not a reliable price.
        self.assertIsNone(E.pick_entry('EV', [market('EV-A', 'A', '0.82', '0.99')], POLICY, r, data_band=True))
        self.assertIsNotNone(E.pick_entry('EV', [market('EV-A', 'A', '0.89', '0.99')], POLICY, r, data_band=True))

    def test_esports_floor_97(self):
        r = rule('esports')
        ms = [market('EV-A', 'A', '0.95', '0.96')]
        self.assertIsNone(E.pick_entry('EV', ms, POLICY, r, data_band=False))
        self.assertEqual(E.pick_entry('EV', ms, POLICY, r, data_band=True).band, 'data')
        self.assertEqual(E.pick_entry('EV', [market('EV-A', 'A', '0.97', '0.98')], POLICY, r,
                                      data_band=False).band, 'rule')

    def test_never_tie_and_cheapest(self):
        r = SOCCER_90
        self.assertIsNone(E.pick_entry('EV', [market('EV-TIE', 'Tie', '0.96', '0.97')], POLICY, r, data_band=True))
        self.assertIsNone(E.pick_entry('EV', [market('EV-X', 'Draw', '0.96', '0.97')], POLICY, r, data_band=True))
        self.assertIsNone(E.pick_entry('EV', [market('EV-TIE', 'No winner', '0.96', '0.97')], POLICY, r, data_band=True))
        two = [market('EV-A', 'A', '0.97', '0.99'), market('EV-B', 'B', '0.95', '0.96')]
        self.assertEqual(E.pick_entry('EV', two, POLICY, r, data_band=False).ticker, 'EV-B')


class MoneyTest(unittest.TestCase):
    def test_fee_and_99c_profit(self):
        self.assertEqual(E.taker_fee(10, D('0.99')), D('0.01'))
        self.assertEqual(E.taker_fee(10, D('0.95')), D('0.04'))
        self.assertEqual(E.taker_fee(10, D('0.96'), D('0.5')), D('0.02'))
        self.assertEqual(E.realized_result(True, 10, D('0.99'), D('0.01')), D('0.09'))
        self.assertEqual(E.realized_result(False, 10, D('0.99'), D('0.01')), D('-9.91'))

    def test_contracts_on_the_cap(self):
        self.assertEqual(E.contracts_for(D(10), D('0.99')), 10)
        self.assertEqual(E.contracts_for(D(10), D('0.95')), 10)

    def test_fill_walks_book_and_needs_full_size(self):
        no = [['0.01', '3'], ['0.03', '4'], ['0.05', '100'], ['0.20', '50']]   # YES asks 99, 97, 95, 80
        self.assertEqual(E.fill_from_book(no, 10, D('0.99')), (10, (D('0.80')*10)/10))
        self.assertEqual(E.fill_from_book(no[:3], 10, D('0.99')), (10, (D('0.95')*10)/10))
        filled, avg = E.fill_from_book([['0.01', '3'], ['0.03', '7']], 10, D('0.99'))
        self.assertEqual((filled, avg), (10, (3*D('0.99')+7*D('0.97'))/10))
        self.assertEqual(E.fill_from_book([['0.01', '9']], 10, D('0.99')), (0, None))
        self.assertEqual(E.fill_from_book([['0.005', '50']], 10, D('0.99')), (0, None))   # 99.5c over the cap

    def test_daily_stop_and_bucket(self):
        self.assertTrue(E.daily_stop_hit(D('-90'), POLICY))
        self.assertFalse(E.daily_stop_hit(D('-89.99'), POLICY))
        self.assertEqual(E.price_bucket('0.9590'), '95c')


def load_trader():
    spec = importlib.util.spec_from_file_location('endgame_trader', ROOT/'scripts'/'endgame_trader.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TraderTest(unittest.TestCase):
    def setUp(self):
        self.T = load_trader()
        self.tmp = tempfile.TemporaryDirectory()
        out = Path(self.tmp.name)
        self.T.OUT, self.T.DB, self.T.STOP_FILE = out, out/'endgame.db', out/'STOP'
        self.calls = []
        self.state = dict(details=live(quarter=4, clock='1:00', home_points=30, away_points=10),
                          bid='0.95', ask='0.97', book=[['0.03', '50']], result='')

    def tearDown(self):
        if hasattr(self, 'db'):
            self.db.close()
        self.tmp.cleanup()

    def fetch(self, path, params=None):
        self.calls.append(path)
        s = self.state
        if path == '/milestones':
            return dict(milestones=[dict(id='m1', type='football_game', start_date='2026-10-03T17:00:00Z',
                                         primary_event_tickers=['KXNFLGAME-X', 'KXNFLSPREAD-X'])])
        if path == '/live_data/batch':
            return dict(live_datas=[dict(milestone_id='m1', details=s['details'])])
        if path == '/events/KXNFLGAME-X':
            return dict(event=dict(markets=[market('KXNFLGAME-X-A', 'A', s['bid'], s['ask']),
                                            market('KXNFLGAME-X-B', 'B', '0.02', '0.04')]))
        if path == '/markets/KXNFLGAME-X-A/orderbook':
            return dict(orderbook_fp=dict(no_dollars=s['book'], yes_dollars=[]))
        if path == '/series/KXNFLGAME':
            return dict(series=dict(fee_multiplier=1))
        if path == '/markets/KXNFLGAME-X-A':
            return dict(market=dict(result=s['result']))
        raise AssertionError(path)

    def trader(self):
        self.db = self.T.open_db(self.T.DB)
        return self.T.Trader(self.db, fetch=self.fetch)

    def rows(self):
        return [dict(r) for r in self.db.execute('SELECT * FROM trades ORDER BY id')]

    def test_paper_buy_once_then_settle(self):
        t = self.trader()
        now = datetime(2026, 10, 3, 18, tzinfo=timezone.utc)
        t.cycle(now)
        t.cycle(now)
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]['ticker'], rows[0]['band'], rows[0]['qty'], rows[0]['price'], rows[0]['fee']),
                         ('KXNFLGAME-X-A', 'rule', 30, '0.9700', '0.07'))
        self.assertNotIn('/events/KXNFLSPREAD-X', self.calls)
        self.assertEqual(self.calls.count('/events/KXNFLGAME-X'), 1)   # traded at the rule: not refetched
        self.state['result'] = 'yes'
        t.cycle(now.replace(minute=10))
        row = self.rows()[0]
        self.assertEqual((row['outcome'], D(row['result'])), ('yes', D('0.83')))

    def test_data_band_then_rule(self):
        self.state.update(bid='0.91', ask='0.93')
        t = self.trader()
        now = datetime(2026, 10, 3, 18, tzinfo=timezone.utc)
        t.cycle(now)
        self.state.update(bid='0.96', ask='0.97')
        t.cycle(now)
        t.cycle(now)
        self.assertEqual([r['band'] for r in self.rows()], ['data', 'rule'])

    def test_thin_book_skips_and_waits(self):
        self.state['book'] = [['0.03', '29']]
        t = self.trader()
        now = datetime(2026, 10, 3, 18, tzinfo=timezone.utc)
        t.cycle(now)
        t.cycle(now)
        self.assertEqual(self.rows(), [])
        self.assertEqual(self.calls.count('/markets/KXNFLGAME-X-A/orderbook'), 1)
        self.assertEqual(t.counts['thin'], 1)

    def test_not_almost_over_and_stop_file(self):
        self.state['details'] = live(quarter=3, clock='1:00', home_points=20, away_points=10)
        t = self.trader()
        now = datetime(2026, 10, 3, 18, tzinfo=timezone.utc)
        t.cycle(now)
        self.assertNotIn('/events/KXNFLGAME-X', self.calls)
        self.T.STOP_FILE.write_text('')
        self.calls.clear()
        self.assertEqual(t.cycle(now), 'stop_file')
        self.assertEqual(self.calls, [])

    def test_report_groups(self):
        t = self.trader()
        t.cycle(datetime(2026, 10, 3, 18, tzinfo=timezone.utc))
        text = self.T.report(self.db)
        self.assertIn('rule/football', text)
        self.assertIn('rule/97c', text)

    def test_soccer_opens_only_the_advances_market(self):
        game = dict(status='live', widget_status='live', time="90+2'", home_same_game_score=2,
                    away_same_game_score=0, home_aggregate_score=2, away_aggregate_score=0)
        calls = []

        def fetch(path, params=None):
            calls.append(path)
            if path == '/milestones':
                return dict(milestones=[dict(id='s1', type='soccer_tournament_multi_leg', start_date='2026-10-03T16:00:00Z',
                                             primary_event_tickers=['KXCOPADELREYADVANCE-26OCT03BAZATL',
                                                                    'KXCOPADELREYGAME-26OCT03BAZATL'])])
            if path == '/live_data/batch':
                return dict(live_datas=[dict(milestone_id='s1', details=game)])
            if path == '/events/KXCOPADELREYADVANCE-26OCT03BAZATL':
                return dict(event=dict(markets=[
                    dict(market('KXCOPADELREYADVANCE-26OCT03BAZATL-BAZ', 'CD Baztan advances', '0.96', '0.97'),
                         expected_expiration_time='2026-10-03T18:30:00Z'),
                    dict(market('KXCOPADELREYADVANCE-26OCT03BAZATL-ATL', 'Atletico Calatayud advances', '0.03', '0.04'),
                         expected_expiration_time='2026-10-03T18:30:00Z')]))
            if path == '/events/KXCOPADELREYGAME-26OCT03BAZATL':
                return dict(event=dict(markets=[market('KXCOPADELREYGAME-26OCT03BAZATL-BAZ', 'CD Baztan', '0.96', '0.97'),
                                                market('KXCOPADELREYGAME-26OCT03BAZATL-TIE', 'Tie', '0.02', '0.03')]))
            if path in ('/markets/KXCOPADELREYADVANCE-26OCT03BAZATL-BAZ/orderbook',
                        '/markets/KXCOPADELREYGAME-26OCT03BAZATL-BAZ/orderbook'):
                return dict(orderbook_fp=dict(no_dollars=[['0.03', '50']]))
            if path in ('/series/KXCOPADELREYADVANCE', '/series/KXCOPADELREYGAME'):
                return dict(series=dict(fee_multiplier=1))
            raise AssertionError(path)
        self.db = self.T.open_db(self.T.DB)
        self.T.Trader(self.db, fetch=fetch).cycle(datetime(2026, 10, 3, 17, 45, tzinfo=timezone.utc))
        self.assertEqual(sorted((r['sport'], r['ticker']) for r in self.rows()),
                         [('soccer', 'KXCOPADELREYADVANCE-26OCT03BAZATL-BAZ'),
                          ('soccer-3way', 'KXCOPADELREYGAME-26OCT03BAZATL-BAZ')])

    def test_never_any_order_code(self):
        source = (ROOT/'scripts'/'endgame_trader.py').read_text(encoding='utf-8')
        for word in ('portfolio', 'load_signer', 'MutationSigner', "'POST'", 'kalshi-bot.txt'):
            self.assertNotIn(word, source)



def load_watch():
    spec = importlib.util.spec_from_file_location('endgame_watch', ROOT/'scripts'/'endgame_watch.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class WatchTest(unittest.TestCase):
    def setUp(self):
        self.W = load_watch()

    def test_alerts_and_recovery(self):
        plan = self.W.plan
        t0 = datetime(2026, 10, 3, 19, tzinfo=timezone.utc)
        mins = lambda m: t0+timedelta(minutes=m)
        # First run ever: silent, no action.
        state, msgs, restart = plan(None, 5, False, t0)
        self.assertEqual((state['state'], msgs, restart), ('up', [], False))
        state, msgs, restart = plan(state, 30, False, mins(1))
        self.assertEqual((msgs, restart), ([], False))
        # Stops: one alert and an immediate restart.
        state, msgs, restart = plan(state, 300, False, mins(2))
        self.assertEqual(([k for k, _ in msgs], restart, state['state']), (['stopped'], True, 'down'))
        self.assertIn('Restarting automatically', msgs[0][1])
        # Still down a minute later: no new alert, no restart inside the gap.
        state, msgs, restart = plan(state, 360, False, mins(3))
        self.assertEqual((msgs, restart), ([], False))
        # After the gap: another restart, quietly.
        state, msgs, restart = plan(state, 420, False, mins(5))
        self.assertEqual((msgs, restart, len(state['restarts'])), ([], True, 2))
        # Back up: one 'started' alert naming the restarts.
        state, msgs, restart = plan(state, 4, False, mins(6))
        self.assertEqual(([k for k, _ in msgs], restart), (['started'], False))
        self.assertIn('2 automatic restarts', msgs[0][1])
        state, msgs, restart = plan(state, 4, False, mins(7))
        self.assertEqual((msgs, restart), ([], False))

    def test_restart_limit_alerts_once(self):
        plan = self.W.plan
        t0 = datetime(2026, 10, 3, 19, tzinfo=timezone.utc)
        state = dict(state='down', restarts=[(t0+timedelta(minutes=m)).isoformat() for m in (0, 4, 8, 12, 16)])
        state, msgs, restart = plan(state, None, False, t0+timedelta(minutes=20))
        self.assertEqual(([k for k, _ in msgs], restart), (['stuck'], False))
        state, msgs, restart = plan(state, None, False, t0+timedelta(minutes=21))
        self.assertEqual((msgs, restart), ([], False))
        # An hour after the first try the oldest restart drops out: trying again.
        state, msgs, restart = plan(state, None, False, t0+timedelta(minutes=61))
        self.assertTrue(restart)

    def test_stop_file_means_no_restart(self):
        plan = self.W.plan
        t0 = datetime(2026, 10, 3, 19, tzinfo=timezone.utc)
        state, msgs, restart = plan(dict(state='up'), None, True, t0)
        self.assertEqual(([k for k, _ in msgs], restart), (['stopped'], False))
        self.assertIn('STOP file', msgs[0][1])
        state, msgs, restart = plan(state, None, True, t0+timedelta(minutes=5))
        self.assertEqual((msgs, restart), ([], False))
        self.assertEqual(plan(dict(state='up'), 119, False, t0)[0]['state'], 'up')
        self.assertEqual(plan(dict(state='up'), 120, False, t0)[0]['state'], 'down')
        # First run while down: record only, act next minute.
        self.assertEqual(plan(None, None, False, t0)[1:], ([], False))

    def test_running_but_failing_alerts_once_then_recovered(self):
        plan = self.W.plan
        t0 = datetime(2026, 10, 3, 19, tzinfo=timezone.utc)
        state = dict(state='up', failing=False)
        state, msgs, restart = plan(state, 5, False, t0, ok_age=599)
        self.assertEqual((msgs, restart, state['failing']), ([], False, False))
        state, msgs, restart = plan(state, 5, False, t0, ok_age=600)
        self.assertEqual(([k for k, _ in msgs], restart), (['failing'], False))
        self.assertIn('10 min', msgs[0][1])
        state, msgs, _ = plan(state, 5, False, t0, ok_age=900)
        self.assertEqual(msgs, [])
        state, msgs, _ = plan(state, 5, False, t0, ok_age=4)
        self.assertEqual([k for k, _ in msgs], ['recovered'])
        self.assertEqual(plan(dict(state='up'), 5, False, t0, ok_age=None)[1][0][0], 'failing')
        self.assertEqual(plan(None, 5, False, t0, ok_age=None)[1], [])     # first run: silent
        self.assertEqual(set(self.W.STYLE), {'started', 'stopped', 'stuck', 'failing', 'recovered'})

    def test_trader_marks_successful_polls(self):
        source = (ROOT/'scripts'/'endgame_trader.py').read_text(encoding='utf-8')
        self.assertIn("LAST_OK.write_text(iso(now_utc())", source)
        self.assertEqual(load_trader().LAST_OK.name, self.W.LAST_OK.name)
        self.assertEqual(load_trader().LOOKBACK_HOURS, 24)

    def test_restart_targets_only_the_trader(self):
        self.assertEqual(self.W.TRADER_MARK, 'scripts' + chr(92) + 'endgame_trader.py run')
        source = (ROOT/'scripts'/'endgame_watch.py').read_text(encoding='utf-8')
        self.assertNotIn('supervised_live', source)
        self.assertNotIn('kalshi_bot', source)

    def test_heartbeat_age(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'heartbeat'
            now = datetime(2026, 10, 3, 19, tzinfo=timezone.utc)
            self.assertIsNone(self.W.heartbeat_age(now, path))
            path.write_text('2026-10-03T18:59:30Z', encoding='utf-8')
            self.assertEqual(self.W.heartbeat_age(now, path), 30)
            path.write_text('garbage', encoding='utf-8')
            self.assertIsNone(self.W.heartbeat_age(now, path))

    def test_trader_writes_heartbeat_each_poll(self):
        source = (ROOT/'scripts'/'endgame_trader.py').read_text(encoding='utf-8')
        self.assertIn("HEARTBEAT.write_text(iso(now_utc())", source)
        self.assertEqual(load_trader().HEARTBEAT.name, self.W.HEARTBEAT.name)


if __name__ == '__main__':
    unittest.main()
