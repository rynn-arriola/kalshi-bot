"""D-165: a settled operator-only trade is adopted exactly, never as bot P&L."""
from contextlib import closing
from datetime import timedelta
from decimal import Decimal as D
import sqlite3
import unittest

from kalshi_bot import operator_trades
from kalshi_bot.account_release import validate_cash
from kalshi_bot.ledger import Fill, Ledger
from kalshi_bot.opening_account import parse_intra_exchange_transfers, parse_settlements
from kalshi_bot.recovery import HistoricalFill, HistoryEvidence
from kalshi_bot.values import InvalidData
from tests import test_bot_account_release as baseline
from tests.test_bot_cash_attribution import cash
from tests.test_bot_opening_account import NOW, settlement

TICKER = 'KXMVECOMBO-S1-B1'
AT = NOW-timedelta(minutes=30)
AT_US = int(AT.timestamp()*1_000_000)


def combo_fill(fee='3.9485'):
    return HistoricalFill(Fill('trade-1', 'operator-order', TICKER, 'bid', D('294.65'),
                               D('.258'), D(fee), AT_US, 1), AT_US, 0, 1)


def combo_settlement(**changes):
    return settlement(ticker=TICKER, event_ticker='KXMVECOMBO-S1', exchange_index=1,
        market_result='no', yes_count_fp='294.65', yes_total_cost_dollars='76.019700',
        no_count_fp='0.00', no_total_cost_dollars='0', revenue=0, fee_cost='3.948500',
        value=0, settled_time=(NOW-timedelta(minutes=10)).isoformat().replace('+00:00', 'Z')) | changes


def combo_transfer(**changes):
    return dict(transfer_id='combo-transfer', source='event_contract',
        destination='event_contract', source_exchange_shard=0, destination_exchange_shard=1,
        amount='79.98', status='complete', created_ts=int(AT.timestamp())) | changes


class OperatorTradeTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = baseline.AccountReleaseTests.asyncSetUp
    asyncTearDown = baseline.AccountReleaseTests.asyncTearDown
    open_epoch = baseline.AccountReleaseTests.open_epoch

    async def refresh(self, records=()):
        audit = await self.writer.audit_history(HistoryEvidence(
            int(baseline.BOUNDARY.timestamp()*1_000_000), int(self.now.timestamp()*1_000_000),
            int(baseline.BOUNDARY.timestamp()*1_000_000), 0, records, 1, 0), self.now,
            read_started_at=self.now, generation=self.account.generation,
            source_revision=self.account.revision)
        token = self.account.begin_reconciliation(self.now)
        self.report = await self.account.finish_reconciliation(token,
            baseline.normalize_snapshot((), (), self.cash, subaccount=0), self.now)
        self.continuity = baseline.ContinuityAssessment(0, self.account.generation,
            self.writer.epoch, self.writer.revision, (audit.enumeration.receipt_id,), (),
            self.epoch.epoch_id, 'open', True, False, ('venue_history_stream_handoff_unproven',))
        return audit

    async def release(self, settlement_row=None, transfer=None):
        return await self.account.reconcile_accounting(baseline.Reads(self.cash,
            settlements=(settlement_row or combo_settlement(),),
            deposits=(self.deposit,), intra_transfers=(self.transfer, transfer or combo_transfer())),
            proposed_boundary=baseline.BOUNDARY, continuity=self.continuity,
            now=lambda: self.now, release=True)

    def evidence(self, *, fee='3.9485', settlement_row=None, transfer=None):
        return dict(records=(combo_fill(fee),),
                    settlement=parse_settlements((settlement_row or combo_settlement(),),
                                                 boundary=baseline.BOUNDARY)[0],
                    transfers=parse_intra_exchange_transfers((transfer or combo_transfer(),),
                                                             boundary=baseline.BOUNDARY))

    async def record(self, **kwargs):
        await self.writer.close()
        try:
            with closing(Ledger(self.path)) as ledger:
                return operator_trades.record(ledger, reference='D165-test', now=self.now,
                                              **self.evidence(**kwargs))
        finally:
            self.writer = await baseline.LedgerWriter(self.path).start()
            self.account = baseline.AccountCoordinator(self.writer, subaccount=0, clock=lambda: self.tick)
            self.account.connect_generation()
            await self.open_epoch()

    def rows(self, sql, *args):
        with closing(sqlite3.connect(self.path)) as conn:
            return conn.execute(sql, args).fetchall()

    async def test_unrecorded_operator_trade_blocks_and_recorded_one_releases(self):
        self.cash = cash('220.02', '200.0118')   # 79.98 moved; 79.9682 spent on shard 1
        audit = await self.refresh((combo_fill(),))
        self.assertEqual(audit.missing_fill_keys, (combo_fill().fill.key,))
        result = await self.release()
        self.assertFalse(result.released)
        for blocker in ('cash_activity_unattributed', 'settlement_reconciliation_required',
                        'accounting_unaccounted_history_fill'):
            self.assertIn(blocker, result.blockers)
        self.assertEqual(await self.record(), {0: D('-79.98'), 1: D('.0118')})
        audit = await self.refresh((combo_fill(),))
        self.assertEqual(audit.missing_fill_keys, ())
        result = await self.release()
        self.assertTrue(result.released, result.blockers)
        self.assertEqual(result.cash_adjustments, ())      # nothing left to attribute
        self.assertEqual({k: D(v) for k, v in self.rows('SELECT * FROM accounting_cash')}
                         , {0: D('220.02'), 1: D('200.0118')})
        self.assertEqual(sorted((k, D(a)) for k, a in self.rows(
            "SELECT kind,amount FROM cash_adjustments")),
            [('operator_trade', D('-79.98')), ('operator_trade', D('.0118'))])
        # History import treats it as done, so it is never retried as unbound.
        key = combo_fill().fill.key
        self.assertEqual(await self.writer.refined_fills((key, '["other","x"]')), {key})
        self.assertEqual(self.rows("SELECT COUNT(*) FROM fills")[0][0], 0)   # not bot P&L
        self.assertEqual(self.rows("SELECT COUNT(*) FROM realized_events")[0][0], 0)
        await self.writer.close()
        with closing(Ledger(self.path)) as ledger:
            validate_cash(ledger)
        self.writer = await baseline.LedgerWriter(self.path).start()

    async def test_changed_settlement_or_new_transfer_still_blocks(self):
        self.cash = cash('220.02', '200.0118')
        await self.record()
        await self.refresh((combo_fill(),))
        changed = await self.release(settlement_row=combo_settlement(fee_cost='3.95'))
        self.assertIn('settlement_reconciliation_required', changed.blockers)
        await self.refresh((combo_fill(),))
        moved = await self.release(transfer=combo_transfer(amount='79.99'))
        self.assertIn('cash_activity_unattributed', moved.blockers)

    async def test_record_requires_exact_matching_operator_only_evidence(self):
        for kwargs in (dict(fee='3.9484'),                                      # fee differs
                       dict(settlement_row=combo_settlement(yes_count_fp='294.64')),
                       dict(settlement_row=combo_settlement(market_result='yes', value=100)),
                       dict(transfer=combo_transfer(destination_exchange_shard=2)),
                       dict(transfer=combo_transfer(status='pending'))):
            with self.assertRaises(InvalidData, msg=str(kwargs)):
                await self.record(**kwargs)
        self.assertEqual(self.rows('SELECT COUNT(*) FROM operator_trades')[0][0], 0)
        await self.record()
        with self.assertRaises(InvalidData):
            await self.record()                                                 # once only
        self.assertEqual(self.rows('SELECT COUNT(*) FROM cash_adjustments')[0][0], 2)

    async def test_a_market_the_bot_traded_is_never_an_operator_trade(self):
        await self.writer.close()
        with closing(Ledger(self.path)) as ledger:
            ledger.reserve_intent('bot', baseline.request('bot') | dict(ticker=TICKER), self.now)
            with self.assertRaises(InvalidData):
                operator_trades.record(ledger, reference='x', now=self.now, **self.evidence())
        self.writer = await baseline.LedgerWriter(self.path).start()


if __name__ == '__main__':
    unittest.main()
