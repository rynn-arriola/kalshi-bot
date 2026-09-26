"""D-151 research dataset: store, entry lifecycle and later collectors."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from kalshi_bot.dispatch import ENTRY_PAIR, DispatchResult, EntryPairCandidate
from kalshi_bot.research import ResearchStore
import test_bot_entry_dispatch as entry_fixture


def rows(path, table):
    with closing(sqlite3.connect(path)) as conn:
        return [(key, json.loads(payload)) for key, payload in
                conn.execute(f'SELECT key,payload FROM {table} ORDER BY id')]


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name)/'research.db'

    def tearDown(self):
        self.temp.cleanup()

    def test_records_are_written_in_the_background_and_flushed_on_close(self):
        store = ResearchStore(self.path).start()
        self.assertTrue(store.record('entries', 'b1', ticker='A', price=D('0.82'),
                                     at=datetime(2026, 9, 26, tzinfo=timezone.utc)))
        store.close()
        self.assertEqual(rows(self.path, 'entries'),
                         [('b1', {'ticker': 'A', 'price': '0.82', 'at': '2026-09-26T00:00:00+00:00'})])
        self.assertEqual((store.status()['written'], store.status()['dropped']), (1, 0))

    def test_close_flushes_a_large_backlog(self):
        store = ResearchStore(self.path, capacity=4096).start()
        for index in range(3000):
            store.record('health_hourly', f'h{index}', index=index)
        store.close()
        self.assertEqual(len(rows(self.path, 'health_hourly')), 3000)
        self.assertEqual(store.status()['written'], 3000)

    def test_venue_identities_are_stored_once(self):
        store = ResearchStore(self.path).start()
        for _ in range(3):
            store.record('fills', 'f1', qty='30')
            store.record('entries', 'b1', n=1)
        store.close()
        self.assertEqual(len(rows(self.path, 'fills')), 1)
        self.assertEqual(len(rows(self.path, 'entries')), 3)

    def test_bad_input_or_a_full_queue_is_dropped_never_raised(self):
        store = ResearchStore(self.path, capacity=1)  # Not started: queue fills.
        self.assertFalse(store.record('no_such_table', 'k'))
        self.assertFalse(store.record('entries', 'k', value=object()))
        self.assertTrue(store.record('entries', 'k1'))
        self.assertFalse(store.record('entries', 'k2'))
        self.assertEqual(store.status()['dropped'], 3)
        store.start()
        store.close()
        self.assertFalse(store.record('entries', 'late'))  # Closed store.

    def test_old_rows_are_pruned_on_start(self):
        old = datetime(2026, 1, 1, tzinfo=timezone.utc)
        store = ResearchStore(self.path, now=lambda: old).start()
        store.record('trades', 't-old')
        store.close()
        store = ResearchStore(self.path, now=lambda: old+timedelta(days=121)).start()
        store.record('trades', 't-new')
        store.close()
        self.assertEqual([key for key, _ in rows(self.path, 'trades')], ['t-new'])


class EntryLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.f = entry_fixture.EntrySourceTests('test_ranked_market_becomes_exact_source_bound_pair')
        await self.f.asyncSetUp()
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name)/'research.db'
        self.store = ResearchStore(self.path).start()
        self.f.runtime.research = self.store

    async def asyncTearDown(self):
        self.store.close()
        await self.f.asyncTearDown()
        self.temp.cleanup()

    async def placed(self, state='ACK', order_ids=('order-bid', 'order-ask')):
        candidate = await self.f.source.refresh('A', ENTRY_PAIR)
        self.assertIsInstance(candidate, EntryPairCandidate)
        self.f.source._dispatch_result(DispatchResult(state, 'A', ENTRY_PAIR,
            candidate.batch_id, order_ids=order_ids))
        return candidate

    async def test_acknowledged_pair_records_its_placement_context(self):
        candidate = await self.placed()
        self.store.close()
        [(key, row)] = rows(self.path, 'entries')
        self.assertEqual(key, candidate.batch_id)
        self.assertEqual(row['order_ids'], ['order-bid', 'order-ask'])
        self.assertEqual(row['ticker'], 'A')
        self.assertEqual({q['side'] for q in row['quotes']}, {'bid', 'ask'})
        self.assertTrue(all(q['visible_ahead'] is not None for q in row['quotes']))
        for field in ('program_id', 'remaining_reward_usd', 'screen', 'worst_fill_loss_usd',
                      'program_end', 'snapshot_share'):
            self.assertIn(field, row)
        self.assertEqual(self.f.source._entry_contexts, {})

    async def test_an_unplaced_attempt_records_nothing_and_leaves_no_context(self):
        await self.placed(state='BLOCKED', order_ids=())
        self.store.close()
        self.assertEqual(rows(self.path, 'entries'), [])
        self.assertEqual(self.f.source._entry_contexts, {})

    def receipt(self, order_id='o1', status='canceled', owned=True, reducing=False, terminal=True):
        order = SimpleNamespace(order_id=order_id, ticker='A', side='bid', yes_price=D('0.5'),
                                initial=D(10), filled=D(0), remaining=D(0), status=status,
                                terminal=terminal)
        return SimpleNamespace(order=order, owned=owned, reducing=reducing)

    async def test_each_entry_end_is_recorded_once_and_never_for_reducers(self):
        r = self.f.runtime
        r._research_entry_end(self.receipt())
        r._research_entry_end(self.receipt())  # Re-delivered terminal update.
        r._research_entry_end(self.receipt('o2', reducing=True))
        r._research_entry_end(self.receipt('o3', owned=False))
        r._research_entry_end(self.receipt('o4', status='resting', terminal=False))
        self.assertEqual(self.store.status()['accepted'], 1)  # Deduplicated in memory.
        self.store.close()
        ends = rows(self.path, 'entry_ends')
        self.assertEqual([key for key, _ in ends], ['o1'])
        self.assertEqual(ends[0][1]['status'], 'canceled')
        self.assertFalse(ends[0][1]['withdrawn'])

    async def test_withdrawn_orders_are_marked(self):
        r = self.f.runtime
        r.maintenance = SimpleNamespace(risk_cycle_for=lambda ticker: SimpleNamespace(
            order_ids=('o9',)))
        r._research_entry_end(self.receipt('o9'))
        self.store.close()
        self.assertTrue(rows(self.path, 'entry_ends')[0][1]['withdrawn'])


if __name__ == '__main__':
    unittest.main()
