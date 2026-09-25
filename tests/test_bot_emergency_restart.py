"""Synthetic request, current-owner deadline and restart orchestration tests."""
from dataclasses import replace
from datetime import datetime, timezone, timedelta
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, AsyncMock

from kalshi_bot.emergency import create_request, requested, flat_receipt
from kalshi_bot.emergency_restart import execute, ready
from kalshi_bot.management import InventoryManager
from kalshi_bot.exits import plan_exit, ExitJournal, ioc_payload
from kalshi_bot.values import InvalidData
from test_bot_exits import terms, book, receipt, NOW


def snapshot(*, child='old', pid=123, flat=False, stamp=100., paused=False):
    return dict(presence=dict(parent=not flat,child=not flat),last_runtime_file_age_seconds=0,
        native=dict(child_id=None if flat else child, diagnostic_pid=None if flat else pid,child_generation=1),
        last_runtime=dict(supervisor_child_id=child,pid=pid,observed_at=datetime.fromtimestamp(stamp,timezone.utc).isoformat(),
            state='STOPPED_FLAT' if flat else ('DRAINING' if paused else 'RUNNING'),
            emergency_flatten_supported=True,account_current=True,positions={},resting_entries=0 if flat else 2,
            risk_blockers=[],accounting_blockers=[],recovery_only=False,entry_allowed=True,
            runtime=dict(readers={'book':'subscribed','account':'subscribed','lifecycle':'subscribed'},logging={'healthy':True})))


class RequestTests(unittest.TestCase):
    def test_exact_generation_and_bounded_lifetime(self):
        with TemporaryDirectory() as root:
            kw=dict(scope_id='test',child_id='child',generation=3,now=100.)
            self.assertFalse(requested(root,**kw))
            create_request(root,**kw,operation='op',timeout=10)
            self.assertTrue(requested(root,**kw))
            for change in (dict(generation=4),dict(child_id='other'),dict(scope_id='other'),dict(now=110.),dict(now=99.)):
                self.assertFalse(requested(root,**(kw|change)))

    def test_terminal_receipt_cannot_reuse_old_process_or_timestamp(self):
        good=snapshot(flat=True,stamp=101.)
        self.assertTrue(flat_receipt(good,child_id='old',pid=123,requested_at=100.))
        self.assertFalse(flat_receipt(good,child_id='other',pid=123,requested_at=100.))
        self.assertFalse(flat_receipt(good,child_id='old',pid=124,requested_at=100.))
        self.assertFalse(flat_receipt(good,child_id='old',pid=123,requested_at=102.))
        good['last_runtime']['positions']={'A':'1'}
        self.assertFalse(flat_receipt(good,child_id='old',pid=123,requested_at=100.))

    def manager(self):
        runtime=SimpleNamespace(writer=SimpleNamespace(claim_management_owner=Mock()),entry_pause_active=False,
            engine=SimpleNamespace(market_shard={'A':'book'},dirty=SimpleNamespace(mark=Mock()),wake=SimpleNamespace(set=Mock())))
        return InventoryManager(runtime),runtime

    def test_explicit_deadline_persists_through_fresh_metadata_without_extending_freshness(self):
        manager,runtime=self.manager(); original=terms(); manager.set_terms(original)
        with self.assertRaises(InvalidData): manager.request_flatten(NOW)
        self.assertIs(manager.terms['A'],original)
        runtime.entry_pause_active=True; manager.request_flatten(NOW)
        self.assertEqual(manager.terms['A'].flatten_at,NOW)
        manager.request_flatten(NOW+timedelta(seconds=10))
        fresh=replace(original,observed_at=NOW+timedelta(seconds=1))
        manager.set_terms(fresh)
        self.assertEqual(manager.terms['A'],replace(fresh,flatten_at=NOW))

    def test_forced_exit_cancels_first_then_exact_ioc_and_keeps_source_guards(self):
        manager,runtime=self.manager(); manager.set_terms(terms()); runtime.entry_pause_active=True
        manager.request_flatten(NOW)
        args=dict(ticker='A',position=D(-10),basis=D('.63'),first_seen_at=NOW,
            orders=(receipt(side='bid',p='.4'),),book=book(),terms=manager.terms['A'],journal=ExitJournal(),now=NOW,complete_scope=True)
        self.assertEqual(plan_exit(**args).mode,'cancel_before_ioc')
        plan=plan_exit(**(args|dict(orders=())))
        self.assertEqual(plan.mode,'ioc'); self.assertEqual(plan.quantity,10)
        partial=plan_exit(**(args|dict(orders=(),position=D(-3))))
        self.assertEqual(partial.quantity,3)
        payload=ioc_payload(ticker='A',client_id='x',position=D(-3),limit_price=partial.limit_price,bands=terms().bands)
        self.assertTrue(payload['reduce_only']); self.assertEqual(payload['time_in_force'],'immediate_or_cancel')
        self.assertEqual(payload['side'],'bid'); self.assertEqual(D(payload['count']),3)
        self.assertNotEqual(plan_exit(**(args|dict(orders=(),complete_scope=False))).mode,'ioc')
        self.assertNotEqual(plan_exit(**(args|dict(orders=(),book=None))).mode,'ioc')
        self.assertNotEqual(plan_exit(**(args|dict(orders=(),now=terms().valid_until))).mode,'ioc')


class WorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def scenario(self, snapshots, *, timeout=3, stop_child='old'):
        with TemporaryDirectory() as root:
            clock=[100.]; rows=iter(snapshots); last=[snapshots[-1]]; events=[]
            def status():
                last[0]=next(rows,last[0]); return last[0],0
            async def sleep(seconds): clock[0]+=seconds
            stop=AsyncMock(return_value=(dict(child_id=stop_child),0))
            launch=Mock(return_value=(dict(state='HOST_STARTED'),0))
            result=await execute(SimpleNamespace(timeout=timeout,startup_timeout=3,initialize=False),
                status=status,stop=stop,launch=launch,now=lambda:clock[0],sleep=sleep,
                scope_factory=lambda:SimpleNamespace(control_root=Path(root),scope_id='test'),emit=events.append)
            return result,stop,launch,events

    async def test_cancel_flat_launch_ready_in_order(self):
        result,stop,launch,events=await self.scenario([snapshot(),snapshot(paused=True),snapshot(flat=True,stamp=100.5),snapshot(child='new',pid=456,stamp=100.5)])
        self.assertEqual(result[1],0)
        self.assertEqual([e['stage'] for e in events],['CANCELING_AND_FLATTENING','FLAT_VERIFIED','STARTING','COMPLETE'])
        stop.assert_awaited_once(); launch.assert_called_once()

    async def test_unconfirmed_flat_never_launches(self):
        bad=snapshot(flat=True,child='older')
        result,_,launch,_=await self.scenario([snapshot(),bad])
        self.assertEqual(result[0]['stage'],'BLOCKED'); launch.assert_not_called()

    async def test_owner_change_while_waiting_never_launches(self):
        result,_,launch,_=await self.scenario([snapshot(),snapshot(child='other',pid=456)])
        self.assertEqual(result[0]['reason'],'owner_changed_during_flatten_no_restart')
        launch.assert_not_called()

    async def test_timeout_reports_blocked_no_launch_or_force_kill(self):
        result,_,launch,_=await self.scenario([snapshot(),snapshot(paused=True)])
        self.assertEqual(result[0]['reason'],'flatten_timeout_no_restart'); launch.assert_not_called()

    async def test_old_build_or_changed_owner_cannot_flatten_new_child(self):
        old=snapshot(); old['last_runtime'].pop('emergency_flatten_supported')
        result,stop,launch,_=await self.scenario([old])
        self.assertEqual(result[0]['stage'],'BLOCKED'); stop.assert_not_called(); launch.assert_not_called()
        result,_,launch,_=await self.scenario([snapshot()],stop_child='changed')
        self.assertEqual(result[0]['reason'],'stop_owner_changed_or_unconfirmed'); launch.assert_not_called()

    def test_readiness_rejects_old_pid_stale_snapshot_and_recovery_only(self):
        value=snapshot(child='new',pid=456,stamp=101.)
        self.assertTrue(ready(value,previous_child='old',started=100.,now=102.))
        self.assertFalse(ready(value,previous_child='old',started=100.,now=108.))
        value['last_runtime']['recovery_only']=True
        self.assertFalse(ready(value,previous_child='old',started=100.,now=102.))

class FlattenRequestSafetyTests(unittest.TestCase):
    def test_malformed_request_never_crashes_a_draining_child(self):
        from tempfile import TemporaryDirectory
        from types import SimpleNamespace
        from kalshi_bot.supervised_live_child import _StopSignal
        with TemporaryDirectory() as root:
            args = SimpleNamespace(control_root=root, scope_id='scope', child_id='child',
                                   child_generation=3)
            signal = _StopSignal(args, SimpleNamespace())
            self.assertFalse(signal.flatten_requested())  # Absent.
            (Path(root)/'flatten-request.json').write_text('{not json', encoding='utf-8')
            self.assertFalse(signal.flatten_requested())  # Malformed: ordinary drain.
