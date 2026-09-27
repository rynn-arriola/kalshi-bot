"""D-151 calibration report over a synthetic research dataset."""
from datetime import datetime, timedelta, timezone
import json
from decimal import Decimal as D
import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from kalshi_bot.research import ResearchStore

SCRIPT = Path(__file__).resolve().parents[1]/'scripts'/'calibration_report.py'
spec = importlib.util.spec_from_file_location('calibration_report', SCRIPT)
calibration_report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(calibration_report)

NOW = datetime(2026, 10, 9, 12, tzinfo=timezone.utc)


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.db = Path(self.temp.name)/'research.db'
        clock = [NOW-timedelta(days=2)]
        store = ResearchStore(self.db, now=lambda: clock[0]).start()
        end = datetime(2026, 10, 8, 3, 59, tzinfo=timezone.utc)
        quotes = lambda ahead: [dict(side='bid', price='0.82', quantity='30', visible_ahead=ahead),
                                dict(side='ask', price='0.9', quantity='30', visible_ahead='500')]
        store.record('entries', 'b1', ticker='KXBROSFT', program_id='prog-one-1', screen='reward_risk',
                     order_ids=['o1', 'o2'], quotes=quotes('200'), volume_24h='487.62',
                     program_end=end)
        store.record('entries', 'b2', ticker='KXQUIET', program_id='prog-two-2', screen='pass',
                     order_ids=['o3', 'o4'], quotes=quotes('1500'), volume_24h='3',
                     program_end=end+timedelta(days=5))
        store.record('entries', 'b3', ticker='KXMID', program_id='prog-three', screen='pass',
                     order_ids=['o5', 'o6'], quotes=quotes('50'), volume_24h='150',
                     program_end=end+timedelta(days=5))
        for order_id, filled, withdrawn in (('o1', '30', False), ('o2', '0', False),
                                            ('o3', '0', True), ('o4', '0', False),
                                            ('o5', '0', False), ('o6', '0', False)):
            store.record('entry_ends', order_id, side='bid' if order_id in ('o1', 'o3', 'o5') else 'ask',
                         filled=filled, withdrawn=withdrawn, status='canceled')
        store.record('fills', 'o1/t1', ticker='KXBROSFT', side='bid', price='0.82', quantity='30',
                     role='entry', estimated_ahead='200', withdrawal_in_progress=False)
        store.record('fill_marks', 'o1/t1@60', best_bid='0.14', best_ask='0.9')
        store.record('withdrawals', 'w1', ticker='KXQUIET', triggers=['time_to_fill'])
        store.record('withdrawal_marks', 'w1@60', level_gone=[])
        store.record('withdrawal_marks', 'w1@30', level_gone=['o3'])  # Only 60 s counts.
        store.record('withdrawals', 'w2', ticker='KXBROSFT', triggers=['time_to_fill'])
        store.record('withdrawal_marks', 'w2@60', level_gone=['o1'])
        store.record('withdrawals', 'w3', ticker='KXMID', triggers=['time_to_fill'])
        store.record('withdrawal_marks', 'w3@60', level_gone=None)  # No book: unchecked.
        for trade_id, size, when in (('t1', '200', 'a'), ('t2', '288', 'a'), ('t3', '5', 'b')):
            store.record('trades', trade_id, ticker='KXBROSFT', created_time=when,
                         taker_side='no', count=size)
        store.record('reward_estimates', 'prog-one-1@h', program_id='prog-one-1',
                     sampled_gross_usd='2.40')
        clock[0] = end+timedelta(hours=3)  # Paid ~2-4 AM ET the day after the end.
        store.record('reward_credits', 'credit-1', kind='unattributed_credit', amount='2.31')
        store.record('reward_credits', 'deposit-1', kind='deposit', amount='300')
        store.record('health_hourly', '2026-10-08T00:00:00+00:00', samples=360,
                     entry_allowed_fraction=0.9, average_resting_entries=48.2,
                     counters={'recovery.post_drain': 3, 'pulls.time_to_fill': 7,
                               'fills_recorded': 1})
        store.close()
        self.text = calibration_report.report(calibration_report.load(self.db, NOW-timedelta(days=7)),
                                           days=7, now=NOW)

    def tearDown(self):
        self.temp.cleanup()

    def line(self, start):
        return next(l for l in self.text.splitlines() if l.startswith(start))

    def test_report_includes_the_business_decision_sections(self):
        self.assertIn('## Fill losses before and after the loss filters', self.text)
        self.assertIn('## $1 finish line', self.text)

    def test_entry_outcomes_by_verdict_volume_and_depth(self):
        self.assertEqual(self.line('| reward_risk'), '| reward_risk | 1 | 2 | 1 | 50% | 0% |')
        self.assertEqual(self.line('| pass'), '| pass | 2 | 4 | 0 | 0% | 25% |')
        self.assertEqual(self.line('| 100-286'), '| 100-286 | 2 | 0 | 0% |')
        self.assertEqual(self.line('| >286'), '| >286 (>2k/wk) | 2 | 1 | 50% |')
        self.assertEqual(self.line('| 100-300'), '| 100-300 | 1 | 1 | 100% |')

    def test_fill_markout_is_the_loss_at_the_bid(self):
        # Bought 30 YES at 0.82, best bid 0.14 a minute later: -$20.40.
        self.assertIn('| KXBROSFT | entry | bid | 0.82 | 30 | 200 | -20.40 | – | – |', self.text)

    def test_pull_precision_uses_the_60_second_check(self):
        self.assertEqual(self.line('| time_to_fill'), '| time_to_fill | 3 | 2 | 1 | 50% |')

    def test_sweeps_group_one_taker_order(self):
        self.assertEqual(self.line('| KXBROSFT | 2'), '| KXBROSFT | 2 | 246 | 488 | 1 |')

    def tracker(self, programs):
        path = Path(self.temp.name)/'account.rewards.json'
        path.write_text(json.dumps(dict(schema=1, scope='primary-account', records=[
            dict(program=dict(program_id=pid, ticker=t, end=end.isoformat()), estimate=est,
                 qualifying_seconds=str(hours*3600), observed_seconds='0')
            for pid, t, end, est, hours in programs])), encoding='utf-8')
        return calibration_report.load_tracker(path)

    def test_credits_are_matched_to_the_et_day_their_programs_ended(self):
        # Programs ending 23:59 ET on 10-07 (03:59 UTC 10-08) are paid the next ET morning.
        day1 = datetime(2026, 10, 8, 3, 59, tzinfo=timezone.utc)
        tracker = self.tracker([('p1', 'A', day1, '0.25', 2), ('p2', 'B', day1, '0.15', 1),
                                ('p3', 'C', day1+timedelta(days=5), '0.40', 3)])
        text = calibration_report.report(calibration_report.load(self.db, NOW-timedelta(days=7)),
                                         days=7, now=NOW, tracker=tracker)
        self.assertIn('1 reward-like credits totalling $2.31.', text)
        self.assertIn('| 2026-10-07 | 2 | 3.0 | 0.40 | 0.0 | 0.00 | 2.31 | 5.8× | – |', text)  # Settled.
        self.assertIn('| 2026-10-12 | 1 | 3.0 | 0.40 | 0.0 | 0.00 | pending | – | – |', text)
        self.assertIn('Settled days: paid $2.31 vs estimated $0.40 (5.8×).', text)
        self.assertIn('the reward calibration a ranker would use: 5.78×.', text)
        self.assertIn('Credits matched to no program day: $0.00.', text)

    def test_a_past_day_with_no_credit_counts_as_paid_nothing(self):
        gone = datetime(2026, 10, 1, 3, 59, tzinfo=timezone.utc)
        text = calibration_report.report(calibration_report.load(self.db, NOW-timedelta(days=7)),
                                         days=7, now=NOW, tracker=self.tracker([('px', 'Z', gone, '0.50', 4)]))
        self.assertIn('| 2026-09-30 | 1 | 4.0 | 0.50 | 0.0 | 0.00 | 0.00 | 0.0× | – |', text)

    def ledger(self, realized=(), cash=(), lots=0, fee_reservations=()):
        import sqlite3
        from contextlib import closing
        path = Path(self.temp.name)/'account.db'
        with closing(sqlite3.connect(path)) as conn:
            conn.executescript("""CREATE TABLE realized_events (fill_id TEXT, gross_pnl TEXT, fee TEXT,
                pnl TEXT, received_at TEXT); CREATE TABLE cash_adjustments (source_key TEXT,
                exchange_index INTEGER, amount TEXT, kind TEXT, event_digest TEXT, at TEXT);
                CREATE TABLE lots (ticker TEXT, direction INTEGER, quantity TEXT);
                CREATE TABLE accounting_fees (client_id TEXT, fee TEXT);""")
            conn.executemany('INSERT INTO realized_events VALUES (?,?,?,?,?)',
                [(f'f{i}', '0', fee, pnl, at.isoformat()) for i, (at, pnl, fee) in enumerate(realized)])
            conn.executemany('INSERT INTO cash_adjustments VALUES (?,?,?,?,?,?)',
                [(f'c{i}', 0, amount, kind, 'd', at.isoformat()) for i, (at, kind, amount) in enumerate(cash)])
            conn.executemany('INSERT INTO lots VALUES (?,?,?)', [('A', 1, '30')]*lots)
            conn.executemany('INSERT INTO accounting_fees VALUES (?,?)', fee_reservations)
            conn.commit()
        return calibration_report.load_ledger(path)

    def test_business_summary_counts_only_measured_money(self):
        old, recent = NOW-timedelta(days=20), NOW-timedelta(days=2)
        ledger = self.ledger(realized=[(old, '-18.36', '0.36'), (recent, '-5.88', '0.48'), (recent, '0', '0')],
                             cash=[(recent, 'unattributed_credit', '1.22'), (old, 'deposit', '300')],
                             lots=1, fee_reservations=[('x', '44.40')])  # Reservations, not charges.
        text = calibration_report.report(calibration_report.load(self.db, NOW-timedelta(days=7)),
                                         days=7, now=NOW, ledger=ledger)
        self.assertIn('| last 7 days | 2 | -5.88 | 0.48 | 1.22 | -4.66 |', text)
        self.assertIn(f'| since the first fill ({old:%Y-%m-%d}) | 3 | -24.24 | 0.84 | 1.22 | -23.02 |', text)
        self.assertIn('Deposits (not income): $300.00. Open positions now: 1', text)
        self.assertIn(f'Coverage: ledger money since {old:%Y-%m-%d %H:%M} UTC; research sections since', text)
        self.assertNotIn('44.40', text)

    def test_resting_estimate_uses_each_legs_own_end(self):
        data = dict(entries=[('2026-10-09T10:00:00+00:00', 'b', dict(program_id='P', program_end=
                              '2026-10-20T03:59:00+00:00', hourly_reward_usd='0.40', order_ids=['o1', 'o2']))],
                    entry_ends=[('2026-10-09T11:00:00+00:00', 'o1', {})])
        now = datetime(2026, 10, 9, 13, tzinfo=timezone.utc)
        [(program, row)] = calibration_report.resting_estimates(data, now).items()
        # o1 rested 1 h, o2 is still resting (3 h): (1+3) h x 0.40/2.
        self.assertEqual((program, row['hours'], row['estimate']), ('P', D(4), D('0.8')))

    def test_summary_and_payout_days_agree_on_unpaid_resting_estimate(self):
        later = datetime(2026, 10, 12, 3, 59, tzinfo=timezone.utc)
        data = calibration_report.load(self.db, NOW-timedelta(days=7))
        data['entries'] = [(NOW.isoformat(), 'b', dict(program_id='p9', program_end=later.isoformat(),
                                                        hourly_reward_usd='0.60', order_ids=['z1'])),
                           # Already ended (and paid or not): never "not yet paid".
                           ((NOW-timedelta(days=2)).isoformat(), 'c', dict(program_id='p0',
                            program_end=(NOW-timedelta(days=1)).isoformat(), hourly_reward_usd='5',
                            order_ids=['z0']))]
        data['entry_ends'] = [((NOW-timedelta(days=1, hours=12)).isoformat(), 'z0', dict(filled='0'))]
        tracker = self.tracker([('p9', 'Z', later, '0.10', 1)])
        text = calibration_report.report(data, days=7, now=NOW+timedelta(hours=2), tracker=tracker,
                                         ledger=self.ledger())
        self.assertIn('resting-based (resting time × estimated rate; leans high): $0.60', text)
        self.assertIn('| 2026-10-11 | 1 | 1.0 | 0.10 | 2.0 | 0.60 | pending | – | – |', text)

    def test_unreadable_ledger_is_said_not_guessed(self):
        self.assertIsNone(calibration_report.load_ledger(Path(self.temp.name)/'missing.db'))
        text = calibration_report.report(calibration_report.load(self.db, NOW-timedelta(days=7)),
                                         days=7, now=NOW)
        self.assertIn('Ledger unavailable: no measured money in this report.', text)

    def test_without_the_tracker_the_section_says_so(self):
        text = calibration_report.report(calibration_report.load(self.db, NOW-timedelta(days=7)),
                                         days=7, now=NOW)
        self.assertIn('Reward tracker checkpoint unavailable', text)

    def test_weighting_favours_the_newest_week(self):
        now = datetime(2026, 10, 30, 12, tzinfo=timezone.utc)
        E = calibration_report.EASTERN
        days = {(now-timedelta(days=2)).astimezone(E).date(): dict(estimate=D(1), paid=D(4), credited=True),
                (now-timedelta(days=9)).astimezone(E).date(): dict(estimate=D(1), paid=D(1), credited=True),
                (now-timedelta(days=16)).astimezone(E).date(): dict(estimate=D(1), paid=D(1), credited=True),
                (now-timedelta(days=30)).astimezone(E).date(): dict(estimate=D(1), paid=D(9), credited=True)}
        # (0.5*4 + 0.25*1 + 0.25*1) / (0.5+0.25+0.25); the 30-day-old day is outside 3 weeks.
        self.assertEqual(calibration_report.weighted_factor(days, now), D('2.5'))

    def test_script_runs_end_to_end_on_a_windows_console(self):
        import os, subprocess, sys
        out = Path(self.temp.name)/'reports'
        env = dict(os.environ, PYTHONIOENCODING='cp1252')
        result = subprocess.run([sys.executable, '-B', str(SCRIPT), '--db', str(self.db),
                                 '--out', str(out), '--days', '3650'],
                                capture_output=True, env=env, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
        [written] = list(out.glob('calibration-*.md'))
        text = written.read_text(encoding='utf-8')
        self.assertTrue(text.startswith('# Calibration report'))
        self.assertIn('Goal: improve the bot.', text)
        self.assertIn('Reward truth', text)

    def test_pulls_are_split_by_real_trades_on_our_side(self):
        t0 = datetime(2026, 9, 26, 20, 0, tzinfo=timezone.utc)
        iso = lambda seconds: (t0+timedelta(seconds=seconds)).isoformat()
        order = lambda side, price: dict(side=side, price=price)
        data = dict(
            trades=[(None, 'x', dict(ticker='A', created_time=iso(-10).replace('+00:00', 'Z'),
                                     taker_side='no', yes_price='0.50', count='5')),   # hits bids >= .50
                    (None, 'y', dict(ticker='B', created_time=iso(-10), taker_side='yes',
                                     yes_price='0.50', count='5')),                  # wrong side for a bid
                    (None, 'z', dict(ticker='C', created_time=iso(-45), taker_side='no',
                                     yes_price='0.60', count='5')),                  # too early
                    (None, 'q', dict(ticker='D', created_time=iso(-5), taker_side='yes',
                                     yes_price='0.75', count='5')),                  # lifts asks at .75
                    (None, 'r', dict(ticker='F', created_time=iso(3), taker_side='no',
                                     yes_price='0.50', count='5')),                  # after the pull
                    (None, 's', dict(ticker='G', created_time=iso(0), taker_side='no',
                                     yes_price='0.30', count='30'))],                # the fill's own sweep
            withdrawals=[(iso(0), 'wA', dict(ticker='A', triggers=['time_to_fill'], orders=[order('bid', '0.5')])),
                         (iso(0), 'wB', dict(ticker='B', triggers=['time_to_fill'], orders=[order('bid', '0.5')])),
                         (iso(0), 'wC', dict(ticker='C', triggers=['time_to_fill'], orders=[order('bid', '0.5')])),
                         (iso(0), 'wD', dict(ticker='D', triggers=['short_queue'], orders=[order('ask', '0.75')])),
                         (iso(0), 'wE', dict(ticker='E', triggers=['time_to_fill'], orders=[order('bid', '0.4')])),
                         (iso(0), 'wF', dict(ticker='F', triggers=['time_to_fill'], orders=[order('bid', '0.5')]))],
            withdrawal_marks=[(None, 'wA@60', dict(level_gone=['o'])), (None, 'wB@60', dict(level_gone=['o'])), (None, 'wC@60', dict(level_gone=None)),
                              (None, 'wE@30', dict(level_gone=['o']))],
            fills=[(None, 'f1', dict(ticker='A', side='bid', price='0.50',
                                     executed_us=(t0+timedelta(seconds=5)).timestamp()*1e6)),
                   (None, 'f2', dict(ticker='E', side='bid', price='0.40', executed_us=t0.timestamp()*1e6)),
                   (None, 'f3', dict(ticker='G', side='bid', price='0.30', executed_us=t0.timestamp()*1e6))])
        text = calibration_report.trade_evidence_section(data)
        line = lambda start: next(l for l in text.splitlines() if l.startswith(start))
        # A backed (and gone, which is not a skip); B wrong side, C too early, E no
        # trades, F only a later trade -> skipped; only B of those was gone at 60 s.
        self.assertEqual(line('| time_to_fill'), '| time_to_fill | 5 | 1 | 4 | 1 |')
        self.assertEqual(line('| short_queue'), '| short_queue | 1 | 1 | 0 | 0 |')
        self.assertIn('3 fills; 1 had trades on our side in the 30 s before', text)

    def test_hourly_health(self):
        self.assertIn('| 2026-10-08T00 | 360 | 90% | 48 | 3 | 7 | 1 |', self.text)


class FinishLineTests(unittest.TestCase):
    """Kalshi pays nothing under $1: each live program's path to the minimum."""
    def data(self, programs):
        entries, ends = [], []
        for pid, rate, rested_hours, end_hours in programs:
            placed = NOW-timedelta(hours=10)
            entries.append((placed.isoformat(), pid, dict(program_id=pid, ticker='T'+pid,
                hourly_reward_usd=str(rate), order_ids=[pid+'b', pid+'a'],
                program_end=(NOW+timedelta(hours=end_hours)).isoformat())))
            for leg in ('b', 'a'):
                ends.append(((placed+timedelta(hours=rested_hours)).isoformat(), pid+leg, {}))
        return dict(entries=entries, entry_ends=ends)

    def test_each_verdict(self):
        data = self.data([('clear', '0.5', 4, 5),     # earned 0.5*4 = $2
                          ('track', '0.05', 5, 20),   # $0.25; needs 0.75/(0.05*20)=75%, has 50%
                          ('ok', '0.05', 8, 40),      # $0.40; needs 0.6/(0.05*40)=30%, has 80%
                          ('never', '0.01', 2, 5),    # $0.02; needs 0.98/0.05 > 100%
                          ('short', '0.1', 1, 5),     # $0.10; needs 0.9/0.5 = 180%
                          ('ended', '1', 5, -1)])     # ended: not a live program
        rows = {r['program_id']: r for r in calibration_report.finish_line(
            data, [dict(program_id='ok', estimate=D('0.1'))], NOW)}
        self.assertEqual({k: r['verdict'] for k, r in rows.items()},
                         dict(clear='cleared $1', track='needs more resting', ok='on track',
                              never='cannot reach', short='cannot reach'))
        self.assertEqual(rows['track']['share'], D('0.5'))
        self.assertEqual(rows['track']['needed'], D('0.75'))
        self.assertEqual(rows['ok']['earned'], D('0.4'))
        self.assertEqual((rows['ok']['strict'], rows['clear']['strict']), (D('0.1'), None))

    def test_the_section_totals_earnings_that_are_not_yet_on_track(self):
        text = calibration_report.finish_line_section(self.data(
            [('track', '0.05', 5, 20), ('never', '0.01', 2, 5), ('ok', '0.05', 8, 40),
             ('big', '0.1', 6, 5)]), None, NOW)  # big: $0.60 earned, needs more resting
        self.assertIn('pay nothing unless that changes): $0.87', text)
        self.assertLess(text.index('| Tok |'), text.index('| Tbig |'))  # verdict before size
        self.assertLess(text.index('| Tbig |'), text.index('| Ttrack |'))
        self.assertIn('No live programs', calibration_report.finish_line_section(
            dict(entries=[], entry_ends=[]), None, NOW))


class LossFilterTests(unittest.TestCase):
    def test_fills_are_split_at_the_filter_start(self):
        live = calibration_report.FILTERS_LIVE
        ledger = dict(realized=[(live-timedelta(days=2), D('-3'), D('0.1')),
                                (live-timedelta(days=1), D('-1'), D('0.1')),
                                (live+timedelta(hours=6), D('-0.5'), D('0.1'))], cash=[], open_lots=0)
        text = calibration_report.loss_filter_section(ledger, live+timedelta(days=1))
        self.assertIn('| before | 2.0 | 2 | -4.00 | -2.00 | 1.0 | -2.00 |', text)
        self.assertIn('| after | 1.0 | 1 | -0.50 | -0.50 | 1.0 | -0.50 |', text)
        self.assertIn('No ledger fills', calibration_report.loss_filter_section(None, live))


if __name__ == '__main__':
    unittest.main()
