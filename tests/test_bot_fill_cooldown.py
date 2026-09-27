"""D-154: no re-entry for 24 hours in a market that filled us."""
import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
import json
from pathlib import Path
import sqlite3
from contextlib import closing
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS
import unittest

from kalshi_bot.ledger import Fill
from kalshi_bot.research import ResearchStore
from kalshi_bot.writer import LedgerWriter

NOW = datetime(2026, 9, 27, 3, 0, tzinfo=timezone.utc)
US = lambda when: int(when.timestamp()*1_000_000)


def fill(key, ticker='A', executed=None, side='bid'):
    return Fill('t-'+key, 'o-'+key, ticker, side, D(30), D('.53'), D(0),
                executed_us=US(executed or NOW), execution_precision_us=1)


class LedgerQueryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        self.writer = await LedgerWriter(Path(self.temp.name)/'writer.db').start()

    async def asyncTearDown(self):
        await self.writer.close()
        self.temp.cleanup()

    async def test_recent_fills_are_read_only_and_bounded_by_time(self):
        await self.writer.fill(fill('old', 'OLD', NOW-timedelta(hours=30)), NOW)
        await self.writer.fill(fill('new', 'NEW', NOW-timedelta(hours=1)), NOW)
        revision = self.writer.revision
        rows = await self.writer.recent_fills(US(NOW-timedelta(hours=24)))
        self.assertEqual(self.writer.revision, revision)  # A read never advances the writer.
        self.assertEqual(rows, ((('o-new', 't-new'), ('NEW', 'bid', '3E+1', '0.53', '0'),
                                 US(NOW-timedelta(hours=1))),))


class CooldownTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import test_bot_fill_protection as protection
        self.p = protection.AnchoredProtectionTests('test_cancel_ahead_then_join_behind_is_never_netted')
        await self.p.asyncSetUp()
        self.m, self.r = self.p.m, self.p.r
        self.now = [NOW]
        self.r.now = lambda: self.now[0]
        self.m.queue_reader_active = False  # Isolate the cooldown from protection freshness.

    async def asyncTearDown(self):
        await self.p.asyncTearDown()

    def load(self, **fills):
        rows = tuple(((f'o-{t}', f't-{t}'), (t, 'bid', '30', '0.53', '0'), US(when))
                     for t, when in fills.items())
        self.m.set_fill_history(rows, self.r.clock())

    def test_off_unless_live_composition_turns_it_on(self):
        self.assertFalse(self.m.fill_cooldown_required)
        self.assertTrue(self.m.fill_cooldown_allows('A'))

    def test_fails_closed_until_the_ledger_is_read(self):
        self.m.fill_cooldown_required = True
        self.assertFalse(self.m.fill_cooldown_allows('A'))
        self.assertFalse(self.m.entry_allowed('A', 'p'))
        self.load()
        self.assertTrue(self.m.fill_cooldown_allows('A'))

    def test_a_market_family_that_filled_us_waits_7_days(self):
        self.m.fill_cooldown_required = True
        self.load(A=NOW-timedelta(hours=1), B=NOW-timedelta(days=7, hours=1))
        self.assertFalse(self.m.fill_cooldown_allows('A'))
        self.assertTrue(self.m.fill_cooldown_allows('B'))
        self.assertTrue(self.m.fill_cooldown_allows('C'))
        blocks = self.m.fill_cooldown_blocks
        self.assertFalse(self.m.entry_allowed('A', 'p'))
        self.assertEqual(self.m.fill_cooldown_blocks, blocks+1)
        self.now[0] = NOW+timedelta(days=6, hours=23, minutes=1)
        self.assertTrue(self.m.fill_cooldown_allows('A'))
        status = self.m.status()['fill_cooldown']
        self.assertEqual((status['required'], status['loaded'], status['markets']), (True, True, 0))

    def test_newest_fill_in_a_market_counts(self):
        self.m.fill_cooldown_required = True
        rows = (((('o1', 't1'), ('A', 'bid', '30', '0.58', '0'), US(NOW-timedelta(hours=30))),
                 (('o2', 't2'), ('A', 'ask', '30', '0.35', '0'), US(NOW-timedelta(hours=2)))))
        self.m.set_fill_history(rows, self.r.clock())
        self.assertFalse(self.m.fill_cooldown_allows('A'))
        self.assertAlmostEqual(self.m.fill_cooldown_status()['hours_left']['A'], 7*24-2, places=2)

    def test_other_markets_in_the_same_family_wait_too(self):
        """D-155: KXTXOIL filled us three times across strikes and days."""
        self.m.fill_cooldown_required = True
        rows = ((('o1', 't1'), ('KXTXOIL-27MAR31-T5.8', 'bid', '30', '0.53', '0'),
                 US(NOW-timedelta(days=3))),)
        self.m.set_fill_history(rows, self.r.clock())
        self.assertFalse(self.m.fill_cooldown_allows('KXTXOIL-27MAR31-T6.2'))
        self.assertFalse(self.m.fill_cooldown_allows('KXTXOIL-28MAR31-T5.8'))
        self.assertTrue(self.m.fill_cooldown_allows('KXTXGAS-27MAR31-T5.8'))
        self.assertEqual(list(self.m.fill_cooldown_status()['hours_left']), ['KXTXOIL'])

    def test_stale_ledger_read_fails_closed(self):
        self.m.fill_cooldown_required = True
        self.load()
        self.m.fill_cooldown_loaded_mono = self.r.clock()-self.m.FILL_COOLDOWN_STALE_SECONDS-1
        self.assertFalse(self.m.fill_cooldown_allows('C'))


class LoopTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import test_bot_fill_protection as protection
        self.p = protection.AnchoredProtectionTests('test_cancel_ahead_then_join_behind_is_never_netted')
        await self.p.asyncSetUp()
        self.m, self.r = self.p.m, self.p.r
        self.m.fill_cooldown_required = True
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name)/'research.db'
        self.store = ResearchStore(self.path).start()
        self.r.research = self.store
        self.r.FILL_HISTORY_SECONDS = .01

    async def asyncTearDown(self):
        self.store.close()
        self.r.research = None
        await self.p.asyncTearDown()
        self.temp.cleanup()

    async def run_once(self, reader):
        self.r.writer.recent_fills = reader
        task = asyncio.create_task(self.r._fill_history_loop())
        await asyncio.sleep(.05)
        self.r.stop_requested.set()
        await asyncio.wait_for(task, 2)
        self.r.stop_requested.clear()

    async def test_loop_loads_the_cooldown_and_backfills_research_once(self):
        now_us = US(self.r.now())
        rows = ((('o-new', 't-new'), ('A', 'bid', '30', '0.53', '0'), now_us-5_000_000),
                (('o-old', 't-old'), ('B', 'ask', '3E+1', '0.35', '0'), now_us-3_600_000_000))
        async def reader(since):
            self.assertLessEqual(abs(since-(now_us-7*24*3600*1_000_000)), 5_000_000)
            return rows
        self.r.RESEARCH_MARK_SECONDS = (60,)
        await self.run_once(reader)
        self.assertFalse(self.m.fill_cooldown_allows('A'))
        self.assertFalse(self.m.fill_cooldown_allows('B'))
        self.assertEqual(self.r._research_marks_pending, 1)  # Only the fresh fill gets a mark.
        self.store.close()
        with closing(sqlite3.connect(self.path)) as conn:
            recorded = {k: json.loads(p) for k, p in conn.execute('SELECT key,payload FROM fills')}
        self.assertEqual(set(recorded), {'o-new/t-new', 'o-old/t-old'})
        self.assertEqual((recorded['o-new/t-new']['role'], recorded['o-new/t-new']['ticker']), ('ledger', 'A'))
        self.assertEqual(recorded['o-old/t-old']['quantity'], '30')

    async def test_stream_recorded_fill_is_not_recorded_twice(self):
        self.r._research_ledger_seen = {'o-new/t-new'}
        now_us = US(self.r.now())
        async def reader(since):
            return ((('o-new', 't-new'), ('A', 'bid', '30', '0.53', '0'), now_us),)
        accepted = self.store.status()['accepted']
        await self.run_once(reader)
        self.assertEqual(self.store.status()['accepted'], accepted)

    async def test_fill_seen_by_the_stream_hook_is_skipped_by_the_sweep(self):
        now_us = US(self.r.now())
        live = NS(order_id='o-live', trade_id='t-live', ticker='A', book_side='bid', yes_price=D('.53'),
                  quantity=D(30), fee=D(0), executed_us=now_us)
        self.r.RESEARCH_MARK_SECONDS = (60,)
        accepted = self.store.status()['accepted']
        self.r._research_fill(live, NS(order=None))
        async def reader(since):
            return ((('o-live', 't-live'), ('A', 'bid', '3E+1', '0.53', '0'), now_us),)
        await self.run_once(reader)
        self.assertEqual(self.store.status()['accepted'], accepted+1)
        self.assertEqual(self.r._research_marks_pending, 1)  # No second set of mark-outs.

    async def test_read_failures_are_counted_and_keep_entries_closed(self):
        async def broken(since):
            raise OSError('disk')
        await self.run_once(broken)
        self.assertGreaterEqual(self.m.fill_cooldown_failures, 1)
        self.assertFalse(self.m.fill_cooldown_allows('A'))


if __name__ == '__main__':
    unittest.main()
