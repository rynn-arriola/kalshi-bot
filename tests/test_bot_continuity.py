"""D-044 Phase 1: local evidence only, with no credentials or venue traffic."""
import asyncio
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, patch

from kalshi_bot.account import UnscopedPositionUpdate
from kalshi_bot.continuity import PrivateEpoch, assess_continuity
from kalshi_bot.runtime import RecoveryRuntime
from kalshi_bot.rest import ReadResult, RestReads, TokenBudget
from kalshi_bot.values import InvalidData
from kalshi_bot.writer import LedgerWriter
from test_bot_auto_recovery import EXEC, NOW
from test_bot_recovery_runtime import AccountReads, FakeReader
from test_bot_recovery_runtime import event as fill_event


CHANNELS = ('fill', 'market_positions', 'order_group_updates', 'user_orders')


class EpochStoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name)/'ledger.db'
        self.writer = await LedgerWriter(self.path).start()

    async def asyncTearDown(self):
        await self.writer.close()
        self.temp.cleanup()

    def epoch(self, key='epoch-1'):
        return PrivateEpoch(key, 0, 1, self.writer.epoch, CHANNELS, NOW)

    async def test_open_marker_survives_restart_as_gap(self):
        await self.writer.open_private_epoch(self.epoch())
        self.assertEqual(await self.writer.private_epoch_gap_count(subaccount=0), 1)
        # Process-local reversal: suppressing the durable-gap query would make
        # the same assertion detect the missing crash marker.
        with patch('kalshi_bot.private_epoch_store.gap_count', return_value=0):
            with self.assertRaises(AssertionError):
                self.assertEqual(await self.writer.private_epoch_gap_count(subaccount=0), 1)
        await self.writer.close()
        self.writer = await LedgerWriter(self.path).start()
        found = await self.writer.inspect_private_epochs(subaccount=0)
        self.assertEqual((len(found), found[0].epoch_id, found[0].closed_at), (1, 'epoch-1', None))
        self.assertEqual(await self.writer.private_epoch_gap_count(subaccount=0), 1)

    async def test_clean_close_is_only_local_and_idempotent(self):
        await self.writer.open_private_epoch(self.epoch())
        options = dict(closed_at=NOW+timedelta(seconds=1), ingress_count=2,
            durable_fill_count=1, terminal_reason='stopped', clean_local_delivery=True)
        result = await self.writer.close_private_epoch('epoch-1', **options)
        self.assertTrue(result.clean_local_delivery)
        self.assertEqual(await self.writer.close_private_epoch('epoch-1', **options), result)
        self.assertEqual(await self.writer.private_epoch_gap_count(subaccount=0), 0)
        await self.writer.close()
        self.writer = await LedgerWriter(self.path).start()
        self.assertEqual(await self.writer.private_epoch_gap_count(subaccount=0), 0)

    async def test_invalid_close_stays_a_persisted_gap(self):
        await self.writer.open_private_epoch(self.epoch())
        await self.writer.close_private_epoch('epoch-1', closed_at=NOW, ingress_count=0,
            durable_fill_count=0, terminal_reason='reader_error', clean_local_delivery=False)
        self.assertEqual(await self.writer.private_epoch_gap_count(subaccount=0), 1)

    async def test_writer_failure_during_close_leaves_open_gap(self):
        await self.writer.open_private_epoch(self.epoch())
        original = self.writer._execute
        def fault(db, command, args):
            if command == 'private_epoch_close':
                raise RuntimeError('injected local disk fault')
            return original(db, command, args)
        with patch.object(self.writer, '_execute', side_effect=fault):
            with self.assertRaises(InvalidData):
                await self.writer.close_private_epoch('epoch-1', closed_at=NOW,
                    ingress_count=0, durable_fill_count=0, terminal_reason='stopped',
                    clean_local_delivery=True)
        self.assertTrue(self.writer.failed)
        await self.writer.close()
        self.writer = await LedgerWriter(self.path).start()
        self.assertEqual(await self.writer.private_epoch_gap_count(subaccount=0), 1)


class AssessmentTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        self.writer = await LedgerWriter(Path(self.temp.name)/'ledger.db').start()
        self.reads = AccountReads()
        async def ignore(*_):
            pass
        self.runtime = RecoveryRuntime(self.writer, self.reads, None, tickers=('A',),
            subaccount=0, history_start=EXEC-timedelta(seconds=1), now=lambda: NOW,
            evaluate=ignore, deadline_handler=ignore, lifecycle_handler=ignore)
        self.runtime.account.connect_generation()
        self.runtime.account_subscribed = True

    async def asyncTearDown(self):
        await self.writer.close()
        self.temp.cleanup()

    async def test_clean_observed_span_still_has_no_venue_handoff(self):
        self.assertTrue(await self.runtime.recover_once())
        account = self.runtime.account
        observed = PrivateEpoch('observed', 0, account.generation, self.writer.epoch, CHANNELS, NOW)
        args = dict(subaccount=0, generation=account.generation,
            writer_epoch=self.writer.epoch, writer_revision=self.writer.revision,
            report=account.current_report(NOW), recovery=self.runtime.last_reports[0],
            epoch=observed, history_ingress_revision=self.runtime.history_ingress_revision,
            ingress_revision=self.runtime.ingress_revision, persisted_gap_count=0)
        assessment = assess_continuity(**args)
        self.assertTrue(assessment.local_evidence_consistent)
        self.assertFalse(assessment.venue_handoff_proven)
        self.assertIn('venue_history_stream_handoff_unproven', assessment.blockers)
        incomplete = replace(observed, ack_channels=('fill',))
        self.assertFalse(assess_continuity(**(args | {'epoch': incomplete})).local_evidence_consistent)
        # Process-local reversal: weakening the required channel set causes
        # the incomplete-span assertion to detect the unsafe local claim.
        with patch('kalshi_bot.continuity.REQUIRED_PRIVATE_CHANNELS', frozenset({'fill'})):
            with self.assertRaises(AssertionError):
                self.assertFalse(assess_continuity(**(args | {'epoch': incomplete})).local_evidence_consistent)
        self.assertFalse(assess_continuity(**(args | {'writer_revision': self.writer.revision+1})).local_evidence_consistent)
        self.assertFalse(assess_continuity(**(args | {'generation': account.generation+1})).local_evidence_consistent)
        self.assertFalse(assess_continuity(**(args | {'persisted_gap_count': 1})).local_evidence_consistent)
        self.assertFalse(assess_continuity(**(args | {'persisted_gap_count': None})).local_evidence_consistent)
        self.assertFalse(assess_continuity(**(args | {'epoch_ambiguous': True})).local_evidence_consistent)

    async def test_starting_candidate_is_explicit_unapproved_and_revision_bound(self):
        self.assertTrue(await self.runtime.recover_once())
        candidate = self.runtime.inspect_starting_account(proposed_boundary=EXEC)
        self.assertFalse(candidate.approved)
        self.assertIn('private_epoch_unobserved', candidate.continuity_blockers)
        self.assertEqual((candidate.subaccount, candidate.positions), (0, ()))
        with self.assertRaises(InvalidData):
            self.runtime.inspect_starting_account(proposed_boundary=NOW+timedelta(seconds=1))
        await self.writer.observe(NOW)
        with self.assertRaises(InvalidData):
            self.runtime.inspect_starting_account(proposed_boundary=EXEC)

    async def test_unscoped_position_invalidates_without_installing_cost(self):
        before = self.writer.revision
        event = {'type': 'market_position', 'msg': {'market_ticker': 'A',
            'position_fp': '3', 'position_cost_dollars': '1.5'}}
        result = await self.runtime.account.on_event(event,
            generation=self.runtime.account.generation, received_at=NOW)
        self.assertIsInstance(result, UnscopedPositionUpdate)
        self.assertEqual(self.runtime.account.position_updates, {})
        self.assertTrue(self.runtime.account.connected)
        self.assertEqual(self.writer.revision, before)
        await self.runtime._private(event, self.runtime.account.generation)
        self.assertTrue(self.runtime._epoch_ambiguous)
        self.assertTrue(self.runtime._unscoped_position_requested)
        self.assertFalse(self.runtime.verification_status()['continuity']['venue_handoff_proven'])
        self.assertTrue(self.runtime.recovery_requested.is_set())

    async def test_position_cursor_missing_after_first_page_is_incomplete(self):
        reads = RestReads(TokenBudget(rate=100, capacity=100, default_cost=10))
        try:
            pages = [ReadResult({'market_positions': [], 'cursor': 'next'}, 20),
                     ReadResult({'market_positions': []}, 20)]
            with patch.object(reads, 'read', AsyncMock(side_effect=pages)):
                with self.assertRaisesRegex(InvalidData, 'required pagination cursor'):
                    await reads.collect('positions', reason='reconcile')
        finally:
            await reads.close()

    async def test_conflicting_scope_remains_fail_closed(self):
        event = {'type': 'market_position', 'msg': {'market_ticker': 'A',
            'position_fp': '3', 'position_cost_dollars': '1.5', 'subaccount': 1}}
        with self.assertRaises(InvalidData):
            await self.runtime.account.on_event(event,
                generation=self.runtime.account.generation, received_at=NOW)
        self.assertFalse(self.runtime.account.connected)

    async def test_pre_ack_fill_is_staged_but_cannot_open_clean_span(self):
        self.runtime.account_subscribed = False
        spec = next(s for s in self.runtime.specs if s.name == 'account')
        with self.assertRaisesRegex(InvalidData, 'before complete subscription'):
            await self.runtime._consume(spec, fill_event(), self.runtime.account.generation,
                                        {'user_orders'})
        self.assertEqual(len(await self.writer.pending_fills(0)), 1)
        self.assertIsNone(self.runtime._epoch)
        self.assertFalse(self.runtime.verification_status()['continuity']['venue_handoff_proven'])


class ReaderEpochTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name)/'ledger.db'
        self.writer = await LedgerWriter(self.path).start()
        self.reads = AccountReads()
        self.connections = {}
        async def ignore(*_):
            pass
        def factory(spec):
            reader = FakeReader(spec)
            self.connections.setdefault(spec.name, []).append(reader)
            return reader
        self.runtime = RecoveryRuntime(self.writer, self.reads, factory, tickers=('A',),
            subaccount=0, history_start=EXEC-timedelta(seconds=1), now=lambda: NOW,
            evaluate=ignore, deadline_handler=ignore, lifecycle_handler=ignore,
            attempts=1)
        self.task = None

    async def asyncTearDown(self):
        if self.task is not None and not self.task.done():
            self.runtime.stop()
            await asyncio.wait_for(self.task, 4)
        await self.writer.close()
        self.temp.cleanup()

    async def eventually(self, predicate):
        async with asyncio.timeout(4):
            while not predicate():
                await asyncio.sleep(.001)

    async def launch(self):
        self.task = asyncio.create_task(self.runtime.run())
        await self.eventually(lambda: self.runtime.account_subscribed)

    async def test_ack_opens_durable_marker_and_orderly_stop_closes_locally(self):
        await self.launch()
        epoch = (await self.runtime.inspect_private_epochs())[0]
        self.assertIsNone(epoch.closed_at)
        self.assertEqual(set(epoch.ack_channels), set(CHANNELS))
        self.runtime.stop()
        await asyncio.wait_for(self.task, 4)
        epoch = (await self.runtime.inspect_private_epochs())[0]
        self.assertTrue(epoch.clean_local_delivery)
        self.assertEqual(epoch.terminal_reason, 'stopped')
        self.assertFalse(self.runtime.status()['live_ready'])

    async def test_reader_failure_persists_gap_across_restart(self):
        await self.launch()
        await self.connections['account'][0].queue.put(InvalidData('injected reader failure'))
        await self.eventually(lambda: self.runtime.reader_states['account'] == 'retry_exhausted')
        epoch = (await self.runtime.inspect_private_epochs())[0]
        self.assertEqual(epoch.terminal_reason, 'reader_error')
        self.assertEqual(self.runtime.verification_status()['continuity']['persisted_gap_count'], 1)
        self.runtime.stop()
        await asyncio.wait_for(self.task, 4)
        await self.writer.close()
        self.writer = await LedgerWriter(self.path).start()
        self.assertEqual(await self.writer.private_epoch_gap_count(subaccount=0), 1)

    async def test_unscoped_update_keeps_fill_reader_but_blocks_repair(self):
        await self.launch()
        account = self.connections['account'][0]
        await account.queue.put({'type': 'market_position', 'msg': {
            'market_ticker': 'A', 'position_fp': '1', 'position_cost_dollars': '.5'}})
        await self.eventually(lambda: self.runtime._epoch_ambiguous)
        self.assertTrue(self.runtime.account.connected)
        await account.queue.put(fill_event())
        await self.eventually(lambda: self.runtime._epoch_fills == 1)
        self.assertEqual(len(await self.writer.pending_fills(0)), 1)
        self.assertFalse(self.runtime.verification_status()['continuity']['local_evidence_consistent'])
        self.assertFalse(self.runtime.entry_allowed)

    async def test_cancelled_run_does_not_claim_clean_delivery(self):
        await self.launch()
        self.task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await self.task
        epoch = (await self.runtime.inspect_private_epochs())[0]
        self.assertFalse(epoch.clean_local_delivery)
        self.assertEqual(epoch.terminal_reason, 'cancelled')

    async def test_orderly_stop_with_reader_backlog_is_not_clean(self):
        await self.launch()
        # Fault injection: the reader is already waiting on its original queue.
        # Expose a distinct nonempty ingress queue at teardown to simulate
        # buffered bytes that the callback never acknowledged.
        reader = self.connections['account'][0]
        reader.queue = asyncio.Queue()
        reader.queue.put_nowait({'type': 'market_position',
            'msg': {'market_ticker': 'A', 'position_fp': '1', 'position_cost_dollars': '.5'}})
        self.runtime.stop()
        await asyncio.wait_for(self.task, 4)
        epoch = (await self.runtime.inspect_private_epochs())[0]
        self.assertFalse(epoch.clean_local_delivery)
        self.assertEqual(epoch.terminal_reason, 'undrained')

    async def test_engine_failure_closes_marker_with_specific_reason(self):
        await self.launch()
        self.runtime.engine.failed = True
        self.runtime.stop()
        try:
            await asyncio.wait_for(self.task, 4)
        except InvalidData:
            pass  # Runtime supervision may observe the injected owner failure.
        epoch = (await self.runtime.inspect_private_epochs())[0]
        self.assertFalse(epoch.clean_local_delivery)
        self.assertEqual(epoch.terminal_reason, 'engine_failure')


if __name__ == '__main__':
    unittest.main()
