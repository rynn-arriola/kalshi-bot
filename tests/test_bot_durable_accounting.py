"""D-067 durable restrictions, source fencing and entry enforcement; synthetic only."""
import asyncio
from contextlib import closing
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import patch

from kalshi_bot import accounting
from kalshi_bot.account import AccountCoordinator, normalize_snapshot
from kalshi_bot.config import BotConfig
from kalshi_bot.execution import begin_send
from kalshi_bot.ledger import Fill, Ledger
from kalshi_bot.opening_account import build_opening_evidence
from kalshi_bot.orders import OrderUpdate
from kalshi_bot.portfolio import portfolio_view, reserve_entry
from kalshi_bot.rest import PageSet, ReadResult
from kalshi_bot.values import InvalidData
from kalshi_bot.writer import LedgerWriter
from tests.test_bot_command_handoff import request
from tests.test_bot_opening_account import NOW, balance, continuity, settlement


class DurableAccountingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name)/'accounting.db'
        self.writer = await LedgerWriter(self.path).start()
        self.account = AccountCoordinator(self.writer, subaccount=0)
        self.account.connect_generation()
        await self.refresh()

    async def asyncTearDown(self):
        await self.writer.close()
        self.temp.cleanup()

    async def refresh(self, now=NOW):
        self.now = now
        token = self.account.begin_reconciliation(now)
        snapshot = normalize_snapshot([], [], dict(balance_dollars='500', updated_ts=1), subaccount=0)
        self.report = await self.account.finish_reconciliation(token, snapshot, now)
        self.continuity = continuity(self.writer, self.writer.revision)

    def evidence(self, settlements=(), *, boundary=None, cash=None, **changes):
        def pages(name, rows=()):
            return PageSet(tuple(rows), 1, 20, name,
                           (('subaccount', 0),) if name == 'settlements' else (), True)
        return build_opening_evidence(**(dict(report=self.report, continuity=self.continuity,
            proposed_boundary=boundary or NOW-timedelta(hours=1), subaccount=0,
            writer_epoch=self.writer.epoch, writer_revision=self.writer.revision,
            cash_document=cash or balance(), settlements=pages('settlements', settlements),
            subaccount_transfers=pages('subaccount_transfers'),
            intra_exchange_transfers=pages('intra_exchange_transfers'),
            deposits=pages('deposits'), withdrawals=pages('withdrawals')) | changes))

    async def capture(self, **kwargs):
        return await self.writer.capture_accounting(self.evidence(**kwargs), self.report)

    async def reserve(self, client='new'):
        return await self.writer.reserve_entry(request(client), attempt_id='attempt-'+client,
            view=await self.writer.portfolio(subaccount=0, now=NOW),
            config=BotConfig(), now=NOW, free_cash=D(500), account_known=True, offline_fixture=True)

    async def test_checkpoint_is_immutable_and_duplicate_rows_do_not_grow(self):
        evidence = self.evidence()
        first = await self.writer.capture_accounting(evidence, self.report)
        self.assertTrue(first.checkpoint_created)
        self.assertFalse(first.status.ready_for_entry)
        second = await self.writer.capture_accounting(evidence, self.report)
        self.assertFalse(second.checkpoint_created)
        self.assertEqual(first.status.checkpoint_digest, second.status.checkpoint_digest)
        self.assertEqual(first.status.event_count, second.status.event_count)
        await self.refresh()
        changed = await self.capture(boundary=NOW-timedelta(hours=2))
        self.assertEqual(changed.status.checkpoint_digest, first.status.checkpoint_digest)
        self.assertIn('opening_boundary_changed', changed.status.holds)

    async def test_settlement_preserves_inventory_pnl_and_survives_restart_empty_history(self):
        await self.capture()
        fill = Fill('fill', 'order', 'A', 'bid', D(2), D('.4'), D('.01'),
                    int(NOW.timestamp())*1000000, 1)
        before = await self.writer.fill(fill, NOW)
        await self.refresh()
        captured = await self.capture(settlements=(settlement(),))
        after = await self.writer.observe(NOW)
        inventory = await self.writer.inventory()
        self.assertEqual(inventory.positions, (('A', D(2)),))
        self.assertEqual(after.realized_pnl, before.window.realized_pnl)
        self.assertIn('settlement_reconciliation_required', captured.status.holds)
        await self.writer.close()
        self.writer = await LedgerWriter(self.path).start()
        self.account = AccountCoordinator(self.writer, subaccount=0)
        self.account.connect_generation()
        await self.refresh(NOW+timedelta(hours=6))
        empty = await self.capture()
        self.assertIn('settlement_reconciliation_required', empty.status.holds)
        self.assertEqual(empty.status.checkpoint_digest, captured.status.checkpoint_digest)

    async def test_conflicting_settlement_keeps_both_versions(self):
        await self.capture(settlements=(settlement(),))
        await self.refresh()
        result = await self.capture(settlements=(settlement(revenue=999),))
        self.assertIn('settlement_economics_conflict', result.status.holds)
        await self.writer.close()
        with closing(sqlite3.connect(self.path)) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM accounting_events WHERE kind='settlement'").fetchone()[0], 2)

    async def test_equal_money_formatting_is_not_a_settlement_correction(self):
        await self.capture(settlements=(settlement(),))
        await self.refresh()
        result = await self.capture(settlements=(settlement(yes_count_fp='10',
            yes_total_cost_dollars='4', fee_cost='0.01'),))
        self.assertNotIn('settlement_economics_conflict', result.status.holds)

    async def test_regressed_cash_is_retained_without_replacing_latest(self):
        await self.capture(cash=balance() | dict(updated_ts=2))
        await self.refresh(NOW+timedelta(seconds=1))
        result = await self.capture(cash=balance() | dict(balance=49900,
            balance_dollars='499', balance_breakdown=[], updated_ts=1))
        self.assertEqual(result.status.observed_cash, D(500))
        self.assertIn('cash_clock_regressed', result.status.holds)
        self.assertIn('cash_observation_changed', result.status.holds)

    async def test_stale_evidence_keeps_positive_settlement_without_candidate(self):
        evidence = self.evidence(settlements=(settlement(),))
        await self.writer.observe(NOW)
        result = await self.writer.capture_accounting(evidence, self.report)
        self.assertFalse(result.checkpoint_created)
        self.assertIn('opening_source_stale', result.status.holds)
        self.assertIn('settlement_reconciliation_required', result.status.holds)

    async def test_new_entries_block_even_with_caller_fixture_booleans(self):
        await self.capture()
        result = await self.reserve()
        self.assertFalse(result.reserved)
        self.assertIn('opening_proof_unresolved', result.blockers)

    async def test_queued_entry_loses_permission_after_accounting_capture(self):
        prepared = (await self.reserve()).receipt
        self.assertIsNotNone(prepared)
        await self.refresh()
        await self.capture(settlements=(settlement(),))
        result = await self.writer.begin_send(prepared)
        self.assertFalse(result.dispatch_allowed)
        self.assertIn('stale_writer_evidence', result.blockers)

    async def test_safety_cancel_remains_available_under_settlement_hold(self):
        prepared = (await self.reserve()).receipt
        await self.writer.begin_send(prepared)
        await self.writer.record_outcome('ack', prepared, dict(order_id='order',
            client_order_id='new', fill_count='0', remaining_count='10', ts_ms=1), NOW)
        await self.writer.order(OrderUpdate('order', 'new', 'A', 'bid', D('.4'),
            D(10), D(0), D(10), 'resting', 0, 1, 1), NOW)
        await self.refresh()
        await self.capture(settlements=(settlement(),))
        proof = await self.writer.cancel_evidence('order')
        cancel = dict(order_id='order', subaccount=0, exchange_index=1, market_ticker='A')
        prepared_cancel = await self.writer.prepare_cancel('cancel', cancel, evidence=proof, now=NOW)
        self.assertIsNotNone(prepared_cancel.receipt, prepared_cancel.blockers)
        self.assertTrue((await self.writer.begin_send(prepared_cancel.receipt)).dispatch_allowed)

    async def test_preboundary_and_undated_fill_stay_outside_pnl(self):
        await self.capture()
        for i, stamp in enumerate((None, int((NOW-timedelta(hours=2)).timestamp())*1000000)):
            result = await self.writer.fill(Fill(str(i), 'order', 'A', 'bid',
                D(2), D('.4'), D('.01'), stamp), NOW)
            self.assertFalse(result.inserted)
            self.assertEqual(result.window.realized_pnl, D(0))
        self.assertEqual((await self.writer.inventory()).positions, ())
        self.assertIn('fill_boundary_unproven', (await self.writer.accounting_status()).holds)

    async def test_known_fill_replay_without_timestamp_keeps_original_receipt(self):
        await self.capture()
        fill = Fill('fill', 'order', 'A', 'bid', D(2), D('.4'), D('.01'),
                    int(NOW.timestamp())*1000000, 1)
        first = await self.writer.fill(fill, NOW)
        replay = await self.writer.fill(replace(fill, executed_us=None), NOW)
        self.assertFalse(replay.inserted)
        self.assertEqual(first.window.realized_pnl, replay.window.realized_pnl)
        self.assertNotIn('fill_boundary_unproven', (await self.writer.accounting_status()).holds)

    async def test_fill_conflict_retains_restriction_across_writer_restart(self):
        fill = Fill('fill', 'order', 'A', 'bid', D(2), D('.4'), D('.01'))
        await self.writer.fill(fill, NOW)
        with self.assertRaises(InvalidData):
            await self.writer.fill(replace(fill, fee=D('.02')), NOW)
        await self.writer.close()
        self.writer = await LedgerWriter(self.path).start()
        self.assertIn('accounting_source_failed', (await self.writer.accounting_status()).holds)

    async def test_journal_capacity_latches_without_removing_evidence(self):
        with patch.object(accounting, 'MAX_ROWS', 2):
            result = await self.capture(settlements=(settlement(),))
        self.assertEqual(result.status.event_count, 2)
        self.assertFalse(result.checkpoint_created)
        self.assertIn('accounting_journal_full', result.status.holds)
        self.assertIn('settlement_reconciliation_required', result.status.holds)

    async def test_review_acknowledgement_cannot_clear_unresolved_economics(self):
        result = await self.capture(settlements=(settlement(),))
        reviewed = await self.writer.record_accounting_review(reference='operator-review-1',
            checkpoint_digest=result.status.checkpoint_digest, now=NOW)
        self.assertIn('settlement_reconciliation_required', reviewed.holds)
        self.assertFalse(reviewed.ready_for_entry)

    async def test_cancelled_caller_still_commits_accepted_capture(self):
        entered, release = Event(), Event()
        original = accounting.capture
        def delayed(*args, **kwargs):
            entered.set()
            if not release.wait(5):
                raise RuntimeError('fixture timeout')
            return original(*args, **kwargs)
        with patch.object(accounting, 'capture', delayed):
            task = asyncio.create_task(self.capture(settlements=(settlement(),)))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 3))
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            finally:
                release.set()
            status = await self.writer.accounting_status()
        self.assertIn('settlement_reconciliation_required', status.holds)

    async def test_coordinator_persists_normalized_evidence(self):
        class Reads:
            async def read(inner, name, **kwargs):
                return ReadResult(balance(), 20)
            async def collect(inner, name, **kwargs):
                rows = (settlement(),) if name == 'settlements' else ()
                return PageSet(rows, 1, 20, name, (('subaccount', 0),)
                               if name == 'settlements' else (), True)
        receipt = await self.account.reconcile_accounting(Reads(),
            proposed_boundary=NOW-timedelta(hours=1), continuity=self.continuity, now=lambda: NOW)
        self.assertTrue(receipt.checkpoint_created)
        self.assertIn('settlement_reconciliation_required', receipt.status.holds)

    async def test_coordinator_disconnect_does_not_discard_positive_settlement(self):
        account = self.account
        class Reads:
            async def read(inner, name, **kwargs):
                account.disconnect()
                return ReadResult(balance(), 20)
            async def collect(inner, name, **kwargs):
                return PageSet((settlement(),) if name == 'settlements' else (), 1, 20,
                    name, (('subaccount', 0),) if name == 'settlements' else (), True)
        result = await account.reconcile_accounting(Reads(),
            proposed_boundary=NOW-timedelta(hours=1), continuity=self.continuity, now=lambda: NOW)
        self.assertFalse(result.checkpoint_created)
        self.assertIn('settlement_reconciliation_required', result.status.holds)
        self.assertIn('opening_source_stale', result.status.holds)

    async def test_coordinator_source_failure_stays_blocked(self):
        class Reads:
            async def read(inner, *args, **kwargs):
                raise InvalidData('synthetic unavailable source')
            async def collect(inner, name, **kwargs):
                return PageSet((), 1, 20, name, (), True)
        with self.assertRaises(InvalidData):
            await self.account.reconcile_accounting(Reads(), proposed_boundary=NOW,
                continuity=self.continuity, now=lambda: NOW)
        self.assertIn('accounting_source_failed', (await self.writer.accounting_status()).holds)


class AccountingTransactionTests(unittest.TestCase):
    def test_corrupt_journal_is_rejected_at_startup(self):
        with TemporaryDirectory() as directory:
            path = Path(directory)/'corrupt.db'
            ledger = Ledger(path)
            with ledger.transaction():
                accounting.record_failure(ledger, 'synthetic')
                accounting._append(ledger, 'review', 'key', '{"value":1}', NOW)
                ledger.connection.execute('UPDATE accounting_events SET payload=?', ('{"value":2}',))
            ledger.close()
            with self.assertRaisesRegex(InvalidData, 'digest'):
                Ledger(path)

    def test_existing_schema_three_is_refused_before_sidecars(self):
        with TemporaryDirectory() as directory:
            path = Path(directory)/'old.db'
            with closing(sqlite3.connect(path)) as conn:
                conn.execute('CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT)')
                conn.execute("INSERT INTO meta VALUES ('schema','3')")
                conn.commit()
            original = path.read_bytes()
            with self.assertRaisesRegex(InvalidData, 'migration'):
                Ledger(path)
            self.assertEqual(path.read_bytes(), original)
            self.assertFalse(Path(str(path)+'-wal').exists())

    def test_entry_send_rechecks_durable_restrictions_in_transaction(self):
        ledger = Ledger(':memory:')
        try:
            view = portfolio_view(ledger, subaccount=0, epoch='writer', revision=0,
                                  now=NOW, capacity=128)
            result = reserve_entry(ledger, request=request(), attempt_id='a', view=view,
                epoch='writer', revision=0, post_revision=1, config=BotConfig(), now=NOW,
                free_cash=D(500), account_known=True, offline_fixture=True, capacity=128)
            with ledger.transaction():
                accounting.record_failure(ledger, 'synthetic_source_failure')
                denied = begin_send(ledger, result.receipt, writer_epoch='writer',
                                    writer_revision=1, post_revision=2)
            self.assertFalse(denied.dispatch_allowed)
            self.assertIn('accounting_source_failed', denied.blockers)
            self.assertEqual(ledger.connection.execute('SELECT phase FROM mutation_attempts').fetchone()[0], 'PREPARED')
        finally:
            ledger.close()

    def test_outer_rollback_removes_evidence_and_restriction_together(self):
        ledger = Ledger(':memory:')
        try:
            with self.assertRaises(RuntimeError):
                with ledger.transaction():
                    accounting.record_failure(ledger, 'synthetic')
                    accounting._append(ledger, 'review', 'key', '{}', NOW)
                    raise RuntimeError('crash before commit')
            status = accounting.inspect(ledger)
            self.assertEqual((status.event_count, status.holds), (0, ()))
            accounting.validate_accounting(ledger)
        finally:
            ledger.close()


if __name__ == '__main__':
    unittest.main()
