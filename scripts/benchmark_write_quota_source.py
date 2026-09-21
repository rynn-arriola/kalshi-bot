"""Bounded shared-pair fixture; fake signer/wire, no network or credentials."""
import asyncio
from datetime import datetime, timedelta, timezone
import json
import math
import time
import tracemalloc

from kalshi_bot.quota import ProbeConfig, QuotaPolicy, QuotaGuard
from kalshi_bot.rest import RestReads, TokenBudget, WireResponse
from kalshi_bot.write_budget import ORDERS
from kalshi_bot.write_quota_source import WriteQuotaSource


class Clock:
    def __init__(self):
        self.t = 0.

    def __call__(self):
        return self.t

    def now(self):
        return datetime(2026, 9, 21, tzinfo=timezone.utc)+timedelta(seconds=self.t)

    async def sleep(self, delay):
        self.t += delay
        await asyncio.sleep(0)


class FixtureSigner:
    def headers(self, *_):
        return {}


def percentiles(values):
    ordered = sorted(values)
    return {key: round(ordered[math.ceil(len(ordered)*q)-1]*1000, 3)
            for key, q in (('p50_ms', .5), ('p95_ms', .95), ('p99_ms', .99))}


async def run(shards):
    clock = Clock()
    requests = []
    limits = dict(usage_tier='fixture', grants=[],
        read=dict(refill_rate=10000, bucket_capacity=10000),
        write=dict(refill_rate=100, bucket_capacity=100))
    costs = dict(default_cost=10, endpoint_costs=[
        dict(method='DELETE', path=ORDERS+'/{order_id}', cost=2)])
    def wire(url, *_):
        requests.append(url.rsplit('/', 1)[-1])
        return WireResponse(200, json.dumps(costs if url.endswith('endpoint_costs') else limits).encode())
    reads = RestReads(TokenBudget(rate=1, capacity=10, default_cost=10,
        clock=clock, sleep=clock.sleep), FixtureSigner(), wire=wire)
    guard = QuotaGuard(QuotaPolicy(ProbeConfig(10000, 10000, 10, 10)), clock=clock, now=clock.now)
    reads.attach_quota(guard)
    source = WriteQuotaSource(reads, shards=tuple(range(shards)), offline_fixture=True)
    lag, latency = [], []
    running = True
    async def heartbeat():
        while running:
            started = time.perf_counter()
            await asyncio.sleep(.001)
            lag.append(max(0., time.perf_counter()-started-.001))
    pulse = asyncio.create_task(heartbeat())
    tracemalloc.start()
    cpu_start, wall_start = time.process_time(), time.perf_counter()
    try:
        for _ in range(8):
            start = time.perf_counter()
            await reads.refresh_budget()
            latency.append(time.perf_counter()-start)
            budget = source.budget
            clock.t += 1
            for shard in range(shards):
                permit = budget.try_reserve('POST', ORDERS, shard=shard, now=source.clock_pair())
                assert permit is not None
                budget.consume(permit, 'POST', ORDERS, shard=shard, now=source.clock_pair())
            await asyncio.sleep(0)
        cpu, wall = time.process_time()-cpu_start, time.perf_counter()-wall_start
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
        running = False
        await pulse
        await reads.close()
    pair, loop = percentiles(latency), percentiles(lag)
    passed = (len(requests) == 16 and cpu < 1 and peak < 8*1024*1024
              and pair['p99_ms'] < 100 and loop['p99_ms'] < 50)
    print(json.dumps(dict(shards=shards, refreshes=8, commands=shards*8,
        injected_gets=len(requests), cpu_seconds=round(cpu, 4), wall_seconds=round(wall, 4),
        allocation_peak_bytes=peak, pair=pair, loop=loop, passed=passed), sort_keys=True))
    return passed


async def main():
    results = [await run(shards) for shards in (30, 120)]
    if not all(results):
        raise SystemExit('write quota source resource acceptance failed')


if __name__ == '__main__':
    asyncio.run(main())
