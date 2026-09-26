"""D-145 fill protection: anchored queue tracking and the three triggers."""
import asyncio
from dataclasses import replace
from decimal import Decimal as D
import unittest

from kalshi_bot.books import BookConnection
from kalshi_bot.fill_risk import FillRisk
import test_bot_quote_maintenance as maintenance_fixture
from test_bot_reward_tracker import QueueReads


class Failing:
    def __init__(self):
        self.calls = []

    async def read(self, name, **params):
        self.calls.append((name, params))
        raise OSError('network down')


class AnchoredProtectionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.f = maintenance_fixture.MaintenanceTests()
        await self.f.asyncSetUp()
        self.r, self.m = self.f.r, self.f.m
        self.book = self.r.management._book('A')[1]
        self.book.bids.set(D('.5'), D(510))
        self.book.asks.set(D('.6'), D(510))
        self.r.reads = QueueReads([dict(order_id=o.order_id, market_ticker='A',
            queue_position_fp='500') for o in self.f.orders])
        self.m.queue_reader_active = True
        self.bid = next(o.order_id for o in self.f.orders if o.side == 'bid')
        await self.m.read_queues_once()
        self.assertIsNone(self.m.cycle)

    async def asyncTearDown(self):
        await self.f.asyncTearDown()

    def remove(self, price, quantity, ladder=None):
        """What BookConnection does for another participant's decrease."""
        ladder = ladder or self.book.bids
        ladder.set(D(price), ladder.levels.get(D(price), D(0))-D(quantity))
        ladder.record_decrease(D(price), D(quantity))

    def join(self, price, quantity, ladder=None):
        ladder = ladder or self.book.bids
        ladder.set(D(price), ladder.levels.get(D(price), D(0))+D(quantity))

    def ahead(self):
        rows = self.m.samples['A']['fill_risk']
        return D(next(r for r in rows if r['order_id'] == self.bid)['ahead_estimate'])

    async def test_reader_anchors_every_resting_entry_with_protection_reason(self):
        self.assertEqual(set(self.m._anchors), {o.order_id for o in self.f.orders})
        name, params = self.r.reads.calls[-1]
        self.assertEqual((name, params['reason'], params['market_tickers']),
                         ('queue_positions', 'protection', 'A'))
        self.assertTrue(self.m.protection_current())
        self.assertEqual(self.ahead(), D(500))

    async def test_cancel_ahead_then_join_behind_is_never_netted(self):
        self.remove('.5', 495)
        self.join('.5', 495)  # The level looks unchanged to a depth snapshot.
        self.m.refresh('A')
        self.assertEqual(self.ahead(), D(5))
        self.assertIsNotNone(self.m.cycle)
        self.assertEqual(self.m.cycle.reason, 'fill_risk_withdrawal')
        self.assertEqual(self.m.risk_triggers['short_queue'], 1)

    async def test_joins_at_our_price_never_move_us_back(self):
        self.remove('.5', 100)
        self.join('.5', 1000)
        self.m.refresh('A')
        self.assertEqual(self.ahead(), D(400))
        self.assertIsNone(self.m.cycle)

    async def test_better_price_liquidity_is_ahead_and_its_churn_never_consumes_us(self):
        self.join('.51', 400)
        self.m.refresh('A')
        self.assertEqual(self.ahead(), D(900))
        for _ in range(3):  # Makers requoting above us.
            self.remove('.51', 400)
            self.join('.51', 400)
        self.m.refresh('A')
        self.assertEqual(self.ahead(), D(900))
        self.assertIsNone(self.m.cycle)

    async def test_later_better_price_joins_raise_the_estimate_again(self):
        self.remove('.5', 100)
        self.m.refresh('A')
        self.assertEqual(self.ahead(), D(400))
        self.join('.51', 300)
        self.m.refresh('A')
        self.assertEqual(self.ahead(), D(700))

    async def test_a_reading_including_better_prices_is_not_double_counted(self):
        # If Kalshi's number already includes better prices, the at-price part
        # is taken as reading minus better size: a lower bound either way.
        self.join('.51', 300)
        await self.m.read_queues_once()
        self.m.refresh('A')
        self.assertEqual(self.ahead(), D(500))
        self.remove('.5', 150)
        self.m.refresh('A')
        self.assertEqual(self.ahead(), D(350))

    async def test_fast_depletion_triggers_time_to_fill(self):
        self.f.f.mono += 1
        self.remove('.5', 400)
        self.m.refresh('A')
        self.assertIsNotNone(self.m.cycle)
        self.assertEqual(self.m.risk_triggers, dict(time_to_fill=1, short_queue=0, blind=0))

    async def test_anchor_survives_age_without_a_new_read(self):
        self.f.f.mono += 60
        self.r.engine.book_received['A'] = self.f.f.mono  # Book itself still live.
        self.m.refresh('A')
        self.assertEqual(self.ahead(), D(500))
        self.assertIsNone(self.m.cycle)
        self.assertEqual(self.m._blind_since, {})

    async def test_new_book_snapshot_invalidates_anchor_then_blind_rule_withdraws(self):
        anchor = self.m._anchors[self.bid]
        self.m._anchors[self.bid] = replace(anchor, lineage=object())
        self.m.refresh('A')
        self.assertIsNone(self.m.cycle)
        self.assertIn(self.bid, self.m._blind_since)
        self.f.f.mono += self.m.BLIND_SECONDS
        self.m.refresh('A')
        self.assertIsNone(self.m.cycle)  # Exactly at the limit is still waiting.
        self.f.f.mono += 0.5
        self.m.refresh('A')
        self.assertIsNotNone(self.m.cycle)
        self.assertEqual(self.m.risk_triggers['blind'], 1)

    async def test_changed_terms_or_generation_invalidate_anchor(self):
        anchor = self.m._anchors[self.bid]
        for changes in (dict(yes_price=D('.49')), dict(side='ask'), dict(ticker='B'),
                        dict(book_generation=anchor.book_generation+1)):
            with self.subTest(changes=changes):
                self.m._anchors[self.bid] = replace(anchor, **changes)
                self.assertEqual(self.m._anchor_for(
                    self.r.management.current('A', require_market=False),
                    next(o for o in self.f.orders if o.order_id == self.bid),
                    *self.r.management._book('A'))[1], 'anchor_invalid')
        self.m._anchors[self.bid] = anchor

    async def test_fresh_read_replaces_anchor_and_clears_blind_clock(self):
        del self.m._anchors[self.bid]
        self.m.refresh('A')
        self.assertIn(self.bid, self.m._blind_since)
        self.assertTrue(self.m._queue_wake is None or self.m._queue_wake.is_set())
        await self.m.read_queues_once()
        self.assertNotIn(self.bid, self.m._blind_since)
        self.assertIn(self.bid, self.m._anchors)

    async def test_a_row_for_another_market_never_anchors_our_order(self):
        self.m._anchors.clear()
        self.r.reads.rows = [dict(order_id=o.order_id, market_ticker='B' if o.order_id == self.bid
                                  else 'A', queue_position_fp='500') for o in self.f.orders]
        await self.m.read_queues_once()
        self.assertNotIn(self.bid, self.m._anchors)
        self.assertEqual(len(self.m._anchors), 1)

    async def test_failed_reader_blocks_entries_until_it_recovers(self):
        self.assertTrue(self.m.entry_allowed('A', self.f.p.program_id))
        self.f.f.mono += self.m.BLIND_SECONDS+1
        self.assertFalse(self.m.entry_allowed('A', self.f.p.program_id))
        await self.m.read_queues_once()
        self.assertTrue(self.m.entry_allowed('A', self.f.p.program_id))
        fresh = type(self.m)(self.r)
        fresh.queue_reader_active = True
        self.assertFalse(fresh.entry_allowed('A', self.f.p.program_id))

    async def test_reader_loop_survives_failures_and_wakes_for_new_orders(self):
        self.r.reads = Failing()
        task = asyncio.create_task(self.m.run_queue_reader())
        try:
            for _ in range(200):
                if self.m.queue_read_failures:
                    break
                await asyncio.sleep(.01)
            self.assertGreaterEqual(self.m.queue_read_failures, 1)
            self.assertFalse(task.done())
            self.r.reads = QueueReads(self.r.reads_rows if hasattr(self.r, 'reads_rows') else
                [dict(order_id=o.order_id, market_ticker='A', queue_position_fp='500')
                 for o in self.f.orders])
            self.m._anchors.clear()
            self.m.refresh('A')  # An unanchored order wakes the reader early.
            for _ in range(150):
                if self.r.reads.calls:
                    break
                await asyncio.sleep(.01)
            self.assertTrue(self.r.reads.calls, 'reader did not wake before its 2 s cycle')
        finally:
            self.r.stop_requested.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            self.r.stop_requested.clear()

    async def test_status_reports_protection(self):
        status = self.m.status()['fill_protection']
        self.assertEqual((status['reader_active'], status['current'], status['anchored_orders'],
                          status['blind_limit_seconds']), (True, True, 2, 10.0))


class LegacyModeTests(unittest.TestCase):
    def test_observe_without_anchor_keeps_five_second_gate(self):
        import inspect
        source = inspect.getsource(FillRisk.observe)
        self.assertIn('not anchored and not now-queue_at < 5', source)


class BookDecreaseTests(unittest.TestCase):
    def setUp(self):
        self.c = BookConnection(('A',))
        self.g = self.c.reconnect()
        self.seq = 0
        self.send('orderbook_snapshot', yes_dollars_fp=[['0.50', '100']], no_dollars_fp=[])

    def send(self, kind, **msg):
        self.seq += 1
        self.c.apply(dict(type=kind, sid=1, seq=self.seq, msg=dict(market_ticker='A', **msg)),
                     generation=self.g)

    def delta(self, change, **extra):
        self.send('orderbook_delta', side='yes', price_dollars='0.50', delta_fp=change, **extra)

    def test_decreases_accumulate_and_joins_never_net_them(self):
        self.delta('-40')
        self.delta('40')
        self.delta('-10')
        ladder = self.c.books['A'].bids
        self.assertEqual(ladder.levels[D('.5')], D(90))
        self.assertEqual(ladder.decreased, {D('.5'): D(50)})

    def test_our_own_deltas_are_excluded(self):
        self.delta('-30', client_order_id='ours')
        self.assertEqual(self.c.books['A'].bids.decreased, {})

    def test_refresh_snapshot_in_the_same_sequence_keeps_lineage_and_tally(self):
        self.delta('-40')
        before = self.c.books['A']
        self.send('orderbook_snapshot', yes_dollars_fp=[['0.50', '60']], no_dollars_fp=[])
        self.assertIsNot(self.c.books['A'], before)
        self.assertIs(self.c.books['A'].lineage, before.lineage)
        self.assertEqual(self.c.books['A'].bids.decreased, {D('.5'): D(40)})

    def test_reconnect_starts_a_new_lineage(self):
        self.delta('-40')
        before = self.c.books['A']
        self.g, self.seq = self.c.reconnect(), 0
        self.send('orderbook_snapshot', yes_dollars_fp=[['0.50', '60']], no_dollars_fp=[])
        self.assertIsNot(self.c.books['A'].lineage, before.lineage)
        self.assertEqual(self.c.books['A'].bids.decreased, {})


if __name__ == '__main__':
    unittest.main()
