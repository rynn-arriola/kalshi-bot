"""D-131 item 7: bounded concurrent protective withdrawals; synthetic owners only."""
from dataclasses import replace
from decimal import Decimal as D
from types import SimpleNamespace
import unittest

from kalshi_bot.config import BotConfig
from kalshi_bot.dispatch import QUOTE_CANCEL
from kalshi_bot.orders import OrderReceipt, OrderUpdate
import test_bot_risk_dispatch_retry as retry_fixture
from test_bot_engine import program


def entry(client, ticker, side='bid', price='0.4'):
    return dict(ticker=ticker, client_order_id=client, side=side, count='10', price=price,
                time_in_force='good_till_canceled', self_trade_prevention_type='taker_at_cross',
                post_only=True, reduce_only=False, cancel_order_on_pause=True,
                subaccount=0, exchange_index=0)


class ConcurrentWithdrawalTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.b = retry_fixture.RiskDispatchRetryTests()
        await self.b.asyncSetUp()  # Market A is latched as the primary cycle.
        self.r, self.m, self.d = self.b.r, self.b.m, self.b.d
        self.source, self.ds = self.b.source, self.b.f.f.f
        self.b_orders = [await self.working('b-bid', 'bid', '0.4'),
                         await self.working('b-ask', 'ask', '0.6')]

    async def asyncTearDown(self):
        await self.b.asyncTearDown()

    async def working(self, client, side, price):
        writer = self.ds.writer
        prepared = await writer.reserve_entry(entry(client, 'B', side, price),
            attempt_id='attempt-'+client, view=await self.r.risk_view(),
            config=BotConfig(), now=self.ds.now, free_cash=D(500),
            account_known=True, offline_fixture=True)
        self.assertTrue(prepared.reserved, prepared.blockers)
        await writer.begin_send(prepared.receipt)
        await writer.record_outcome('ack', prepared.receipt, dict(order_id='order-'+client,
            fill_count='0', remaining_count='10', ts_ms=1), self.ds.now)
        order = OrderUpdate('order-'+client, client, 'B', side, D(price), D(10), D(0),
                            D(10), 'resting', 0, 0, 1)
        await writer.order(order, self.ds.now)
        return order

    def latch_b(self):
        plan = SimpleNamespace(ticker='B', inventory=SimpleNamespace(orders=tuple(
            OrderReceipt(o, True, False, False, 'ACKNOWLEDGED') for o in self.b_orders)))
        return self.m._latch_secondary(plan, replace(program(), ticker='B'))

    async def turn(self, ticker):
        self.b.owner.request(ticker, QUOTE_CANCEL)
        return await self.d.run_one()

    async def test_second_market_latches_immediately_and_both_pairs_drain(self):
        self.assertEqual(self.m.cycle.ticker, 'A')
        self.assertTrue(self.latch_b())
        self.assertEqual(self.m.risk_cycle_for('B').order_ids,
                         tuple(sorted(o.order_id for o in self.b_orders)))
        self.assertIsNotNone(self.m.risk_cycle_for('A'))
        # Production latching of the primary is followed by its dispatch wake
        # (runtime._request_quote_dispatch); the secondary registers itself.
        self.r._request_quote_dispatch('A')
        self.assertEqual(set(self.source._current_drains()), {'A', 'B'})
        acks = 0
        for _ in range(20):
            self.b.advance(.3)
            self.r._resume_risk_drain()
            result = await self.d.run_one()
            acks += result.state == 'ACK'
            if result.state == 'IDLE' and not self.source.risk_drain_pending:
                break
        self.assertEqual(acks, 4)
        sent = [request['order_id'] for kind, request in self.ds.calls if kind == 'cancel']
        self.assertEqual(len(sent), len(set(sent)))  # Never sent twice.
        self.assertEqual(set(sent), set(self.m.risk_cycle_for('A').order_ids)
                         | {o.order_id for o in self.b_orders})
        self.assertFalse(self.r.recovery_requested.is_set())
        # Reconciliation starts only once no latched pair has a cancelable leg.
        self.assertFalse(self.source.risk_drain_pending)
        self.assertTrue(self.r._request_post_drain_recovery())

    async def test_bounded_to_four_concurrent_cycles(self):
        self.assertTrue(self.latch_b())
        for index in range(5):
            fake = SimpleNamespace(ticker=f'X{index}', inventory=SimpleNamespace(orders=()))
            self.m._latch_secondary(fake, replace(program(), ticker=f'X{index}'))
        self.assertEqual(len(self.m.risk_cycles()), self.m.MAX_RISK_CYCLES)

    async def test_secondary_blocks_reentry_and_is_visible(self):
        self.assertTrue(self.latch_b())
        self.assertFalse(self.m.entry_allowed('B', program().program_id))
        status = self.m.status()
        self.assertEqual(status['latched_risk_cycles'], ['B'])
        self.assertIn('B', status['markets'])

    async def test_repeat_withdrawals_are_counted_per_market(self):
        self.assertTrue(self.latch_b())
        self.m._finish_secondary('B')
        self.b.advance(1)
        self.assertTrue(self.latch_b())
        self.assertEqual(self.m.status()['repeat_withdrawals_last_hour'], {'B': 2})


if __name__ == '__main__':
    unittest.main()
