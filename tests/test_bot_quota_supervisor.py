"""Automatic quota supervision and runtime holds with injected transports only."""
import asyncio
from copy import deepcopy
from datetime import timedelta
from dataclasses import replace
import gc
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from unittest.mock import patch
import unittest
import weakref

from kalshi_bot.quota import QuotaUnavailable
from kalshi_bot.quota_supervisor import QuotaSupervisor, RolloverBoundary
from kalshi_bot.rest import WireResponse, ReadFailure
from kalshi_bot.runtime import RecoveryRuntime
from kalshi_bot.values import InvalidData
from kalshi_bot.writer import LedgerWriter
from test_bot_quota import setup, candidate, eventually, BASE, LIMITS
from test_bot_recovery_runtime import FakeReader, event


class SupervisorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clock,self.reads,self.guard=setup()
        self.supervisor=QuotaSupervisor(self.reads,jitter=lambda:0)
    async def asyncTearDown(self):
        await self.supervisor.close()
        await self.reads.close()

    async def drain(self):
        for _ in range(100):
            self.supervisor.step()
            if self.supervisor.active is None: return
            await asyncio.sleep(.001)
        self.fail('supervisor did not drain')

    async def test_bootstrap_and_exact_scheduled_refresh(self):
        await self.drain()
        self.assertEqual((self.supervisor.started,self.supervisor.completed),(1,1))
        due=self.guard.lease.deadline_mono-self.guard.policy.refresh_lead
        self.clock.t=due-.1; await self.drain()
        self.assertEqual(self.supervisor.started,1)
        self.clock.t=due; await self.drain()
        self.assertEqual(self.supervisor.completed,2)
        self.assertFalse(self.supervisor.status()['live_authority'])

    async def test_valid_unchanged_grant_defers_once_and_downgrades_after_expiry(self):
        limits=deepcopy(LIMITS)
        limits['grants']=[dict(exchange_instance='event_contract',level='x',source='manual',
                              expires_ts=int(BASE.timestamp()+300))]
        original=self.reads.wire
        calls=[]
        def wire(url,*args):
            calls.append(url)
            if url.endswith('/limits'):
                import json
                return WireResponse(200,json.dumps(limits).encode())
            return original(url,*args)
        self.reads.wire=wire
        await self.drain()
        lease=self.guard.lease
        self.clock.t=205
        await self.drain()
        self.assertEqual((self.supervisor.failures,self.supervisor.completed),(0,1))
        self.assertTrue(self.supervisor.rollover_used)
        self.assertTrue(self.supervisor.status()['rollover_pending'])
        self.assertIs(self.guard.lease,lease)
        for _ in range(1000): self.supervisor.request_refresh()
        self.clock.t=225
        await self.drain()
        self.assertEqual((self.supervisor.started,len(calls)),(2,4))
        self.clock.t=295
        self.assertFalse(self.guard.poll())
        self.assertFalse(self.guard.status()['available'])
        limits['grants']=[]
        limits['read']=dict(refill_rate=500,bucket_capacity=500)
        self.clock.t=300
        await self.drain()
        self.assertEqual((self.supervisor.started,self.supervisor.completed),(3,2))
        self.assertFalse(self.supervisor.exhausted)
        self.assertEqual(self.reads.budget.rate,500)
        self.assertTrue(self.guard.status()['available'])

    async def test_second_near_boundary_response_spends_failure_budget(self):
        limits=deepcopy(LIMITS)
        limits['grants']=[dict(exchange_instance='event_contract',level='x',source='manual',
                              expires_ts=int(BASE.timestamp()+300))]
        original=self.reads.wire
        def wire(url,*args):
            if url.endswith('/limits'):
                import json
                return WireResponse(200,json.dumps(limits).encode())
            return original(url,*args)
        self.reads.wire=wire
        await self.drain()
        self.clock.t=205; await self.drain()
        self.clock.t=300
        limits['grants'][0]['expires_ts']=int(BASE.timestamp()+350)
        await self.drain()
        self.assertEqual(self.supervisor.failures,1)
        self.assertFalse(self.supervisor.status()['rollover_pending'])
        self.assertTrue(self.supervisor.rollover_used)

    async def test_pending_boundary_does_not_retain_candidate_or_traceback(self):
        limits=deepcopy(LIMITS)
        limits['grants']=[dict(exchange_instance='event_contract',level='x',source='manual',
                              expires_ts=int(BASE.timestamp()+300))]
        original_wire=self.reads.wire
        def wire(url,*args):
            if url.endswith('/limits'):
                import json
                return WireResponse(200,json.dumps(limits).encode())
            return original_wire(url,*args)
        self.reads.wire=wire
        await self.drain()
        candidate_refs=[]
        original_install=self.guard.install
        def observe(item):
            candidate_refs.append(weakref.ref(item))
            return original_install(item)
        self.clock.t=205
        with patch.object(self.guard,'install',observe):
            await self.drain()
        await eventually(lambda:self.reads.budget_refresh is None)
        # budget_refresh clears before every done callback holding the completed
        # task has run. Test lasting ownership only after that callback turn.
        await asyncio.sleep(0)
        gc.collect()
        self.assertIsInstance(self.supervisor.rollover,RolloverBoundary)
        self.assertEqual(len(candidate_refs),1)
        self.assertIsNone(candidate_refs[0]())
        self.assertEqual((self.supervisor.failures,self.supervisor.completed),(0,1))

    async def test_run_status_after_second_cancellation_during_drain(self):
        entered,release=Event(),Event()
        def wire(url,*_):
            if url.endswith('endpoint_costs'):
                entered.set();release.wait(3)
                return WireResponse(429,b'')
            return WireResponse(200,b'{}')
        self.reads.wire=wire
        run_task=asyncio.create_task(self.supervisor.run())
        try:
            await eventually(entered.is_set)
            run_task.cancel()
            await eventually(lambda:self.supervisor.stopping)
            await asyncio.sleep(0)
            run_task.cancel()
            await asyncio.gather(run_task,return_exceptions=True)
            self.assertFalse(self.supervisor.running)
            self.assertTrue(self.supervisor.used)
            self.assertTrue(self.supervisor.stopping)
            self.assertEqual(self.reads._slot_used,1)
            release.set()
            await self.supervisor.close()
            await self.reads.close()
            self.assertFalse(self.supervisor.running)
            self.assertEqual(self.reads._slot_used,0)
            self.assertEqual(self.reads.budget.throttles,1)
        finally:
            release.set()
            await asyncio.gather(run_task,return_exceptions=True)

    async def test_failure_then_deferral_preserves_failure_count(self):
        limits=deepcopy(LIMITS)
        limits['grants']=[dict(exchange_instance='event_contract',level='x',source='manual',
                              expires_ts=int(BASE.timestamp()+300))]
        original=self.reads.wire
        def wire(url,*args):
            if 205<=self.clock.t<210 and url.endswith('endpoint_costs'):
                return WireResponse(500,b'')
            if url.endswith('/limits'):
                import json
                return WireResponse(200,json.dumps(limits).encode())
            return original(url,*args)
        self.reads.wire=wire
        await self.drain()
        self.clock.t=205
        await self.drain()
        self.assertEqual(self.supervisor.failures,1)
        self.clock.t=self.supervisor.not_before
        await self.drain()
        self.assertEqual(self.supervisor.failures,1)
        self.assertTrue(self.supervisor.status()['rollover_pending'])
        self.clock.t=300.01
        limits['grants']=[]
        await self.drain()
        self.assertEqual((self.supervisor.failures,self.supervisor.completed),(0,2))

    async def test_early_renewal_installs_without_deferral(self):
        limits=deepcopy(LIMITS)
        limits['grants']=[dict(exchange_instance='event_contract',level='x',source='manual',
                              expires_ts=int(BASE.timestamp()+300))]
        original=self.reads.wire
        def wire(url,*args):
            if url.endswith('/limits'):
                import json
                return WireResponse(200,json.dumps(limits).encode())
            return original(url,*args)
        self.reads.wire=wire
        await self.drain()
        self.clock.t=205
        limits['grants'][0]['expires_ts']=int(BASE.timestamp()+500)
        await self.drain()
        self.assertEqual(self.supervisor.completed,2)
        self.assertFalse(self.supervisor.rollover_used)
        self.assertFalse(self.supervisor.status()['rollover_pending'])
        self.assertGreater(self.guard.lease.deadline_mono,295)

    async def test_explicit_refresh_clock_fault_during_cooldown_finishes(self):
        self.reads.wire=lambda *_:WireResponse(401,b'')
        await self.drain()
        self.supervisor.running=True
        self.assertTrue(self.supervisor.request_refresh(retry=True))
        waiter=asyncio.create_task(self.reads.refresh_budget())
        await asyncio.sleep(0)
        self.assertFalse(waiter.done())
        self.clock.offset=3
        self.guard.poll()
        with self.assertRaises(QuotaUnavailable):
            await asyncio.wait_for(waiter,1)
        self.assertEqual(self.supervisor.started,1)

    async def test_explicit_refresh_close_during_cooldown_finishes(self):
        self.reads.wire=lambda *_:WireResponse(401,b'')
        await self.drain()
        self.supervisor.running=True
        self.supervisor.request_refresh(retry=True)
        waiter=asyncio.create_task(self.reads.refresh_budget())
        await asyncio.sleep(0)
        await self.reads.close()
        with self.assertRaises(QuotaUnavailable):
            await asyncio.wait_for(waiter,1)
        self.assertEqual(self.supervisor.started,1)

    async def test_cancelled_supervisor_close_keeps_active_worker_owned(self):
        entered,release=Event(),Event()
        self.guard.policy=replace(self.guard.policy,pair_timeout=.03)
        def wire(url,*_):
            if url.endswith('endpoint_costs'):
                entered.set(); release.wait(3)
                return WireResponse(429,b'')
            return WireResponse(200,b'{}')
        self.reads.wire=wire
        actual_timeout=asyncio.timeout
        controlled=[]
        def timeout(delay):
            if delay==.03:
                handle=actual_timeout(None)
                controlled.append(handle)
                return handle
            return actual_timeout(delay)
        with patch('kalshi_bot.rest.asyncio.timeout',timeout):
            self.supervisor.step()
            second_close=None
            try:
                await eventually(entered.is_set)
                controlled[0].reschedule(asyncio.get_running_loop().time())
                await eventually(lambda:self.reads._control_scope is None)
                close=asyncio.create_task(self.supervisor.close())
                await asyncio.sleep(0)
                close.cancel()
                await asyncio.gather(close,return_exceptions=True)
                self.assertEqual((self.reads._slot_used,len(self.reads._control_tasks)),(1,1))
                second_close=asyncio.create_task(self.supervisor.close())
                await asyncio.sleep(0)
                self.assertFalse(second_close.done())
                release.set()
                await asyncio.wait_for(second_close,2)
                self.assertEqual(self.reads.budget.throttles,1)
                self.assertEqual(self.reads._slot_used,0)
            finally:
                release.set()
                if second_close is not None:
                    await asyncio.gather(second_close,return_exceptions=True)

    async def test_request_storm_coalesces_one_pair(self):
        self.supervisor.step()
        for _ in range(1000): self.supervisor.request_refresh()
        await self.drain()
        self.assertEqual(self.supervisor.started,1)
        self.assertEqual(self.reads.budget.spent,20)

    async def test_retry_exhaustion_and_explicit_cooldown(self):
        self.reads.wire=lambda *_:WireResponse(500,b'')
        for failure in range(1,4):
            await self.drain()
            self.assertEqual(self.supervisor.failures,failure)
            if failure<3: self.clock.t=self.supervisor.not_before
        self.assertTrue(self.supervisor.exhausted)
        self.assertFalse(self.supervisor.request_refresh())
        deadline=self.supervisor.not_before
        self.assertTrue(self.supervisor.request_refresh(retry=True))
        await self.drain()
        self.assertEqual(self.supervisor.started,3)
        self.assertEqual(self.supervisor.not_before,deadline)

    async def test_auth_failure_exhausts_without_three_pair_retries(self):
        self.reads.wire=lambda *_:WireResponse(401,b'')
        await self.drain()
        self.assertTrue(self.supervisor.exhausted)
        self.assertEqual((self.supervisor.started,self.supervisor.failures),(1,1))

    async def test_early_failure_does_not_extend_good_lease(self):
        await self.drain(); lease=self.guard.lease
        self.reads.wire=lambda *_:WireResponse(500,b'')
        self.clock.t=lease.deadline_mono-90
        await self.drain()
        self.assertIs(self.guard.lease,lease)
        self.assertTrue(self.guard.poll())
        self.clock.t=lease.deadline_mono
        self.guard.poll()
        self.assertFalse(self.guard.status()['available'])

    async def test_clock_fault_does_not_auto_reanchor(self):
        await self.drain(); self.clock.offset=10
        self.supervisor.step()
        self.assertEqual(self.guard.state,'clock_fault')
        self.clock.offset=0
        self.assertFalse(self.supervisor.request_refresh(retry=True))
        self.supervisor.step()
        self.assertEqual(self.supervisor.started,1)

    async def test_direct_refresh_obeys_supervisor_exhaustion(self):
        self.supervisor.running=True; self.supervisor.exhausted=True
        with self.assertRaises(QuotaUnavailable): await self.reads.refresh_budget()
        self.assertIsNone(self.reads.budget_refresh)

    async def test_unexpected_fault_propagates(self):
        async def failure(): raise RuntimeError('fixture')
        with patch.object(self.reads,'_refresh_budget_owned',failure):
            self.supervisor.step()
            await asyncio.sleep(0)
            with self.assertRaises(RuntimeError): self.supervisor.step()

    async def test_stop_and_reuse_rejected(self):
        task=asyncio.create_task(self.supervisor.run())
        await eventually(lambda:self.supervisor.completed==1)
        self.supervisor.stop(); await task
        self.assertEqual(self.guard.state,'stopped')
        self.assertFalse(self.supervisor.request_refresh(retry=True))
        self.assertIsNone(self.supervisor.active)
        with self.assertRaises(InvalidData): await self.supervisor.run()


class RuntimeQuotaTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=TemporaryDirectory()
        self.writer=await LedgerWriter(Path(self.temp.name)/'quota.db').start()
        self.clock,self.reads,self.guard=setup()
        self.supervisor=QuotaSupervisor(self.reads,jitter=lambda:0)
        self.connections={}
        def factory(spec):
            reader=FakeReader(spec); self.connections[spec.name]=reader; return reader
        async def noop(*_): pass
        self.runtime=RecoveryRuntime(self.writer,self.reads,factory,tickers=('A','B'),subaccount=0,
            history_start=BASE-timedelta(seconds=60),now=self.clock.now,clock=self.clock,
            evaluate=noop,deadline_handler=noop,lifecycle_handler=noop,quota_supervisor=self.supervisor)
        self.tasks=[]
    async def asyncTearDown(self):
        self.runtime.stop()
        for task in self.tasks: task.cancel()
        await asyncio.gather(*self.tasks,return_exceptions=True)
        await self.supervisor.close(); await self.reads.close(); await self.writer.close()
        self.temp.cleanup()

    async def test_stream_fill_durable_during_quota_outage(self):
        self.reads.wire=lambda *_:WireResponse(401,b'')
        task=asyncio.create_task(self.runtime.run()); self.tasks.append(task)
        await eventually(lambda:self.runtime.account_subscribed and self.supervisor.exhausted)
        self.connections['account'].queue.put_nowait(event('unknown'))
        async with asyncio.timeout(3):
            while not await self.writer.pending_fills(0): await asyncio.sleep(.001)
        self.assertEqual(len(await self.writer.pending_fills(0)),1)
        self.assertEqual(self.runtime.recovery_attempts,0)
        self.assertFalse(self.runtime.entry_allowed)
        self.assertIn('quota_unavailable',self.runtime.verification_status()['blockers'])
        self.runtime.stop(); await task

    async def test_quota_hold_does_not_consume_recovery_attempt(self):
        self.guard.install(candidate(self.guard))
        calls=0
        async def recover():
            nonlocal calls
            calls+=1
            if calls==1:
                self.clock.t+=301; self.guard.poll()
                raise QuotaUnavailable()
            return True
        self.runtime.recover_once=recover
        self.runtime.account_subscribed=True
        self.runtime.request_recovery()
        task=asyncio.create_task(self.runtime._recover()); self.tasks.append(task)
        await eventually(lambda:self.runtime.recovery_state=='awaiting_quota')
        self.assertEqual(self.runtime.recovery_attempts,0)
        self.guard.install(candidate(self.guard))
        await eventually(lambda:self.runtime.recovery_state=='repaired_entries_blocked')
        self.assertEqual((calls,self.runtime.recovery_attempts),(2,1))

    async def test_quota_recovery_preserves_independent_exhaustion(self):
        self.runtime.recovery_state='blocked_retry_exhausted'
        self.runtime.recovery_attempts=3
        self.guard.install(candidate(self.guard))
        self.assertFalse(self.runtime.recovery_requested.is_set())
        self.clock.t+=301; self.guard.poll()
        self.guard.install(candidate(self.guard))
        self.assertEqual(self.runtime.recovery_state,'blocked_retry_exhausted')
        self.assertEqual(self.runtime.recovery_attempts,3)
        self.assertFalse(self.runtime.recovery_requested.is_set())

    async def test_revocation_occurs_once_not_per_status_read(self):
        self.guard.install(candidate(self.guard)); before=self.runtime.ingress_revision
        self.clock.t+=301
        for _ in range(100): self.guard.status()
        self.assertEqual(self.runtime.ingress_revision,before+1)

    async def test_logging_failure_still_stops_runtime(self):
        def fail(): raise InvalidData('fixture log failure')
        with patch.object(self.runtime.diagnostics,'ensure_healthy',fail):
            with self.assertRaises(InvalidData): await self.runtime.run()
        self.assertEqual(self.guard.state,'stopped')


class MetadataHoldTests(unittest.IsolatedAsyncioTestCase):
    async def test_quota_hold_preserves_market_failures_and_exhaustion(self):
        from kalshi_bot.market_inputs import ExitInputService
        from kalshi_bot.metadata_scheduler import MetadataScheduler
        clock,reads,guard=setup()
        service=ExitInputService(reads,('A','B'),now=clock.now,clock=clock,ttl=10)
        service.bind(lambda _:None,lambda _:None)
        service.begin(1)
        service.subscribed(1,1)
        scheduler=MetadataScheduler(service)
        scheduler.failures['A']=1; scheduler.exhausted.add('B')
        scheduler.request('A'); scheduler.request('B')
        try:
            for _ in range(10): scheduler.step()
            self.assertFalse(scheduler.active)
            self.assertEqual(scheduler.failures,{'A':1})
            self.assertEqual(scheduler.exhausted,{'B'})
            # Exercise a hold returned by an already active dependency.
            async def blocked(_): raise QuotaUnavailable()
            guard.install(candidate(guard))
            with patch.object(service,'refresh',blocked):
                scheduler.step(); await asyncio.sleep(0); scheduler.step()
            self.assertEqual(scheduler.failures,{'A':1})
            self.assertEqual(scheduler.exhausted,{'B'})
        finally:
            await scheduler.close(); await reads.close()
