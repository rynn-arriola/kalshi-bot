"""D-155: stay out of a market for an hour after a big sweep (Finding 215)."""
import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS
import unittest

from kalshi_bot.quote_maintenance import sweeps_from_trades
from kalshi_bot.values import InvalidData

NOW = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)
S = lambda when: int(when.timestamp())


def trade(ticker, when, side, count, price='0.5'):
    return dict(ticker=ticker, created_time=when.isoformat().replace('+00:00', 'Z'),
                taker_side=side, count_fp=str(count), yes_price_dollars=price)


class GroupingTests(unittest.TestCase):
    def test_one_taker_order_is_the_trades_sharing_time_and_side(self):
        t1, t2 = NOW-timedelta(minutes=10), NOW-timedelta(minutes=3)
        rows = [trade('A', t1, 'no', 100), trade('A', t1, 'no', 60),     # 160: a sweep
                trade('B', t1, 'no', 100), trade('B', t1, 'yes', 60),    # two orders of <150
                trade('C', t2, 'yes', 149.99),                          # just under
                trade('A', t2, 'yes', 500),                             # newer sweep wins
                dict(ticker='D', created_time='bad', taker_side='no', count_fp='900'),
                dict(ticker='E')]
        self.assertEqual(sweeps_from_trades(rows, 150), {'A': S(t2)})


class FilterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import test_bot_fill_protection as protection
        self.p = protection.AnchoredProtectionTests('test_cancel_ahead_then_join_behind_is_never_netted')
        await self.p.asyncSetUp()
        self.m, self.r = self.p.m, self.p.r
        self.now = [NOW]
        self.r.now = lambda: self.now[0]
        self.m.queue_reader_active = False

    async def asyncTearDown(self):
        await self.p.asyncTearDown()

    def test_off_unless_live_composition_turns_it_on(self):
        self.assertTrue(self.m.sweep_allows('A'))

    def test_fails_closed_until_a_complete_poll_and_when_stale(self):
        self.m.sweep_filter_required = True
        self.assertFalse(self.m.sweep_allows('A'))
        self.m.record_sweeps({}, mono=self.r.clock(), polled_s=S(NOW))
        self.assertTrue(self.m.sweep_allows('A'))
        self.m.sweeps_loaded_mono = self.r.clock()-self.m.SWEEP_STALE_SECONDS-1
        self.assertFalse(self.m.sweep_allows('A'))

    def test_a_swept_market_waits_an_hour(self):
        self.m.sweep_filter_required = True
        self.m.record_sweeps({'A': S(NOW-timedelta(minutes=12)), 'B': S(NOW-timedelta(minutes=61))},
                             mono=self.r.clock(), polled_s=S(NOW))
        self.assertFalse(self.m.sweep_allows('A'))
        self.assertNotIn('B', self.m.sweeps)  # Expired entries are dropped.
        blocks = self.m.sweep_blocks
        self.assertFalse(self.m.entry_allowed('A', 'p'))
        self.assertEqual(self.m.sweep_blocks, blocks+1)
        self.assertEqual(self.m.status()['sweep_filter']['markets_blocked'], 1)
        self.now[0] = NOW+timedelta(minutes=48, seconds=1)
        self.assertTrue(self.m.sweep_allows('A'))

    def test_a_newer_poll_never_moves_a_sweep_earlier(self):
        self.m.sweep_filter_required = True
        self.m.record_sweeps({'A': S(NOW-timedelta(minutes=5))}, mono=self.r.clock(), polled_s=S(NOW))
        self.m.record_sweeps({'A': S(NOW-timedelta(minutes=40))}, mono=self.r.clock(), polled_s=S(NOW))
        self.assertEqual(self.m.sweeps['A'], S(NOW-timedelta(minutes=5)))


class PollTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import test_bot_fill_protection as protection
        self.p = protection.AnchoredProtectionTests('test_cancel_ahead_then_join_behind_is_never_netted')
        await self.p.asyncSetUp()
        self.m, self.r = self.p.m, self.p.r
        self.m.sweep_filter_required = True
        self.r.now = lambda: NOW
        self.temp = TemporaryDirectory()
        self.r.sweep_state_path = Path(self.temp.name)/'sweeps.json'
        self.r.SWEEP_POLL_SECONDS = .01
        self.calls = []

    async def asyncTearDown(self):
        await self.p.asyncTearDown()
        self.temp.cleanup()

    def reads(self, rows_for, too_big=lambda start, end: False):
        async def collect(name, *, reason, max_pages, max_rows, limit, min_ts, max_ts):
            self.assertEqual((name, reason, limit), ('trades', 'sweeps', 1000))
            self.calls.append((min_ts, max_ts))
            if too_big(min_ts, max_ts):
                raise InvalidData('pagination resource limit; result is incomplete')
            return NS(rows=rows_for(min_ts, max_ts))
        self.r.reads = NS(collect=collect)

    async def run_once(self):
        task = asyncio.create_task(self.r._sweep_watch_loop())
        await asyncio.sleep(.05)
        self.r.stop_requested.set()
        await asyncio.wait_for(task, 2)
        self.r.stop_requested.clear()

    async def test_first_poll_covers_the_last_minute_and_saves_the_list(self):
        swept = NOW-timedelta(seconds=20)
        self.reads(lambda a, b: [trade('A', swept, 'no', 400)] if a <= S(swept) <= b else [])
        await self.run_once()
        self.assertEqual(self.calls[0], (S(NOW)-60, S(NOW)))
        self.assertFalse(self.m.sweep_allows('A'))
        self.assertTrue(self.m.sweep_allows('B'))
        saved = json.loads(self.r.sweep_state_path.read_text(encoding='utf-8'))
        self.assertEqual((saved['polled_s'], saved['sweeps']), (S(NOW), {'A': S(swept)}))

    async def test_each_poll_also_feeds_the_research_sweep_counts(self):
        from kalshi_bot.research import ResearchStore
        store = ResearchStore(Path(self.temp.name)/'research.db').start()
        self.r.research = store
        try:
            tracked = next(iter(self.r.management._plans))
            swept = NOW-timedelta(seconds=20)
            self.reads(lambda a, b: [trade(tracked, swept, 'no', 400)] if a <= S(swept) <= b else [])
            await self.run_once()
            counts = self.r._research_sweep_state['counts']
            self.assertEqual([row['at_least_150'] for (t, _), row in counts.items() if t == tracked], [1])
        finally:
            self.r.research = None
            store.close()

    async def test_a_restart_reloads_the_list_and_catches_up_the_gap(self):
        self.r.sweep_state_path.write_text(json.dumps(dict(
            polled_s=S(NOW)-200, sweeps={'OLD': S(NOW)-1800})), encoding='utf-8')
        self.reads(lambda a, b: [])
        await self.run_once()
        self.assertEqual(self.calls[:4], [(S(NOW)-205, S(NOW)-145), (S(NOW)-145, S(NOW)-85),
                                          (S(NOW)-85, S(NOW)-25), (S(NOW)-25, S(NOW))])
        self.assertFalse(self.m.sweep_allows('OLD'))  # Still inside its hour after the restart.

    async def test_catch_up_is_bounded_to_ten_minutes(self):
        self.r.sweep_state_path.write_text(json.dumps(dict(polled_s=S(NOW)-7200, sweeps={})),
                                           encoding='utf-8')
        self.reads(lambda a, b: [])
        await self.run_once()
        self.assertEqual(self.calls[0][0], S(NOW)-600)

    async def test_a_window_too_big_for_one_read_is_split(self):
        swept = NOW-timedelta(seconds=40)
        self.reads(lambda a, b: [trade('A', swept, 'yes', 300)] if a <= S(swept) <= b else [],
                   too_big=lambda a, b: b-a > 15)
        await self.run_once()
        self.assertEqual(self.m.sweep_failures, 0)  # Split, not failed.
        self.assertFalse(self.m.sweep_allows('A'))
        self.assertTrue(self.m.sweep_allows('B'))  # The poll completed and loaded.

    async def test_a_poll_that_cannot_complete_counts_and_stays_closed(self):
        self.reads(lambda a, b: [], too_big=lambda a, b: True)
        await self.run_once()
        self.assertGreaterEqual(self.m.sweep_failures, 1)
        self.assertFalse(self.m.sweep_allows('A'))


if __name__ == '__main__':
    unittest.main()
