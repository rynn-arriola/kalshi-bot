"""D-130 recovery-churn and protective-drain scheduling; synthetic owners only."""
import asyncio
from unittest.mock import patch
import unittest

from kalshi_bot.dispatch import DispatcherStatus, ENTRY_PAIR, QUOTE_CANCEL
from kalshi_bot.dispatch_supervisor import DispatchSupervisor
import test_bot_risk_dispatch_retry as retry_fixture
import test_bot_risk_observation as observation_fixture


class UnsentRebaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.b = retry_fixture.RiskDispatchRetryTests()
        await self.b.asyncSetUp()
        self.r, self.d, self.source = self.b.r, self.b.d, self.b.source
        self.ds = self.b.f.f.f
        orders = tuple(o for o in self.b.f.f.orders if not o.terminal)
        await self.ds.report('0', orders)
        self.report = self.r.account.current_report(self.r.now())
        self.assertIsNotNone(self.report)
        self.r._routine_account_proof = None

    async def asyncTearDown(self):
        await self.b.asyncTearDown()

    async def denied_turn(self):
        self.b.owner.request('A', QUOTE_CANCEL)
        with patch.object(self.d.executor, 'validate_proof', return_value=False):
            result = await self.d.run_one()
        self.assertEqual(result.state, 'BLOCKED')
        await self.source.after_turn(result)
        return result

    async def test_proven_unsent_command_rebases_report_without_full_recovery(self):
        before = self.r.writer.revision
        await self.denied_turn()
        self.assertGreater(self.r.writer.revision, before)  # prepare + abort
        self.assertFalse(self.r.recovery_requested.is_set())
        current = self.r.account.current_report(self.r.now())
        self.assertIsNotNone(current)
        self.assertIsNot(current, self.report)  # Old proofs bound to it are stale.
        self.assertIs(current.snapshot, self.report.snapshot)
        self.assertEqual(current.observed_at, self.report.observed_at)
        self.assertEqual(current.audit.writer_revision, self.r.writer.revision)
        self.assertEqual(self.ds.calls, [])
        self.assertEqual(self.r.unsent_rebases, 1)

    async def test_rebase_keeps_original_five_second_bound(self):
        self.b.advance(0)
        self.ds.now += __import__('datetime').timedelta(seconds=6)
        await self.denied_turn()
        self.assertIsNone(self.r.account.current_report(self.r.now()))
        self.assertTrue(self.r.recovery_requested.is_set())  # Ordinary fallback.

    async def test_private_ingress_during_reaudit_falls_back_to_recovery(self):
        original = self.r.writer.reaudit
        async def raced(snapshot):
            audit = await original(snapshot)
            self.r.account.revision += 1  # A private event overtook the read.
            return audit
        with patch.object(self.r.writer, 'reaudit', side_effect=raced):
            await self.denied_turn()
        self.assertTrue(self.r.recovery_requested.is_set())
        self.assertIsNone(self.r.account.current_report(self.r.now()))

    async def test_supervisor_runs_post_turn_hook_after_each_turn(self):
        seen = []
        async def hook(result):
            seen.append(result.state)
            self.b.owner.stop()
        self.b.owner.running = False
        self.b.owner.request('A', QUOTE_CANCEL)
        with patch.object(self.source, 'after_turn', side_effect=hook), \
                patch.object(self.d.executor, 'validate_proof', return_value=False):
            await self.b.owner.run()
        self.assertEqual(seen, ['BLOCKED'])

    async def test_transport_call_never_rebases(self):
        self.b.owner.request('A', QUOTE_CANCEL)
        result = await self.d.run_one()
        self.assertEqual(result.state, 'ACK')
        await self.source.after_turn(result)
        self.assertEqual(self.r.unsent_rebases, 0)
        self.assertIsNone(self.r.account.current_report(self.r.now()))


class RecoveryDrainGateTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.b = retry_fixture.RiskDispatchRetryTests()
        await self.b.asyncSetUp()
        self.r, self.d, self.source = self.b.r, self.b.d, self.b.source

    async def asyncTearDown(self):
        await self.b.asyncTearDown()

    async def test_any_recovery_cause_waits_for_pending_second_leg(self):
        await self.b.first_ack()
        await self.b.block_private()
        self.assertTrue(self.source.risk_drain_pending)
        passes = []
        async def recover_once():
            passes.append(self.source.risk_drain_pending)
            self.r.stop_requested.set()
            return True
        self.r.account_subscribed = True
        self.r.request_recovery('routine_refresh_failed')
        with patch.object(self.r, 'recover_once', side_effect=recover_once):
            task = asyncio.create_task(self.r._recover())
            await asyncio.sleep(.12)
            self.assertEqual(passes, [])
            self.assertEqual(self.r.recovery_state, 'awaiting_risk_drain')
            self.b.advance()
            self.r._resume_risk_drain()
            self.assertEqual((await self.d.run_one()).state, 'ACK')
            await self.d.run_one()  # Authoritative no-further-candidate read.
            await asyncio.wait_for(task, 3)
        self.assertEqual(passes, [False])
        self.assertEqual(len(self.b.f.f.f.calls), 2)
        self.assertEqual(self.r.recovery_risk_drain_waits, 1)

    async def test_wait_is_bounded_when_drain_never_finishes(self):
        await self.b.first_ack()
        await self.b.block_private()
        passes = []
        async def recover_once():
            passes.append(True)
            self.r.stop_requested.set()
            return True
        self.r.account_subscribed = True
        self.r.request_recovery('quota_restored')
        with patch.object(self.r, 'recover_once', side_effect=recover_once), \
                patch.object(type(self.source), 'risk_drain_pending', True), \
                patch.object(self.source, 'resume_risk_drain'):
            await asyncio.wait_for(self.r._recover(), 10)
        self.assertEqual(passes, [True])  # Never suppressed, only delayed.


class RiskLatchTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.f = observation_fixture.RiskObservationTests()
        await self.f.asyncSetUp()
        self.r, self.m = self.f.r, self.f.m
        ff = self.f.f.f
        self.owner = DispatchSupervisor(ff.source, ff.dispatcher, offline_fixture=True)
        self.r.dispatch_supervisor = self.owner

    async def asyncTearDown(self):
        self.r.dispatch_supervisor = None
        await self.f.asyncTearDown()

    def busy(self, ticker):
        return patch.object(self.owner.dispatcher, 'status', return_value=DispatcherStatus(
            (), (ticker, ENTRY_PAIR), 1, False, False))

    async def test_threat_latches_during_another_markets_command(self):
        await self.f.gap()
        with self.busy('B'):
            self.m.refresh('A')
        self.assertIsNotNone(self.m.cycle)
        self.assertEqual(self.m.cycle.reason, 'fill_risk_withdrawal')

    async def test_threat_joins_command_for_same_market(self):
        await self.f.gap()
        with self.busy('A'):
            self.m.refresh('A')
        self.assertIsNone(self.m.cycle)



class MaintenanceVisibilityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import test_bot_quote_maintenance as maintenance_fixture
        self.f = maintenance_fixture.MaintenanceTests()
        await self.f.asyncSetUp()
        self.r, self.m = self.f.r, self.f.m

    async def asyncTearDown(self):
        await self.f.asyncTearDown()

    async def test_owned_market_stays_visible_while_plan_is_rebuilt(self):
        self.m.samples.clear()
        self.r.management._plans.clear()
        status = self.m.status()
        self.assertIn('A', status['markets'])
        self.assertEqual(status['markets']['A']['state'], 'UNKNOWN')
        self.assertEqual(status['markets']['A']['reason'], 'no_current_sample')
        self.assertEqual(status['coverage']['owned_markets'], 1)
        self.assertEqual(status['coverage']['reward_observed_current'], 0)

    async def test_cycle_start_and_finish_are_logged_with_fixed_reason(self):
        with patch.object(self.r.diagnostics, 'emit') as emit:
            await self.f.drift()
            self.m._finish('A')
        started = [c for c in emit.call_args_list if c.args[0] == 'maintenance_cycle_started']
        finished = [c for c in emit.call_args_list if c.args[0] == 'maintenance_cycle_finished']
        self.assertEqual(len(started), 1)
        self.assertEqual(len(finished), 1)
        self.assertEqual(started[0].kwargs['maintenance_reason'], 'restore_reference_pair')
        self.assertEqual(started[0].kwargs['count'], 2)
        self.assertGreaterEqual(started[0].kwargs['dwell_ms'], 30000)
        from kalshi_bot import observability
        self.assertIn('restore_reference_pair',
                      observability.ENUMS['maintenance_reason'])


if __name__ == '__main__':
    unittest.main()
