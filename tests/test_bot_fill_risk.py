"""Synthetic queue/latency scenarios and real-owner withdrawal regressions."""
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
import json
import time
import tracemalloc
import unittest

from kalshi_bot.fill_risk import FillRisk, FillRiskPolicy
from kalshi_bot.dispatch import QUOTE_CANCEL, ENTRY_PAIR, SAFETY_CANCEL
from kalshi_bot.orders import OrderUpdate
from kalshi_bot.values import InvalidData
from test_bot_engine import book, program
from test_bot_reward_tracker import QueueReads
import test_bot_quote_maintenance as maintenance_fixture


class EstimateTests(unittest.TestCase):
    def setUp(self):
        self.r = FillRisk()
        self.o = OrderUpdate('owned', 'client', 'A', 'bid', D('.5'), D(10),
                             D(0), D(10), 'resting', 0, 0, 1)
        self.b = book(bids=(('.5', '1010'), ('.4', '1000')),
                      asks=(('.6', '1000'), ('.7', '1000')))
        self.p = program(target=D(1000))

    def observe(self, now=0, queue_at=0, ahead='500', **kwargs):
        args = dict(order=self.o, book=self.b, program=self.p, identity=('writer',1,1),
                    ahead=D(ahead), queue_at=queue_at, now=now, interval=4)
        return self.r.observe(**(args | kwargs))

    def test_first_sample_unknown_rate_is_not_infinite_safety(self):
        row = self.observe()
        self.assertEqual(row['state'], 'WARMING_UP')
        self.assertIsNone(row['seconds_to_reach'])
        self.assertFalse(row['withdraw'])

    def test_websocket_depletion_triggers_without_waiting_for_another_rest_read(self):
        self.observe()
        self.b.bids.set(D('.5'), D(610))
        row = self.observe(now=1)
        self.assertEqual(D(row['ahead_estimate']), 100)
        self.assertEqual(D(row['depletion_per_second']), 400)
        self.assertEqual(D(row['seconds_to_reach']), D('.25'))
        self.assertTrue(row['withdraw'])

    def test_slow_depletion_stays_and_replenishment_does_not_invent_queue_priority(self):
        self.observe()
        self.b.bids.set(D('.5'), D(1009))
        row = self.observe(now=1)
        self.assertFalse(row['withdraw'])
        self.b.bids.set(D('.5'), D(2000))
        row = self.observe(now=2)
        self.assertEqual(D(row['ahead_estimate']), 499)
        self.assertFalse(row['withdraw'])

    def test_new_queue_read_corrects_conservative_aggregate_estimate(self):
        self.observe()
        self.b.bids.set(D('.5'), D(610))
        self.observe(now=1)
        row = self.observe(now=4, queue_at=4, ahead='500')
        self.assertEqual(D(row['ahead_estimate']), 500)

    def test_queue_drop_catches_coalesced_book_changes(self):
        self.observe()
        row = self.observe(now=4, queue_at=4, ahead='50')
        self.assertEqual(D(row['depletion_per_second']), D('112.5'))
        self.assertTrue(row['withdraw'])

    def test_zero_ahead_is_immediate_even_on_first_sample(self):
        self.assertTrue(self.observe(ahead='0')['withdraw'])

    def test_ask_uses_yes_price_ascending_and_excludes_worse_liquidity(self):
        order = replace(self.o, side='ask', yes_price=D('.6'))
        row = self.observe(order=order)
        self.assertEqual(D(row['ahead_estimate']), 500)
        self.b.asks.set(D('.6'), D(100))
        self.assertTrue(self.observe(now=1, order=order)['withdraw'])
        # A huge worse-priced level cannot protect the .60 order.
        self.b.asks.set(D('.7'), D(100000))
        self.assertLessEqual(D(self.observe(now=2, order=order)['ahead_estimate']), 90)

    def test_target_sets_reference_depth_but_does_not_fabricate_ahead_volume(self):
        self.b.bids.set(D('.5'), D(100))
        small = self.observe(program=replace(self.p, target=D(200)), ahead='50')
        large = self.observe(program=replace(self.p, target=D(1000)), ahead='50')
        self.assertEqual(D(small['reference_depth']), 40)
        self.assertEqual(D(large['reference_depth']), 200)
        self.assertEqual(D(small['reference_price']), D('.5'))
        self.assertEqual(D(large['reference_price']), D('.4'))
        self.assertEqual(D(large['ahead_estimate']), 50)
        self.assertEqual(D(large['ahead_fraction_of_reference_depth']), D('.25'))

    def test_epoch_quantity_program_and_gap_reset_trend(self):
        for changes in ({'identity': ('writer',1,2)}, {'order': replace(self.o, remaining=D(9))},
                        {'program':replace(self.p, target=D(200))}, {'now':20,'queue_at':20}):
            self.r = FillRisk()
            self.b.bids.set(D('.5'), D(1010))
            self.observe()
            self.b.bids.set(D('.5'), D(610))
            self.observe(now=1)
            row = self.observe(**(dict(now=2) | changes))
            self.assertIsNone(row['seconds_to_reach'], changes)

    def test_stale_future_invalid_or_wrong_ticker_book_is_unknown(self):
        for changes in ({'now':5}, {'now':-1}, {'book':replace(self.b, valid=False)},
                        {'book':replace(self.b,ticker='OTHER')}):
            self.assertIsNone(self.observe(**changes))

    def test_cancel_tail_increases_horizon_and_history_is_bounded(self):
        for _ in range(200): self.r.cancel_ack(9)
        self.assertEqual(len(self.r.cancel_seconds),128)
        self.assertEqual(self.r.cancel_budget(),9)
        self.assertEqual(self.observe()['horizon_seconds'],14)
        for bad in (float('inf'),float('nan'),-1): self.r.cancel_ack(bad)
        self.assertEqual(self.r.cancel_budget(),9)

    def test_capacity_pruning_and_invalid_configuration(self):
        self.r = FillRisk(FillRiskPolicy(capacity=1))
        self.observe()
        self.assertIsNone(self.observe(order=replace(self.o,order_id='other')))
        self.r.prune(['other'])
        self.assertIsNotNone(self.observe(order=replace(self.o,order_id='other')))
        with self.assertRaises(InvalidData): FillRiskPolicy(cooldown_seconds=-1)


class WithdrawalTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.f = maintenance_fixture.MaintenanceTests()
        await self.f.asyncSetUp()
        self.r, self.m = self.f.r, self.f.m

    async def asyncTearDown(self):
        await self.f.asyncTearDown()

    async def queues(self, ahead='0'):
        self.r.reads = QueueReads([dict(order_id=o.order_id, market_ticker='A',
            queue_position_fp=ahead) for o in self.f.orders])
        return await self.f.rewards.reflect_once()

    async def test_risk_withdrawal_bypasses_reprice_dwell_and_keeps_other_markets_available(self):
        self.assertIsNone(self.m.cycle)
        await self.queues()
        self.assertEqual(self.m.cycle.reason,'fill_risk_withdrawal')
        self.assertFalse(self.m.cycle.reenter)
        self.assertFalse(self.m.entry_allowed('A','P'))
        self.assertTrue(self.m.entry_allowed('B','P'))
        self.assertIsNotNone(await self.f.f.source.refresh('A',QUOTE_CANCEL))
        self.assertIsNone(await self.f.f.source.refresh('A',ENTRY_PAIR))
        self.assertEqual(len(self.r.reads.calls),1)
        self.assertEqual(self.m.samples['A']['fill_risk'][0]['target_size'],str(self.f.p.target))

    async def test_ordinary_maintenance_on_another_market_cannot_block_risk_withdrawal(self):
        from kalshi_bot.quote_maintenance import MaintenanceCycle
        self.m.cycle=MaintenanceCycle('B',replace(self.f.p,ticker='B'),(),
                                      'restore_reference_pair',True)
        await self.queues()
        self.assertEqual(self.m.cycle.ticker,'A')
        self.assertEqual(self.m.cycle.reason,'fill_risk_withdrawal')

    async def test_replacement_ranking_excludes_cooled_market_without_blocking_others(self):
        from kalshi_bot.selection import MarketSelector
        from test_bot_selection import terms, view, window
        await self.queues()
        selector=MarketSelector()
        for ticker in ('A','B','C'):
            selector.update(replace(book(),ticker=ticker),
                (program(ticker=ticker,pool_centicents=5000000),),
                terms=terms(ticker),now=self.f.f.now,
                valid_until=self.f.f.now+timedelta(seconds=4))
        result=selector.propose(view=view(entry_count=26),window=window(),free_cash=D(400),
            account_known=True,now=self.f.f.now,current=lambda t:True,
            entry_allowed=self.m.entry_allowed)
        self.assertEqual({row.ticker for row in result.additions},{'B','C'})
        self.assertTrue(all(row.gross_remaining_usd >= 2 for row in result.additions))

    async def test_actual_cancel_ack_is_measured_and_requires_terminal_reconciliation(self):
        await self.queues()
        self.f.f.mono += .25
        result = await self.f.f.run_priority(QUOTE_CANCEL)
        self.assertEqual(result.state,'ACK')
        self.assertEqual(self.m.fill_risk.status()['cancel_samples'],1)
        self.assertGreaterEqual(self.m.fill_risk.cancel_seconds[-1],.25)
        self.assertIsNone(await self.f.f.source.refresh('A',ENTRY_PAIR))
        self.assertIsNone(await self.f.f.source.refresh('A',QUOTE_CANCEL))

    async def test_confirmed_terminal_pair_releases_slots_but_same_market_cools_down(self):
        await self.queues()
        for old in self.f.orders:
            await self.f.f.writer.order(replace(old,remaining=D(0),status='canceled',version_us=2),self.f.f.now)
        self.f.orders=[]
        await self.f.sample()
        self.assertIsNone(self.m.cycle)
        self.assertFalse(self.m.entry_allowed('A','P'))
        self.assertTrue(self.m.entry_allowed('B','P'))
        self.assertTrue(self.r._entry_dirty)
        self.f.f.mono += 301
        self.assertTrue(self.m.entry_allowed('A','P'))

    async def test_racing_partial_fill_hands_to_existing_inventory_exit(self):
        from kalshi_bot.ledger import Fill
        await self.queues()
        bid=self.f.orders[0]
        filled=replace(bid,filled=D(4),remaining=D(6),version_us=2)
        await self.f.f.writer.order(filled,self.f.f.now)
        await self.f.f.writer.fill(Fill('risk-race',bid.order_id,'A','bid',D(4),D('.5'),D(0)),self.f.f.now)
        self.f.orders[0]=filled
        await self.f.sample(quantity='4')
        self.assertIsNone(self.m.cycle)
        self.assertIsNone(await self.f.f.source.refresh('A',QUOTE_CANCEL))
        self.assertIsNotNone(await self.f.f.source.refresh('A',SAFETY_CANCEL))

    async def test_missing_queue_evidence_does_not_trigger(self):
        self.assertIsNone(self.m.cycle)
        self.m.refresh('A')
        self.assertIsNone(self.m.cycle)
        self.assertEqual(self.m.fill_risk.status()['tracked_orders'],0)

    async def test_long_rest_request_cannot_publish_fresh_risk_evidence(self):
        self.r.reads=QueueReads([dict(order_id=o.order_id,market_ticker='A',queue_position_fp='0')
                                for o in self.f.orders])
        async def delay(): self.f.f.mono += 6
        self.r.reads.before=delay
        await self.f.rewards.reflect_once()
        self.assertIsNone(self.m.cycle)

    async def test_reconnect_during_queue_read_cannot_seed_new_book_epoch(self):
        self.r.reads=QueueReads([dict(order_id=o.order_id,market_ticker='A',queue_position_fp='0')
                                for o in self.f.orders])
        async def reconnect():
            shard=self.r.engine.shards[self.r.engine.market_shard['A']]
            shard.generation += 1
        self.r.reads.before=reconnect
        await self.f.rewards.reflect_once()
        self.assertIsNone(self.m.cycle)


class ResourceTests(unittest.TestCase):
    def test_bounded_30_and_120_order_estimates(self):
        # 100 levels per side, 20 evaluations per order, no network or ledger.
        # Acceptance: p99 <50ms per evaluation; bounded 256 samples / <4MiB.
        rows=[]
        for size in (30,120):
            estimator=FillRisk()
            b=book(bids=tuple((str(D('.5')-D(i)/1000),'100') for i in range(100)),
                   asks=tuple((str(D('.6')+D(i)/1000),'100') for i in range(100)))
            orders=[OrderUpdate(str(i),'c'+str(i),'A','bid',D('.45'),D(10),D(0),D(10),
                                'resting',0,0,1) for i in range(size)]
            p=program(target=D(1000))
            elapsed=[]
            tracemalloc.start()
            cpu=time.process_time()
            for tick in range(20):
                for order in orders:
                    started=time.perf_counter()
                    estimator.observe(order=order,book=b,program=p,identity=('w',1,1),
                        ahead=D(5000-tick),queue_at=tick/10,now=tick/10,interval=4)
                    elapsed.append((time.perf_counter()-started)*1000)
            cpu=time.process_time()-cpu
            _,peak=tracemalloc.get_traced_memory()
            tracemalloc.stop()
            p99=sorted(elapsed)[int(.99*len(elapsed))-1]
            self.assertLess(p99,50)
            self.assertLess(peak,4*1024*1024)
            self.assertEqual(len(estimator.samples),size)
            rows.append(dict(orders=size,evaluations=len(elapsed),cpu_seconds=cpu,
                             p99_ms=p99,peak_bytes=peak))
        print('FILL_RISK_RESOURCE '+json.dumps(rows))


if __name__ == '__main__': unittest.main()
