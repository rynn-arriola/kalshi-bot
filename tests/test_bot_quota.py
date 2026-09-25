"""Quota leases and real GET dispatch with injected clocks/wire, never accounts."""
import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from threading import Event
from unittest.mock import patch
import unittest

from kalshi_bot.quota import (ProbeConfig, QuotaPolicy, QuotaScope, QuotaGuard,
                              QuotaRolloverPending,
                              QuotaUnavailable, parse_candidate)
from kalshi_bot.rest import RestReads, TokenBudget, WireResponse
from kalshi_bot.values import InvalidData

LIMITS = dict(usage_tier='fixture', grants=[], read=dict(refill_rate=10000, bucket_capacity=10000),
              write=dict(refill_rate=100, bucket_capacity=100))
COSTS = dict(default_cost=10, endpoint_costs=[])
BASE = datetime(2026, 9, 20, tzinfo=timezone.utc)


class Clock:
    def __init__(self): self.t, self.offset = 0., 0.
    def __call__(self): return self.t
    def now(self): return BASE+timedelta(seconds=self.t+self.offset)
    async def sleep(self, delay):
        self.t += delay
        await asyncio.sleep(0)


class Signer:
    def headers(self, *_): return {}


def setup(*, wire=None, clock=None, policy=None, **kwargs):
    clock = clock or Clock()
    policy = policy or QuotaPolicy(ProbeConfig(10000, 10000, 10, 10))
    def default_wire(url, *_):
        return WireResponse(200, json.dumps(COSTS if url.endswith('endpoint_costs') else
            LIMITS if url.endswith('/limits') else dict(ok=True)).encode())
    reads = RestReads(TokenBudget(rate=1, capacity=10, default_cost=10,
        clock=clock, sleep=clock.sleep), Signer(), wire=wire or default_wire, **kwargs)
    guard = QuotaGuard(policy, clock=clock, now=clock.now)
    reads.attach_quota(guard)
    return clock, reads, guard


def candidate(guard, limits=None, costs=None):
    epoch, sequence, start = guard.begin()
    return parse_candidate(deepcopy(LIMITS if limits is None else limits),
        deepcopy(COSTS if costs is None else costs), scope=guard.scope, epoch=epoch,
        sequence=sequence, start=start, end=guard._sample())


async def eventually(predicate):
    async with asyncio.timeout(3):
        while not predicate(): await asyncio.sleep(.001)


class LeaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clock, self.reads, self.guard = setup()
    async def asyncTearDown(self): await self.reads.close()

    def install(self, limits=None, costs=None):
        self.guard.install(candidate(self.guard, limits, costs))

    async def test_empty_grants_and_unknown_tier_use_numeric_limits(self):
        self.install()
        self.assertTrue(self.guard.poll())
        self.assertEqual(self.reads.budget.rate, 10000)
        self.assertEqual(self.reads.budget.tokens, 0)
        self.assertFalse(self.guard.status()['write_enabled'])

    async def test_grants_earliest_event_lane_even_lower_tier(self):
        limits = deepcopy(LIMITS)
        limits['grants'] = [dict(exchange_instance='margined', level='x', source='manual', expires_ts=1),
            dict(exchange_instance='event_contract', level='high', source='manual'),
            dict(exchange_instance='event_contract', level='low', source='volume', expires_ts=int(BASE.timestamp()+200))]
        self.install(limits)
        self.assertEqual(self.guard.lease.deadline_mono, 195)
        self.clock.t = 195
        with self.assertRaises(QuotaUnavailable): self.guard.check('/markets/{ticker}')

    async def test_invalid_grants_do_not_install(self):
        row = dict(exchange_instance='event_contract', level='x', source='manual')
        for changes in ({'expires_ts':None}, {'expires_ts':True}, {'expires_ts':-1},
                        {'expires_ts':1.5}, {'exchange_instance':'unknown'}, {'level':''}, {'source':None}):
            limits = deepcopy(LIMITS)
            limits['grants'] = [dict(row, **changes)]
            with self.subTest(changes=changes), self.assertRaises(InvalidData): self.install(limits)
        self.assertIsNone(self.guard.lease)

    async def test_permanent_and_nullable_other_lane(self):
        limits = deepcopy(LIMITS)
        limits['grants'] = [dict(exchange_instance='event_contract', level='x', source='manual'),
            dict(exchange_instance='margined', level='x', source='manual', expires_ts=None)]
        self.install(limits)
        self.assertEqual(self.guard.lease.deadline_mono, 300)

    async def test_grant_and_cost_bounds_required_fields(self):
        for key in LIMITS:
            limits = deepcopy(LIMITS); limits.pop(key)
            with self.subTest(key=key), self.assertRaises(InvalidData): self.install(limits)
        limits = deepcopy(LIMITS); limits['grants'] = [{}]*129
        with self.assertRaises(InvalidData): self.install(limits)
        with self.assertRaises(InvalidData): self.install(costs=dict(default_cost=10,endpoint_costs=[{}]*2049))

    async def test_cost_prefix_method_and_duplicate_validation(self):
        self.install(costs=dict(default_cost=10, endpoint_costs=[
            dict(method='GET', path='/trade-api/v2/markets/{ticker}', cost=20),
            dict(method='POST', path='/markets/{ticker}', cost=30)]))
        self.assertEqual(self.reads.budget.costs, {'/markets/{ticker}':20})
        with self.assertRaises(InvalidData):
            self.install(costs=dict(default_cost=10,endpoint_costs=[
                dict(method='GET', path='/markets/{ticker}', cost=20),
                dict(method='GET', path='/trade-api/v2/markets/{ticker}', cost=30)]))

    async def test_expiry_is_anchored_at_start_and_equal_is_expired(self):
        item = candidate(self.guard)
        self.clock.t = 10
        self.guard.install(item)
        self.assertEqual(self.guard.lease.deadline_mono, 300)
        self.clock.t = 300
        self.assertFalse(self.guard.poll())
        with self.assertRaises(QuotaUnavailable): await self.reads.read('market',reason='metadata',ticker='A')

    async def test_late_and_near_expiry_candidates_rejected(self):
        item = candidate(self.guard)
        self.clock.t = 66
        with self.assertRaises(QuotaUnavailable): self.guard.install(item)
        limits = deepcopy(LIMITS)
        limits['grants'] = [dict(exchange_instance='event_contract', level='x', source='manual',
                                  expires_ts=int(self.clock.now().timestamp()+90))]
        with self.assertRaises(QuotaRolloverPending): self.install(limits)

    async def test_boundary_observation_keeps_identical_lease_without_extending_it(self):
        limits=deepcopy(LIMITS)
        limits['grants']=[dict(exchange_instance='event_contract',level='x',source='manual',
                              expires_ts=int(BASE.timestamp()+300))]
        self.install(limits)
        lease=self.guard.lease
        revision=self.guard.revision
        self.clock.t=205
        with self.assertRaises(QuotaRolloverPending) as caught:
            self.install(limits)
        self.assertEqual(caught.exception.expiry_mono,300)
        self.assertIs(self.guard.lease,lease)
        self.assertEqual((self.guard.revision,lease.deadline_mono),(revision,295))
        self.clock.t=295
        self.assertFalse(self.guard.poll())

    async def test_changed_read_evidence_revokes_before_boundary(self):
        limits=deepcopy(LIMITS)
        limits['grants']=[dict(exchange_instance='event_contract',level='x',source='manual',
                              expires_ts=int(BASE.timestamp()+300))]
        self.install(limits)
        self.clock.t=205
        changed=deepcopy(limits)
        changed['read']['refill_rate']=9000
        with self.assertRaises(QuotaRolloverPending): self.install(changed)
        self.assertEqual(self.guard.state,'stale')
        self.assertFalse(self.guard.status()['available'])
        self.assertEqual(self.reads.budget.rate,10000)  # Retained probe, not new settings.

    async def test_near_boundary_cold_start_is_typed_hold(self):
        limits=deepcopy(LIMITS)
        limits['grants']=[dict(exchange_instance='event_contract',level='x',source='manual',
                              expires_ts=int(BASE.timestamp()+90))]
        with self.assertRaises(QuotaRolloverPending): self.install(limits)
        self.assertIsNone(self.guard.lease)
        self.assertFalse(self.guard.status()['available'])

    async def test_changed_endpoint_cost_revokes_before_boundary(self):
        limits=deepcopy(LIMITS)
        limits['grants']=[dict(exchange_instance='event_contract',level='x',source='manual',
                              expires_ts=int(BASE.timestamp()+300))]
        self.install(limits)
        self.clock.t=205
        costs=dict(default_cost=12,endpoint_costs=[])
        with self.assertRaises(QuotaRolloverPending): self.install(limits,costs)
        self.assertEqual(self.guard.state,'stale')
        self.assertFalse(self.guard.status()['available'])

    async def test_expired_grant_and_stale_pair_do_not_defer(self):
        limits=deepcopy(LIMITS)
        limits['grants']=[dict(exchange_instance='event_contract',level='x',source='manual',
                              expires_ts=int(BASE.timestamp()+90))]
        item=candidate(self.guard,limits)
        self.clock.t=90
        with self.assertRaises(QuotaUnavailable) as caught: self.guard.install(item)
        self.assertNotIsInstance(caught.exception,QuotaRolloverPending)
        self.clock.t=91
        item=candidate(self.guard,limits)
        with self.assertRaises(QuotaUnavailable) as caught: self.guard.install(item)
        self.assertNotIsInstance(caught.exception,QuotaRolloverPending)

    async def test_scope_sequence_and_stopped_epoch(self):
        item = candidate(self.guard)
        with self.assertRaises(QuotaUnavailable): self.guard.install(replace(item,scope=QuotaScope()))
        candidate(self.guard)
        with self.assertRaises(QuotaUnavailable): self.guard.install(item)
        item = candidate(self.guard)
        self.guard.stop()
        with self.assertRaises(QuotaUnavailable): self.guard.install(item)

    async def test_clock_drift_is_sticky(self):
        self.install()
        self.clock.offset = 3
        self.assertFalse(self.guard.poll())
        self.clock.offset = 0
        self.assertFalse(self.guard.poll())
        self.assertEqual(self.guard.state, 'clock_fault')
        with self.assertRaises(QuotaUnavailable): await self.reads.refresh_budget()

    async def test_slow_cumulative_drift_is_not_a_clock_fault(self):
        # D-131: measured live drift is ~64 ms/hour; 40 polls x 0.1 s = 4 s
        # total drift must not fault, while each step stays within tolerance.
        self.install()
        for step in range(1, 41):
            self.clock.t = step*10
            self.clock.offset = -0.1*step
            self.guard.poll()
            self.assertNotEqual(self.guard.state, 'clock_fault')

    async def test_monotonic_regression(self):
        self.install(); self.clock.t = 1; self.guard.poll(); self.clock.t = .9
        self.assertFalse(self.guard.poll())
        self.assertEqual(self.guard.state, 'clock_fault')

    async def test_probe_transition_never_resets_on_status_reads(self):
        self.install(); self.clock.t = 301; self.guard.poll()
        self.reads.budget.throttle(5)
        original = (self.reads.budget.updated,self.reads.budget.blocked_until,self.reads.budget.configuration_revision)
        for _ in range(10000): self.guard.status()
        self.assertEqual(original, (self.reads.budget.updated,self.reads.budget.blocked_until,
                                   self.reads.budget.configuration_revision))

    async def test_probe_clamps_old_allowance_and_does_not_truncate_cost(self):
        limits = deepcopy(LIMITS); limits['read'] = dict(refill_rate=1,bucket_capacity=20)
        self.install(limits, dict(default_cost=10, endpoint_costs=[dict(method='GET',path='/account/limits',cost=30)]))
        self.clock.t = 301; self.guard.poll()
        self.assertEqual((self.reads.budget.rate,self.reads.budget.capacity),(1,20))
        self.assertEqual(self.reads.budget.costs['/account/limits'],30)

    async def test_direct_budget_reconfiguration_is_blocked(self):
        with self.assertRaises(QuotaUnavailable): self.reads.budget.reconfigure(LIMITS,COSTS)
        with self.assertRaises(QuotaUnavailable): await self.reads.budget.acquire('/account/limits',30)

    async def test_policy_rejects_bad_configuration(self):
        for changes in ({'maximum_age':False},{'pair_timeout':100},{'refresh_lead':301},{'clock_tolerance':float('nan')}):
            with self.subTest(changes=changes), self.assertRaises(InvalidData): replace(self.guard.policy,**changes)
        with self.assertRaises(InvalidData): ProbeConfig(1,1,2,1)


class DispatchTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.calls = []
        self.gate = Event(); self.gate.set()
        self.entered = Event()
        self.payloads = deepcopy({'limits':LIMITS,'endpoint_costs':COSTS})
        self.response = None
        def wire(url, *_):
            self.calls.append(url)
            if '/markets/' in url:
                self.entered.set()
                self.gate.wait(3)
                return self.response or WireResponse(200,b'{"ok":true}')
            return WireResponse(200,json.dumps(self.payloads[url.rsplit('/',1)[-1]]).encode())
        self.clock, self.reads, self.guard = setup(wire=wire)
    async def asyncTearDown(self):
        self.gate.set()
        await self.reads.close()

    async def test_cold_and_unforgeable_ordinary_control_calls(self):
        for name in ('limits','costs'):
            with self.assertRaises(QuotaUnavailable): await self.reads.read(name,reason='budget')
        with self.assertRaises(InvalidData): await self.reads.read('limits',reason='budget',_control_scope=object())
        self.assertEqual(self.calls,[])

    async def test_coalesced_pair_and_shared_budget(self):
        results = await asyncio.gather(*(self.reads.refresh_budget() for _ in range(20)))
        self.assertEqual(len(self.calls),2)
        self.assertTrue(self.calls[0].endswith('endpoint_costs'))
        self.assertEqual(self.reads.budget.spent,20)
        self.assertEqual({row['quota']['revision'] for row in results},{1})
        await self.reads.read('market',reason='metadata',ticker='A')
        self.assertEqual(self.reads.budget.spent,30)

    async def test_bad_second_document_preserves_existing_lease(self):
        await self.reads.refresh_budget(); before = self.guard.lease
        self.payloads['limits'] = {}
        with self.assertRaises(InvalidData): await self.reads.refresh_budget()
        self.assertIs(self.guard.lease,before)
        self.assertTrue(self.guard.poll())

    async def test_late_response_rejected_and_429_still_shared(self):
        for response in (WireResponse(200,b'{}'),WireResponse(429,b'')):
            self.gate.clear(); self.entered.clear(); self.response=response
            await self.reads.refresh_budget()
            request = asyncio.create_task(self.reads.read('market',reason='metadata',ticker='A'))
            await eventually(self.entered.is_set)
            self.clock.t += 301; self.guard.poll(); self.gate.set()
            with self.assertRaises(QuotaUnavailable): await request
        self.assertGreater(self.reads.budget.blocked_until,self.clock.t)
        self.assertEqual(self.reads.budget.throttles,1)

    async def test_cancelled_consumer_retains_wire_slot(self):
        await self.reads.refresh_budget()
        self.gate.clear()
        task = asyncio.create_task(self.reads.read('market',reason='metadata',ticker='A'))
        await eventually(self.entered.is_set); task.cancel()
        await asyncio.gather(task,return_exceptions=True)
        self.assertEqual(self.reads._slot_used,1)
        self.gate.set()
        await eventually(lambda:not self.reads.inflight)
        self.assertEqual(self.reads._slot_used,0)

    async def test_old_revision_response_not_shared_after_refresh(self):
        await self.reads.refresh_budget(); self.gate.clear()
        old = asyncio.create_task(self.reads.read('market',reason='metadata',ticker='A'))
        await eventually(self.entered.is_set)
        await self.reads.refresh_budget()
        self.gate.set()
        with self.assertRaises(QuotaUnavailable): await old
        await self.reads.read('market',reason='metadata',ticker='A')
        self.assertEqual(sum('/markets/' in c for c in self.calls),2)

    async def test_admission_reserves_control_under_critical_saturation(self):
        await self.reads.refresh_budget(); self.gate.clear()
        # Critical requests use distinct public cost-read scopes; blocking wire
        # via the same fixture gate keeps all 31 admissions occupied.
        original = self.reads.wire
        def gated(url,*args):
            if url.endswith('endpoint_costs') and not self.allow_control:
                self.entered.set(); self.gate.wait(3)
            return original(url,*args)
        self.allow_control=False; self.reads.wire=gated
        tasks=[asyncio.create_task(self.reads.read('costs',reason='budget',coalesce_scope=i)) for i in range(31)]
        await eventually(lambda:len(self.reads.inflight)==31)
        with self.assertRaises(InvalidData): await self.reads.read('costs',reason='budget',coalesce_scope=32)
        refresh=asyncio.create_task(self.reads.refresh_budget())
        await eventually(lambda:len(self.reads.inflight)==32)
        self.allow_control=True; self.gate.set()
        await refresh
        await asyncio.gather(*tasks,return_exceptions=True)
        self.assertFalse(self.reads._slot_waiters)
        self.assertEqual(self.reads._slot_used,0)

    async def test_scope_change_blocks_dispatch(self):
        await self.reads.refresh_budget(); self.reads.signer=Signer()
        with self.assertRaises(QuotaUnavailable): await self.reads.read('market',reason='metadata',ticker='A')

    async def test_token_wait_is_revoked_by_shared_clock_watch(self):
        limits=deepcopy(LIMITS)
        limits['read']=dict(refill_rate=1,bucket_capacity=10)
        limits['grants']=[dict(exchange_instance='event_contract',level='x',source='manual',
                               expires_ts=int(BASE.timestamp()+100))]
        self.guard.install(candidate(self.guard,limits))
        self.clock.t=94
        # Drain the elapsed refill first; hold the head timer without advancing
        # fixture time. The single shared watchdog must revoke this wait.
        self.reads.budget.tokens=0; self.reads.budget.updated=94
        async def held_sleep(_): await asyncio.Event().wait()
        self.reads.budget.sleep=held_sleep
        task=asyncio.create_task(self.reads.read('market',reason='metadata',ticker='A'))
        await eventually(lambda:bool(self.reads.budget.waiters))
        self.clock.t=95
        with self.assertRaises(QuotaUnavailable): await asyncio.wait_for(task,2)
        self.assertEqual(self.calls,[])
        self.assertFalse(self.reads.budget.waiters)

    async def test_waiting_slot_never_dispatches_after_expiry(self):
        await self.reads.refresh_budget(); self.gate.clear()
        first=asyncio.create_task(self.reads.read('market',reason='metadata',ticker='A'))
        second=asyncio.create_task(self.reads.read('market',reason='metadata',ticker='B'))
        await eventually(lambda:bool(self.reads._slot_waiters))
        self.clock.t+=301; self.guard.poll()
        with self.assertRaises(QuotaUnavailable): await second
        self.gate.set()
        with self.assertRaises(QuotaUnavailable): await first
        self.assertFalse(any(url.endswith('/B') for url in self.calls))

    async def test_superseded_pair_drains_before_retry(self):
        entered,release=Event(),Event()
        original=self.reads.wire
        def wire(url,*args):
            if url.endswith('endpoint_costs'):
                entered.set(); release.wait(3)
            return original(url,*args)
        self.reads.wire=wire
        task=asyncio.create_task(self.reads.refresh_budget())
        try:
            await eventually(entered.is_set)
            self.guard.stop()
            self.assertEqual(len(self.reads._control_tasks),1)
            self.assertIsNotNone(self.reads.budget_refresh)
            release.set()
            with self.assertRaises(QuotaUnavailable): await task
            self.assertIsNone(self.guard.lease)
            self.assertFalse(self.reads._control_tasks)
        finally:
            release.set(); await asyncio.gather(task,return_exceptions=True)

    async def test_refresh_consumer_cancel_does_not_cancel_pair(self):
        entered,release=Event(),Event()
        original=self.reads.wire
        def wire(url,*args):
            if url.endswith('endpoint_costs'):
                entered.set(); release.wait(3)
            return original(url,*args)
        self.reads.wire=wire
        task=asyncio.create_task(self.reads.refresh_budget())
        try:
            await eventually(entered.is_set); task.cancel()
            await asyncio.gather(task,return_exceptions=True)
            pair=self.reads.budget_refresh
            self.assertIsNotNone(pair)
            release.set(); await pair
            self.assertTrue(self.guard.poll())
        finally: release.set()

    async def test_timeout_drains_wire_before_another_pair_can_start(self):
        entered,release=Event(),Event()
        original=self.reads.wire
        self.guard.policy=replace(self.guard.policy,pair_timeout=.03)
        count=0
        def wire(url,*args):
            nonlocal count
            count+=1
            if count==1:
                entered.set(); release.wait(3)
            return original(url,*args)
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
            first=asyncio.create_task(self.reads.refresh_budget())
            try:
                await eventually(entered.is_set)
                self.assertEqual(len(controlled),1)
                controlled[0].reschedule(asyncio.get_running_loop().time())
                await eventually(lambda:self.reads._control_scope is None)
                second=asyncio.create_task(self.reads.refresh_budget())
                await asyncio.sleep(0)
                self.assertEqual(count,1)
                self.assertFalse(first.done())
                release.set()
                results=await asyncio.gather(first,second,return_exceptions=True)
                self.assertTrue(all(isinstance(result,TimeoutError) for result in results))
                self.assertIsNone(self.guard.lease)
                self.guard.policy=replace(self.guard.policy,pair_timeout=65)
                await self.reads.refresh_budget()
                self.assertEqual(count,3)
            finally:
                release.set(); await asyncio.gather(first,return_exceptions=True)

    async def test_cancelled_close_keeps_late_429_worker_owned(self):
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
            refresh=asyncio.create_task(self.reads.refresh_budget())
            second_close=None
            try:
                await eventually(entered.is_set)
                controlled[0].reschedule(asyncio.get_running_loop().time())
                await eventually(lambda:self.reads._control_scope is None)
                close=asyncio.create_task(self.reads.close())
                await eventually(lambda:self.reads._close_task is not None)
                close.cancel()
                await asyncio.gather(close,return_exceptions=True)
                self.assertEqual((self.reads._slot_used,len(self.reads._control_tasks)),(1,1))
                self.assertFalse(self.reads._close_task.done())
                second_close=asyncio.create_task(self.reads.close())
                await asyncio.sleep(0)
                self.assertFalse(second_close.done())
                release.set()
                await asyncio.wait_for(second_close,2)
                with self.assertRaises(TimeoutError): await refresh
                self.assertEqual(self.reads.budget.throttles,1)
                self.assertEqual(self.reads._slot_used,0)
                self.assertFalse(self.reads._control_tasks)
            finally:
                release.set()
                await asyncio.gather(refresh,*([] if second_close is None else [second_close]),
                                     return_exceptions=True)

    async def test_pair_timeout_before_worker_dispatch_owns_no_thread(self):
        self.guard.policy=replace(self.guard.policy,pair_timeout=.03)
        calls=[]
        self.reads.wire=lambda *_: calls.append(1) or WireResponse(200,b'{}')
        actual_timeout=asyncio.timeout
        with patch('kalshi_bot.rest.asyncio.timeout',
                   lambda delay: actual_timeout(0) if delay==.03 else actual_timeout(delay)):
            with self.assertRaises(TimeoutError): await self.reads.refresh_budget()
        self.assertEqual(calls,[])
        self.assertEqual(self.reads._slot_used,0)
        self.assertFalse(self.reads._control_tasks)
        self.assertIsNone(self.guard.lease)

    async def test_late_refresh_candidate_cannot_extend_its_observation(self):
        original=self.reads.wire
        def wire(url,*args):
            if url.endswith('/limits'): self.clock.t+=66
            return original(url,*args)
        self.reads.wire=wire
        with self.assertRaises(InvalidData): await self.reads.refresh_budget()
        self.assertIsNone(self.guard.lease)

    async def test_paginated_read_cannot_send_next_page_after_expiry(self):
        await self.reads.refresh_budget()
        def wire(*_):
            self.clock.t+=301
            return WireResponse(200,b'{"fills":[],"cursor":"next"}')
        self.reads.wire=wire
        with self.assertRaises(QuotaUnavailable): await self.reads.collect('fills',reason='history')
        self.assertEqual(self.reads.budget.spent,30)

    async def test_small_or_used_service_refuses_supervision(self):
        for kwargs in ({'inflight_limit':2},{'concurrency':1}):
            with self.assertRaises(InvalidData): setup(**kwargs)
        with self.assertRaises(InvalidData): self.reads.attach_quota(self.guard)
