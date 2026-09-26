"""D-151 research dataset: store, entry lifecycle and later collectors."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from threading import Event
from types import SimpleNamespace
import unittest

from kalshi_bot.dispatch import ENTRY_PAIR, DispatchResult, EntryPairCandidate
from kalshi_bot.research import ResearchStore
import test_bot_entry_dispatch as entry_fixture


def _broken_mark():
    raise KeyError('ticker')


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

    def test_a_failing_prune_never_stops_the_writer(self):
        class LockedDeletes:
            def __init__(self, conn):
                self.conn = conn
            def execute(self, sql, *args):
                if sql.startswith('DELETE'):
                    raise sqlite3.OperationalError('database is locked')
                return self.conn.execute(sql, *args)
            def __enter__(self):
                return self.conn.__enter__()
            def __exit__(self, *args):
                return self.conn.__exit__(*args)
            def close(self):
                self.conn.close()

        class Store(ResearchStore):
            def _connect(self):
                return LockedDeletes(super()._connect())

        clock = [datetime(2026, 9, 26, tzinfo=timezone.utc)]
        store = Store(self.path, now=lambda: clock[0]).start()  # Startup prune fails.
        self.assertTrue(store.status()['alive'])
        clock[0] += timedelta(hours=7)  # The next batch also runs the periodic prune.
        store.record('trades', 't1')
        for _ in range(100):
            if store.status()['written'] == 1:
                break
            Event().wait(.05)
        store.record('trades', 't2')
        store.close()
        self.assertEqual([key for key, _ in rows(self.path, 'trades')], ['t1', 't2'])
        self.assertEqual((store.status()['failures'], store.status()['last_error']),
                         (2, 'OperationalError'))


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


class FillContextTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.f = entry_fixture.EntrySourceTests('test_ranked_market_becomes_exact_source_bound_pair')
        await self.f.asyncSetUp()
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name)/'research.db'
        self.store = ResearchStore(self.path).start()
        self.r = self.f.runtime
        self.r.research = self.store

    async def asyncTearDown(self):
        self.store.close()
        await self.f.asyncTearDown()
        self.temp.cleanup()

    def fill(self, trade='t1'):
        from kalshi_bot.ledger import Fill
        return Fill(trade, 'o1', 'A', 'bid', D(30), D('0.82'), D(0), 1790401936916817)

    async def test_fill_records_context_and_later_marks(self):
        self.r.RESEARCH_MARK_SECONDS = (0.01, 0.02)
        self.r.maintenance = SimpleNamespace(
            fill_risk=SimpleNamespace(samples={'o1': SimpleNamespace(ahead=D(200), rate=D(0), at=self.r.clock())}),
            _anchors={'o1': SimpleNamespace(ahead=D(230), read_mono=self.r.clock())},
            risk_cycle_for=lambda ticker: None)
        receipt = SimpleNamespace(order=SimpleNamespace(reducing=False))
        self.r._research_fill(self.fill(), receipt)
        self.assertEqual(self.r.research_fills_recorded, 1)
        import asyncio
        await asyncio.sleep(.1)
        self.store.close()
        [(key, row)] = rows(self.path, 'fills')
        self.assertEqual(key, 'o1/t1')
        self.assertEqual((row['role'], row['estimated_ahead'], row['anchor_ahead'], row['price']),
                         ('entry', '200', '230', '0.82'))
        self.assertIn('best_bid', row)
        self.assertFalse(row['withdrawal_in_progress'])
        marks = rows(self.path, 'fill_marks')
        self.assertEqual(sorted(m['delay_seconds'] for _, m in marks), [0.01, 0.02])
        self.assertEqual(self.r._research_marks_pending, 0)

    async def test_exit_fills_are_labelled_and_pending_marks_are_bounded(self):
        self.r.RESEARCH_MAX_PENDING_MARKS = 3
        self.r.RESEARCH_MARK_SECONDS = (60, 300, 1800)
        receipt = SimpleNamespace(order=SimpleNamespace(reducing=True))
        self.r._research_fill(self.fill('t1'), receipt)
        self.r._research_fill(self.fill('t2'), receipt)  # Over the bound: no marks.
        self.assertEqual(self.r._research_marks_pending, 3)
        self.store.close()
        self.assertEqual([r['role'] for _, r in rows(self.path, 'fills')], ['exit', 'exit'])

    async def test_a_research_failure_never_stops_fill_processing(self):
        from kalshi_bot.runtime import RecoveryRuntime
        calls = []
        async def apply_pending_fill(key, **_):
            return SimpleNamespace(order=None)
        async def refresh(ticker):
            calls.append(('refresh', ticker))
        stub = SimpleNamespace(account_lock=__import__('asyncio').Lock(),
            account=SimpleNamespace(apply_pending_fill=apply_pending_fill),
            management=SimpleNamespace(refresh=refresh), research=self.store,
            research_failures=0, now=lambda: None,
            _request_inventory_dispatch=lambda t: calls.append(('dispatch', t)),
            _resume_risk_drain=lambda: calls.append('drain'),
            request_recovery=lambda *a: calls.append('recover'))
        stub._research_safely = lambda fn, *a: RecoveryRuntime._research_safely(stub, fn, *a)
        def broken(*_):
            raise RuntimeError('research bug')
        stub._research_fill = broken
        event = dict(type='fill', msg=dict(trade_id='t9', order_id='o9', market_ticker='A',
            book_side='bid', count_fp='1.00', yes_price_dollars='0.5', fee_cost='0',
            ts=1790401936))
        await RecoveryRuntime._private(stub, event, 1)
        self.assertEqual(calls, [('refresh', 'A'), ('dispatch', 'A'), 'drain'])
        self.assertEqual(stub.research_failures, 1)


class RewardTruthTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.f = entry_fixture.EntrySourceTests('test_ranked_market_becomes_exact_source_bound_pair')
        await self.f.asyncSetUp()
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name)/'research.db'
        self.store = ResearchStore(self.path).start()
        self.r = self.f.runtime
        self.r.research = self.store

    async def asyncTearDown(self):
        self.store.close()
        await self.f.asyncTearDown()
        self.temp.cleanup()

    async def test_cash_credits_are_recorded_once(self):
        from kalshi_bot.cash_attribution import CashAdjustment
        result = SimpleNamespace(cash_adjustments=(
            CashAdjustment('credit-1', 0, D('1.25'), 'unattributed_credit'),
            CashAdjustment('deposit-1', 0, D('300'), 'deposit')))
        self.r.accounting_result = result
        self.r.accounting_result = result  # Same adjustments in a later release.
        self.store.close()
        credits = rows(self.path, 'reward_credits')
        self.assertEqual(sorted(k for k, _ in credits), ['credit-1', 'deposit-1'])
        self.assertEqual({r['kind']: r['amount'] for _, r in credits},
                         {'unattributed_credit': '1.25', 'deposit': '300'})

    def rewards(self):
        from dataclasses import dataclass
        @dataclass
        class Progress:
            program_id: str
            sampled_gross_usd: D
        def progress(program_id):
            if program_id == 'broken':
                raise KeyError(program_id)
            return Progress(program_id, D('0.5'))
        return SimpleNamespace(tracker=SimpleNamespace(records={'p1': 1, 'broken': 2}),
                               progress=progress)

    def stub(self):
        from kalshi_bot.runtime import RecoveryRuntime
        import asyncio
        stub = SimpleNamespace(rewards=self.rewards(), research=self.store, research_failures=0,
            stop_requested=asyncio.Event(), now=self.r.now, RESEARCH_TICK_SECONDS=.01,
            RESEARCH_TRADE_SECONDS=0, clock=__import__('time').monotonic)
        stub.samples, stub.health = [], []
        stub._research_sample_health = lambda: stub.samples.append(1)
        stub._research_health = lambda hour: stub.health.append(hour)
        stub._research_safely = lambda fn, *a: RecoveryRuntime._research_safely(stub, fn, *a)
        stub._research_reward_estimates = (
            lambda hour: RecoveryRuntime._research_reward_estimates(stub, hour))
        return stub, RecoveryRuntime

    async def test_hourly_estimates_skip_failures_and_repeat_per_hour_once(self):
        stub, runtime = self.stub()
        hour = datetime(2026, 9, 26, 17, tzinfo=timezone.utc)
        runtime._research_reward_estimates(stub, hour)
        runtime._research_reward_estimates(stub, hour)  # Restart within the hour.
        self.store.close()
        estimates = rows(self.path, 'reward_estimates')
        self.assertEqual([k for k, _ in estimates], ['p1@2026-09-26T17:00:00+00:00'])
        self.assertEqual(estimates[0][1]['sampled_gross_usd'], '0.5')
        self.assertEqual(stub.research_failures, 2)

    async def test_loop_writes_the_current_hour_then_stops(self):
        import asyncio
        stub, runtime = self.stub()
        polls = []
        async def trades():
            polls.append(1)
        stub._research_trades = trades
        task = asyncio.create_task(runtime._research_loop(stub))
        await asyncio.sleep(.05)
        stub.stop_requested.set()
        await asyncio.wait_for(task, 2)
        self.assertEqual(self.store.status()['accepted'], 1)  # Several ticks, one hour.
        self.assertGreaterEqual(len(polls), 2)  # Trades are polled every tick.
        self.assertGreaterEqual(len(stub.samples), 2)  # Health is sampled every tick.
        self.assertEqual(stub.research_failures, 1)  # Only the stub's broken program.
        self.store.close()
        self.assertEqual(len(rows(self.path, 'reward_estimates')), 1)

class WithdrawalOutcomeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import test_bot_fill_protection as protection
        self.p = protection.AnchoredProtectionTests('test_cancel_ahead_then_join_behind_is_never_netted')
        await self.p.asyncSetUp()
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name)/'research.db'
        self.store = ResearchStore(self.path).start()
        self.p.r.research = self.store

    async def asyncTearDown(self):
        self.store.close()
        await self.p.asyncTearDown()
        self.temp.cleanup()

    async def test_primary_pull_records_trigger_orders_and_later_market(self):
        import asyncio
        self.p.m.RESEARCH_MARK_SECONDS = (0.01,)
        self.p.remove('.5', 495)  # Short queue: fewer than one entry ahead.
        self.p.m.refresh('A')
        self.assertIsNotNone(self.p.m.cycle)
        self.p.book.bids.set(D('.5'), D(0))  # Our bid level is gone afterwards.
        await asyncio.sleep(.1)
        self.store.close()
        [(key, row)] = rows(self.path, 'withdrawals')
        self.assertEqual((row['kind'], row['ticker'], row['triggers']),
                         ('primary', 'A', ['short_queue']))
        self.assertEqual({o['side'] for o in row['orders']}, {'bid', 'ask'})
        self.assertTrue(any(s['trigger'] == 'short_queue' for s in row['samples']))
        self.assertEqual(row['repeats_last_hour'], 1)
        [(mark_key, mark)] = rows(self.path, 'withdrawal_marks')
        self.assertEqual(mark_key, key+'@0.01')
        self.assertEqual(mark['level_gone'], [self.p.bid])
        self.assertEqual(self.p.m._research_marks_pending, 0)

    async def test_a_level_still_there_is_not_counted_as_reached(self):
        import asyncio
        self.p.m.RESEARCH_MARK_SECONDS = (0.01,)
        self.p.remove('.5', 495)  # 15 contracts still bid at our price.
        self.p.m.refresh('A')
        await asyncio.sleep(.1)
        self.store.close()
        [(_, mark)] = rows(self.path, 'withdrawal_marks')
        self.assertEqual(mark['best_bid'], '0.5')
        self.assertEqual(mark['level_gone'], [])

    async def test_no_book_later_is_unknown_not_reached(self):
        import asyncio
        self.p.m.RESEARCH_MARK_SECONDS = (0.01,)
        self.p.remove('.5', 495)
        self.p.m.refresh('A')
        self.p.r.management._book = lambda ticker: (None, None)  # Book gone after the pull.
        await asyncio.sleep(.1)
        self.store.close()
        [(_, mark)] = rows(self.path, 'withdrawal_marks')
        self.assertIsNone(mark['level_gone'])

    async def test_pending_marks_are_bounded_and_no_research_means_no_record(self):
        self.p.m.RESEARCH_MAX_PENDING_MARKS = 1
        self.p.remove('.5', 495)
        self.p.m.refresh('A')
        self.assertEqual(self.p.m._research_marks_pending, 0)  # Two marks exceed the bound.
        self.p.r.research = None
        self.p.m._research_withdrawal(SimpleNamespace(ticker='A'), 'primary')  # No-op.
        self.assertEqual(self.p.r.research_failures, 0)
        self.store.close()
        self.assertEqual(len(rows(self.path, 'withdrawals')), 1)

    async def test_secondary_latch_is_recorded(self):
        import test_bot_concurrent_withdrawals as concurrent
        c = concurrent.ConcurrentWithdrawalTests('test_bounded_to_four_concurrent_cycles')
        await c.asyncSetUp()
        try:
            c.r.research = self.store
            self.assertTrue(c.latch_b())
        finally:
            await c.asyncTearDown()
        self.store.close()
        kinds = [(r['ticker'], r['kind']) for _, r in rows(self.path, 'withdrawals')]
        self.assertIn(('B', 'secondary'), kinds)


class TradeHistoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import asyncio
        from kalshi_bot.runtime import RecoveryRuntime
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name)/'research.db'
        self.store = ResearchStore(self.path).start()
        self.calls, self.failing = [], set()
        self.trades = {'A': [dict(trade_id='t1', created_time='2026-09-26T05:52:16.916817Z',
                                  taker_side='no', count_fp='488.00', yes_price_dollars='0.82')],
                       'B': []}
        async def read(name, **params):
            self.calls.append((name, params))
            if params['ticker'] in self.failing:
                raise OSError('down')
            return SimpleNamespace(payload={'trades': self.trades.get(params['ticker'], [])})
        plans = {'A': SimpleNamespace(inventory=SimpleNamespace(orders=(1,), position=0)),
                 'B': SimpleNamespace(inventory=SimpleNamespace(orders=(), position=5)),
                 'C': SimpleNamespace(inventory=SimpleNamespace(orders=(), position=0))}
        now = datetime(2026, 9, 26, 6, tzinfo=timezone.utc)
        stub = SimpleNamespace(reads=SimpleNamespace(read=read), research=self.store,
            research_failures=0, stop_requested=asyncio.Event(), now=lambda: now,
            management=SimpleNamespace(_plans=plans), maintenance=None,
            _research_trade_since={}, RESEARCH_TRADE_SECONDS=60,
            RESEARCH_TRADE_MARKETS=64, RESEARCH_TRADE_LIMIT=200, RESEARCH_TRADE_OVERLAP=30)
        stub._research_trade_tickers = lambda: RecoveryRuntime._research_trade_tickers(stub)
        self.stub, self.runtime = stub, RecoveryRuntime

    async def asyncTearDown(self):
        self.store.close()
        self.temp.cleanup()

    async def test_trades_for_quoted_or_held_markets_are_stored_once(self):
        await self.runtime._research_trades(self.stub)
        await self.runtime._research_trades(self.stub)  # Overlapping window.
        self.store.close()
        [(key, trade)] = rows(self.path, 'trades')
        self.assertEqual((key, trade['ticker'], trade['count'], trade['taker_side']),
                         ('t1', 'A', '488.00', 'no'))
        self.assertEqual(sorted({p['ticker'] for _, p in self.calls}), ['A', 'B'])  # Not C.
        self.assertTrue(all(name == 'trades' and p['reason'] == 'research'
                            for name, p in self.calls))

    async def test_the_next_read_starts_at_the_latest_trade(self):
        await self.runtime._research_trades(self.stub)
        first = {p['ticker']: p['min_ts'] for _, p in self.calls}
        self.assertEqual(first['A'], int(datetime(2026, 9, 26, 5, 59, tzinfo=timezone.utc).timestamp()))
        self.calls.clear()
        await self.runtime._research_trades(self.stub)
        second = {p['ticker']: p['min_ts'] for _, p in self.calls}
        # A quiet window still advances, keeping a 30 s overlap for late trades.
        overlap = int(datetime(2026, 9, 26, 5, 59, 30, tzinfo=timezone.utc).timestamp())
        self.assertEqual((second['A'], second['B']), (overlap, overlap))
        # A newer trade moves the window to that trade's second.
        self.trades['A'].append(dict(trade_id='t2', created_time='2026-09-26T05:59:50Z',
                                     taker_side='yes', count_fp='5.00', yes_price_dollars='0.2'))
        self.calls.clear()
        await self.runtime._research_trades(self.stub)
        await self.runtime._research_trades(self.stub)
        third = {p['ticker']: p['min_ts'] for _, p in self.calls[-2:]}
        self.assertEqual(third['A'], int(datetime(2026, 9, 26, 5, 59, 50, tzinfo=timezone.utc).timestamp()))

    async def test_one_market_failing_does_not_stop_the_others(self):
        self.failing.add('A')
        await self.runtime._research_trades(self.stub)
        self.assertEqual(self.stub.research_failures, 1)
        self.assertIn('B', self.stub._research_trade_since)
        self.assertNotIn('A', self.stub._research_trade_since)

    async def test_market_count_is_bounded_and_no_reads_means_no_work(self):
        self.stub.RESEARCH_TRADE_MARKETS = 1
        await self.runtime._research_trades(self.stub)
        self.assertEqual([p['ticker'] for _, p in self.calls], ['A'])
        self.stub.reads = None
        await self.runtime._research_trades(self.stub)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.stub.research_failures, 0)

    def test_endpoint_is_public_background_research_only(self):
        from kalshi_bot.rest import ENDPOINTS, request_path
        from kalshi_bot.values import InvalidData
        spec, path = request_path('trades', dict(ticker='A', min_ts=1, limit=200), 'research')
        self.assertFalse(spec.authenticated)
        self.assertTrue(path.startswith('/markets/trades?'))
        with self.assertRaises(InvalidData):
            request_path('trades', dict(ticker='A'), 'metadata')
        self.assertIn('research', ENDPOINTS['trades'].reasons)


class HealthSummaryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.f = entry_fixture.EntrySourceTests('test_ranked_market_becomes_exact_source_bound_pair')
        await self.f.asyncSetUp()
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name)/'research.db'
        self.store = ResearchStore(self.path).start()
        self.r = self.f.runtime
        self.r.research = self.store

    async def asyncTearDown(self):
        self.store.close()
        await self.f.asyncTearDown()
        self.temp.cleanup()

    async def test_hour_summary_has_fractions_and_counter_changes(self):
        r = self.r
        for _ in range(4):
            r._research_sample_health()
        r._recovery_state = 'recovering'
        r._research_sample_health()
        hour1 = datetime(2026, 9, 26, 17, tzinfo=timezone.utc)
        r.recovery_request_counts['post_drain'] = 7
        r._research_health(hour1)
        r._recovery_state = None
        r._research_sample_health()
        r.recovery_request_counts['post_drain'] = 10
        r.research_fills_recorded = 2
        r._research_health(hour1.replace(hour=18))
        self.store.close()
        [(k1, h1), (k2, h2)] = rows(self.path, 'health_hourly')
        self.assertEqual((k1, h1['samples'], h1['recovering_fraction'], h1['since_start']),
                         ('2026-09-26T17:00:00+00:00', 5, 0.2, True))
        self.assertIn('entry_allowed_fraction', h1)
        self.assertEqual(h1['counters']['recovery.post_drain'], 7)
        self.assertEqual((h2['samples'], h2['recovering_fraction'], h2['since_start']), (1, 0.0, False))
        self.assertEqual((h2['counters']['recovery.post_drain'], h2['counters']['fills_recorded']), (3, 2))

    async def test_blockers_explain_exactly_when_entries_are_closed(self):
        """D-152: the breakdown names every false ``entry_allowed`` term."""
        from types import SimpleNamespace as NS
        from unittest import mock
        r = self.r
        with mock.patch('kalshi_bot.live_session.permits', return_value=True):
            r.writer._accounting_lease = NS(fence=NS(current=lambda: True))
            r._accounting_result = NS(released=True, window=None)
            self.assertEqual((r._entry_blockers(), r.entry_allowed), ([], True))
            for term, close, reopen in (
                    ('accounting_unreleased', lambda: setattr(r, '_accounting_result', NS(released=False, window=None)),
                     lambda: setattr(r, '_accounting_result', NS(released=True, window=None))),
                    ('venue_paused', lambda: setattr(r, '_venue_paused', True),
                     lambda: setattr(r, '_venue_paused', False)),
                    ('lease_stale', lambda: setattr(r.writer, '_accounting_lease', NS(fence=NS(current=lambda: False))),
                     lambda: setattr(r.writer, '_accounting_lease', NS(fence=NS(current=lambda: True)))),
                    ('stopping', r.stop_requested.set, r.stop_requested.clear),
                    ('entry_pause', lambda: setattr(r, '_recovery_safety_pause', True),
                     lambda: setattr(r, '_recovery_safety_pause', False))):
                close()
                self.assertEqual((r._entry_blockers(), r.entry_allowed), ([term], False), term)
                reopen()
                self.assertEqual((r._entry_blockers(), r.entry_allowed), ([], True), term)
            r._accounting_result = None
            self.assertEqual((r._entry_blockers(), r.entry_allowed), (['accounting_missing'], False))
            r.writer._accounting_lease = None
            self.assertIn('lease_missing', r._entry_blockers())
        self.assertIn('session', r._entry_blockers())  # Offline fixture: no live session.

    async def test_hour_summary_says_which_gate_term_closed_entries(self):
        from types import SimpleNamespace as NS
        r = self.r
        r._accounting_result = NS(released=False, window=None)
        for _ in range(3):
            r._research_sample_health()
        r._research_health(datetime(2026, 9, 26, 17, tzinfo=timezone.utc))
        self.store.close()
        [(_, h)] = rows(self.path, 'health_hourly')
        self.assertEqual(h['entry_allowed_fraction'], 0.0)
        self.assertEqual(h['entry_blocked_fraction']['accounting_unreleased'], 1.0)

    async def test_failures_are_counted_by_site_and_type(self):
        r = self.r
        r._research_safely(_broken_mark)
        r._research_safely(_broken_mark)
        r._research_safely(lambda: 1/0)
        self.assertEqual(r.research_failures, 3)
        sites = r.status()['research']['failure_sites']
        self.assertEqual(sites['_broken_mark:KeyError'], 2)
        self.assertEqual(sites['test_failures_are_counted_by_site_and_type:ZeroDivisionError'], 1)
        self.assertIn('ZeroDivisionError', r.status()['research']['last_failure'])

    async def test_empty_hour_reports_no_fraction(self):
        self.r._research_health(datetime(2026, 9, 26, 17, tzinfo=timezone.utc))
        self.store.close()
        [(_, h)] = rows(self.path, 'health_hourly')
        self.assertEqual((h['samples'], h['entry_allowed_fraction'], h['average_resting_entries']),
                         (0, None, None))

    async def test_loop_closes_the_previous_hour_when_the_hour_changes(self):
        import asyncio
        from kalshi_bot.runtime import RecoveryRuntime
        clock = [datetime(2026, 9, 26, 17, 59, 59, tzinfo=timezone.utc)]
        stub = SimpleNamespace(research=self.store, research_failures=0, rewards=None,
            stop_requested=asyncio.Event(), now=lambda: clock[0], clock=__import__('time').monotonic,
            RESEARCH_TICK_SECONDS=.01, RESEARCH_TRADE_SECONDS=999)
        closed = []
        stub._research_safely = lambda fn, *a: RecoveryRuntime._research_safely(stub, fn, *a)
        stub._research_reward_estimates = lambda hour: None
        stub._research_sample_health = lambda: None
        stub._research_health = closed.append
        async def trades():
            pass
        stub._research_trades = trades
        task = asyncio.create_task(RecoveryRuntime._research_loop(stub))
        await asyncio.sleep(.03)
        clock[0] = clock[0]+timedelta(seconds=2)
        await asyncio.sleep(.03)
        stub.stop_requested.set()
        await asyncio.wait_for(task, 2)
        self.assertEqual(closed, [datetime(2026, 9, 26, 17, tzinfo=timezone.utc)])


if __name__ == '__main__':
    unittest.main()
