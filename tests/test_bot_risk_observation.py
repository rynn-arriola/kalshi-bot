"""Order-scoped cancellation observations: synthetic owners, no venue access."""
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from kalshi_bot.dispatch import QUOTE_CANCEL, ENTRY_PAIR
import test_bot_quote_maintenance as maintenance_fixture
from test_bot_reward_tracker import QueueReads


class RiskObservationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.f = maintenance_fixture.MaintenanceTests()
        await self.f.asyncSetUp()
        self.r, self.m = self.f.r, self.f.m
        self.book = self.r.management._book('A')[1]
        self.book.bids.set(D('.5'), D(510))
        self.r.reads = QueueReads([dict(order_id=o.order_id, market_ticker='A',
            queue_position_fp='500') for o in self.f.orders])
        await self.f.rewards.reflect_once()
        self.assertIsNone(self.m.cycle)

    async def asyncTearDown(self):
        await self.f.asyncTearDown()

    async def gap(self):
        self.r.account._invalidate()
        await self.r.management.refresh('A')
        self.book.bids.set(D('.5'), D(10))

    async def test_report_gap_detects_and_dispatches_exact_pair_without_releasing_entries(self):
        await self.gap()
        self.m.refresh('A')
        self.assertIsNotNone(self.m.cycle)
        self.assertEqual(self.m.cycle.reason, 'fill_risk_withdrawal')
        self.assertIsNone(self.r.account.current_report(self.r.now()))
        self.assertIsNone(await self.f.f.source.refresh('A', ENTRY_PAIR))
        first = await self.f.f.run_priority(QUOTE_CANCEL)
        second = await self.f.f.run_priority(QUOTE_CANCEL)
        self.assertEqual((first.state, second.state), ('ACK', 'ACK'))
        self.assertEqual({first.order_id, second.order_id},
                         {o.order_id for o in self.f.orders})
        self.assertEqual(sum(o.order.remaining for o in await self.f.f.writer.orders()), 20)

    async def test_reward_metadata_gap_does_not_hide_threat(self):
        self.r.management.revoke_terms('A')
        self.f.rewards.invalidate('A')
        await self.r.management.refresh('A')
        self.book.bids.set(D('.5'), D(10))
        self.m.refresh('A')
        self.assertIsNotNone(self.m.cycle)
        self.assertEqual(self.m.cycle.reason, 'fill_risk_withdrawal')

    async def test_queue_read_publishes_before_missing_reward_join(self):
        self.r.management.revoke_terms('A')
        self.f.rewards.invalidate('A')
        await self.r.management.refresh('A')
        self.book.bids.set(D('.5'), D(10))
        self.m._risk_queues.clear()
        await self.f.rewards.reflect_once()
        self.assertIsNotNone(self.m.cycle)
        self.assertFalse(self.f.rewards.current('A'))
        self.assertEqual(len(self.r.reads.calls), 2)  # Existing reflection only.

    async def test_expiry_and_clock_regression_never_renew_queue(self):
        await self.gap()
        anchor = self.m._risk_queues['A']
        mono = self.f.f.mono
        for changes, delta in (({'valid_until': self.r.now()}, 0),
                               ({}, 5), ({}, -1)):
            with self.subTest(changes=changes, delta=delta):
                self.m._risk_queues['A'] = replace(anchor, **changes)
                self.f.f.mono = mono+delta
                # Keep the inventory lookup fresh to isolate queue expiry.
                await self.r.management.refresh('A')
                self.m.refresh('A')
                self.assertIsNone(self.m.cycle)
                self.assertNotIn('A', self.m._risk_queues)
        self.f.f.mono = mono

    async def test_changed_source_identity_cannot_reuse_anchor(self):
        await self.gap()
        anchor = self.m._risk_queues['A']
        for changes in ({'writer_epoch': 'another-writer'},
                        {'account_generation': anchor.account_generation+1},
                        {'book_generation': anchor.book_generation+1},
                        {'program': replace(self.f.p, target=D(200))},
                        {'signature': ()}):
            with self.subTest(changes=changes):
                self.m._risk_queues['A'] = replace(anchor, **changes)
                self.m.refresh('A')
                self.assertIsNone(self.m.cycle)
                self.assertNotIn('A', self.m._risk_queues)

    async def test_missing_book_or_inventory_does_not_authorize_withdrawal(self):
        await self.gap()
        with patch.object(self.r.management, '_book', return_value=(None, None)):
            self.m.refresh('A')
        self.assertIsNone(self.m.cycle)
        with patch.object(self.r.management, 'current', return_value=None):
            self.m.refresh('A')
        self.assertIsNone(self.m.cycle)
        self.m.refresh('A')
        self.assertIsNotNone(self.m.cycle)

    async def test_pending_private_work_blocks_detection_until_processed(self):
        await self.gap()
        self.r.account._processing = True
        self.m.refresh('A')
        self.assertIsNone(self.m.cycle)
        self.r.account._processing = False
        self.m.refresh('A')
        self.assertIsNotNone(self.m.cycle)

    async def test_private_backlog_and_inventory_blockers_prevent_latching(self):
        await self.gap()
        self.r.engine.private.append(object())
        self.m.refresh('A')
        self.assertIsNone(self.m.cycle)
        self.r.engine.private.clear()
        plan = self.r.management.current('A', require_market=False)
        altered = replace(plan, inventory=replace(plan.inventory, blockers=('pending_fills',)))
        with patch.object(self.r.management, 'current', return_value=altered):
            self.m.refresh('A')
        self.assertIsNone(self.m.cycle)

    async def test_runtime_evaluation_requests_dispatch_during_report_gap(self):
        await self.gap()
        calls = []
        self.r.dispatch_supervisor = SimpleNamespace(
            dispatcher=self.f.f.dispatcher, request=lambda *args: calls.append(args))
        try:
            await self.r._evaluate('A', self.book, self.r.management._book('A')[0].generation)
            self.assertIn(('A', QUOTE_CANCEL), calls)
            self.assertIsNone(self.r.account.current_report(self.r.now()))
        finally:
            self.r.dispatch_supervisor = None

    async def test_replaced_pair_finishes_old_cycle_only_with_report(self):
        self.book.bids.set(D('.5'), D(10))
        self.m.refresh('A')
        self.m.cycle = replace(self.m.cycle, order_ids=('retired-order',))
        self.m.refresh('A')
        self.assertIsNone(self.m.cycle)

    async def test_owned_terms_change_foreign_reducer_and_pending_fill_block(self):
        await self.gap()
        anchor = self.m._risk_queues['A']
        plan = self.r.management.current('A', require_market=False)
        row = plan.inventory.orders[0]
        for changes in ({'owned': False}, {'reducing': True}, {'awaiting_fills': True},
                        {'order': replace(row.order, remaining=D(9))},
                        {'order': replace(row.order, yes_price=D('.49'))}):
            with self.subTest(changes=changes):
                self.m._risk_queues['A'] = anchor
                altered = replace(plan, inventory=replace(plan.inventory,
                    orders=(replace(row, **changes),)+plan.inventory.orders[1:]))
                with patch.object(self.r.management, 'current', return_value=altered):
                    self.m.refresh('A')
                self.assertIsNone(self.m.cycle)

    async def test_new_position_hands_back_to_exit_policy(self):
        await self.gap()
        plan = self.r.management.current('A', require_market=False)
        altered = replace(plan, inventory=replace(plan.inventory, position=D(1)))
        with patch.object(self.r.management, 'current', return_value=altered):
            self.m.refresh('A')
        self.assertIsNone(self.m.cycle)
        self.assertNotIn('A', self.m._risk_queues)
        self.assertEqual(self.m.samples['A']['action'], 'existing_exit_policy')

    async def test_queue_cache_bound_and_empty_publication_clear_trends(self):
        from kalshi_bot.fill_risk import FillRiskPolicy
        self.assertEqual(len(self.m.fill_risk.samples), 2)
        proofs = dict(self.f.rewards._reflection)
        self.m.fill_risk.policy = FillRiskPolicy(capacity=1)
        self.m.accept_risk_queues(proofs)
        self.assertEqual(self.m._risk_queues, {})
        self.assertEqual(self.m.fill_risk.samples, {})
        self.m.accept_risk_queues({})
        self.assertEqual(self.m._risk_queues, {})

    async def test_sample_throttle_threat_transition_and_gap_counts(self):
        self.m._risk_log_at.clear()
        with patch.object(self.r.diagnostics, 'emit') as emit:
            for _ in range(50):
                self.m.refresh('A')
            samples = [c for c in emit.call_args_list if c.args[0] == 'fill_risk_sample']
            self.assertEqual(len(samples), 2)
            await self.gap()
            self.m.refresh('A')
            samples = [c for c in emit.call_args_list if c.args[0] == 'fill_risk_sample']
            self.assertEqual(len(samples), 4)
            self.assertTrue(any(c.kwargs['risk_state'] == 'threat' for c in samples))
            self.assertTrue(all('depth_hundredths' in c.kwargs for c in samples))
            for _ in range(100):
                self.m._risk_gap('A', 'book_unavailable')
            counts = [c.kwargs['count'] for c in emit.call_args_list
                      if c.args[0] == 'fill_risk_observation_gap']
            self.assertEqual(counts, [1, 2, 4, 8, 16, 32, 64])

    async def test_ack_log_correlates_owned_id_and_full_decision_delay(self):
        await self.gap()
        self.m.refresh('A')
        self.f.f.mono += .25
        with patch.object(self.r.diagnostics, 'emit') as emit:
            result = await self.f.f.run_priority(QUOTE_CANCEL)
            self.m.dispatch_result(result)  # Duplicate callback must not log twice.
            logs = [c for c in emit.call_args_list if c.args[0] == 'fill_risk_cancel_ack']
            submits = [c for c in emit.call_args_list if c.args[0] == 'cancel_submit_attempt']
        self.assertEqual(len(logs), 1)
        self.assertEqual(len(submits), 1)
        self.assertEqual(submits[0].kwargs['order'], result.order_id)
        self.assertIn('operation', submits[0].kwargs)
        self.assertEqual(logs[0].kwargs['order'], result.order_id)
        self.assertGreaterEqual(logs[0].kwargs['elapsed_ms'], 250)

    async def test_unsent_cancel_does_not_log_submission(self):
        await self.gap()
        self.m.refresh('A')
        executor = self.f.f.dispatcher.executor
        with patch.object(executor, 'validate_proof', side_effect=[True, False]), \
                patch.object(self.r.diagnostics, 'emit') as emit:
            result = await self.f.f.run_priority(QUOTE_CANCEL)
            submits = [c for c in emit.call_args_list if c.args[0] == 'cancel_submit_attempt']
        self.assertNotEqual(result.state, 'ACK')
        self.assertEqual(submits, [])
        self.assertEqual(self.f.f.calls, [])


if __name__ == '__main__':
    unittest.main()
