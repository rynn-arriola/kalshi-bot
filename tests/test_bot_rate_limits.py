"""Shared read-budget/priority checks with injected wire and clocks only."""
import asyncio
import json
from threading import Event
import unittest

from kalshi_bot.rest import RestReads, TokenBudget, WireResponse, ReadFailure
from kalshi_bot.values import InvalidData
from test_bot_integration import FakeClock


class FakeSigner:
    def headers(self, *_): return {}


LIMITS = dict(usage_tier='fixture',grants=[],read=dict(refill_rate=200,bucket_capacity=600),
              write=dict(refill_rate=100,bucket_capacity=100))
COSTS = dict(default_cost=10,endpoint_costs=[dict(method='GET',path='/trade-api/v2/markets/{ticker}',cost=20)])


class BudgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_document_capacity_not_assumed_available_tokens(self):
        clock=FakeClock()
        budget=TokenBudget.from_documents(LIMITS,COSTS,clock=clock,sleep=clock.sleep)
        self.assertEqual((budget.rate,budget.capacity,budget.tokens),(200,600,0))
        await budget.acquire('/markets/{ticker}',20)
        self.assertEqual(budget.spent,20)
        self.assertAlmostEqual(clock.sleeps[0],.1)

    async def test_background_preserves_headroom(self):
        clock=FakeClock()
        budget=TokenBudget(rate=10,capacity=30,default_cost=10,initial_tokens=10,
                           background_reserve=10,clock=clock,sleep=clock.sleep)
        await budget.acquire('/metadata',20,priority=1)
        self.assertEqual(clock.sleeps,[1])
        self.assertEqual(budget.tokens,10)
        await budget.acquire('/account',20)
        self.assertEqual(clock.sleeps,[1])

    async def test_waiting_background_does_not_hold_account_lock(self):
        sleeping,release=asyncio.Event(),asyncio.Event()
        async def sleep(delay):
            sleeping.set()
            await release.wait()
        budget=TokenBudget(rate=1,capacity=30,default_cost=10,initial_tokens=10,
                           background_reserve=10,sleep=sleep)
        background=asyncio.create_task(budget.acquire('/metadata',budget.clock()+10,priority=1))
        try:
            await asyncio.wait_for(sleeping.wait(),1)
            await asyncio.wait_for(budget.acquire('/account',budget.clock()+10),.2)
            self.assertFalse(background.done())
            self.assertEqual(budget.spent,10)
        finally:
            background.cancel()
            await asyncio.gather(background,return_exceptions=True)
        self.assertEqual(budget.waiters,{})

    async def test_waiter_saturation_and_cancellation(self):
        sleeping=asyncio.Event()
        async def sleep(delay):
            sleeping.set()
            await asyncio.Event().wait()
        budget=TokenBudget(rate=1,capacity=10,default_cost=10,initial_tokens=0,waiter_limit=1,sleep=sleep)
        first=asyncio.create_task(budget.acquire('/a',budget.clock()+20))
        try:
            await sleeping.wait()
            with self.assertRaises(InvalidData): await budget.acquire('/b',budget.clock()+20)
        finally:
            first.cancel()
            await asyncio.gather(first,return_exceptions=True)
        self.assertFalse(budget.waiters)

    async def test_config_update_keeps_shared_throttle_and_starts_empty(self):
        clock=FakeClock()
        budget=TokenBudget(rate=100,capacity=100,default_cost=10,clock=clock,sleep=clock.sleep)
        budget.throttle(3)
        blocked=budget.blocked_until
        budget.reconfigure(LIMITS,COSTS)
        self.assertEqual(budget.blocked_until,blocked)
        self.assertEqual((budget.tokens,budget.configuration_revision),(0,1))
        await budget.acquire('/markets/{ticker}',20)
        self.assertEqual(clock.sleeps,[3])

    async def test_invalid_refresh_does_not_half_apply(self):
        budget=TokenBudget(rate=100,capacity=100,default_cost=10)
        with self.assertRaises(InvalidData): budget.reconfigure(LIMITS,dict(default_cost=10,endpoint_costs=[{}]))
        self.assertEqual((budget.rate,budget.capacity,budget.configuration_revision),(100,100,0))

    async def test_expensive_endpoint_clamps_reserve_not_cost(self):
        clock=FakeClock()
        budget=TokenBudget(rate=10,capacity=20,default_cost=20,background_reserve=10,
                           clock=clock,sleep=clock.sleep)
        await budget.acquire('/full',20,priority=1)
        self.assertEqual(budget.tokens,0)
        self.assertEqual(budget.spent,20)

    async def test_duplicate_costs_boolean_limits_and_bad_backoff_rejected(self):
        for limits,costs in ((dict(read=dict(refill_rate=True,bucket_capacity=30)),COSTS),
                (LIMITS,dict(default_cost=10,endpoint_costs=COSTS['endpoint_costs']*2))):
            with self.assertRaises(InvalidData): TokenBudget.from_documents(limits,costs)
        budget=TokenBudget(rate=1,capacity=1,default_cost=1)
        for delay in (-1,float('nan'),True):
            with self.assertRaises(InvalidData): budget.throttle(delay)

    async def test_reconfiguration_wakes_sleeping_head_without_old_timer(self):
        entered=asyncio.Event()
        clock=FakeClock()
        async def sleep(delay):
            entered.set()
            await asyncio.Event().wait()
        budget=TokenBudget(rate=1,capacity=20,default_cost=10,initial_tokens=0,
                           clock=clock,sleep=sleep)
        task=asyncio.create_task(budget.acquire('/account',30))
        try:
            await asyncio.wait_for(entered.wait(),1)
            self.assertEqual(budget.spent,0)
            budget.reconfigure(dict(read=dict(refill_rate=1000,bucket_capacity=100)),
                               dict(default_cost=10,endpoint_costs=[]))
            clock.now+=.1
            await asyncio.wait_for(task,.3)
            self.assertEqual(budget.spent,10)
            self.assertFalse(budget.waiters)
        finally:
            task.cancel()
            await asyncio.gather(task,return_exceptions=True)

    async def test_head_rechecks_lower_rate_and_extended_throttle(self):
        for change in ('lower_rate','throttle'):
            entered=asyncio.Event()
            clock=FakeClock()
            sleeps=[]
            async def sleep(delay):
                sleeps.append(delay)
                if len(sleeps)==1:
                    entered.set()
                    await asyncio.Event().wait()
                else:
                    clock.now+=delay
                    await asyncio.sleep(0)
            budget=TokenBudget(rate=10,capacity=20,default_cost=10,
                               initial_tokens=0,clock=clock,sleep=sleep)
            task=asyncio.create_task(budget.acquire('/account',clock.now+30))
            try:
                await asyncio.wait_for(entered.wait(),1)
                if change=='lower_rate':
                    budget.reconfigure(dict(read=dict(refill_rate=1,bucket_capacity=20)),
                                       dict(default_cost=10,endpoint_costs=[]))
                    minimum=10
                else:
                    budget.throttle(3)
                    minimum=3
                await asyncio.wait_for(task,.3)
                self.assertGreaterEqual(sleeps[1],minimum)
                self.assertEqual(budget.spent,10)
                self.assertFalse(budget.waiters)
            finally:
                task.cancel()
                await asyncio.gather(task,return_exceptions=True)


class ReadTests(unittest.IsolatedAsyncioTestCase):
    async def test_refresh_is_coalesced_and_read_write_limits_stay_separate(self):
        calls=[]
        def wire(url,*_):
            calls.append(url)
            doc=LIMITS if url.endswith('/limits') else COSTS
            return WireResponse(200,json.dumps(doc).encode())
        reads=RestReads(TokenBudget(rate=100,capacity=100,default_cost=10),FakeSigner(),wire=wire)
        try:
            results=await asyncio.gather(*(reads.refresh_budget() for _ in range(5)))
            self.assertEqual(len(calls),2)
            self.assertEqual(reads.budget.configuration_revision,1)
            self.assertEqual(results[0]['write'],dict(rate=100,capacity=100))
            self.assertFalse(results[0]['write_enabled'])
            self.assertEqual(reads.budget.rate,200)
        finally: await reads.close()

    async def test_last_429_still_throttles_shared_budget(self):
        clock=FakeClock()
        budget=TokenBudget(rate=100,capacity=100,default_cost=10,clock=clock,sleep=clock.sleep)
        reads=RestReads(budget,wire=lambda *_:WireResponse(429,b''),jitter=lambda:0)
        try:
            with self.assertRaises(ReadFailure): await reads.read('costs',reason='budget')
            self.assertEqual((budget.throttles,budget.spent),(3,30))
            self.assertGreater(budget.blocked_until,clock.now)
            self.assertEqual(budget.tokens,0)
        finally: await reads.close()

    async def test_429_after_deadline_still_throttles_shared_budget(self):
        clock=FakeClock()
        budget=TokenBudget(rate=100,capacity=100,default_cost=10,clock=clock,sleep=clock.sleep)
        def wire(*_):
            clock.now += 31
            return WireResponse(429,b'')
        reads=RestReads(budget,wire=wire,jitter=lambda:0)
        try:
            with self.assertRaises(InvalidData): await reads.read('costs',reason='budget')
            self.assertEqual((budget.throttles,budget.spent),(1,10))
            self.assertGreater(budget.blocked_until,clock.now)
        finally: await reads.close()

    async def test_background_cannot_occupy_all_transport_slots(self):
        entered,release=Event(),Event()
        calls=[]
        def wire(url,*_):
            calls.append(url)
            if '/markets/' in url:
                entered.set()
                release.wait(3)
            return WireResponse(200,b'{}')
        reads=RestReads(TokenBudget(rate=1000,capacity=1000,default_cost=10),wire=wire,concurrency=2)
        tasks=[asyncio.create_task(reads.read('market',reason='metadata',ticker=t)) for t in ('A','B')]
        try:
            self.assertTrue(await asyncio.to_thread(entered.wait,1))
            await asyncio.wait_for(reads.read('costs',reason='budget'),.3)
            self.assertEqual(sum('/markets/' in url for url in calls),1)
        finally:
            release.set()
            await asyncio.gather(*tasks)
            await reads.close()

    async def test_background_saturation_preserves_two_critical_admissions(self):
        entered,release=Event(),Event()
        def wire(url,*_):
            if '/markets/' in url:
                entered.set()
                release.wait(3)
            return WireResponse(200,b'{}')
        reads=RestReads(TokenBudget(rate=1000,capacity=1000,default_cost=10),
                        FakeSigner(),wire=wire,inflight_limit=32,concurrency=2)
        tasks=[asyncio.create_task(reads.read('market',reason='metadata',ticker=f'M{i}'))
               for i in range(32)]
        try:
            self.assertTrue(await asyncio.to_thread(entered.wait,1))
            await asyncio.sleep(.02)
            self.assertEqual(reads.background_inflight,30)
            self.assertEqual(reads.slots._value,1)
            await asyncio.wait_for(asyncio.gather(reads.read('costs',reason='budget'),
                                                 reads.read('limits',reason='budget')),.3)
            self.assertEqual(reads.background_inflight,30)
        finally:
            release.set()
            results=await asyncio.gather(*tasks,return_exceptions=True)
            self.assertEqual(sum(isinstance(r,InvalidData) for r in results),2)
            await reads.close()
        self.assertEqual(reads.background_inflight,0)

    async def test_new_metadata_scope_cannot_inherit_old_wire_response(self):
        entered,release=Event(),Event()
        calls=[]
        def wire(*_):
            calls.append(len(calls)+1)
            if len(calls)==1:
                entered.set()
                release.wait(3)
            return WireResponse(200,json.dumps({'version':len(calls)}).encode())
        reads=RestReads(TokenBudget(rate=1000,capacity=1000,default_cost=10),wire=wire)
        old=asyncio.create_task(reads.read('market',reason='metadata',ticker='A',coalesce_scope=('old',1)))
        try:
            self.assertTrue(await asyncio.to_thread(entered.wait,1))
            old.cancel()
            await asyncio.gather(old,return_exceptions=True)
            new=asyncio.create_task(reads.read('market',reason='metadata',ticker='A',coalesce_scope=('new',2)))
            release.set()
            result=await asyncio.wait_for(new,2)
            self.assertEqual(result.payload['version'],2)
            self.assertEqual(len(calls),2)
        finally:
            release.set()
            await reads.close()

    async def test_small_admission_capacity_reports_its_real_reservation(self):
        entered,release=Event(),Event()
        def wire(url,*_):
            if '/markets/' in url:
                entered.set()
                release.wait(3)
            return WireResponse(200,b'{}')
        for limit in (1,2):
            reads=RestReads(TokenBudget(rate=1000,capacity=1000,default_cost=10),
                            wire=wire,inflight_limit=limit,concurrency=2)
            task=asyncio.create_task(reads.read('market',reason='metadata',ticker='A'))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait,1))
                if limit==1:
                    with self.assertRaises(InvalidData):
                        await reads.read('costs',reason='budget')
                else:
                    await asyncio.wait_for(reads.read('costs',reason='budget'),.3)
            finally:
                release.set()
                await task
                await reads.close()
                entered.clear()
                release.clear()

    async def test_bad_limits_leave_existing_budget_and_emit_safe_failure(self):
        events=[]
        class Log:
            def emit(self,event,**fields): events.append(event)
        reads=RestReads(TokenBudget(rate=100,capacity=100,default_cost=10),FakeSigner(),
                        wire=lambda *_:WireResponse(200,b'{}'),diagnostics=Log())
        try:
            with self.assertRaises(InvalidData): await reads.refresh_budget()
            await asyncio.sleep(0)
            self.assertEqual(reads.budget.configuration_revision,0)
            self.assertIn('read_budget_failed',events)
        finally: await reads.close()
