"""D-151 weekly calibration report over a synthetic research dataset."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from kalshi_bot.research import ResearchStore

SCRIPT = Path(__file__).resolve().parents[1]/'scripts'/'research_report.py'
spec = importlib.util.spec_from_file_location('research_report', SCRIPT)
research_report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(research_report)

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
        self.text = research_report.report(research_report.load(self.db, NOW-timedelta(days=7)),
                                           days=7, now=NOW)

    def tearDown(self):
        self.temp.cleanup()

    def line(self, start):
        return next(l for l in self.text.splitlines() if l.startswith(start))

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
        self.assertEqual(self.line('| time_to_fill'), '| time_to_fill | 2 | 2 | 1 | 50% |')

    def test_sweeps_group_one_taker_order(self):
        self.assertEqual(self.line('| KXBROSFT | 2'), '| KXBROSFT | 2 | 246 | 488 | 1 |')

    def test_credits_match_programs_that_ended_the_day_before(self):
        self.assertIn('1 reward-like credits totalling $2.31.', self.text)
        self.assertIn('| prog-one | 2026-10-08 | 2.40 | yes | 2.31 |', self.text)
        self.assertIn('| prog-two | 2026-10-13 | – | no | – |', self.text)

    def test_script_runs_end_to_end_on_a_windows_console(self):
        import os, subprocess, sys
        out = Path(self.temp.name)/'reports'
        env = dict(os.environ, PYTHONIOENCODING='cp1252')
        result = subprocess.run([sys.executable, '-B', str(SCRIPT), '--db', str(self.db),
                                 '--out', str(out), '--days', '3650'],
                                capture_output=True, env=env, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
        [written] = list(out.glob('research-*.md'))
        self.assertIn('Reward truth', written.read_text(encoding='utf-8'))

    def test_hourly_health(self):
        self.assertIn('| 2026-10-08T00 | 360 | 90% | 48 | 3 | 7 | 1 |', self.text)


if __name__ == '__main__':
    unittest.main()
