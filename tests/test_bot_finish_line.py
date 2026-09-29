"""D-161 phase 3: a saved project list drives contracts past Kalshi's $1 floor."""
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

import kalshi_bot.finish_line as fl
from kalshi_bot.finish_line import CANNOT, CLEARED, FULL, NEW, PROJECT, TARGET_USD, FinishLine
from kalshi_bot.lip_meter import LipMeter
from kalshi_bot.selection import MarketSelector
from test_bot_engine import NOW, book, program
from test_bot_selection import terms, view, window


def meter(**earned):
    m = LipMeter()
    m.programs = {pid: dict(ticker='T'+pid, end=NOW+timedelta(days=1), first_at=NOW, earned=D(e), seconds=D(1))
                  for pid, e in earned.items()}
    return m


def row(pid='P', rate='0.10', hours=48, until=None, ticker=None):
    return NS(program_id=pid, ticker=ticker or 'T'+pid, gross_hourly_usd=None if rate is None else D(rate),
              program_end=NOW+timedelta(hours=hours), earning_until=until)


def project(pid, ticker):
    return NS(program_id=pid, ticker=ticker, earning_until=None, program_end=NOW+timedelta(hours=40))


class PlanTests(unittest.TestCase):
    def test_new_contracts_become_projects_while_the_list_has_room(self):
        f = FinishLine(meter())
        self.assertEqual(f.plan(row('A'), NOW), (NEW, TARGET_USD/D('0.10')))
        self.assertTrue(f.claim(row('A'), NOW))
        self.assertEqual(f.tickers(), ('TA',))
        self.assertEqual(f.plan(row('A'), NOW), (PROJECT, TARGET_USD/D('0.10')))
        with patch.object(fl, 'MAX_PROJECTS', 1):
            self.assertEqual(f.plan(row('B'), NOW), FULL)
            self.assertFalse(f.claim(row('B'), NOW))
            self.assertTrue(f.claim(row('A'), NOW))         # a project always passes
        self.assertEqual(set(f.projects), {'A'})

    def test_contracts_that_cannot_reach_the_target_in_half_their_time_do_not_start(self):
        f = FinishLine(meter(P='0.30'))
        self.assertEqual(FinishLine(meter()).plan(row(hours=24.9), NOW), CANNOT)   # needs 12.5 h
        self.assertEqual(FinishLine(meter()).plan(row(hours=25), NOW)[0], NEW)
        self.assertEqual(f.plan(row(hours=19), NOW)[0], NEW)         # earnings shorten it
        self.assertEqual(f.plan(row(hours=100, until=NOW+timedelta(hours=10)), NOW), CANNOT)
        for bad in (row(rate=None), row(rate='0')):
            self.assertEqual(FinishLine(meter()).plan(bad, NOW), CANNOT)

    def test_a_project_continues_while_a_dollar_is_reachable_at_all(self):
        f = FinishLine(meter(P='0.30'))
        f.claim(row(), NOW)
        # Needs 9.5 h for $1.25, has 12 h: more than half, still a project.
        self.assertEqual(f.plan(row(hours=12), NOW), (PROJECT, D('9.5')))
        # $1 needs 7 h at 0.10/h: with 6 h left it is hopeless and dropped.
        self.assertEqual(f.plan(row(hours=6), NOW), CANNOT)
        self.assertEqual(f.projects, {})
        self.assertEqual(f.closed[-1]['reason'], CANNOT)

    def test_contracts_past_a_dollar_pass_without_taking_a_project_slot(self):
        f = FinishLine(meter(C='1.00'))
        self.assertEqual(f.plan(row('C', rate='0.30'), NOW), (CLEARED, D('-0.30')))
        with patch.object(fl, 'MAX_PROJECTS', 0):
            self.assertTrue(f.claim(row('C'), NOW))
        self.assertEqual(f.projects, {})

    def test_review_closes_cleared_and_expired_projects(self):
        m = meter(A='0.5', B='0.2')
        f = FinishLine(m)
        f.claim(row('A'), NOW)
        f.claim(row('B', until=NOW+timedelta(hours=1)), NOW)
        f.review(NOW)
        self.assertEqual(set(f.projects), {'A', 'B'})
        m.programs['A']['earned'] = D('1.01')
        f.review(NOW+timedelta(hours=2))
        self.assertEqual(f.projects, {})
        self.assertEqual({c['program_id']: c['reason'] for c in f.closed},
                         {'A': 'cleared', 'B': 'ended_under_minimum'})
        s = f.status(NOW)
        self.assertEqual((s['cleared_total'], s['dropped_total'], s['active']), (1, 1, 0))

    def test_hopeless_uses_the_better_of_current_and_measured_rate(self):
        m = meter(P='0.5')
        f = FinishLine(m)
        until = NOW+timedelta(hours=4)
        self.assertTrue(f.hopeless('P', D('0.10'), until, NOW))          # 0.5+0.4 < 1
        m.programs['P']['seconds'] = D(3600)                              # measured 0.5/h
        self.assertFalse(f.hopeless('P', D('0.10'), until, NOW))
        m.programs['P']['seconds'] = D(599)                               # too little data
        self.assertTrue(f.hopeless('P', D('0.10'), until, NOW))
        self.assertFalse(f.hopeless('P', D('0.13'), until, NOW))          # 0.5+0.52 >= 1
        self.assertFalse(FinishLine(meter(P='1')).hopeless('P', D(0), until, NOW))
        self.assertTrue(FinishLine(meter()).hopeless('X', None, until, NOW))

    def test_the_list_survives_a_restart_and_corrupt_files_start_empty(self):
        with TemporaryDirectory() as temp:
            path = Path(temp)/'projects.json'
            f = FinishLine(meter(A='0.4'), path)
            f.claim(row('A'), NOW)
            f.claim(row('B'), NOW)
            f.drop('B', NOW)
            self.assertFalse(path.with_suffix('.tmp').exists())
            back = FinishLine(meter(A='0.4'), path).load()
            self.assertEqual(back.projects, f.projects)
            self.assertEqual([(c['program_id'], c['reason']) for c in back.closed], [('B', CANNOT)])
            s = back.status(NOW)
            self.assertEqual(s['projects'][0]['ticker'], 'TA')
            self.assertEqual((s['projects'][0]['to_dollar'], s['projects'][0]['hours_left']), ('0.6000', 48.0))
            for bad in ('{', '[]', '{"projects": {"A": {"ticker": 1}}, "closed": []}',
                        json.dumps(dict(projects={str(i): dict(ticker='T', until=NOW.isoformat(),
                            added_at=NOW.isoformat()) for i in range(31)}, closed=[]))):
                path.write_text(bad, encoding='utf-8')
                self.assertEqual(FinishLine(meter(), path).load().projects, {}, bad[:40])
            self.assertEqual(FinishLine(meter()).load().projects, {})

    def test_a_failed_save_is_counted_not_fatal(self):
        with TemporaryDirectory() as temp:
            f = FinishLine(meter(), Path(temp)/'missing'/'projects.json')
            self.assertTrue(f.claim(row(), NOW))
            self.assertEqual(f.save_failures, 1)


class SelectorTests(unittest.TestCase):
    """The real selector with the project list; without it nothing changes."""
    def setUp(self):
        self.s = MarketSelector(128)
        for ticker, pool in (('A', 9000000), ('B', 6000000), ('C', 3000000)):
            self.add(ticker, pool, NOW+timedelta(hours=40))

    def add(self, ticker, pool, end):
        risk = min(end, NOW+timedelta(hours=40))
        self.s.update(replace(book(), ticker=ticker),
                      (program(program_id='P'+ticker, ticker=ticker, pool_centicents=pool, end=end),),
                      terms=terms(ticker, event_risk_at=risk, close_at=NOW+timedelta(hours=41)),
                      now=NOW, valid_until=NOW+timedelta(seconds=10))

    def choose(self, **kwargs):
        args = dict(view=view(), window=window(), free_cash=D(500), account_known=True,
                    now=NOW, current=lambda t: True)
        args.update(kwargs)
        return self.s.propose(**args)

    def test_projects_first_then_new_projects_then_cleared(self):
        self.assertEqual([r.ticker for r in self.choose().additions], ['A', 'B', 'C'])  # rate order
        f = FinishLine(meter(PA='1.40'))                     # A already past $1
        f.claim(project('PC', 'C'), NOW)
        self.assertEqual([r.ticker for r in self.choose(finish=f).additions], ['C', 'B', 'A'])
        self.assertEqual(set(f.projects), {'PC', 'PB'})       # B joined the list; A did not

    def test_a_full_list_blocks_other_new_contracts(self):
        f = FinishLine(meter())
        with patch.object(fl, 'MAX_PROJECTS', 1):
            result = self.choose(finish=f)
        self.assertEqual([r.ticker for r in result.additions], ['A'])
        self.assertIn(('B', (FULL,)), result.exclusions)
        self.assertEqual(f.tickers(), ('A',))

    def test_one_selection_cannot_claim_more_than_the_room_left(self):
        f = FinishLine(meter())
        with patch.object(fl, 'MAX_PROJECTS', 2):
            f.claim(project('PX', 'X'), NOW)
            result = self.choose(finish=f)
        self.assertEqual([r.ticker for r in result.additions], ['A'])
        self.assertIn(('B', (FULL,)), result.exclusions)

    def test_contracts_that_cannot_reach_a_dollar_are_not_entered(self):
        self.add('D', 3000000, NOW+timedelta(minutes=50))
        result = self.choose(finish=FinishLine(meter()))
        self.assertNotIn('D', [r.ticker for r in result.additions])
        self.assertIn(('D', (CANNOT,)), result.exclusions)
        self.assertIn('D', [r.ticker for r in self.choose().additions])   # policy off: unchanged

    def test_the_entry_cap_fills_with_projects_first(self):
        f = FinishLine(meter())
        f.claim(project('PC', 'C'), NOW)
        result = self.choose(finish=f, window=window(cap=2))
        self.assertEqual([r.ticker for r in result.additions], ['C'])

    def test_selection_reviews_the_list_first(self):
        m = meter(PC='0.2')
        f = FinishLine(m)
        f.claim(project('PC', 'C'), NOW)
        m.programs['PC']['earned'] = D('1.5')
        self.choose(finish=f)
        self.assertEqual(f.closed[-1]['reason'], 'cleared')


class WiringTests(unittest.TestCase):
    def test_live_runtime_feeds_the_meter_and_list_to_selection(self):
        src = Path(__file__).resolve().parents[1]/'src'/'kalshi_bot'
        self.assertIn("finish=getattr(r, 'finish_line', None)", (src/'selection_runtime.py').read_text(encoding='utf-8'))
        live = (src/'live.py').read_text(encoding='utf-8')
        self.assertIn("runtime.finish_line = FinishLine(runtime.lip_meter,", live)
        self.assertIn("Path(writer.path).with_name('projects.json')).load()", live)
        runtime = (src/'runtime.py').read_text(encoding='utf-8')
        self.assertIn("finish_line=self.finish_line.status(self.now()) if self.finish_line is not None else None", runtime)


if __name__ == '__main__':
    unittest.main()
