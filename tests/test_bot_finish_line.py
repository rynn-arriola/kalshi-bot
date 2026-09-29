"""D-161 phase 3: new entries drive contracts past Kalshi's $1-per-contract floor."""
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
from types import SimpleNamespace as NS
import unittest

from kalshi_bot.finish_line import CLEARED, NEW, STARTED, TARGET_USD, FinishLine
from kalshi_bot.lip_meter import LipMeter
from test_bot_engine import NOW, book, program
from kalshi_bot.selection import MarketSelector
from test_bot_selection import terms, view, window


def meter(**earned):
    m = LipMeter()
    m.programs = {pid: dict(ticker=pid, end=NOW+timedelta(days=1), first_at=NOW, earned=D(e), seconds=D(1))
                  for pid, e in earned.items()}
    return m


def row(pid='P', rate='0.10', hours=48, until=None):
    return NS(program_id=pid, gross_hourly_usd=None if rate is None else D(rate),
              program_end=NOW+timedelta(hours=hours), earning_until=until)


class PlanTests(unittest.TestCase):
    def test_tiers_started_new_cleared(self):
        f = FinishLine(meter(S='0.40', C='1.00'))
        self.assertEqual(f.plan(row('S'), NOW), (STARTED, (TARGET_USD-D('0.40'))/D('0.10')))
        self.assertEqual(f.plan(row('N'), NOW), (NEW, TARGET_USD/D('0.10')))
        self.assertEqual(f.plan(row('C', rate='0.30'), NOW), (CLEARED, D('-0.30')))
        self.assertEqual(f.plan(row('C', rate=None), NOW), (CLEARED, D(0)))

    def test_a_contract_that_cannot_reach_the_target_in_half_its_time_is_blocked(self):
        f = FinishLine(meter())
        # 1.25 / 0.10 = 12.5 h of resting needed: needs 25 h left.
        self.assertIsNotNone(f.plan(row(hours=25), NOW))
        self.assertIsNone(f.plan(row(hours=24.9), NOW))
        # Earnings so far shorten what is needed.
        self.assertIsNotNone(FinishLine(meter(P='0.30')).plan(row(hours=19), NOW))
        # The earlier of program end and earning deadline counts.
        self.assertIsNone(f.plan(row(hours=100, until=NOW+timedelta(hours=10)), NOW))
        for bad in (row(rate=None), row(rate='0'), row(hours=-1)):
            self.assertIsNone(f.plan(bad, NOW))
        self.assertEqual((f.planned, f.blocked), (1, 5))
        self.assertEqual(f.status(NOW)['blocked'], 5)


class SelectorTests(unittest.TestCase):
    """The real selector with the policy; without it nothing changes."""
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

    def test_started_contracts_finish_first_then_new_then_cleared(self):
        self.assertEqual([r.ticker for r in self.choose().additions], ['A', 'B', 'C'])  # rate order
        f = FinishLine(meter(PC='0.50', PA='1.40'))                     # C started, A past $1
        self.assertEqual([r.ticker for r in self.choose(finish=f).additions], ['C', 'B', 'A'])

    def test_contracts_that_cannot_reach_a_dollar_are_not_entered(self):
        self.add('D', 3000000, NOW+timedelta(minutes=50))
        result = self.choose(finish=FinishLine(meter()))
        self.assertNotIn('D', [r.ticker for r in result.additions])
        self.assertIn(('D', ('cannot_reach_payout_minimum',)), result.exclusions)
        self.assertIn('D', [r.ticker for r in self.choose().additions])   # policy off: unchanged

    def test_the_entry_cap_fills_with_the_best_finish_first(self):
        result = self.choose(finish=FinishLine(meter(PC='0.50')), window=window(cap=2))
        self.assertEqual([r.ticker for r in result.additions], ['C'])


class WiringTests(unittest.TestCase):
    def test_live_runtime_feeds_the_meter_to_selection(self):
        from pathlib import Path
        src = Path(__file__).resolve().parents[1]/'src'/'kalshi_bot'
        self.assertIn("finish=getattr(r, 'finish_line', None)", (src/'selection_runtime.py').read_text(encoding='utf-8'))
        self.assertIn('runtime.finish_line = FinishLine(runtime.lip_meter)', (src/'live.py').read_text(encoding='utf-8'))
        runtime = (src/'runtime.py').read_text(encoding='utf-8')
        self.assertIn("finish_line=self.finish_line.status(self.now()) if self.finish_line is not None else None", runtime)


if __name__ == '__main__':
    unittest.main()
