"""Synthetic real-owner cancellation scheduling; no venue or live ledger I/O."""
from dataclasses import replace
from unittest.mock import patch
import unittest

from kalshi_bot.dispatch import DispatchResult, QUOTE_CANCEL, ENTRY_PAIR
from kalshi_bot.dispatch_supervisor import DispatchSupervisor
import test_bot_risk_observation as fixture


class RiskDispatchRetryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.f = fixture.RiskObservationTests()
        await self.f.asyncSetUp()
        self.r, self.m = self.f.r, self.f.m
        self.source, self.d = self.f.f.f.source, self.f.f.f.dispatcher
        self.owner = DispatchSupervisor(self.source, self.d, offline_fixture=True)
        self.r.dispatch_supervisor = self.owner
        self.owner.running = True
        self.r.recovery_state = 'repaired_entries_blocked'
        await self.f.gap()
        self.m.refresh('A')
        self.assertIsNotNone(self.m.cycle)

    async def asyncTearDown(self):
        self.r.dispatch_supervisor = None
        await self.f.asyncTearDown()

    def advance(self, seconds=.5):
        self.f.f.f.mono += seconds

    async def first_ack(self):
        self.owner.request('A', QUOTE_CANCEL)
        result = await self.d.run_one()
        self.assertEqual(result.state, 'ACK')
        return result

    async def block_private(self):
        self.r.account._processing = True
        result = await self.d.run_one()
        self.r.account._processing = False
        self.assertEqual(result.state, 'BLOCKED')
        self.assertFalse(self.d.status().queued)
        return result

    async def test_second_leg_survives_popped_key_without_post_drain_recovery(self):
        first = await self.first_ack()
        await self.block_private()
        self.assertTrue(self.source.risk_drain_pending)
        self.assertFalse(self.r._request_post_drain_recovery())
        self.assertFalse(self.r.recovery_requested.is_set())
        self.advance()
        self.r._resume_risk_drain()
        second = await self.d.run_one()
        self.assertEqual(second.state, 'ACK')
        self.assertNotEqual(first.order_id, second.order_id)
        self.assertFalse(self.r._request_post_drain_recovery())
        await self.d.run_one()  # Authoritative local no-further-candidate read.
        self.assertFalse(self.source.risk_drain_pending)
        self.assertTrue(self.r._request_post_drain_recovery())
        self.assertFalse(self.r._request_post_drain_recovery())
        self.assertEqual(len(self.f.f.f.calls), 2)
        self.assertEqual(sum(o.order.remaining for o in await self.r.writer.orders()), 20)

    async def test_first_leg_temporary_block_is_retained_too(self):
        self.owner.request('A', QUOTE_CANCEL)
        await self.block_private()
        self.advance()
        self.r._resume_risk_drain()
        self.assertEqual((await self.d.run_one()).state, 'ACK')
        self.assertEqual(len(self.f.f.f.calls), 1)

    async def test_wait_is_bounded_coalesced_and_does_not_busy_loop(self):
        await self.first_ack()
        await self.block_private()
        for _ in range(1000):
            self.r._resume_risk_drain()
            self.r._request_quote_dispatch('A')
        self.assertFalse(self.d.status().queued)
        self.advance()
        for _ in range(1000):
            self.r._resume_risk_drain()
        self.assertEqual(self.d.status().queued, ((QUOTE_CANCEL, 'A'),))
        self.assertEqual(self.source.risk_cancel_deferrals, 1)

    async def test_retry_expiry_waits_for_inflight_outcome(self):
        await self.first_ack()
        await self.block_private()
        self.advance(5)
        state = replace(self.d.status(), active=('A', QUOTE_CANCEL))
        with patch.object(self.d, 'status', return_value=state):
            self.r._resume_risk_drain()
        self.assertTrue(self.source.risk_drain_pending)
        self.assertFalse(self.r.recovery_requested.is_set())

    async def test_retry_exhaustion_requests_recovery_once_without_resending(self):
        await self.first_ack()
        await self.block_private()
        self.advance(5)
        self.r._resume_risk_drain()
        self.assertFalse(self.source.risk_drain_pending)
        self.assertTrue(self.r.recovery_requested.is_set())
        self.assertFalse(self.d.status().queued)
        with patch.object(self.r, 'request_recovery') as request:
            self.r._resume_risk_drain()
            request.assert_not_called()
        self.assertEqual(len(self.f.f.f.calls), 1)

    async def test_retry_attempt_limit_applies_before_deadline(self):
        await self.first_ack()
        for _ in range(8):
            await self.block_private()
            self.advance(.25)
            self.r._resume_risk_drain()
        self.assertFalse(self.source.risk_drain_pending)
        self.assertTrue(self.r.recovery_requested.is_set())
        self.assertEqual(len(self.f.f.f.calls), 1)

    async def test_changed_cycle_stop_and_disconnect_never_schedule_old_intent(self):
        await self.first_ack()
        await self.block_private()
        self.advance()
        old = self.m.cycle
        self.m.cycle = replace(old, order_ids=())
        self.r._resume_risk_drain()
        self.assertFalse(self.d.status().queued)
        self.m.cycle = old
        self.r.account.connected = False
        self.r._resume_risk_drain()
        self.assertFalse(self.d.status().queued)
        self.r.account.connected = True
        self.source.stop()
        self.r._resume_risk_drain()
        self.assertFalse(self.d.status().queued)

    async def test_explicit_rejection_does_not_retry_transport(self):
        from kalshi_bot.command_types import MutationHTTPFailure
        async def reject(*args):
            raise MutationHTTPFailure(404, 'not_found')
        self.d.executor.invoke.invoke = reject
        result = await self.first_result()
        self.assertEqual(result.state, 'REJECTED')
        self.assertFalse(self.source.risk_drain_pending)
        self.assertTrue(self.r.recovery_requested.is_set())
        self.advance()
        self.r._resume_risk_drain()
        self.assertFalse(self.d.status().queued)

    async def test_unknown_cancel_does_not_retry_transport(self):
        async def timeout(*args):
            raise TimeoutError()
        self.d.executor.invoke.invoke = timeout
        with self.assertRaises(TimeoutError):
            await self.first_result()
        self.assertEqual((await self.r.writer.mutations())[-1]['phase'], 'UNKNOWN')
        self.assertFalse(self.source.risk_drain_pending)
        self.assertTrue(self.r.recovery_requested.is_set())
        self.advance()
        self.r._resume_risk_drain()
        self.assertFalse(self.d.status().queued)

    async def test_source_change_during_evidence_read_keeps_pending_intent(self):
        original = self.r.writer.next_entry_cancel_evidence
        async def race(*args, **kwargs):
            value = await original(*args, **kwargs)
            self.r.account._processing = True
            return value
        with patch.object(self.r.writer, 'next_entry_cancel_evidence', side_effect=race):
            result = await self.first_result()
        self.r.account._processing = False
        self.assertEqual(result.state, 'BLOCKED')
        self.assertTrue(self.source.risk_drain_pending)
        self.advance()
        self.r._resume_risk_drain()
        self.assertEqual((await self.d.run_one()).state, 'ACK')

    async def test_permanent_preparation_block_goes_to_recovery_not_retry(self):
        from types import SimpleNamespace
        with patch.object(self.r.writer, 'prepare_cancel', return_value=SimpleNamespace(
                reserved=False, receipt=None, blockers=('command_reauthorization_limit',))):
            result = await self.first_result()
        self.assertEqual(result.state, 'BLOCKED')
        self.assertFalse(self.source.risk_drain_pending)
        self.assertTrue(self.r.recovery_requested.is_set())
        self.advance()
        self.r._resume_risk_drain()
        self.assertFalse(self.d.status().queued)

    async def first_result(self):
        self.owner.request('A', QUOTE_CANCEL)
        return await self.d.run_one()

    async def test_proven_unsent_send_edge_race_is_rechecked_not_replayed(self):
        with patch.object(self.d.executor, 'validate_proof', return_value=False):
            result = await self.first_result()
        self.assertEqual(result.state, 'BLOCKED')
        self.assertTrue(self.source.risk_drain_pending)
        self.assertEqual(len(self.f.f.f.calls), 0)
        self.advance()
        self.r._resume_risk_drain()
        self.assertEqual((await self.d.run_one()).state, 'ACK')
        self.assertEqual(len(self.f.f.f.calls), 1)

    async def test_private_completion_wakes_exact_pending_cancel(self):
        await self.first_ack()
        await self.block_private()
        self.advance()
        event = dict(type='user_order', msg=dict(ticker='A'))
        with patch.object(self.r.account, 'on_event', return_value=None):
            await self.r._private(event, self.r.account.generation)
        self.assertEqual(self.d.status().queued, ((QUOTE_CANCEL, 'A'),))

    async def test_watchdog_keeps_refresh_from_overtaking_pending_cancel(self):
        await self.first_ack()
        await self.block_private()
        self.r.account_subscribed = True
        self.r.account._processing = True
        async def stop_wait():
            self.r.stop_requested.set()
        with patch.object(self.r.stop_requested, 'wait', side_effect=stop_wait), \
                patch.object(self.r, '_refresh_routine_account') as refresh:
            await self.r._live_refresh()
        refresh.assert_not_called()
        self.assertFalse(self.r.recovery_requested.is_set())
        self.r.account._processing = False

    async def test_deferred_warning_wakes_after_dispatch_and_cycle_finish(self):
        self.m._risk_since['B'] = self.r.clock()
        with patch.object(self.r.engine.dirty, 'mark') as mark:
            self.source._dispatch_result(DispatchResult('BLOCKED', 'A', ENTRY_PAIR))
            mark.assert_called_with('A')  # Entry advisory wake, not other risk cycle.
            self.assertNotIn(unittest.mock.call('B'), mark.call_args_list)
            self.m._finish('A')
            mark.assert_any_call('B')
            mark.reset_mock()
            self.source._dispatch_result(DispatchResult('BLOCKED', 'A', ENTRY_PAIR))
            mark.assert_any_call('B')


if __name__ == '__main__':
    unittest.main()
