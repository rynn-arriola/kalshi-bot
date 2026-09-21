"""D-062 opening-account/cash evidence tests; injected documents only."""
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import patch

import kalshi_bot.opening_account as opening
from kalshi_bot.account import AccountCoordinator, normalize_snapshot
from kalshi_bot.continuity import ContinuityAssessment
from kalshi_bot.opening_account import (build_opening_evidence, parse_cash,
                                        parse_settlements, parse_funding,
                                        parse_intra_exchange_transfers,
                                        assess_opening_accounting)
from kalshi_bot.rest import PageSet, ReadResult, request_path
from kalshi_bot.values import InvalidData
from kalshi_bot.writer import LedgerWriter


NOW = datetime(2026, 9, 21, 12, tzinfo=timezone.utc)


def balance():
    return dict(balance=50000, balance_dollars='500', portfolio_value=50125, updated_ts=1,
                balance_breakdown=[dict(exchange_index=0, balance='300'),
                                   dict(exchange_index=1, balance='200')])


def settlement(**changes):
    row = dict(ticker='A', exchange_index=0, event_ticker='E', market_result='yes',
        yes_count_fp='10.00', yes_total_cost_dollars='4.0000', no_count_fp='0.00',
        no_total_cost_dollars='0.0000', revenue=1000,
        settled_time='2026-09-21T11:00:00Z', fee_cost='0.0100', value=100)
    row.update(changes)
    return row


def continuity(writer, revision):
    return ContinuityAssessment(0, 1, writer.epoch, revision, (), (), None,
        'unobserved', False, False, ('venue_history_stream_handoff_unproven',))


class OpeningEvidenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        self.writer = await LedgerWriter(Path(self.temp.name)/'opening.db').start()
        self.account = AccountCoordinator(self.writer, subaccount=0)
        self.account.connect_generation()
        token = self.account.begin_reconciliation(NOW)
        snapshot = normalize_snapshot([], [], dict(balance_dollars='500', updated_ts=1),
                                      subaccount=0)
        self.report = await self.account.finish_reconciliation(token, snapshot, NOW)
        self.continuity = continuity(self.writer, self.writer.revision)

    async def asyncTearDown(self):
        await self.writer.close()
        self.temp.cleanup()

    def pages(self, rows=(), source='settlements'):
        query = (('subaccount', 0),) if source == 'settlements' else ()
        return PageSet(tuple(rows), 1, 20, source, query, True)

    def arguments(self, **changes):
        values = dict(report=self.report, continuity=self.continuity,
            proposed_boundary=NOW-timedelta(hours=1), subaccount=0,
            writer_epoch=self.writer.epoch, writer_revision=self.writer.revision,
            cash_document=balance(), settlements=self.pages(source='settlements'),
            subaccount_transfers=self.pages(source='subaccount_transfers'),
            intra_exchange_transfers=self.pages(source='intra_exchange_transfers'),
            deposits=self.pages(source='deposits'),
            withdrawals=self.pages(source='withdrawals'))
        return values | changes

    def build(self, **changes):
        return build_opening_evidence(**self.arguments(**changes))

    async def test_batched_matches_synchronous_and_preserves_raw_source_counts(self):
        rows = tuple(settlement(ticker=f'A{i}') for i in range(512))
        args = self.arguments(settlements=self.pages(rows+(rows[0],)))
        result = await opening.build_opening_evidence_async(**args)
        self.assertEqual(result, build_opening_evidence(**args))
        self.assertEqual(len(result.settlements), 512)
        self.assertEqual(result.sources[0].rows, 513)

    async def test_batched_rejects_conflicting_duplicates_across_chunk_boundary(self):
        rows = tuple(settlement(ticker=f'A{i}') for i in range(512))
        args = self.arguments(settlements=self.pages(rows+(rows[0] | dict(revenue=999),)))
        with self.assertRaisesRegex(InvalidData, 'conflicting duplicate settlement'):
            await opening.build_opening_evidence_async(**args)

    async def test_flat_complete_sources_remain_non_authorizing(self):
        evidence = self.build()
        self.assertEqual((str(evidence.cash.available), str(evidence.cash.portfolio_value)),
                         ('500', '501.25'))
        self.assertFalse(evidence.approved)
        self.assertFalse(evidence.ready_for_entry)
        for blocker in ('venue_history_stream_handoff_unproven',
                        'cash_snapshot_not_atomic',
                        'operator_boundary_not_approved',
                        'primary_account_flat_start_not_verified',
                        'opening_basis_not_installed'):
            self.assertIn(blocker, evidence.blockers)
        self.assertNotIn('account_exclusivity_not_approved', evidence.blockers)

    async def test_accounting_assessment_is_local_only_even_when_flat(self):
        assessment = assess_opening_accounting(self.build(), self.report)
        self.assertTrue(assessment.local_flat_candidate)
        self.assertTrue(assessment.cash_snapshot_agrees)
        self.assertEqual((assessment.settlement_rows, assessment.cash_activity_rows), (0, 0))
        self.assertFalse(assessment.observed_settlement_reconciliation_required)
        self.assertFalse(assessment.approved or assessment.ready_for_entry)
        self.assertIn('venue_history_stream_handoff_unproven', assessment.blockers)
        self.assertIn('operator_boundary_not_approved', assessment.blockers)

    async def test_accounting_assessment_rejects_inventory_orders_and_wrong_scope(self):
        position = dict(ticker='A', exchange_index=0, position_fp='1',
                        market_exposure_dollars='0')
        order = dict(order_id='resting', client_order_id='client', ticker='A',
                     exchange_index=0, book_side='bid', yes_price_dollars='0.4',
                     remaining_count_fp='10', status='resting')
        for orders, positions in (([], [position]), ([order], [])):
            snapshot = normalize_snapshot(orders, positions,
                dict(balance_dollars='500', updated_ts=1), subaccount=0)
            report = replace(self.report, snapshot=snapshot)
            self.assertFalse(assess_opening_accounting(
                self.build(report=report), report).local_flat_candidate)
        report = replace(self.report, snapshot=replace(self.report.snapshot, subaccount=1))
        scoped = replace(self.continuity, subaccount=1)
        pages = replace(self.pages(), query=(('subaccount', 1),))
        evidence = self.build(subaccount=1, report=report, continuity=scoped,
                              settlements=pages)
        self.assertFalse(assess_opening_accounting(evidence, report).local_flat_candidate)

    async def test_accounting_assessment_retains_cash_and_settlement_uncertainty(self):
        changed_cash = balance() | dict(balance_dollars='499', balance=49900,
            balance_breakdown=[dict(exchange_index=0, balance='299'),
                               dict(exchange_index=1, balance='200')])
        evidence = self.build(cash_document=changed_cash,
            settlements=self.pages((settlement(),), 'settlements'))
        result = assess_opening_accounting(evidence, self.report)
        self.assertFalse(result.cash_snapshot_agrees)
        self.assertEqual(result.settlement_rows, 1)
        self.assertTrue(result.observed_settlement_reconciliation_required)
        self.assertIn('cash_changed_since_account_snapshot', result.blockers)
        self.assertIn('settlement_history_requires_ledger_contract', result.blockers)
        self.assertIn('observed_settlement_requires_reconciliation', result.blockers)
        self.assertFalse(result.ready_for_entry)

    async def test_old_settlement_is_historical_not_new_settlement_pause(self):
        old = settlement(settled_time='2026-09-21T10:00:00Z')
        result = assess_opening_accounting(self.build(
            settlements=self.pages((old,), 'settlements')), self.report)
        self.assertEqual(result.settlement_rows, 0)
        self.assertFalse(result.observed_settlement_reconciliation_required)
        self.assertFalse(result.ready_for_entry)
        self.assertIn('operator_boundary_not_approved', result.blockers)

    async def test_settlement_does_not_change_six_hour_matched_fill_meter(self):
        evidence = self.build(settlements=self.pages((settlement(),), 'settlements'))
        before = await self.writer.observe(NOW)
        result = assess_opening_accounting(evidence, self.report)
        after = await self.writer.observe(NOW)
        self.assertTrue(result.observed_settlement_reconciliation_required)
        self.assertEqual(after.realized_pnl, before.realized_pnl)
        self.assertEqual(after.cap, before.cap)

    async def test_accounting_assessment_requires_same_audit_and_revision(self):
        evidence = self.build()
        with self.assertRaisesRegex(InvalidData, 'revision or scope'):
            assess_opening_accounting(evidence, replace(self.report,
                audit=replace(self.report.audit, writer_revision=self.writer.revision+1)))
        with self.assertRaisesRegex(InvalidData, 'report and audit disagree'):
            assess_opening_accounting(evidence, replace(self.report,
                unresolved_intents=self.report.unresolved_intents+1))
        pending_audit = replace(self.report.audit, pending_fills=1,
                                blockers=('pending_fills',))
        pending = replace(self.report, audit=pending_audit)
        self.assertFalse(assess_opening_accounting(evidence, pending).local_flat_candidate)

    async def test_nonprimary_scope_cannot_be_opening_policy_candidate(self):
        snapshot = replace(self.report.snapshot, subaccount=1)
        report = replace(self.report, snapshot=snapshot)
        assessment = replace(self.continuity, subaccount=1)
        pages = self.pages(source='settlements')
        pages = replace(pages, query=(('subaccount', 1),))
        result = self.build(subaccount=1, report=report, continuity=assessment,
                            settlements=pages)
        self.assertIn('primary_account_required', result.blockers)
        self.assertFalse(result.approved or result.ready_for_entry)

    async def test_flat_rule_checks_nonzero_quantity_and_resting_orders(self):
        row = dict(ticker='A', exchange_index=0, position_fp='0',
                   market_exposure_dollars='0')
        zero = normalize_snapshot([], [row], dict(balance_dollars='500',
            updated_ts=1), subaccount=0)
        result = self.build(report=replace(self.report, snapshot=zero))
        self.assertNotIn('opening_inventory_present', result.blockers)
        nonzero = normalize_snapshot([], [row | dict(position_fp='1')],
            dict(balance_dollars='500', updated_ts=1), subaccount=0)
        result = self.build(report=replace(self.report, snapshot=nonzero))
        self.assertIn('opening_inventory_present', result.blockers)
        order = dict(order_id='resting', client_order_id='client', ticker='A',
                     exchange_index=0, book_side='bid', yes_price_dollars='0.4',
                     remaining_count_fp='10', status='resting')
        working = normalize_snapshot([order], [], dict(balance_dollars='500',
            updated_ts=1), subaccount=0)
        result = self.build(report=replace(self.report, snapshot=working))
        self.assertIn('opening_resting_orders_present', result.blockers)
        self.assertFalse(result.approved or result.ready_for_entry)

    async def test_settlement_and_cash_activity_are_retained_and_block(self):
        transfer = dict(transfer_id='transfer', from_subaccount=0, to_subaccount=1,
                        amount_cents=100, created_ts=int(NOW.timestamp()), exchange_index=0)
        deposit = dict(id='deposit', status='applied', type='ach', amount_cents=500,
                       fee_cents=0, created_ts=int(NOW.timestamp()),
                       finalized_ts=int(NOW.timestamp()))
        evidence = self.build(settlements=self.pages((settlement(),), 'settlements'),
            subaccount_transfers=self.pages((transfer,), 'subaccount_transfers'),
            deposits=self.pages((deposit,), 'deposits'))
        self.assertEqual((len(evidence.settlements), len(evidence.subaccount_transfers),
                          len(evidence.funding)), (1, 1, 1))
        self.assertIn('settlement_history_requires_ledger_contract', evidence.blockers)
        self.assertIn('cash_activity_requires_operator_attribution', evidence.blockers)

    async def test_conflicting_duplicates_and_scope_revision_fail_closed(self):
        rows = (settlement(), settlement(revenue=999))
        with self.assertRaisesRegex(InvalidData, 'conflicting duplicate settlement'):
            self.build(settlements=self.pages(rows, 'settlements'))
        changed = replace(self.continuity, writer_revision=self.writer.revision+1)
        with self.assertRaisesRegex(InvalidData, 'source revision'):
            self.build(continuity=changed)

    async def test_strict_cash_and_settlement_documents(self):
        self.assertEqual(len(parse_cash(balance(), subaccount=0).exchange_balances), 2)
        with self.assertRaises(InvalidData):
            parse_cash(balance() | {'portfolio_value': -1}, subaccount=0)
        with self.assertRaises(InvalidData):
            parse_settlements((settlement(market_result='unknown'),),
                              boundary=NOW-timedelta(hours=1))

    async def test_optional_settlement_value_and_invalid_payout(self):
        row = settlement()
        del row['value']
        for item in (row, settlement(value=None)):
            self.assertIsNone(parse_settlements((item,), boundary=NOW-timedelta(hours=1))[0].value_cents)
        for item in (settlement(value=101), settlement(revenue=-1)):
            with self.assertRaises(InvalidData):
                parse_settlements((item,), boundary=NOW-timedelta(hours=1))

    async def test_subcent_cash_is_preserved_with_unverified_legacy_rounding(self):
        document = balance() | dict(balance_dollars='500.0068', balance_breakdown=[])
        evidence = self.build(cash_document=document)
        self.assertEqual(str(evidence.cash.available), '500.0068')
        self.assertEqual(evidence.cash.legacy_balance_cents, 50000)
        self.assertIn('legacy_balance_precision_unverified', evidence.blockers)
        with self.assertRaises(InvalidData):
            parse_cash(balance() | dict(balance=49900), subaccount=0)
        with self.assertRaises(InvalidData):
            parse_cash(balance() | dict(balance_breakdown=[dict(exchange_index=0, balance='499')]), subaccount=0)

    async def test_wrong_source_incomplete_and_filtered_pages_are_rejected(self):
        for bad in (PageSet((), 1, 20), self.pages(source='withdrawals'),
                    replace(self.pages(source='deposits'), exhausted=False),
                    replace(self.pages(source='deposits'), query=(('cursor', 'later'),))):
            with self.assertRaises(InvalidData):
                self.build(deposits=bad)
        for query in ((('subaccount', 1),),
                      (('subaccount', 0), ('min_ts', int(NOW.timestamp()))),
                      (('subaccount', 0), ('ticker', 'A'))):
            with self.assertRaises(InvalidData):
                self.build(settlements=replace(self.pages(), query=query))

    async def test_member_funding_never_becomes_primary_account_attribution(self):
        deposit = dict(id='deposit', status='applied', type='ach', amount_cents=500,
                       fee_cents=0, created_ts=int(NOW.timestamp()))
        evidence = self.build(deposits=self.pages((deposit,), 'deposits'))
        self.assertIn('member_funding_not_subaccount_scoped', evidence.blockers)
        with self.assertRaises(InvalidData):
            parse_funding((deposit | dict(status='completed'),), kind='deposit', boundary=NOW)

    async def test_preboundary_pending_and_unknown_completion_records_are_retained(self):
        old = int((NOW-timedelta(days=1)).timestamp())
        for kind in ('deposit', 'withdrawal'):
            for status in ('pending', 'applied', 'failed', 'returned'):
                row = dict(id='old', status=status, type='ach', amount_cents=100,
                           fee_cents=0, created_ts=old)
                for document in (row, row | dict(finalized_ts=None)):
                    with self.subTest(kind=kind, status=status):
                        self.assertEqual(len(parse_funding((document,), kind=kind,
                            boundary=NOW, observed_at=NOW)), 1)
            finalized_before = row | dict(finalized_ts=old+10)
            self.assertEqual(parse_funding((finalized_before,), kind=kind,
                                          boundary=NOW, observed_at=NOW), ())
        for status in ('pending', 'complete'):
            row = dict(transfer_id='old', source='event_contract', destination='margined',
                source_exchange_shard=0, destination_exchange_shard=1, amount='1',
                status=status, created_ts=old)
            self.assertEqual(len(parse_intra_exchange_transfers((row,), boundary=NOW,
                                                               observed_at=NOW)), 1)
            evidence = self.build(intra_exchange_transfers=self.pages((row,), 'intra_exchange_transfers'))
            self.assertIn('intra_exchange_transfer_completion_time_unproven', evidence.blockers)

    async def test_snapshot_and_inspection_timestamps_are_distinct(self):
        observed = NOW+timedelta(seconds=1)
        evidence = self.build(observed_at=observed)
        self.assertEqual(evidence.snapshot_observed_at, NOW)
        self.assertEqual(evidence.observed_at, observed)
        with self.assertRaises(InvalidData):
            self.build(cash_document=balance() | dict(updated_ts=int(observed.timestamp())+1),
                       observed_at=observed)

    async def test_inspection_joins_sibling_reads_before_reporting_failure(self):
        completed = []
        class Reads:
            async def read(inner, name, **_):
                raise InvalidData('synthetic source failure')
            async def collect(inner, name, **_):
                await asyncio.sleep(0)
                completed.append(name)
                return PageSet((), 1, 20, name, (), True)
        with self.assertRaisesRegex(InvalidData, 'synthetic source failure'):
            await self.account.inspect_opening_account(Reads(), proposed_boundary=NOW,
                continuity=self.continuity, now=lambda: NOW)
        self.assertEqual(len(completed), 5)

    async def test_historical_fills_and_cash_sources_are_get_only_allowlisted(self):
        self.assertIn('subaccount=3', request_path('historical_fills',
            dict(subaccount=3), 'history')[1])
        for name in ('settlements', 'subaccount_transfers',
                     'intra_exchange_transfers', 'deposits', 'withdrawals'):
            spec, path = request_path(name, {}, 'cash')
            self.assertTrue(spec.authenticated)
            self.assertTrue(path.startswith('/portfolio/'))
        with self.assertRaises(InvalidData):
            request_path('settlements', {}, 'metadata')

    async def test_account_revision_change_during_reads_discards_result(self):
        account, writer = self.account, self.writer
        class Reads:
            changed = False
            async def read(inner, name, **_):
                return ReadResult(balance(), 20)
            async def collect(inner, name, **_):
                if not inner.changed:
                    inner.changed = True
                    await writer.observe(NOW)
                return PageSet((), 1, 20, name, (), True)
        result = await account.inspect_opening_account(Reads(),
            proposed_boundary=NOW-timedelta(hours=1),
            continuity=self.continuity, now=lambda: NOW)
        self.assertIsNone(result)

    async def test_normalization_race_discards_evidence_and_cancellation_retains_slot(self):
        entered, release = Event(), Event()
        original = opening._assemble_opening_evidence
        class Reads:
            async def read(inner, name, **_):
                return ReadResult(balance(), 20)
            async def collect(inner, name, **kwargs):
                return PageSet((), 1, 20, name, tuple(sorted(
                    (key, value) for key, value in kwargs.items()
                    if key not in {'reason', 'max_rows', 'max_pages', 'byte_limit'})), True)
        def delayed(*args):
            entered.set()
            if not release.wait(5):
                raise RuntimeError('test release timeout')
            return original(*args)
        with patch('kalshi_bot.opening_account._assemble_opening_evidence', delayed):
            caller = asyncio.create_task(self.account.inspect_opening_account(Reads(),
                proposed_boundary=NOW, continuity=self.continuity, now=lambda: NOW))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 3))
                owner = self.account._opening_task
                caller.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await caller
                with self.assertRaisesRegex(InvalidData, 'already active'):
                    await self.account.inspect_opening_account(Reads(),
                        proposed_boundary=NOW, continuity=self.continuity, now=lambda: NOW)
                await self.writer.observe(NOW)
            finally:
                release.set()
                await asyncio.gather(caller, return_exceptions=True)
                if self.account._opening_task is not None:
                    result = await self.account._opening_task
            self.assertIsNone(result)
            self.assertTrue(owner.done())
        await asyncio.sleep(0)
        self.assertIsNone(self.account._opening_task)

    async def test_account_inspection_returns_evidence_without_authority(self):
        calls = []
        class Reads:
            async def read(inner, name, **kwargs):
                calls.append((name, kwargs))
                return ReadResult(balance(), 20)
            async def collect(inner, name, **kwargs):
                calls.append((name, kwargs))
                return PageSet((), 1, 20, name, tuple(sorted(
                    (key, value) for key, value in kwargs.items()
                    if key not in {'reason', 'max_rows', 'max_pages', 'byte_limit'})), True)
        result = await self.account.inspect_opening_account(Reads(),
            proposed_boundary=NOW-timedelta(hours=1), continuity=self.continuity,
            now=lambda: NOW)
        self.assertIsNotNone(result)
        self.assertFalse(result.ready_for_entry)
        self.assertEqual({name for name, _ in calls}, {'balance', 'settlements',
            'subaccount_transfers', 'intra_exchange_transfers', 'deposits',
            'withdrawals'})
        settlement_args = next(args for name, args in calls if name == 'settlements')
        self.assertEqual(settlement_args['min_ts'],
                         int((NOW-timedelta(hours=1)).timestamp())-1)


if __name__ == '__main__':
    unittest.main()
