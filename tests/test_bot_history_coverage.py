"""D-035 uses disposable ledgers and injected reads only."""
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import sqlite3
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import patch
import zlib

from kalshi_bot.account import AccountCoordinator
from kalshi_bot.history_coverage import complete_enumeration, enumeration_coverage
from kalshi_bot.ledger import Fill, Ledger
from kalshi_bot.orders import timestamp_us
from kalshi_bot.recovery import HistoricalFill, HistoryEvidence, stage_history
from kalshi_bot.runtime import RecoveryRuntime
from kalshi_bot.values import InvalidData
from kalshi_bot.writer import LedgerWriter
from test_bot_recovery_runtime import AccountReads

NOW = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)


def us(value):
    return timestamp_us(value.isoformat())


def evidence(start=0, end=10, *, rows=0, scope=0):
    base = NOW-timedelta(hours=1)
    left, right = us(base+timedelta(seconds=start)), us(base+timedelta(seconds=end))
    records = tuple(HistoricalFill(Fill(f'f{i}', f'o{i}', f'M{i%30}', 'bid', '1', '.5', '.01'),
                                   left, scope, i%2) for i in range(rows))
    return HistoryEvidence(left, right, left+1, scope, records, 1, 0)


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.db = Ledger(':memory:')

    def tearDown(self):
        self.db.close()

    def complete(self, ev=None, key='r1', **changes):
        ev = ev or evidence()
        stage_history(self.db, ev, NOW)
        return complete_enumeration(self.db, ev, **(dict(receipt_id=key, writer_epoch='epoch',
            read_started_at=NOW, observed_at=NOW, generation=1, source_revision=0) | changes))

    def inspect(self, start=0, end=10, scope=0):
        ev = evidence(start, end, scope=scope)
        return enumeration_coverage(self.db, subaccount=scope, start_us=ev.start_us, end_us=ev.end_us)

    def test_no_receipts_entire_interval_is_gap(self):
        result = self.inspect()
        self.assertEqual(result.gaps, ((result.start_us, result.end_us),))
        self.assertIn('history_enumeration_gaps', result.blockers)
        self.assertFalse(result.ready_for_entry)

    def test_empty_completed_enumeration_has_receipt_not_complete_proof(self):
        receipt = self.complete()
        result = self.inspect()
        self.assertEqual((receipt.row_count, receipt.omitted_rows, result.gaps), (0, 0, ()))
        self.assertIn('history_enumeration_not_atomic_proof', result.blockers)
        self.assertIn('launch_boundary_not_established', result.blockers)
        self.assertFalse(result.ready_for_entry)

    def test_unstaged_row_cannot_complete(self):
        with self.assertRaises(InvalidData):
            complete_enumeration(self.db, evidence(rows=1), receipt_id='r', writer_epoch='e',
                                 read_started_at=NOW, observed_at=NOW)
        self.assertEqual(self.inspect().receipt_ids, ())

    def test_conflicting_staged_economics_cannot_complete(self):
        ev = evidence(rows=1)
        stage_history(self.db, ev, NOW)
        bad = replace(ev, records=(replace(ev.records[0], fill=replace(ev.records[0].fill, fee='1')),))
        with self.assertRaises(InvalidData):
            complete_enumeration(self.db, bad, receipt_id='r', writer_epoch='e',
                                 read_started_at=NOW, observed_at=NOW)
        self.assertEqual(self.inspect().receipt_ids, ())

    def test_idempotent_receipt_and_immutable_conflict(self):
        first = self.complete()
        self.assertEqual(self.complete(), first)
        with self.assertRaises(InvalidData):
            self.complete(observed_at=NOW+timedelta(seconds=1))
        self.assertEqual(self.inspect().receipt_ids, ('r1',))

    def test_digest_stable_when_return_order_changes(self):
        ev = evidence(rows=3)
        first = self.complete(ev)
        second = self.complete(replace(ev, records=tuple(reversed(ev.records))), key='r2')
        self.assertEqual(first.digest, second.digest)
        self.assertEqual(first.row_count, 3)

    def test_digest_tracks_timestamp_shard_and_economics(self):
        first = self.complete(evidence(rows=1)).digest
        # Separate ledgers: conflicting immutable history is never rewritten.
        for change in ('time', 'shard', 'fee'):
            ev = evidence(rows=1)
            row = ev.records[0]
            row = (replace(row, executed_us=row.executed_us+1) if change == 'time' else
                   replace(row, exchange_index=8) if change == 'shard' else
                   replace(row, fill=replace(row.fill, fee='2')))
            db = Ledger(':memory:')
            try:
                altered = replace(ev, records=(row,))
                stage_history(db, altered, NOW)
                receipt = complete_enumeration(db, altered, receipt_id='r', writer_epoch='e',
                    read_started_at=NOW, observed_at=NOW)
                self.assertNotEqual(receipt.digest, first)
            finally:
                db.close()

    def test_union_handles_overlap_adjacency_and_internal_gap(self):
        for i, (start, end) in enumerate(((0, 2), (2, 4), (1, 3), (6, 10))):
            self.complete(evidence(start, end), key=str(i))
        result = self.inspect(-1, 12)
        base = evidence().start_us
        self.assertEqual(result.intervals, ((base, base+4000000), (base+6000000, base+10000000)))
        self.assertEqual(result.gaps, ((base-1000000, base), (base+4000000, base+6000000),
                                       (base+10000000, base+12000000)))

    def test_scope_isolation(self):
        self.complete(evidence(scope=1))
        self.assertTrue(self.inspect().gaps)
        self.assertEqual(self.inspect(scope=1).gaps, ())

    def test_half_open_adjacent_outside_query_is_not_included(self):
        self.complete(evidence(10, 20))
        self.assertEqual(self.inspect().receipt_ids, ())

    def test_future_query_credit_stops_at_read_start_not_completion(self):
        ev = evidence(0, 10)
        started = datetime.fromtimestamp((ev.start_us+3000000)/1000000, timezone.utc)
        receipt = self.complete(ev, read_started_at=started, observed_at=NOW)
        self.assertEqual(receipt.eligible_end_us, ev.start_us+3000000)
        self.assertEqual(self.inspect().gaps, ((ev.start_us+3000000, ev.end_us),))

    def test_entire_future_interval_gets_no_credit(self):
        ev = evidence(0, 10)
        started = datetime.fromtimestamp((ev.start_us-1)/1000000, timezone.utc)
        self.complete(ev, read_started_at=started)
        self.assertEqual(self.inspect().intervals, ())

    def test_omitted_remembered_fill_is_not_silently_forgotten(self):
        self.complete(evidence(rows=1))
        later = self.complete(key='r2')
        self.assertEqual(later.omitted_rows, 1)
        result = self.inspect()
        self.assertEqual(result.omission_receipts, 1)
        self.assertIn('previously_observed_fills_omitted', result.blockers)
        self.assertEqual(self.db.connection.execute('SELECT COUNT(*) FROM recovery_fills').fetchone()[0], 1)

    def test_partial_prior_evidence_omission_does_not_cover_interval(self):
        stage_history(self.db, evidence(rows=1), NOW)
        self.complete()
        self.assertEqual(self.inspect().intervals, ())

    def test_capacity_archives_exact_old_receipt_and_keeps_new_hot(self):
        with patch('kalshi_bot.history_coverage.MAX_RECEIPTS', 1):
            self.complete()
            self.complete(key='r2')
            result = self.inspect()
            self.assertEqual(result.receipt_ids, ('r2',))
            self.assertEqual((result.archived_receipts, result.archive_count), (1, 1))
            self.assertIn('history_receipts_archived', result.blockers)
            archive = self.db.connection.execute(
                'SELECT receipt_count,scope_summary,payload FROM history_enumeration_archives').fetchone()
            summary = json.loads(archive['scope_summary'])
            self.assertEqual(archive['receipt_count'], 1)
            self.assertEqual(summary['0']['count'], 1)
            exact = json.loads(zlib.decompress(archive['payload']))
            self.assertEqual(exact['version'], 1)
            self.assertEqual(exact['receipts'][0][0], 'r1')

    def test_archive_insert_failure_rolls_back_without_losing_hot_receipt(self):
        with patch('kalshi_bot.history_coverage.MAX_RECEIPTS', 1):
            self.complete()
            self.db.connection.execute(
                "CREATE TRIGGER reject_archive BEFORE INSERT ON history_enumeration_archives "
                "BEGIN SELECT RAISE(ABORT, 'injected'); END")
            with self.assertRaises(sqlite3.IntegrityError):
                self.complete(key='r2')
            self.assertEqual(self.inspect().receipt_ids, ('r1',))
            self.assertEqual(self.db.connection.execute(
                'SELECT COUNT(*) FROM history_enumeration_archives').fetchone()[0], 0)

    def test_archive_scope_summary_does_not_block_other_subaccount(self):
        with patch('kalshi_bot.history_coverage.MAX_RECEIPTS', 1):
            self.complete(evidence(scope=1))
            self.complete(key='r2')
            self.assertEqual(self.inspect().archived_receipts, 0)
            self.assertEqual(self.inspect(scope=1).archived_receipts, 1)
            self.assertEqual(self.inspect(10,20,scope=1).archived_receipts, 0)

    def test_archive_capacity_fails_before_deleting_hot_receipt(self):
        with (patch('kalshi_bot.history_coverage.MAX_RECEIPTS', 1),
              patch('kalshi_bot.history_coverage.MAX_ARCHIVES', 0)):
            self.complete()
            with self.assertRaises(InvalidData):
                self.complete(key='r2')
            self.assertEqual(self.inspect().receipt_ids, ('r1',))

    def test_existing_schema_five_ledger_adds_archive_table(self):
        with TemporaryDirectory() as folder:
            path = Path(folder)/'existing.db'
            ledger = Ledger(path)
            ledger.connection.execute('DROP TABLE history_enumeration_archives')
            ledger.connection.commit()
            ledger.close()
            reopened = Ledger(path)
            try:
                tables = {row[0] for row in reopened.connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}
                self.assertIn('history_enumeration_archives', tables)
            finally:
                reopened.close()

    def test_invalid_metadata_rolls_back(self):
        for changes in ({'observed_at': NOW-timedelta(seconds=1)}, {'generation': None},
                        {'source_revision': -1}, {'writer_epoch': ''}):
            with self.subTest(changes=changes), self.assertRaises(InvalidData):
                self.complete(**changes)
            self.assertEqual(self.inspect().receipt_ids, ())

    def test_index_payload_conflict_blocks_inspection(self):
        self.complete()
        with self.db.transaction():
            self.db.connection.execute('UPDATE history_enumerations SET eligible_end_us=0')
        with self.assertRaises(InvalidData):
            self.inspect()

    def test_evidence_completion_never_changes_accounting_or_risk(self):
        self.complete(evidence(rows=4))
        for table in ('fills', 'lots', 'risk_windows', 'intents', 'realized_events'):
            self.assertEqual(self.db.connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0], 0)

    def test_receipt_insert_failure_retains_rows_but_not_completion(self):
        self.db.connection.execute("CREATE TRIGGER reject_receipt BEFORE INSERT ON history_enumerations "
                                   "BEGIN SELECT RAISE(ABORT, 'injected'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.complete(evidence(rows=1))
        self.assertEqual(self.inspect().receipt_ids, ())
        self.assertEqual(self.db.connection.execute('SELECT COUNT(*) FROM recovery_fills').fetchone()[0], 1)


class WriterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name)/'ledger.db'
        self.writer = await LedgerWriter(self.path).start()

    async def asyncTearDown(self):
        await self.writer.close()
        self.temp.cleanup()

    async def inspect(self):
        return await self.writer.history_coverage(subaccount=0,
            start=NOW-timedelta(hours=1), end=NOW-timedelta(hours=1)+timedelta(seconds=10))

    async def test_receipt_survives_restart_without_importing_rows(self):
        result = await self.writer.audit_history(evidence(rows=2), NOW, generation=1, source_revision=3)
        epoch = self.writer.epoch
        await self.writer.close()
        self.writer = await LedgerWriter(self.path).start()
        self.assertNotEqual(self.writer.epoch, epoch)
        coverage = await self.inspect()
        self.assertEqual(coverage.receipt_ids, (result.enumeration.receipt_id,))
        self.assertFalse(coverage.ready_for_entry)
        self.assertEqual((await self.writer.inventory()).positions, ())

    async def test_read_only_inspection_does_not_revoke_writer_revision(self):
        await self.writer.audit_history(evidence(), NOW)
        revision = self.writer.revision
        await self.inspect()
        self.assertEqual(self.writer.revision, revision)

    async def test_cancellation_between_chunks_never_completes(self):
        entered, release = Event(), Event()
        original = self.writer._execute
        def paused(db, command, args):
            result = original(db, command, args)
            if command == 'history':
                entered.set()
                release.wait(3)
            return result
        with patch.object(self.writer, '_execute', side_effect=paused):
            task = asyncio.create_task(self.writer.audit_history(evidence(rows=300), NOW))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 2))
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            finally:
                release.set()
        self.assertEqual((await self.inspect()).receipt_ids, ())
        self.assertFalse(self.writer.failed)
        # Existing positive rows are retained; the next complete pass is safe.
        await self.writer.audit_history(evidence(rows=300), NOW)
        self.assertEqual(len((await self.inspect()).receipt_ids), 1)

    async def test_cancellation_after_final_submit_retains_valid_receipt(self):
        entered, release = Event(), Event()
        original = self.writer._execute
        def paused(db, command, args):
            if command == 'history_complete':
                entered.set()
                release.wait(3)
            return original(db, command, args)
        with patch.object(self.writer, '_execute', side_effect=paused):
            task = asyncio.create_task(self.writer.audit_history(evidence(rows=2), NOW))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 2))
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            finally:
                release.set()
        self.assertEqual(len((await self.inspect()).receipt_ids), 1)

    async def test_failed_second_chunk_leaves_no_receipt(self):
        original = self.writer._execute
        calls = 0
        def fail(db, command, args):
            nonlocal calls
            if command == 'history':
                calls += 1
                if calls == 2:
                    raise OSError('injected disk failure')
            return original(db, command, args)
        with patch.object(self.writer, '_execute', side_effect=fail):
            with self.assertRaises(InvalidData):
                await self.writer.audit_history(evidence(rows=300), NOW)
        self.assertTrue(self.writer.failed)
        await self.writer.close()
        self.writer = await LedgerWriter(self.path).start()
        self.assertEqual((await self.inspect()).receipt_ids, ())

    async def test_current_generation_required_for_recovery_report(self):
        owner = AccountCoordinator(self.writer, subaccount=0)
        owner.connect_generation()
        original = self.writer.audit_history
        async def disconnect(*args, **kwargs):
            result = await original(*args, **kwargs)
            owner.disconnect()
            return result
        with patch.object(self.writer, 'audit_history', side_effect=disconnect):
            result = await owner.recover_history(AccountReads(), start=NOW-timedelta(hours=1),
                                                 end=NOW, now=lambda: NOW)
        self.assertIsNone(result)
        self.assertIsNone(owner.history_report)
        self.assertEqual(len((await self.inspect()).receipt_ids), 1)

    async def test_recovery_report_carries_source_provenance(self):
        owner = AccountCoordinator(self.writer, subaccount=0)
        owner.connect_generation()
        result = await owner.recover_history(AccountReads(), start=NOW-timedelta(hours=1),
                                             end=NOW, now=lambda: NOW)
        self.assertEqual(result.enumeration.generation, owner.generation)
        self.assertEqual(result.enumeration.source_revision, result.revision)
        self.assertEqual(result.enumeration.writer_epoch, self.writer.epoch)
        self.assertFalse(result.ready_for_entry)

    async def test_runtime_inspection_is_local_historical_only(self):
        await self.writer.audit_history(evidence(), NOW)
        async def noop(*args): pass
        def no_reader(*args): raise AssertionError('must not open stream')
        reads = AccountReads()
        runtime = RecoveryRuntime(self.writer, reads, no_reader, tickers=('A',), subaccount=0,
            history_start=NOW-timedelta(hours=1), now=lambda: NOW, evaluate=noop,
            deadline_handler=noop, lifecycle_handler=noop)
        await runtime.inspect_history_coverage(start=NOW-timedelta(hours=1), end=NOW)
        result = runtime.verification_status()
        self.assertTrue(result['durable_history_inspection']['historical_only'])
        self.assertEqual(result['durable_history_inspection']['gap_count'], 1)
        self.assertIn('current_history_pass_missing', result['blockers'])
        self.assertFalse(runtime.entry_allowed)
        self.assertEqual(reads.calls, [])

    async def test_runtime_does_not_label_omitted_history_repaired(self):
        # Unbound positive evidence, then an empty REST pass, no synthetic import.
        ev = evidence(rows=1)
        await self.writer.audit_history(ev, NOW)
        async def noop(*args): pass
        runtime = RecoveryRuntime(self.writer, AccountReads(), lambda _: None, tickers=('A',),
            subaccount=0, history_start=NOW-timedelta(hours=1), now=lambda: NOW,
            evaluate=noop, deadline_handler=noop, lifecycle_handler=noop)
        runtime.account.connect_generation()
        runtime.account_subscribed = True
        self.assertFalse(await runtime.recover_once())
        self.assertEqual(runtime.recovery_passes, 0)
        self.assertIn('previously_observed_fills_omitted', runtime.verification_status()['blockers'])

    async def test_invalid_query_rejected_before_owner_failure(self):
        with self.assertRaises(InvalidData):
            await self.writer.history_coverage(subaccount=0, start=NOW, end=NOW)
        self.assertFalse(self.writer.failed)

    async def test_bad_source_provenance_does_not_stage_anything(self):
        with self.assertRaises(InvalidData):
            await self.writer.audit_history(evidence(rows=1), NOW, generation=1)
        self.assertFalse(self.writer.failed)
        self.assertEqual((await self.inspect()).receipt_ids, ())

    async def test_omission_has_specific_payload_free_diagnostic(self):
        events = []
        class Diagnostics:
            def emit(self, name, **fields): events.append((name, fields))
        self.writer.diagnostics = Diagnostics()
        await self.writer.audit_history(evidence(rows=1), NOW)
        await self.writer.audit_history(evidence(), NOW)
        self.assertIn(('history_omission', {'blocker_count': 1}), events)
        self.assertTrue(all(set(fields) == {'blocker_count'} for _, fields in events))
