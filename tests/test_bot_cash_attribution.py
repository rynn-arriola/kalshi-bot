"""D-141 external cash movements: funding and reward credits never stop trading."""
from contextlib import closing
from datetime import timedelta
from decimal import Decimal as D
import sqlite3
import unittest

from kalshi_bot.account_release import validate_cash
from kalshi_bot.ledger import Ledger
from kalshi_bot.rest import PageSet
from kalshi_bot.values import InvalidData
from tests import test_bot_account_release as baseline
from tests.test_bot_opening_account import balance


def cash(shard0, shard1='200'):
    total = D(shard0)+D(shard1)
    return balance() | dict(balance_dollars=str(total), balance=int(total*100),
        balance_breakdown=[dict(exchange_index=0, balance=shard0),
                           dict(exchange_index=1, balance=shard1)])


class Reads(baseline.Reads):
    def __init__(self, *args, withdrawals=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.withdrawals = withdrawals

    async def collect(self, name, **kwargs):
        if name == 'withdrawals':
            return PageSet(self.withdrawals, 1, 20, name, (), True)
        return await super().collect(name, **kwargs)


class CashAttributionTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = baseline.AccountReleaseTests.asyncSetUp
    asyncTearDown = baseline.AccountReleaseTests.asyncTearDown
    open_epoch = baseline.AccountReleaseTests.open_epoch
    refresh = baseline.AccountReleaseTests.refresh
    reserve = baseline.AccountReleaseTests.reserve

    def later(self, record_id, **changes):
        return self.deposit | dict(id=record_id,
            created_ts=int((baseline.BOUNDARY+timedelta(seconds=1)).timestamp())) | changes

    async def release(self, venue, *, deposits=(), withdrawals=()):
        self.cash = venue
        await self.refresh()
        return await self.account.reconcile_accounting(Reads(self.cash,
            deposits=(self.deposit, *deposits), intra_transfers=(self.transfer,),
            withdrawals=withdrawals), proposed_boundary=baseline.BOUNDARY,
            continuity=self.continuity, now=lambda: self.now, release=True)

    def rows(self, sql, *args):
        with closing(sqlite3.connect(self.path)) as conn:
            return conn.execute(sql, args).fetchall()

    def local(self):
        return {k: D(v) for k, v in self.rows('SELECT * FROM accounting_cash')}

    def adjustments(self):
        return [(k, D(a)) for k, a in self.rows('SELECT kind,amount FROM cash_adjustments ORDER BY at')]

    async def test_reward_style_credit_is_recorded_once_and_trading_continues(self):
        result = await self.release(cash('301'))
        self.assertTrue(result.released, result.blockers)
        self.assertEqual([(a.kind, a.amount) for a in result.cash_adjustments],
                         [('unattributed_credit', D(1))])
        self.assertEqual(self.local()[0], D(301))
        again = await self.release(cash('301'))
        self.assertTrue(again.released, again.blockers)
        self.assertEqual(again.cash_adjustments, ())
        self.assertEqual(self.adjustments(), [('unattributed_credit', D(1))])

    async def test_surplus_is_never_credited_from_an_inconsistent_account(self):
        self.assertTrue((await self.release(cash('300'))).released)
        reserved = await self.reserve('uncertain')
        self.assertTrue(reserved.reserved, reserved.blockers)
        await self.writer.begin_send(reserved.receipt)  # SENDING: unresolved.
        result = await self.release(cash('301'))
        self.assertFalse(result.released)
        self.assertIn('accounting_mutation_unresolved', result.blockers)
        self.assertIn('accounting_cash_unexplained', result.blockers)
        self.assertEqual(self.adjustments(), [])

    async def test_applied_deposit_is_credited_exactly(self):
        deposit = self.later('new-deposit', amount_cents=30000)
        result = await self.release(cash('600'), deposits=(deposit,))
        self.assertTrue(result.released, result.blockers)
        self.assertEqual([(a.kind, a.amount) for a in result.cash_adjustments],
                         [('deposit', D(300))])
        self.assertNotIn('cash_activity_unattributed', (await self.writer.accounting_status()).holds)

    async def test_pending_deposit_neither_blocks_nor_double_counts(self):
        pending = self.later('pending-deposit', amount_cents=30000, status='pending')
        for venue in ('300', '600'):  # Before and after the venue shows it.
            result = await self.release(cash(venue), deposits=(pending,))
            self.assertTrue(result.released, result.blockers)
            self.assertEqual(result.cash_adjustments, ())
        applied = pending | dict(status='applied')
        result = await self.release(cash('600'), deposits=(applied,))
        self.assertTrue(result.released, result.blockers)
        self.assertEqual(self.adjustments(), [('deposit', D(300))])
        self.assertEqual(self.local()[0], D(600))

    async def test_withdrawals_pending_then_applied(self):
        pending = self.later('out', kind=None, amount_cents=10000, status='pending')
        pending.pop('kind')
        result = await self.release(cash('200'), withdrawals=(pending,))
        self.assertTrue(result.released, result.blockers)  # Pending debit tolerated.
        self.assertEqual(result.cash_adjustments, ())
        done = pending | dict(status='applied')
        result = await self.release(cash('200'), withdrawals=(done,))
        self.assertTrue(result.released, result.blockers)
        self.assertEqual(self.adjustments(), [('withdrawal', D(-100))])
        self.assertEqual(self.local()[0], D(200))

    async def test_failed_funding_changes_nothing(self):
        failed = self.later('failed-deposit', amount_cents=30000, status='failed')
        result = await self.release(cash('300'), deposits=(failed,))
        self.assertTrue(result.released, result.blockers)
        self.assertEqual(self.adjustments(), [])

    async def test_new_transfer_between_shards_still_needs_operator(self):
        self.cash = cash('300')
        await self.refresh()
        moved = self.transfer | dict(transfer_id='new-transfer',
            created_ts=int((baseline.BOUNDARY+timedelta(seconds=1)).timestamp()))
        result = await self.account.reconcile_accounting(Reads(self.cash,
            deposits=(self.deposit,), intra_transfers=(self.transfer, moved)),
            proposed_boundary=baseline.BOUNDARY, continuity=self.continuity,
            now=lambda: self.now, release=True)
        self.assertFalse(result.released)
        self.assertIn('cash_activity_unattributed', result.blockers)

    async def test_cold_start_reproduces_adjustments_and_detects_tampering(self):
        deposit = self.later('new-deposit', amount_cents=30000)
        self.assertTrue((await self.release(cash('601'), deposits=(deposit,))).released)
        self.assertEqual(sorted(self.adjustments()),
                         [('deposit', D(300)), ('unattributed_credit', D(1))])
        await self.writer.close()
        with closing(Ledger(self.path)) as ledger:
            validate_cash(ledger)  # Baseline + fills + journaled adjustments.
            ledger.connection.execute("UPDATE cash_adjustments SET amount='400' WHERE kind='deposit'")
            with self.assertRaises(InvalidData):
                validate_cash(ledger)
        self.writer = await baseline.LedgerWriter(self.path).start()


if __name__ == '__main__':
    unittest.main()
