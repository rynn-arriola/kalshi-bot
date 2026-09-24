"""D-068 operational release through the real owners, synthetic sources only."""
import asyncio
from contextlib import closing
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from kalshi_bot.account import AccountCoordinator, normalize_snapshot
from kalshi_bot.account_release import (cash_limit, record_operator_close,
                                        validate_cash)
from kalshi_bot.command_types import CommandDenied
from kalshi_bot.config import BotConfig
from kalshi_bot.continuity import ContinuityAssessment, PrivateEpoch, REQUIRED_PRIVATE_CHANNELS
from kalshi_bot.execution import InjectedExecutor
from kalshi_bot.ledger import Fill, Ledger
from kalshi_bot.orders import OrderUpdate
from kalshi_bot.recovery import HistoryEvidence
from kalshi_bot.opening_account import parse_cash
from kalshi_bot.rest import PageSet, ReadResult
from kalshi_bot.values import InvalidData
from kalshi_bot.writer import LedgerWriter
from tests import test_bot_command_handoff as handoff
from tests.test_bot_command_handoff import request
from tests.test_bot_opening_account import NOW, balance, settlement


BOUNDARY = NOW-timedelta(hours=1)


class Reads:
    def __init__(self, cash=None, settlements=(), deposits=(), intra_transfers=()):
        self.cash = cash or balance()
        self.settlements = settlements
        self.deposits = deposits
        self.intra_transfers = intra_transfers

    async def read(self, name, **kwargs):
        assert name == 'balance'
        return ReadResult(self.cash, 1)

    async def collect(self, name, **kwargs):
        rows = {'settlements': self.settlements, 'deposits': self.deposits,
                'intra_exchange_transfers': self.intra_transfers}.get(name, ())
        return PageSet(rows, 1, 20, name,
            (('subaccount', 0), ('min_ts', int(BOUNDARY.timestamp())-1))
            if name == 'settlements' else (), True)


class AccountReleaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name)/'release.db'
        self.writer = await LedgerWriter(self.path).start()
        self.tick = 0.0
        self.now = NOW
        self.cash = balance()
        self.account = AccountCoordinator(self.writer, subaccount=0, clock=lambda: self.tick)
        self.account.connect_generation()
        await self.open_epoch()
        await self.refresh()
        old = int((BOUNDARY-timedelta(days=1)).timestamp())
        self.deposit = dict(id='personal-deposit', status='applied', type='ach',
            amount_cents=50000, fee_cents=0, created_ts=old)
        self.transfer = dict(transfer_id='completed-transfer', source='event_contract',
            destination='event_contract', source_exchange_shard=0,
            destination_exchange_shard=1, amount='.44', status='complete',
            created_ts=old)
        captured = await self.account.reconcile_accounting(
            Reads(deposits=(self.deposit,), intra_transfers=(self.transfer,)),
            proposed_boundary=BOUNDARY,
            continuity=self.continuity, now=lambda: self.now)
        self.checkpoint = captured.status.checkpoint_digest
        self.assertIsNotNone(self.checkpoint)
        self.assertTrue(await self.writer.approve_opening(checkpoint_digest=self.checkpoint,
            reference='synthetic-approval', now=self.now))

    async def asyncTearDown(self):
        await self.writer.close()
        self.temp.cleanup()

    async def open_epoch(self):
        self.epoch = PrivateEpoch('private-'+self.writer.epoch, 0, self.account.generation,
            self.writer.epoch, tuple(sorted(REQUIRED_PRIVATE_CHANNELS)), self.now)
        await self.writer.open_private_epoch(self.epoch)

    async def refresh(self, *, orders=(), positions=(), history_start=BOUNDARY,
                      history_end=None, source_revision=None):
        end = history_end or self.now
        audit = await self.writer.audit_history(HistoryEvidence(
            int(history_start.timestamp()*1_000_000), int(end.timestamp()*1_000_000),
            int(BOUNDARY.timestamp()*1_000_000), 0, (), 1, 0), self.now,
            read_started_at=self.now, generation=self.account.generation,
            source_revision=self.account.revision if source_revision is None else source_revision)
        token = self.account.begin_reconciliation(self.now)
        self.report = await self.account.finish_reconciliation(token,
            normalize_snapshot(orders, positions, self.cash, subaccount=0), self.now)
        self.continuity = ContinuityAssessment(0, self.account.generation,
            self.writer.epoch, self.writer.revision, (audit.enumeration.receipt_id,), (),
            self.epoch.epoch_id, 'open', True, False, ('venue_history_stream_handoff_unproven',))

    async def release(self, *, reads=None):
        return await self.account.reconcile_accounting(reads or Reads(self.cash,
            deposits=(self.deposit,), intra_transfers=(self.transfer,)),
            proposed_boundary=BOUNDARY, continuity=self.continuity, now=lambda: self.now, release=True)

    async def ready(self):
        await self.refresh()
        result = await self.release()
        self.assertTrue(result.released, result.blockers)
        self.assertFalse(result.venue_handoff_proven or result.live_ready)
        return result

    async def reserve(self, client='client', *, req=None, fee=D('.01'), fixture=True):
        return await self.writer.reserve_entry(req or request(client), attempt_id='attempt-'+client,
            view=await self.writer.portfolio(subaccount=0, now=self.now), config=BotConfig(),
            now=self.now, free_cash=D(999999), account_known=False, offline_fixture=fixture,
            fee_per_contract_bound=fee)

    async def seed_exact_closed_settlement(self):
        """Install two retained owned fills matching one zero-revenue settlement."""
        await self.writer.close()
        opened_at, closed_at = NOW-timedelta(minutes=30), NOW-timedelta(minutes=20)
        with closing(Ledger(self.path)) as ledger:
            rows = (
                ('open-client', 'open-order', 'bid', D('.2'), D(0), opened_at),
                ('close-client', 'close-order', 'ask', D('.02'), D('.0138'), closed_at),
            )
            for client, order_id, side, price, fee, at in rows:
                intent = request(client) | dict(ticker='SETTLED', client_order_id=client,
                    side=side, price=str(price), exchange_index=0)
                ledger.reserve_intent(client, intent, at)
                ledger.transition_intent(client, 'SENDING')
                ledger.transition_intent(client, 'ACKNOWLEDGED')
                ledger.transition_intent(client, 'TERMINAL')
                order = OrderUpdate(order_id, client, 'SETTLED', side, price,
                    D(10), D(10), D(0), 'executed', 0, 0,
                    int(at.timestamp()*1_000_000))
                with ledger.transaction():
                    ledger.connection.execute('INSERT INTO order_evidence VALUES (?,?,?,?)',
                        (order.order_id, order.client_id, order.encode(), at.isoformat()))
                self.assertTrue(ledger.record_fill(Fill(client+'-fill', order_id, 'SETTLED',
                    side, D(10), price, fee, int(at.timestamp()*1_000_000), 1), at))
            self.assertEqual(ledger.position('SETTLED'), 0)
            self.assertEqual(ledger.realized(BOUNDARY, NOW), D('-1.8138'))
        self.cash = balance() | dict(balance=49819, balance_dollars='498.1862',
            portfolio_value=49819, updated_ts=2,
            balance_breakdown=[dict(exchange_index=0, balance='298.1862'),
                               dict(exchange_index=1, balance='200')])
        self.writer = await LedgerWriter(self.path).start()
        self.account = AccountCoordinator(self.writer, subaccount=0, clock=lambda: self.tick)
        self.account.connect_generation()
        await self.open_epoch()
        await self.refresh()
        return settlement(ticker='SETTLED', event_ticker='SETTLED-EVENT',
            market_result='no', yes_count_fp='10', yes_total_cost_dollars='2',
            no_count_fp='10', no_total_cost_dollars='9.8', revenue=0,
            fee_cost='.0138', value=0,
            settled_time=(NOW-timedelta(minutes=10)).isoformat().replace('+00:00', 'Z'))

    async def test_positive_release_reserve_send_and_audited_hold_removal(self):
        result = await self.ready()
        prepared = await self.reserve()
        self.assertTrue(prepared.reserved, prepared.blockers)
        self.assertTrue(self.writer.entry_accounting_current(prepared.receipt))
        sent = await self.writer.begin_send(prepared.receipt)
        self.assertTrue(sent.dispatch_allowed, sent.blockers)
        with closing(sqlite3.connect(self.path)) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM accounting_holds').fetchone()[0], 0)
            payload = json.loads(conn.execute('SELECT payload FROM accounting_events WHERE digest=?',
                                              (result.release_digest,)).fetchone()[0])
            self.assertIn('opening_proof_unresolved', [r[0] for r in payload['resolved']])

    async def test_exact_approved_cash_activity_clears_legacy_stale_hold(self):
        await self.writer.close()
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute("INSERT INTO accounting_holds VALUES "
                         "('cash_activity_unattributed','legacy-stale-hold',?)",
                         (self.now.isoformat(),))
            conn.commit()
        self.writer = await LedgerWriter(self.path).start()
        self.account = AccountCoordinator(self.writer, subaccount=0, clock=lambda: self.tick)
        self.account.connect_generation()
        await self.open_epoch()
        await self.refresh()
        result = await self.release()
        self.assertTrue(result.released, result.blockers)
        self.assertNotIn('cash_activity_unattributed',
                         (await self.writer.accounting_status()).holds)

    async def test_new_cash_activity_after_baseline_remains_blocked(self):
        await self.refresh()
        later = self.deposit | dict(id='later-deposit', amount_cents=1,
            created_ts=int((BOUNDARY+timedelta(seconds=1)).timestamp()))
        result = await self.release(reads=Reads(self.cash,
            deposits=(self.deposit, later), intra_transfers=(self.transfer,)))
        self.assertFalse(result.released)
        self.assertIn('cash_activity_unattributed', result.blockers)

    async def test_approved_deposit_finalization_enrichment_releases(self):
        await self.refresh()
        finalized = self.deposit | dict(finalized_ts=self.deposit['created_ts'])
        result = await self.release(reads=Reads(self.cash,
            deposits=(finalized,), intra_transfers=(self.transfer,)))
        self.assertTrue(result.released, result.blockers)
        self.assertNotIn('cash_activity_unattributed',
                         (await self.writer.accounting_status()).holds)

    async def test_approved_deposit_omission_remains_blocked(self):
        await self.refresh()
        result = await self.release(reads=Reads(self.cash,
            deposits=(), intra_transfers=(self.transfer,)))
        self.assertFalse(result.released)
        self.assertIn('cash_activity_unattributed', result.blockers)

    async def test_finalized_deposit_economic_change_remains_blocked(self):
        await self.refresh()
        changed = self.deposit | dict(finalized_ts=self.deposit['created_ts'],
                                      amount_cents=self.deposit['amount_cents']+1)
        result = await self.release(reads=Reads(self.cash,
            deposits=(changed,), intra_transfers=(self.transfer,)))
        self.assertFalse(result.released)
        self.assertIn('cash_activity_unattributed', result.blockers)

    async def test_later_unchanged_balance_timestamp_releases(self):
        self.cash = self.cash | dict(updated_ts=2)
        await self.refresh()
        later = self.cash | dict(updated_ts=3)
        result = await self.release(reads=Reads(later,
            deposits=(self.deposit,), intra_transfers=(self.transfer,)))
        self.assertTrue(result.released, result.blockers)

    async def test_live_authorization_is_still_independent(self):
        await self.ready()
        denied = await self.reserve(fixture=False)
        self.assertIn('live_authorization_missing', denied.blockers)
        self.assertFalse(denied.reserved)

    async def test_expiry_and_disconnect_block_prepared_send(self):
        await self.ready()
        prepared = (await self.reserve()).receipt
        self.tick = 6
        self.assertFalse(self.writer.entry_accounting_current(prepared))
        self.assertFalse((await self.writer.begin_send(prepared)).dispatch_allowed)
        self.account.disconnect()
        self.assertFalse(self.writer.entry_accounting_current(prepared))

    async def test_missing_fee_bound_cannot_use_caller_cash(self):
        await self.ready()
        result = await self.reserve(fee=None)
        self.assertFalse(result.reserved)
        self.assertIn('accounting_cash_or_fee_bound_missing', result.blockers)

    async def test_wrong_history_source_and_interval_fail_closed(self):
        await self.refresh(source_revision=self.account.revision+1)
        self.assertIn('accounting_history_receipt_invalid', (await self.release()).blockers)
        await self.refresh(history_start=BOUNDARY+timedelta(minutes=1))
        self.assertIn('accounting_history_interval_gap', (await self.release()).blockers)
        await self.refresh(history_end=self.now-timedelta(minutes=1))
        self.assertIn('accounting_history_interval_gap', (await self.release()).blockers)

    async def test_settlement_cannot_be_cleared_by_fresh_empty_history_or_review(self):
        await self.refresh()
        result = await self.release(reads=Reads(settlements=(settlement(),)))
        self.assertIn('settlement_reconciliation_required', result.blockers)
        await self.writer.record_accounting_review(reference='not-economic-proof',
            checkpoint_digest=self.checkpoint, now=self.now)
        await self.refresh()
        self.assertIn('settlement_reconciliation_required', (await self.release()).blockers)

    async def test_exact_closed_settlement_releases_without_double_booking(self):
        row = await self.seed_exact_closed_settlement()
        result = await self.release(reads=Reads(self.cash, settlements=(row,),
            deposits=(self.deposit,), intra_transfers=(self.transfer,)))
        self.assertTrue(result.released, result.blockers)
        self.assertNotIn('settlement_reconciliation_required',
                         (await self.writer.accounting_status()).holds)
        await self.refresh()
        repeated = await self.release(reads=Reads(self.cash, settlements=(row,),
            deposits=(self.deposit,), intra_transfers=(self.transfer,)))
        self.assertTrue(repeated.released, repeated.blockers)
        await self.writer.close()
        with closing(Ledger(self.path)) as ledger:
            self.assertEqual(ledger.realized(BOUNDARY, NOW), D('-1.8138'))
            self.assertEqual(D(ledger.connection.execute(
                'SELECT cash FROM accounting_cash WHERE exchange_index=0').fetchone()[0]),
                D('298.1862'))
            payload = json.loads(ledger.connection.execute(
                "SELECT payload FROM accounting_events WHERE kind='operational_release' "
                'ORDER BY rowid DESC LIMIT 1').fetchone()[0])
            self.assertEqual(payload['settlements'][0]['ticker'], 'SETTLED')
            self.assertEqual(payload['settlements'][0]['fill_count'], 2)
        self.writer = await LedgerWriter(self.path).start()

    async def test_closed_settlement_economics_mismatch_remains_blocked(self):
        row = await self.seed_exact_closed_settlement()
        changed = row | dict(yes_total_cost_dollars='2.01')
        result = await self.release(reads=Reads(self.cash, settlements=(changed,),
            deposits=(self.deposit,), intra_transfers=(self.transfer,)))
        self.assertFalse(result.released)
        self.assertIn('settlement_reconciliation_required', result.blockers)

    async def test_settlement_identity_change_after_release_reblocks(self):
        row = await self.seed_exact_closed_settlement()
        exact = await self.release(reads=Reads(self.cash, settlements=(row,),
            deposits=(self.deposit,), intra_transfers=(self.transfer,)))
        self.assertTrue(exact.released, exact.blockers)
        await self.refresh()
        changed = row | dict(
            settled_time=(NOW-timedelta(minutes=5)).isoformat().replace('+00:00', 'Z'))
        result = await self.release(reads=Reads(self.cash, settlements=(changed,),
            deposits=(self.deposit,), intra_transfers=(self.transfer,)))
        self.assertFalse(result.released)
        self.assertIn('settlement_reconciliation_required', result.blockers)

    async def test_external_writer_evidence_revokes_lease(self):
        await self.ready()
        prepared = (await self.reserve()).receipt
        await self.writer.observe(self.now)
        self.assertFalse(self.writer.entry_accounting_current(prepared))

    async def test_restart_needs_new_epoch_history_and_lease(self):
        await self.ready()
        await self.writer.close()
        self.writer = await LedgerWriter(self.path).start()
        denied = await self.reserve()
        self.assertIn('accounting_lease_required', denied.blockers)
        self.account = AccountCoordinator(self.writer, subaccount=0, clock=lambda: self.tick)
        self.account.connect_generation()
        await self.open_epoch()
        await self.ready()
        self.assertTrue((await self.reserve()).reserved)

    async def test_unexplained_cash_cannot_become_spendable(self):
        self.cash = balance() | dict(balance_dollars='501', balance=50100,
            balance_breakdown=[dict(exchange_index=0, balance='301'),
                               dict(exchange_index=1, balance='200')])
        await self.refresh()
        self.assertIn('accounting_cash_unexplained', (await self.release()).blockers)

    async def test_schema_four_refused_without_migration(self):
        await self.writer.close()
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute("UPDATE meta SET value='4' WHERE key='schema'")
            conn.commit()
        before = self.path.read_bytes()
        with self.assertRaises(InvalidData):
            Ledger(self.path)
        self.assertEqual(self.path.read_bytes(), before)

    async def test_cash_yes_no_partial_close_reversal_and_duplicate_fees(self):
        await self.writer.close()
        with closing(Ledger(self.path)) as ledger:
            for i, (ticker, side, quantity, price, fee, expected) in enumerate((
                    ('A', 'bid', '10', '.4', '.01', '195.99'),
                    ('A', 'ask', '3', '.6', '.02', '197.77'),
                    ('A', 'ask', '9', '.7', '.03', '202.04'),
                    ('A', 'bid', '2', '.5', '.01', '203.03'),
                    ('B', 'ask', '4', '.3', '.01', '200.22'),
                    ('B', 'bid', '4', '.2', '.01', '203.41'),
                    ('A', 'bid', '.01', '.123456789012', '.000000000001', '203.40876543210888'),
                    ('A', 'ask', '.01', '.3', '0', '203.41176543210888'))):
                order = OrderUpdate('order'+str(i), 'client'+str(i), ticker, side,
                    D(price), D(quantity), D(quantity), D(0), 'executed', 0, 1, 1)
                # Closed synthetic evidence only; no production database/transport.
                with ledger.transaction():
                    ledger.connection.execute('INSERT INTO order_evidence VALUES (?,?,?,?)',
                        (order.order_id, order.client_id, order.encode(), NOW.isoformat()))
                fill = Fill(str(i), order.order_id, ticker, side, D(quantity), D(price), D(fee),
                            int(NOW.timestamp()*1_000_000), 1)
                self.assertTrue(ledger.record_fill(fill, NOW))
                self.assertFalse(ledger.record_fill(fill, NOW))
                self.assertEqual(D(ledger.connection.execute(
                    'SELECT cash FROM accounting_cash WHERE exchange_index=1').fetchone()[0]), D(expected))
        with closing(Ledger(self.path)) as restarted:
            self.assertEqual(restarted.position('A'), 0)
            self.assertEqual(restarted.position('B'), 0)

    async def test_explicit_operator_close_retains_external_scope_and_cash(self):
        await self.writer.close()
        with closing(Ledger(self.path)) as ledger:
            opening = OrderUpdate('owned-order', 'owned-client', 'A', 'bid',
                D('.4'), D(10), D(10), D(0), 'executed', 0, 1, 1)
            with ledger.transaction():
                ledger.connection.execute('INSERT INTO order_evidence VALUES (?,?,?,?)',
                    (opening.order_id, opening.client_id, opening.encode(), NOW.isoformat()))
            ledger.record_fill(Fill('owned-trade', opening.order_id, 'A', 'bid',
                D(10), D('.4'), D(0), int(NOW.timestamp()*1_000_000), 1), NOW)
            external = OrderUpdate('manual-order', 'manual-client', 'A', 'ask',
                D('.3'), D(10), D(10), D(0), 'executed', 0, 1, 2)
            close = Fill('manual-trade', external.order_id, 'A', 'ask',
                D(10), D('.3'), D('.1'), int(NOW.timestamp()*1_000_000)+1, 1)
            self.assertTrue(record_operator_close(ledger, close, external,
                reference='test-incident', now=NOW+timedelta(seconds=1)))
            self.assertEqual(ledger.position('A'), 0)
            self.assertFalse(ledger.connection.execute(
                'SELECT 1 FROM order_evidence WHERE order_id=?',
                (external.order_id,)).fetchone())
            scope = ledger.connection.execute(
                'SELECT reference FROM operator_fill_scopes WHERE order_id=?',
                (external.order_id,)).fetchone()
            self.assertEqual(scope[0], 'test-incident')
            validate_cash(ledger)
            with self.assertRaisesRegex(InvalidData, 'already reconciled'):
                record_operator_close(ledger, close, external,
                    reference='test-incident', now=NOW+timedelta(seconds=2))
        with closing(Ledger(self.path)) as restarted:
            self.assertEqual(restarted.position('A'), 0)
            validate_cash(restarted)

    async def test_independent_cash_ceilings_no_double_subtraction_or_cross_shard_credit(self):
        await self.writer.close()
        with closing(Ledger(self.path)) as ledger:
            ledger.reserve_intent('client', request(), NOW)
            with ledger.transaction():
                ledger.connection.execute("INSERT INTO accounting_fees VALUES ('client','.01')")
            self.assertEqual(cash_limit(ledger, parse_cash(balance(), subaccount=0), 1), D('195.9'))
            held = balance() | dict(balance_dollars='495.9', balance=49590,
                balance_breakdown=[dict(exchange_index=0, balance='300'),
                                   dict(exchange_index=1, balance='195.9')])
            self.assertEqual(cash_limit(ledger, parse_cash(held, subaccount=0), 1), D('195.9'))
            self.assertEqual(cash_limit(ledger, parse_cash(held, subaccount=0), 0), D(300))
            with self.assertRaises(InvalidData):
                cash_limit(ledger, parse_cash(held, subaccount=0), 2)

    async def test_revocation_at_last_send_edge_calls_no_transport(self):
        await self.ready()
        prepared = (await self.reserve()).receipt
        calls = []
        async def invoke(*args):
            calls.append(args)
            raise AssertionError('must not reach transport')
        executor = InjectedExecutor(self.writer, invoke=invoke, validate_proof=lambda *a: True,
            offline_fixture=True, now=lambda: self.now)
        with self.assertRaises(CommandDenied):
            await executor.execute_prepared(prepared, before_invoke=self.account.disconnect)
        self.assertEqual(calls, [])
        self.assertEqual((await self.writer.mutations())[0]['phase'], 'UNKNOWN')

    async def test_cancelled_consumer_joins_reads_but_cannot_issue_authority(self):
        await self.refresh()
        entered, finish = asyncio.Event(), asyncio.Event()
        class Slow(Reads):
            async def read(inner, name, **kwargs):
                entered.set()
                await finish.wait()
                return await super().read(name, **kwargs)
        task = asyncio.create_task(self.release(reads=Slow()))
        await entered.wait()
        retained = self.account._opening_task
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        finish.set()
        result = await retained
        self.assertFalse(result.released)
        self.assertIsNone(self.writer._accounting_lease)

    async def test_ingress_after_commit_cannot_return_success(self):
        await self.refresh()
        original = self.writer.release_accounting
        async def interrupted(*args, **kwargs):
            result = await original(*args, **kwargs)
            self.account._invalidate()
            return result
        with patch.object(self.writer, 'release_accounting', interrupted):
            self.assertFalse((await self.release()).released)
        self.assertFalse((await self.reserve()).reserved)

    async def test_monotonic_age_includes_snapshot_and_read_time(self):
        await self.refresh()
        self.tick = 6  # Wall clock is deliberately frozen.
        self.assertIn('accounting_source_stale', (await self.release()).blockers)

    async def test_release_transaction_failure_keeps_hold_and_no_lease(self):
        from kalshi_bot.account_release import _append
        await self.refresh()
        def fail(ledger, kind, *args):
            if kind == 'operational_release':
                raise InvalidData('synthetic disk failure')
            return _append(ledger, kind, *args)
        with patch('kalshi_bot.account_release._append', fail):
            with self.assertRaises(InvalidData):
                await self.release()
        self.assertIsNone(self.writer._accounting_lease)
        with closing(sqlite3.connect(self.path)) as conn:
            self.assertGreater(conn.execute('SELECT count(*) FROM accounting_holds').fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT count(*) FROM accounting_events WHERE kind='operational_release'").fetchone()[0], 0)

    async def test_cash_tampering_fails_cold_validation(self):
        await self.writer.close()
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute("UPDATE accounting_cash SET cash='999' WHERE exchange_index=1")
            conn.commit()
        with self.assertRaisesRegex(InvalidData, 'derived cash'):
            Ledger(self.path)

    async def test_late_fill_count_blocks_release_until_exact_fill_imported(self):
        await self.ready()
        prepared = (await self.reserve()).receipt
        await self.writer.begin_send(prepared)
        await self.writer.record_outcome('ack', prepared, dict(order_id='owned',
            client_order_id='client', fill_count='3', remaining_count='0', ts_ms=1), self.now)
        await self.writer.order(OrderUpdate('owned', 'client', 'A', 'bid', D('.4'),
            D(10), D(3), D(0), 'canceled', 0, 1, 1), self.now)
        await self.refresh()
        self.assertIn('owned_order_fill_gap', (await self.release()).blockers)
        fill = Fill('late', 'owned', 'A', 'bid', D(3), D('.4'), D('.01'),
                    int(NOW.timestamp()*1_000_000), 1)
        await self.writer.fill(fill, self.now)
        self.cash = balance() | dict(balance=49879, balance_dollars='498.79', updated_ts=2,
            balance_breakdown=[dict(exchange_index=0, balance='300'),
                               dict(exchange_index=1, balance='198.79')])
        await self.refresh(positions=(dict(ticker='A', exchange_index=1, position_fp='3',
                                          market_exposure_dollars='1.2'),))
        result = await self.release()
        self.assertTrue(result.released, result.blockers)

    async def test_approved_residual_common_delay_is_not_claimed_detected(self):
        # An event absent from BOTH injected sources is unknowable here. The
        # policy permits local agreement, never certifies global completeness.
        result = await self.ready()
        self.assertTrue(result.released)
        self.assertFalse(result.venue_handoff_proven)

    async def test_runtime_recovery_uses_existing_owner_and_release_path(self):
        from kalshi_bot.runtime import RecoveryRuntime
        class RuntimeReads(Reads):
            async def read(inner, name, **kwargs):
                if name == 'cutoff':
                    return ReadResult(dict(trades_created_ts=BOUNDARY.isoformat()), 1)
                return await super().read(name, **kwargs)
            async def collect(inner, name, **kwargs):
                if name in {'orders', 'positions', 'fills', 'historical_fills'}:
                    return PageSet((), 1, 20)
                return await super().collect(name, **kwargs)
        async def no_op(*args):
            pass
        runtime = RecoveryRuntime(self.writer, RuntimeReads(), lambda spec: None,
            tickers=('A',), subaccount=0, history_start=BOUNDARY, now=lambda: self.now,
            evaluate=no_op, deadline_handler=no_op, lifecycle_handler=no_op,
            accounting_boundary=BOUNDARY)
        # Same real owner used to capture/approve the synthetic opening; no sockets.
        runtime.account = self.account
        runtime._epoch = self.epoch
        runtime._persisted_epoch_gaps = 0
        runtime.account_subscribed = True
        runtime.engine.begin_private_epoch()
        self.assertTrue(await runtime.recover_once())
        self.assertTrue(runtime.accounting_result.released)
        self.assertFalse(runtime.entry_allowed)

    async def test_approved_baseline_keeps_cancel_and_reducer_available_without_lease(self):
        await self.ready()
        prepared = (await self.reserve()).receipt
        await self.writer.begin_send(prepared)
        await self.writer.record_outcome('ack', prepared, dict(order_id='owned',
            client_order_id='client', fill_count='3', remaining_count='7', ts_ms=1), self.now)
        order = OrderUpdate('owned', 'client', 'A', 'bid', D('.4'), D(10), D(3), D(7),
                            'resting', 0, 1, 1)
        await self.writer.order(order, self.now)
        await self.writer.fill(Fill('fill', 'owned', 'A', 'bid', D(3), D('.4'), D('.01'),
            int(NOW.timestamp()*1_000_000), 1), self.now)
        await self.writer.accounting_source_failed()
        cancel = await self.writer.prepare_cancel('cancel', dict(order_id='owned', subaccount=0,
            exchange_index=1, market_ticker='A'), evidence=await self.writer.cancel_evidence('owned'),
            now=self.now)
        self.assertTrue(cancel.reserved, cancel.blockers)
        self.assertTrue((await self.writer.begin_send(cancel.receipt)).dispatch_allowed)
        await self.writer.record_outcome('unknown', cancel.receipt, {}, self.now)
        await self.refresh(orders=(dict(order_id='owned', client_order_id='client', ticker='A',
            book_side='bid', yes_price_dollars='.4', remaining_count_fp='7',
            status='resting', exchange_index=1),), positions=(dict(ticker='A', exchange_index=1,
            position_fp='3', market_exposure_dollars='1.2'),))
        self.assertIn('accounting_mutation_unresolved', (await self.release()).blockers)
        await self.writer.order(replace(order, remaining=D(0), status='canceled', version_us=2), self.now)
        req = handoff.CommandHandoffTests.reducer()
        proof, at = await handoff.CommandHandoffTests.reduction_proof(self, req, now=self.now)
        reduction = await self.writer.prepare_reduction('reduce', req, evidence=proof, now=at)
        self.assertTrue(reduction.reserved, reduction.blockers)
        self.assertTrue((await self.writer.begin_send(reduction.receipt)).dispatch_allowed)
        with closing(sqlite3.connect(self.path)) as conn:
            self.assertEqual(D(conn.execute("SELECT fee FROM accounting_fees WHERE client_id='reduce'").fetchone()[0]), D('.01'))

    async def test_saturation_cannot_clear_transient_holds(self):
        await self.refresh()
        with patch('kalshi_bot.accounting.MAX_ROWS', 0):
            result = await self.release()
        self.assertFalse(result.released)
        self.assertIn('accounting_journal_full', result.blockers)
        self.assertIsNone(self.writer._accounting_lease)
        self.assertIn('accounting_journal_full', (await self.writer.accounting_status()).holds)

    async def test_closed_epoch_and_missing_history_receipt_are_not_caller_overrideable(self):
        await self.writer.close_private_epoch(self.epoch.epoch_id, closed_at=self.now,
            ingress_count=0, durable_fill_count=0, terminal_reason='stopped', clean_local_delivery=True)
        await self.refresh()
        self.continuity = replace(self.continuity, receipt_ids=('made-up',))
        result = await self.release()
        self.assertIn('accounting_private_epoch_invalid', result.blockers)
        self.assertIn('accounting_history_receipt_missing', result.blockers)

    async def test_failed_financial_evidence_leaves_nontransient_hold_after_restart(self):
        await self.ready()
        with self.assertRaises(InvalidData):
            await self.writer.fill(Fill('unknown', 'not-owned', 'A', 'bid', D(1), D('.4'), D(0),
                int(NOW.timestamp()*1_000_000), 1), self.now)
        await self.writer.close()
        self.writer = await LedgerWriter(self.path).start()
        self.account = AccountCoordinator(self.writer, subaccount=0, clock=lambda: self.tick)
        self.account.connect_generation()
        await self.open_epoch()
        await self.refresh()
        self.assertIn('accounting_economics_failed', (await self.release()).blockers)

    async def test_releasing_again_does_not_reauthorize_old_prepared_receipt(self):
        await self.ready()
        prepared = (await self.reserve()).receipt
        await self.writer.abort_prepared(prepared)
        await self.ready()
        self.assertFalse(self.writer.entry_accounting_current(prepared))
        self.assertFalse((await self.writer.begin_send(prepared)).dispatch_allowed)

    async def test_writer_revision_change_at_send_edge_calls_no_transport(self):
        await self.ready()
        prepared = (await self.reserve()).receipt
        calls = []
        async def invoke(*args):
            calls.append(args)
            raise AssertionError('must not invoke after writer revision changes')
        def advance_revision():
            # Deterministic competing local-write boundary, no real account work.
            self.writer._revision += 1
        executor = InjectedExecutor(self.writer, invoke=invoke, validate_proof=lambda *a: True,
            offline_fixture=True, now=lambda: self.now)
        with self.assertRaises(CommandDenied):
            await executor.execute_prepared(prepared, before_invoke=advance_revision)
        self.assertEqual(calls, [])
