"""Offline quota scope, saturation, timing and leak checks. No real transport."""
import asyncio
from datetime import datetime, timedelta, timezone
import json
import time
import tracemalloc

from benchmark_archive import percentiles
from kalshi_bot.market_inputs import ExitInputService
from kalshi_bot.metadata_scheduler import MetadataScheduler
from kalshi_bot.quota import ProbeConfig, QuotaGuard, QuotaPolicy
from kalshi_bot.quota_supervisor import QuotaSupervisor
from kalshi_bot.rest import RestReads, TokenBudget, WireResponse
from kalshi_bot.values import InvalidData


class Clock:
    def __init__(self): self.t=0.
    def __call__(self): return self.t
    def now(self): return datetime(2026,9,20,tzinfo=timezone.utc)+timedelta(seconds=self.t)
    async def sleep(self,delay):
        self.t+=delay
        await asyncio.sleep(0)


class Signer:
    def headers(self,*_): return {}


async def measure(count, automatic):
    clock=Clock()
    calls=[]
    limits=dict(usage_tier='fixture',grants=[],read=dict(refill_rate=10000,bucket_capacity=10000),
                write=dict(refill_rate=100,bucket_capacity=100))
    def wire(url,*_):
        calls.append(url)
        payload=(dict(default_cost=10,endpoint_costs=[]) if url.endswith('endpoint_costs') else
                 limits if url.endswith('/limits') else dict(ok=True))
        return WireResponse(200,json.dumps(payload).encode())
    budget=TokenBudget(rate=10,capacity=10,default_cost=10,clock=clock,sleep=clock.sleep)
    reads=RestReads(budget,Signer(),wire=wire)
    guard=QuotaGuard(QuotaPolicy(ProbeConfig(10,10,10,10)),clock=clock,now=clock.now)
    reads.attach_quota(guard)
    supervisor=QuotaSupervisor(reads,jitter=lambda:0) if automatic else None
    scheduler=None
    if automatic:
        service=ExitInputService(reads,tuple('M'+str(i) for i in range(count)),now=clock.now,clock=clock,ttl=10)
        service.bind(lambda _:None,lambda _:None)
        scheduler=MetadataScheduler(service)
    stop=asyncio.Event()
    lags,gate_times,request_times=[],[],[]
    high=dict(inflight=0,slots=0,waiters=0)
    async def heartbeat():
        while not stop.is_set():
            due=time.perf_counter()+.002
            await asyncio.sleep(.002)
            lags.append(max(0,time.perf_counter()-due))
            high['inflight']=max(high['inflight'],len(reads.inflight))
            high['slots']=max(high['slots'],reads._slot_used)
            high['waiters']=max(high['waiters'],len(budget.waiters))
    async def drain():
        for _ in range(2000):
            supervisor.step()
            if supervisor.active is None: return
            await asyncio.sleep(.001)
        raise AssertionError('fixture refresh did not drain')
    async def request(index):
        start=time.perf_counter()
        try:
            if index%3:
                await reads.read('market',reason='metadata',ticker='M'+str(index))
            else:
                await reads.read('costs',reason='budget',coalesce_scope=index)
            return True
        except InvalidData:
            return False  # Saturation is explicit refusal, not unbounded queueing.
        finally: request_times.append(time.perf_counter()-start)
    tracemalloc.start()
    wall,cpu=time.perf_counter(),time.process_time()
    timer=asyncio.create_task(heartbeat())
    try:
        if automatic:
            supervisor.step()
            for _ in range(1000): supervisor.request_refresh()
            await drain()
        else:
            await asyncio.gather(*(reads.refresh_budget() for _ in range(count)))
        quota_calls=len(calls)
        assert quota_calls==2
        before=len(calls)
        if scheduler is not None:
            # Lifecycle requests without stream ACK cannot manufacture bootstrap;
            # cardinality does not cause quota GETs.
            for ticker in scheduler.service.tickers: scheduler.request(ticker)
            scheduler.step()
            assert len(calls)==before
        results=await asyncio.gather(*(request(i) for i in range(count)))
        for i in range(10000):
            start=time.perf_counter()
            guard.check('/markets/{ticker}'); guard.status()
            gate_times.append(time.perf_counter()-start)
            if i%100==0: await asyncio.sleep(0)
        used=time.process_time()-cpu
        elapsed=time.perf_counter()-wall
        peak=tracemalloc.get_traced_memory()[1]
    finally:
        if supervisor is not None: await supervisor.close()
        if scheduler is not None: await scheduler.close()
        await reads.close()
        stop.set(); await timer
        tracemalloc.stop()
    leftovers=[t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()]
    result=dict(callers=count,automatic=automatic,quota_gets=quota_calls,
        accepted=sum(results),rejected=count-sum(results),wire_gets=len(calls),tokens=budget.spent,
        wall_seconds=round(elapsed,4),cpu_seconds=round(used,4),peak_bytes=peak,
        loop_lag=percentiles(lags),gate_check=percentiles(gate_times),request_wait=percentiles(request_times),
        high_water=high,pending_tasks=len(leftovers))
    result['diagnostic_pass']=(quota_calls==2 and used<(1 if count==30 else 3) and peak<8*1024*1024
        and result['loop_lag']['p99_ms']<50 and not leftovers and not reads.inflight
        and not budget.waiters and high['inflight']<=32 and high['slots']<=2 and high['waiters']<=128
        and budget.spent==len(calls)*10)
    return result


async def idle():
    clock=Clock()
    calls=[]
    def wire(url,*_):
        calls.append(url)
        payload=(dict(default_cost=10,endpoint_costs=[]) if url.endswith('endpoint_costs') else
            dict(usage_tier='fixture',grants=[],read=dict(refill_rate=10,bucket_capacity=10),
                 write=dict(refill_rate=10,bucket_capacity=10)))
        return WireResponse(200,json.dumps(payload).encode())
    reads=RestReads(TokenBudget(rate=10,capacity=10,default_cost=10,clock=clock,sleep=clock.sleep),Signer(),wire=wire)
    guard=QuotaGuard(QuotaPolicy(ProbeConfig(10,10,10,10)),clock=clock,now=clock.now)
    reads.attach_quota(guard)
    supervisor=QuotaSupervisor(reads)
    task=asyncio.create_task(supervisor.run())
    try:
        async with asyncio.timeout(3):
            while supervisor.completed<1: await asyncio.sleep(.001)
        # Let completion/change notifications drain before counting idle wakes.
        await asyncio.sleep(.05)
        starts,wakes=len(calls),supervisor.wakes
        await asyncio.sleep(10)
        result=dict(idle_seconds=10,extra_gets=len(calls)-starts,extra_wakes=supervisor.wakes-wakes)
        result['diagnostic_pass']=result['extra_gets']==0 and result['extra_wakes']<=12
        return result
    finally:
        supervisor.stop(); await task; await reads.close()


async def rollover(count):
    """One deferral plus one boundary pair despite many coalesced requests."""
    clock=Clock()
    calls=[]
    limits=dict(usage_tier='fixture', grants=[dict(exchange_instance='event_contract',
        level='x', source='manual', expires_ts=int(clock.now().timestamp()+300))],
        read=dict(refill_rate=10000,bucket_capacity=10000),
        write=dict(refill_rate=100,bucket_capacity=100))
    def wire(url,*_):
        calls.append(url)
        payload=(dict(default_cost=10,endpoint_costs=[]) if url.endswith('endpoint_costs')
                 else limits if url.endswith('/limits') else dict(ok=True))
        return WireResponse(200,json.dumps(payload).encode())
    reads=RestReads(TokenBudget(rate=10000,capacity=10000,default_cost=10,
        clock=clock,sleep=clock.sleep),Signer(),wire=wire)
    guard=QuotaGuard(QuotaPolicy(ProbeConfig(10000,10000,10,10)),clock=clock,now=clock.now)
    reads.attach_quota(guard)
    supervisor=QuotaSupervisor(reads,jitter=lambda:0)
    async def drain():
        for _ in range(2000):
            supervisor.step()
            if supervisor.active is None: return
            await asyncio.sleep(.001)
        raise AssertionError('rollover fixture did not drain')
    tracemalloc.start()
    wall,cpu=time.perf_counter(),time.process_time()
    try:
        await drain()
        clock.t=205
        await drain()
        after_deferral=len(calls)
        for _ in range(1000): supervisor.request_refresh()
        for _ in range(count): supervisor.request_refresh()
        clock.t=225
        await drain()
        before=len(calls)
        assert before==4 and supervisor.status()['rollover_pending']
        clock.t=295
        assert not guard.status()['available']
        limits['grants']=[]
        limits['read']=dict(refill_rate=500,bucket_capacity=500)
        clock.t=300
        await drain()
        result=dict(rollover_markets=count,wire_gets=len(calls),get_between_pairs=before-after_deferral,
            available=guard.status()['available'],failures=supervisor.failures,
            tokens=reads.budget.spent,wall_seconds=round(time.perf_counter()-wall,4),
            cpu_seconds=round(time.process_time()-cpu,4),
            peak_bytes=tracemalloc.get_traced_memory()[1])
    finally:
        await supervisor.close(); await reads.close(); tracemalloc.stop()
    result['pending_tasks']=len([t for t in asyncio.all_tasks()
                                 if t is not asyncio.current_task() and not t.done()])
    result['diagnostic_pass']=(result['wire_gets']==6 and result['get_between_pairs']==0
        and result['available'] and result['failures']==0 and result['tokens']==60
        and result['peak_bytes']<8*1024*1024 and result['pending_tasks']==0
        and not reads.inflight and not reads._control_tasks and reads._slot_used==0)
    return result


async def main():
    results=[]
    for automatic in (False,True):
        for count in (30,120):
            result=await measure(count,automatic); results.append(result)
            print(json.dumps(result,sort_keys=True))
    for count in (30,120):
        result=await rollover(count); results.append(result)
        print(json.dumps(result,sort_keys=True))
    result=await idle(); results.append(result); print(json.dumps(result,sort_keys=True))
    if not all(row['diagnostic_pass'] for row in results): raise SystemExit(1)


if __name__=='__main__': asyncio.run(main())
