"""D-175 Endgame Trader: per-sport rules on real Kalshi live-data shapes,
entry choice, fees, paper fills and the dry-run process (no network)."""
import importlib.util
import json
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
# NO on the trailer: switched off 10-05 (operator "Switch it off" after Aruba's
# comeback at 99c); the code stays, tested with this rule.
NO_TRAILER = E.SportRule(kind='minute', types=('soccer_tournament_multi_leg',), min_minute=88, min_lead=1,
                         side='no_trailer', experimental=True, test_price=D('0.92'))


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
        self.assertEqual(set(POLICY.rules), {'soccer', 'soccer-3way', 'basketball', 'football',
                                             'hockey', 'tennis', 'table-tennis', 'esports', 'esports-dota2',
                                             'esports-valorant', 'esports-lol', 'esports-r6', 'esports-overwatch',
                                             'baseball', 'rugby', 'volleyball'})
        # Operator 10-05 "Follow current polymarket entry strategy": 3-option soccer
        # is a main rule (Polymarket trades it live); no 20/30 s waits (Polymarket
        # removed them: they blocked most fills; the 3c gap cap covers esports spikes).
        self.assertEqual({s for s, r in POLICY.rules.items() if r.experimental},
                         {'rugby', 'volleyball', 'soccer', 'esports-r6', 'esports-overwatch'})
        self.assertEqual({s: r.hold_seconds for s, r in POLICY.rules.items() if r.hold_seconds}, {})
        self.assertEqual(rule('esports-overwatch').max_price, D('0.98'))
        self.assertEqual([s for s, _ in POLICY.rules_for('basketball_game')], ['basketball'])
        # NHL games are 'hockey_match' on Kalshi (missed until 10-03).
        self.assertEqual([s for s, _ in POLICY.rules_for('hockey_match')], ['hockey'])
        self.assertEqual(E.winner_events(['KXNHLGAME-26OCT01PHINJ', 'KXNHL1P-26OCT01PHINJ', 'KXNHLOT-26OCT01PHINJ',
                                          'KXNHL3PSPREAD-26OCT01PHINJ', 'KXNHLF10G-26OCT01PHINJ']),
                         ['KXNHLGAME-26OCT01PHINJ'])
        self.assertEqual(POLICY.rules_for('cricket_match'), [])
        # Soccer: the 2-option cup 'advances' markets; the 3-option 90-minute game
        # market is tracked on paper only, as its own sport (operator: "add it for paper").
        rules = dict(POLICY.rules_for('soccer_tournament_multi_leg'))
        soccer, three = rules['soccer'], rules['soccer-3way']
        self.assertEqual(set(rules), {'soccer', 'soccer-3way'})
        self.assertEqual((soccer.kind, soccer.events), ('advance', 'advance'))
        self.assertEqual((three.kind, three.events, three.experimental), ('minute', 'winner', False))
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

    def test_soccer_polymarket_research_88_two_goals_80_three(self):
        # D-176 (Polymarket research, 4,294 Kalshi goal timelines): 2 goals from
        # 88' (85' was break-even), 3+ goals from 80'; never 1 goal.
        r = rule('soccer-3way')
        game = dict(status='live', widget_status='live', time="88'", home_same_game_score=2, away_same_game_score=0)
        self.assertTrue(E.almost_over(r, 'soccer_tournament_multi_leg', game))
        self.assertTrue(E.almost_over(r, 'soccer_tournament_multi_leg', dict(game, time="90+5'")))
        self.assertFalse(E.almost_over(r, 'soccer_tournament_multi_leg', dict(game, time="87'")))
        self.assertTrue(E.almost_over(r, 'soccer_tournament_multi_leg', dict(game, time="80'", home_same_game_score=3)))
        self.assertFalse(E.almost_over(r, 'soccer_tournament_multi_leg', dict(game, time="79'", home_same_game_score=3)))
        self.assertFalse(E.almost_over(r, 'soccer_tournament_multi_leg', dict(game, away_same_game_score=1)))
        racing = dict(game, time="90+4'", home_same_game_score=1, away_same_game_score=0)
        self.assertFalse(E.almost_over(r, 'soccer_tournament_multi_leg', racing))
        # The NO-on-the-trailer paper rule takes 1-goal leads from 88'.
        nt = NO_TRAILER
        self.assertTrue(E.almost_over(nt, 'soccer_tournament_multi_leg', racing))
        self.assertFalse(E.almost_over(nt, 'soccer_tournament_multi_leg', dict(racing, time="87'")))
        self.assertFalse(E.almost_over(nt, 'soccer_tournament_multi_leg', dict(racing, away_same_game_score=1)))

    def test_soccer_advance_normal_time_extra_time_penalties(self):
        r = rule('soccer')
        game = dict(status='live', widget_status='live', time="90+3'", home_same_game_score=2,
                    away_same_game_score=0, home_aggregate_score=2, away_aggregate_score=0)
        self.assertTrue(E.almost_over(r, 'soccer_tournament_multi_leg', game))
        self.assertTrue(E.almost_over(r, 'soccer_tournament_multi_leg', dict(game, time="88'")))
        self.assertFalse(E.almost_over(r, 'soccer_tournament_multi_leg', dict(game, time="87'")))
        self.assertTrue(E.almost_over(r, 'soccer_tournament_multi_leg',
                                      dict(game, time="80'", home_aggregate_score=3)))
        self.assertFalse(E.almost_over(r, 'soccer_tournament_multi_leg',
                                       dict(game, home_aggregate_score=1, away_aggregate_score=0)))
        # Extra time: 91'-119' has up to half an hour left; 120'+ counts (2+ lead).
        self.assertFalse(E.almost_over(r, 'soccer_tournament_multi_leg', dict(game, time="105'")))
        self.assertFalse(E.almost_over(r, 'soccer_tournament_multi_leg', dict(game, time="119'", home_aggregate_score=4)))
        self.assertTrue(E.almost_over(r, 'soccer_tournament_multi_leg', dict(game, time="120+1'")))
        # Penalties never.
        self.assertFalse(E.almost_over(r, 'soccer_tournament_multi_leg', dict(game, show_penalties=True)))
        self.assertFalse(E.almost_over(r, 'soccer_tournament_multi_leg', dict(game, match_status='penalties')))
        # Two legs: the aggregate decides. 2-0 tonight but 2-4 on aggregate is a lead for the away side.
        two_leg = dict(game, home_aggregate_score=2, away_aggregate_score=4)
        self.assertTrue(E.almost_over(r, 'soccer_tournament_multi_leg', two_leg))
        level = dict(game, home_aggregate_score=3, away_aggregate_score=3)
        self.assertFalse(E.almost_over(r, 'soccer_tournament_multi_leg', level))
        # No aggregate: the same-game score.
        single = {k: v for k, v in game.items() if 'aggregate' not in k}
        self.assertTrue(E.almost_over(r, 'soccer_tournament_multi_leg', single))
        self.assertFalse(E.almost_over(r, 'soccer_tournament_multi_leg', dict(single, away_same_game_score=1)))
        self.assertFalse(E.almost_over(r, 'soccer_tournament_multi_leg', dict(single, time="100'")))

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
        # 14-day study 10-03: late 95-96c favourites lost ~2-3% (close games);
        # operator chose a 7+ point lead over a 97c floor.
        game = live(period=4, period_type='quarter', period_remaining_time='01:59',
                    home_points=84, away_points=77)
        self.assertTrue(E.almost_over(rule('basketball'), 'basketball_game', game))
        self.assertTrue(E.almost_over(rule('basketball'), 'basketball_game', dict(game, period=5)))
        self.assertFalse(E.almost_over(rule('basketball'), 'basketball_game', dict(game, period=3)))
        self.assertFalse(E.almost_over(rule('basketball'), 'basketball_game',
                                       dict(game, period_remaining_time='02:01')))
        self.assertFalse(E.almost_over(rule('basketball'), 'basketball_game', dict(game, home_points=77)))
        self.assertFalse(E.almost_over(rule('basketball'), 'basketball_game', dict(game, home_points=83)))
        self.assertFalse(E.almost_over(rule('basketball'), 'basketball_game', dict(game, status='halftime')))
        college = dict(game, period=2, period_type='half')
        self.assertTrue(E.almost_over(rule('basketball'), 'basketball_game', college))
        self.assertFalse(E.almost_over(rule('basketball'), 'basketball_game', dict(college, period=1)))

    def test_football_possession_rule(self):
        # D-176 (Polymarket research, 402 NFL/FBS games): last 3:00 with a 9+ lead
        # only while the leader has the ball, or 17+ in the last 2:00.
        meta = dict(home_team_id='H', away_team_id='A')
        game = live(quarter=4, clock='2:59', home_points=30, away_points=21,
                    situation=dict(possession_team_id='H'))
        fb = lambda g: E.almost_over(rule('football'), 'football_game', g, meta=meta)
        self.assertTrue(fb(game))
        self.assertFalse(fb(dict(game, situation=dict(possession_team_id='A'))))   # NC A&T: Bryant driving
        self.assertFalse(fb(dict(game, situation={})))                             # unknown: skip
        self.assertFalse(E.almost_over(rule('football'), 'football_game', game))    # no team ids: skip
        self.assertFalse(fb(dict(game, clock='3:01')))
        self.assertFalse(fb(dict(game, home_points=29)))
        self.assertFalse(fb(dict(game, quarter=3)))
        away = live(quarter=4, clock='1:00', home_points=21, away_points=30, situation=dict(possession_team_id='A'))
        self.assertTrue(fb(away))
        big = live(quarter=4, clock='2:00', home_points=10, away_points=27, situation=dict(possession_team_id='H'))
        self.assertTrue(fb(big))                                                   # 17+ in the last 2:00
        self.assertFalse(fb(dict(big, clock='2:30')))
        self.assertFalse(fb(dict(big, away_points=26)))

    def test_hockey_two_goals_and_nhl_periods(self):
        # D-176: 2+ goal lead in the last 2:00 (NHL 4,192 games: 0.23% lost); 1-goal
        # leads lose 8% at 2:00. NHL 'hockey_match' used to count P2 as the last period.
        puck = live(period=3, period_remaining_time='00:45', home_points=3, away_points=1)
        for kind in ('hockey_tournament', 'hockey_match'):
            self.assertTrue(E.almost_over(rule('hockey'), kind, puck))
            self.assertFalse(E.almost_over(rule('hockey'), kind, dict(puck, period=2)))
            self.assertFalse(E.almost_over(rule('hockey'), kind, dict(puck, home_points=2)))
            self.assertTrue(E.almost_over(rule('hockey'), kind, dict(puck, period=4)))

    def test_rugby_needs_eight(self):
        game = live(period=2, period_remaining_time='01:00', home_points=14, away_points=26)
        self.assertTrue(E.almost_over(rule('rugby'), 'rugby_match', game))
        self.assertFalse(E.almost_over(rule('rugby'), 'rugby_match', dict(game, home_points=19)))

    def test_baseball_ninth_three_run_lead(self):
        # D-176 (Kalshi MLB prices x play-by-play, 329 games): 3+ runs 0 lost; 2 runs 1.7%.
        game = live(inning=9, inning_half=1, outs=0, home_points=6, away_points=3)
        self.assertTrue(E.almost_over(rule('baseball'), 'baseball_game', game))
        self.assertTrue(E.almost_over(rule('baseball'), 'baseball_game', dict(game, inning=11)))
        self.assertFalse(E.almost_over(rule('baseball'), 'baseball_game', dict(game, inning=8)))
        self.assertFalse(E.almost_over(rule('baseball'), 'baseball_game', dict(game, away_points=4)))
        self.assertFalse(E.almost_over(rule('baseball'), 'baseball_game', dict(game, away_points=6)))

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

    def test_esports_rules_per_title(self):
        # D-176/177: per-title rules (Polymarket, Kalshi 60-day replay per title);
        # best of 3/5 from the total-maps market, unknown format = skip.
        game = dict(status='live', widget_status='live', home_score=1, away_score=0)
        ok = lambda name, g, title, units: E.almost_over(rule(name), 'esports_match', g, meta=dict(game=title),
                                                          units_to_win=units)
        # CS2: 1-0 or 1-1 in a best of 3; one map from 3 in a best of 5.
        self.assertTrue(ok('esports', game, 'CS2', 2))
        self.assertTrue(ok('esports', dict(game, away_score=1), 'CS2', 2))
        self.assertFalse(ok('esports', game, 'CS2', None))
        self.assertFalse(ok('esports', game, 'Dota 2', 2))
        self.assertFalse(ok('esports', dict(game, home_score=0), 'CS2', 2))
        self.assertFalse(ok('esports', dict(game, home_score=2), 'CS2', 2))
        self.assertFalse(ok('esports', game, 'CS2', 3))
        self.assertTrue(ok('esports', dict(game, home_score=2), 'CS2', 3))
        # Dota 2 and Valorant: best of 3, deciding map (1-1) only.
        for name, title in (('esports-dota2', 'Dota 2'), ('esports-valorant', 'Valorant')):
            self.assertFalse(ok(name, game, title, 2))
            self.assertTrue(ok(name, dict(game, away_score=1), title, 2))
            self.assertFalse(ok(name, dict(game, home_score=2, away_score=2), title, 3))   # no best of 5
        # LoL: best of 3 at 1-0 only; best of 5 at 2-1 / 2-2, never 2-0.
        self.assertTrue(ok('esports-lol', game, 'League of Legends', 2))
        self.assertFalse(ok('esports-lol', dict(game, away_score=1), 'League of Legends', 2))
        self.assertFalse(ok('esports-lol', dict(game, home_score=2), 'League of Legends', 3))
        self.assertTrue(ok('esports-lol', dict(game, home_score=2, away_score=1), 'League of Legends', 3))
        self.assertTrue(ok('esports-lol', dict(game, home_score=2, away_score=2), 'League of Legends', 3))
        # Overwatch (no total-maps market): forced first to 3, 2-1 / 2-2 only.
        self.assertTrue(ok('esports-overwatch', dict(game, home_score=2, away_score=1), 'Overwatch', None))
        self.assertFalse(ok('esports-overwatch', dict(game, home_score=2), 'Overwatch', None))
        self.assertFalse(ok('esports-overwatch', game, 'Overwatch', None))
        self.assertEqual(E.maps_to_win([dict(floor_strike=2.5)]), 2)
        self.assertEqual(E.maps_to_win([dict(floor_strike=3.5), dict(floor_strike=4.5)]), 3)
        self.assertIsNone(E.maps_to_win([]))
        self.assertIsNone(E.maps_to_win([dict(floor_strike=None)]))

    def test_tennis_match_tiebreak_needs_nine_points_and_three(self):
        r = rule('tennis')
        mt = lambda a, b: dict(tennis([('winner', 6), ('loser', 3), ('ongoing', a)],
                                      [('loser', 4), ('winner', 6), ('ongoing', b)]),
                               last_set_scoring_type='MatchTiebreak')
        self.assertFalse(E.almost_over(r, 'tennis_tournament_doubles', mt(5, 4)))   # points, not games
        self.assertFalse(E.almost_over(r, 'tennis_tournament_doubles', mt(9, 7)))
        self.assertTrue(E.almost_over(r, 'tennis_tournament_doubles', mt(9, 6)))
        self.assertTrue(E.almost_over(r, 'tennis_tournament_doubles', mt(3, 9)))     # the other side 9-3
        self.assertFalse(E.almost_over(r, 'tennis_tournament_doubles', mt(8, 2)))   # 8 points: not yet
        # Not the deciding set: the normal games rule.
        early = dict(tennis([('winner', 6), ('ongoing', 5)], [('loser', 4), ('ongoing', 3)]),
                     last_set_scoring_type='MatchTiebreak')
        self.assertTrue(E.almost_over(r, 'tennis_tournament_doubles', early))

    def test_finished_or_not_started_never(self):
        game = live(period=3, period_remaining_time='00:10', home_points=4, away_points=1)
        self.assertTrue(E.almost_over(rule('hockey'), 'hockey_match', game))
        for status, widget in (('closed', 'finished'), ('not_started', 'pre'), ('inprogress', 'pre')):
            self.assertFalse(E.almost_over(rule('hockey'), 'hockey_match',
                                           dict(game, status=status, widget_status=widget)))
        self.assertFalse(E.almost_over(None, 'hockey_match', game))


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
        r = rule('hockey')
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
        ms = [market('EV-A', 'A', '0.90', '0.91')]
        self.assertIsNone(E.pick_entry('EV', ms, POLICY, r, data_band=False))
        self.assertEqual(E.pick_entry('EV', ms, POLICY, r, data_band=True).band, 'data')
        self.assertIsNone(E.pick_entry('EV', [market('EV-A', 'A', '0.88', '0.91')], POLICY, r, data_band=True))
        # 90.5c middle but a 17c spread: not a reliable price.
        self.assertIsNone(E.pick_entry('EV', [market('EV-A', 'A', '0.82', '0.99')], POLICY, r, data_band=True))
        self.assertIsNotNone(E.pick_entry('EV', [market('EV-A', 'A', '0.89', '0.99')], POLICY, r, data_band=True))

    def test_test_band_between_data_and_rule(self):
        # Paper-only test floors from the 14-day replay: tennis/table tennis 92c, esports 95c.
        self.assertEqual((rule('tennis').test_price, rule('table-tennis').test_price, rule('esports').test_price),
                         (D('0.92'), D('0.92'), D('0.95')))
        # Operator 10-04 "All sports": every sport has a paper test floor (92c; esports 95c).
        self.assertEqual({n for n, r in POLICY.rules.items() if r.test_price is None}, set())
        self.assertEqual(rule('basketball').test_price, D('0.92'))
        pick = lambda r, bid, ask, data=True: E.pick_entry('EV', [market('EV-A', 'A', bid, ask)], POLICY, r,
                                                           data_band=data)
        self.assertEqual(pick(rule('tennis'), '0.91', '0.93').band, 'test')     # 92c middle
        self.assertEqual(pick(rule('tennis'), '0.90', '0.92').band, 'data')     # 91c middle
        self.assertEqual(pick(rule('tennis'), '0.95', '0.96').band, 'rule')
        self.assertEqual(pick(rule('esports'), '0.95', '0.96').band, 'test')    # 95.5c: under the 97c rule
        self.assertEqual(pick(rule('esports'), '0.93', '0.94').band, 'data')
        self.assertEqual(pick(rule('basketball'), '0.91', '0.93').band, 'test')
        self.assertEqual(pick(rule('basketball'), '0.90', '0.92').band, 'data')
        self.assertIsNone(pick(rule('tennis'), '0.91', '0.93', data=False))      # live: rule only

    def test_per_sport_spread_price_caps_and_no_trailer(self):
        # CS2: gap <= 3c and ask <= 98c (Polymarket strict esports rule).
        cs2 = rule('esports')
        pick = lambda r, ms, data=False: E.pick_entry('EV', ms, POLICY, r, data_band=data)
        self.assertEqual(pick(cs2, [market('EV-A', 'A', '0.97', '0.98')]).band, 'rule')
        self.assertIsNone(pick(cs2, [market('EV-A', 'A', '0.98', '0.99')]))      # ask over 98c
        self.assertIsNone(pick(cs2, [market('EV-A', 'A', '0.94', '0.98')]))      # 4c gap
        self.assertIsNone(pick(cs2, [market('EV-A', 'A', '0.92', '0.98')], True))  # test band: 6c gap
        self.assertEqual(pick(cs2, [market('EV-A', 'A', '0.95', '0.98')], True).band, 'test')
        # NO on the trailer: the cheapest team, priced from 1 - its YES quotes.
        nt = NO_TRAILER
        ms = [market('EV-LEAD', 'Leader', '0.80', '0.82'), market('EV-TRAIL', 'Trailer', '0.02', '0.03'),
              market('EV-TIE', 'Tie', '0.15', '0.17')]
        cand = pick(nt, ms)
        self.assertEqual((cand.ticker, cand.side, cand.bid, cand.ask, cand.mid, cand.band),
                         ('EV-TRAIL', 'no', D('0.97'), D('0.98'), D('0.975'), 'rule'))
        self.assertIsNone(pick(nt, ms[:1]+ms[2:]))                               # one team only
        self.assertIsNone(pick(nt, ms[1:]))                                      # trailer alone: no leader seen
        self.assertIsNone(pick(nt, [ms[0], market('EV-TRAIL', 'Trailer', '0.06', '0.08'), ms[2]]))  # 93c NO
        self.assertEqual(pick(nt, [ms[0], market('EV-TRAIL', 'Trailer', '0.06', '0.08'), ms[2]], True).band, 'test')
        # The live book: best YES bid and 1 - best NO bid.
        book = dict(yes_dollars=[['0.95', '10'], ['0.96', '5'], ['0.97', '0']], no_dollars=[['0.02', '9'], ['0.03', '4']])
        m = E.book_market('T', 'Team', book)
        self.assertEqual((m['yes_bid_dollars'], m['yes_ask_dollars']), ('0.96', '0.97'))
        self.assertIsNone(E.book_market('T', 'Team', dict(yes_dollars=[], no_dollars=[]))['yes_ask_dollars'])

    def test_esports_floor_97(self):
        r = rule('esports')
        ms = [market('EV-A', 'A', '0.95', '0.96')]
        self.assertIsNone(E.pick_entry('EV', ms, POLICY, r, data_band=False))
        self.assertEqual(E.pick_entry('EV', ms, POLICY, r, data_band=True).band, 'test')   # paper test floor 95c
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
        # Single-poll tests: no 20/30 s hold (test_hold_seconds_waits_for_a_steady_entry covers it).
        from dataclasses import replace
        real_load = self.T.load_policy
        self.T.load_policy = lambda path: (lambda pol: replace(pol, rules={k: replace(r, hold_seconds=0)
                                                                    for k, r in pol.rules.items()}))(real_load(path))
        self.calls = []
        self.state = dict(details=live(quarter=4, clock='1:00', home_points=30, away_points=10),
                          bid='0.95', ask='0.97', depth='50', result='')

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
            # The book matches the quote: YES bid = bid, YES ask = 1 - best NO bid.
            return dict(orderbook_fp=dict(no_dollars=[[str(1-D(s['ask'])), s['depth']]],
                                          yes_dollars=[[s['bid'], '50']]))
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

    def test_data_band_then_test_then_rule(self):
        self.state.update(bid='0.90', ask='0.91')                         # 90.5c: data
        t = self.trader()
        now = datetime(2026, 10, 3, 18, tzinfo=timezone.utc)
        t.cycle(now)
        self.state.update(bid='0.91', ask='0.93')                         # 92c: test
        t.cycle(now)
        self.state.update(bid='0.96', ask='0.97')                         # 96.5c: rule
        t.cycle(now)
        t.cycle(now)
        self.assertEqual([r['band'] for r in self.rows()], ['data', 'test', 'rule'])

    def test_stale_listing_is_rechecked_on_the_book(self):
        t = self.trader()
        real = self.fetch

        def fetch(path, params=None):
            if path == '/markets/KXNFLGAME-X-A/orderbook':     # the book says 87c, not 96c
                return dict(orderbook_fp=dict(no_dollars=[['0.12', '50']], yes_dollars=[['0.86', '50']]))
            return real(path, params)
        t.get = fetch
        t.cycle(datetime(2026, 10, 3, 18, tzinfo=timezone.utc))
        self.assertEqual(self.rows(), [])
        self.assertEqual(t.counts['stale'], 1)

    def test_book_band_wins_over_the_listing(self):
        t = self.trader()
        real = self.fetch
        book = {'no': '0.07', 'yes': '0.92'}                                 # book: 92/93 -> 92.5c (test band)

        def fetch(path, params=None):
            if path == '/markets/KXNFLGAME-X-A/orderbook':
                return dict(orderbook_fp=dict(no_dollars=[[book['no'], '50']], yes_dollars=[[book['yes'], '50']]))
            return real(path, params)
        t.get = fetch
        now = datetime(2026, 10, 3, 18, tzinfo=timezone.utc)
        t.cycle(now)                                                       # listing says 96c (rule)
        self.assertEqual([(r['band'], r['price']) for r in self.rows()], [('test', '0.9300')])
        t.cycle(now)                                                       # the test band is already recorded
        self.assertEqual((len(self.rows()), t.counts['trades'], t.counts['stale']), (1, 1, 1))

    def test_maps_format_reads_the_total_maps_market(self):
        calls = []

        def fetch(path, params=None):
            calls.append(path)
            if path == '/events/KXCS2MAP-X-1':
                return dict(event=dict(markets=[dict(ticker='KXCS2MAP-X-1-A', floor_strike=None)]))
            if path == '/events/KXCS2TOTALMAPS-X':
                return dict(event=dict(markets=[dict(ticker='KXCS2TOTALMAPS-X-2', floor_strike=2.5)]))
            raise AssertionError(path)
        self.db = self.T.open_db(self.T.DB)
        t = self.T.Trader(self.db, fetch=fetch)
        m = dict(id='e1', related_event_tickers=['KXCS2GAME-X', 'KXCS2MAP-X-1', 'KXCS2TOTALMAPS-X'])
        self.assertEqual(t.maps_format(m), 2)
        self.assertEqual(t.maps_format(m), 2)
        self.assertEqual(calls, ['/events/KXCS2TOTALMAPS-X'])            # cached
        self.assertIsNone(t.maps_format(dict(id='e2', related_event_tickers=['KXOWGAME-Y'])))

    def test_stale_feed_blocks_buys(self):
        # D-177: live data unchanged for 15 minutes = stuck feed: no buy.
        t = self.trader()
        now = datetime(2026, 10, 3, 18, tzinfo=timezone.utc)
        self.state.update(bid='0.80', ask='0.82')                         # not buyable yet
        t.cycle(now)
        t.cycle(now+timedelta(minutes=16))                                 # same data 16 min later
        self.state.update(bid='0.95', ask='0.97')
        t.cycle(now+timedelta(minutes=17))
        self.assertEqual(self.rows(), [])
        self.assertGreaterEqual(t.counts['stale_feed'], 1)
        before = t.counts['stale_feed']
        self.state['details'] = dict(self.state['details'], status='not_started', widget_status='pre')
        t.cycle(now+timedelta(minutes=17, seconds=10))
        t.cycle(now+timedelta(minutes=40))
        self.assertEqual(t.counts['stale_feed'], before)                   # not-started games are not counted
        self.state['details'] = dict(self.state['details'], status='inprogress', widget_status='live')
        self.state['details'] = dict(self.state['details'], clock='0:50')   # the feed moves again
        t.cycle(now+timedelta(minutes=18))
        self.assertEqual(len(self.rows()), 1)

    def test_hold_seconds_waits_for_a_steady_entry(self):
        t = self.trader()
        t.policy = E.Policy(**{**{k: getattr(t.policy, k) for k in E.Policy.__dataclass_fields__ if k != 'rules'},
                               'rules': {'football': E.SportRule(kind='clock', types=('football_game',),
                                                                 max_clock_minutes=3, min_lead=9, hold_seconds=30)}})
        self.T.load_policy = lambda path: t.policy
        now = datetime(2026, 10, 3, 18, tzinfo=timezone.utc)
        t.cycle(now)
        t.cycle(now+timedelta(seconds=20))
        self.assertEqual(self.rows(), [])
        self.state.update(bid='0.80', ask='0.82')                         # drops out: the clock restarts
        t.cycle(now+timedelta(seconds=25))
        self.state.update(bid='0.95', ask='0.97')
        t.cycle(now+timedelta(seconds=35))
        t.cycle(now+timedelta(seconds=60))
        self.assertEqual(self.rows(), [])
        t.cycle(now+timedelta(seconds=66))
        self.assertEqual(len(self.rows()), 1)

    def test_thin_book_skips_and_waits(self):
        self.state['depth'] = '29'
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

    def test_uncovered_sports_are_counted(self):
        t = self.trader()
        real = self.fetch

        def fetch(path, params=None):
            if path == '/milestones':
                page = real(path, params)
                page['milestones'] += [dict(id='d1', type='darts_match', category='Sports',
                                            start_date='2026-10-03T17:00:00Z', primary_event_tickers=[]),
                                       dict(id='w1', type='one_off_milestone', category='Economics',
                                            start_date='2026-10-03T17:00:00Z', primary_event_tickers=[])]
                return page
            return real(path, params)
        t.get = fetch
        t.cycle(datetime(2026, 10, 3, 18, tzinfo=timezone.utc))
        self.assertEqual(t.uncovered, {'darts_match': 1})
        self.assertEqual(set(t.milestones), {'m1'})

    def test_recorder_once_a_minute_and_on_score_change(self):
        t = self.trader()
        now = datetime(2026, 10, 3, 18, tzinfo=timezone.utc)
        t.cycle(now)
        t.cycle(now.replace(second=10))                                   # same score, clock moved
        self.state['details'] = dict(self.state['details'], clock='0:50')
        t.cycle(now.replace(second=20))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM snapshots').fetchone()[0], 1)
        self.state['details'] = dict(self.state['details'], home_points=33)  # score change
        t.cycle(now.replace(second=30))
        t.cycle(now.replace(minute=1, second=31))                          # a minute later
        snaps = [json.loads(r[0]) for r in self.db.execute('SELECT state FROM snapshots ORDER BY rowid')]
        self.assertEqual([s['home_points'] for s in snaps], [30, 33, 33])
        # A game that is not live (here: not started yet) is not recorded.
        self.state['details'] = dict(self.state['details'], status='not_started', widget_status='pre', home_points=40)
        t.cycle(now.replace(minute=3))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM snapshots').fetchone()[0], 3)
        game = self.db.execute('SELECT * FROM games').fetchone()
        self.assertEqual((game['milestone_id'], game['type']), ('m1', 'football_game'))
        self.assertEqual(json.loads(game['event_tickers']), ['KXNFLGAME-X', 'KXNFLSPREAD-X'])
        # Pruned after SNAPSHOT_KEEP_DAYS.
        t.pruned_at = None
        t.cycle(now+timedelta(days=self.T.SNAPSHOT_KEEP_DAYS, hours=1))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM snapshots WHERE at<?',
                                         ('2026-10-04',)).fetchone()[0], 0)

    def test_report_groups(self):
        t = self.trader()
        t.cycle(datetime(2026, 10, 3, 18, tzinfo=timezone.utc))
        self.assertIn('trades=0', self.T.report(self.db, since='2026-10-03T18:00:01Z'))
        text = self.T.report(self.db)
        self.assertIn('rule/football', text)
        self.assertIn('rule/97c', text)

    def test_no_on_the_trailer_fills_and_settles(self):
        game = dict(status='live', widget_status='live', time="90+1'", home_same_game_score=1, away_same_game_score=0)

        def fetch(path, params=None):
            if path == '/milestones':
                return dict(milestones=[dict(id='s1', type='soccer_tournament_multi_leg', start_date='2026-10-03T16:00:00Z',
                                             primary_event_tickers=['KXNWSLGAME-26OCT03RACURO'])])
            if path == '/live_data/batch':
                return dict(live_datas=[dict(milestone_id='s1', details=game)])
            if path == '/events/KXNWSLGAME-26OCT03RACURO':
                return dict(event=dict(markets=[market('KXNWSLGAME-26OCT03RACURO-RAC', 'Racing', '0.80', '0.82'),
                                                market('KXNWSLGAME-26OCT03RACURO-URO', 'Utah', '0.02', '0.03'),
                                                market('KXNWSLGAME-26OCT03RACURO-TIE', 'Tie', '0.15', '0.17')]))
            if path == '/markets/KXNWSLGAME-26OCT03RACURO-URO/orderbook':
                # NO asks = 1 - YES bids: 98c x 40.
                return dict(orderbook_fp=dict(yes_dollars=[['0.02', '40']], no_dollars=[['0.97', '50']]))
            if path == '/series/KXNWSLGAME':
                return dict(series=dict(fee_multiplier=1))
            if path == '/markets/KXNWSLGAME-26OCT03RACURO-URO':
                return dict(market=dict(result='no'))                     # a draw: NO on Utah wins
            if path.startswith('/markets/'):
                return dict(market=dict(result=''))
            raise AssertionError(path)
        from dataclasses import replace
        base = self.T.load_policy
        self.T.load_policy = lambda path: (lambda pol: replace(pol, rules={**pol.rules,
                                                                       'soccer-no-trailer': NO_TRAILER}))(base(path))
        self.db = self.T.open_db(self.T.DB)
        t = self.T.Trader(self.db, fetch=fetch)
        now = datetime(2026, 10, 3, 17, 45, tzinfo=timezone.utc)
        t.cycle(now)
        rows = [r for r in self.rows() if r['sport'] == 'soccer-no-trailer']
        self.assertEqual([(r['ticker'], r['side'], r['price'], r['band']) for r in rows],
                         [('KXNWSLGAME-26OCT03RACURO-URO', 'no', '0.9800', 'rule')])
        t.cycle(now.replace(minute=55))
        row = [r for r in self.rows() if r['sport'] == 'soccer-no-trailer'][0]
        self.assertEqual((row['outcome'], D(row['result'])), ('no', D(30)*D('0.02')-D(row['fee'])))

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
                return dict(orderbook_fp=dict(no_dollars=[['0.03', '50']], yes_dollars=[['0.96', '50']]))
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
        self.assertEqual(set(self.W.STYLE), {'started', 'stopped', 'stuck', 'failing', 'recovered', 'restarted'})

    def test_quick_restart_alerts_once(self):
        plan = self.W.plan
        t0 = datetime(2026, 10, 3, 21, tzinfo=timezone.utc)
        state, msgs, _ = plan(dict(state='up'), 5, False, t0, started_at='2026-10-03T20:00:00Z')
        self.assertEqual(msgs, [])                        # first sight of a start time: silent
        state, msgs, _ = plan(state, 5, False, t0, started_at='2026-10-03T20:00:00Z')
        self.assertEqual(msgs, [])
        state, msgs, restart = plan(state, 5, False, t0, started_at='2026-10-03T20:58:10Z')
        self.assertEqual(([k for k, _ in msgs], restart), (['restarted'], False))
        self.assertIn('20:58 UTC', msgs[0][1])
        state, msgs, _ = plan(state, 5, False, t0, started_at='2026-10-03T20:58:10Z')
        self.assertEqual(msgs, [])
        # A missing start file keeps the last known time (no false alert).
        state, msgs, _ = plan(state, 5, False, t0, started_at=None)
        self.assertEqual((msgs, state['started_at']), ([], '2026-10-03T20:58:10Z'))
        # Down then up: one 'started' alert, not also 'restarted'.
        down, _, _ = plan(state, 300, False, t0)
        up, msgs, _ = plan(down, 5, False, t0, started_at='2026-10-03T21:03:00Z')
        self.assertEqual([k for k, _ in msgs], ['started'])
        self.assertEqual(up['started_at'], '2026-10-03T21:03:00Z')

    def test_trader_marks_successful_polls(self):
        source = (ROOT/'scripts'/'endgame_trader.py').read_text(encoding='utf-8')
        self.assertIn("LAST_OK.write_text(iso(now_utc())", source)
        self.assertEqual(load_trader().LAST_OK.name, self.W.LAST_OK.name)
        self.assertEqual(load_trader().STARTED.name, self.W.STARTED.name)
        self.assertIn("STARTED.write_text(iso(now_utc())", source)
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
