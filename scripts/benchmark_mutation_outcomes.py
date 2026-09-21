"""Injected outcome overhead only: no HTTP, credentials, ledger or live bot."""
import asyncio
import json
import time
import tracemalloc

from kalshi_bot.mutation_outcomes import MutationHTTPFailure, MutationOutcomeOwner
from kalshi_bot.quota import QuotaScope
from kalshi_bot.write_budget import WriteBudget, WriteQuotaSnapshot
from benchmark_write_quota_source import percentiles


async def run(shards):
    stamp = (0., 1700000000.)
    evidence = WriteQuotaSnapshot(
        dict(usage_tier='fixture', grants=[],
             read=dict(refill_rate=100, bucket_capacity=100),
             write=dict(refill_rate=100, bucket_capacity=100)),
        dict(default_cost=10, endpoint_costs=[]), scope=QuotaScope(), epoch=1,
        sequence=1, start=stamp, end=stamp, ttl=300)
    budget = WriteBudget(evidence, shards=tuple(range(shards)), now=stamp, offline_fixture=True)
    calls = notifications = 0
    async def invoke(*args):
        nonlocal calls
        calls += 1
        raise MutationHTTPFailure(429)
    def notify(notice):
        nonlocal notifications
        notifications += 1
        assert notice.http_status == 429
    owner = MutationOutcomeOwner(budget, invoke=invoke, clock_pair=lambda: stamp,
        notify=notify, offline_fixture=True)
    req = dict(ticker='FIXTURE', client_order_id='fixture', side='ask', count='10', price='.5',
        time_in_force='good_till_canceled', self_trade_prevention_type='taker_at_cross',
        post_only=True, reduce_only=True, cancel_order_on_pause=True, subaccount=0, exchange_index=0)
    latency, lag = [], []
    running = True
    async def heartbeat():
        while running:
            start = time.perf_counter()
            await asyncio.sleep(.001)
            lag.append(max(0., time.perf_counter()-start-.001))
    pulse = asyncio.create_task(heartbeat())
    tracemalloc.start()
    cpu_start, wall_start = time.process_time(), time.perf_counter()
    try:
        for index in range(shards*10):
            req['exchange_index'] = index % shards
            start = time.perf_counter()
            try:
                await owner('create', req)
            except MutationHTTPFailure:
                pass
            latency.append(time.perf_counter()-start)
            await asyncio.sleep(0)
        cpu, wall = time.process_time()-cpu_start, time.perf_counter()-wall_start
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
        running = False
        await pulse
    outcome, loop = percentiles(latency), percentiles(lag)
    passed = (calls == notifications == shards*10 and not owner.busy
        and cpu < 1 and peak < 8*1024*1024 and outcome['p99_ms'] < 20 and loop['p99_ms'] < 50)
    print(json.dumps(dict(shards=shards, calls=calls, notifications=notifications,
        retained_notices=int(owner.last is not None), outcome=outcome, loop=loop,
        cpu_seconds=round(cpu, 4), wall_seconds=round(wall, 4), allocation_peak_bytes=peak,
        passed=passed), sort_keys=True))
    return passed


async def main():
    results = [await run(shards) for shards in (30, 120)]
    if not all(results):
        raise SystemExit('mutation outcome resource acceptance failed')


if __name__ == '__main__':
    asyncio.run(main())
