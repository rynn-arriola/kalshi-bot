"""Bounded scheduling fixture; no venue, credentials or synthetic profit."""
import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import tracemalloc

from kalshi_bot.dispatch import PASSIVE_REDUCER
from kalshi_bot.dispatch_sources import InventoryDispatchSource
from kalshi_bot.quota import QuotaScope
from kalshi_bot.runtime import RecoveryRuntime
from kalshi_bot.write_budget import WriteBudget, WriteQuotaSnapshot
from kalshi_bot.writer import LedgerWriter
from benchmark_write_quota_source import percentiles


async def run(markets):
    stamp = (0., 1700000000.)
    now = datetime(2026, 9, 21, tzinfo=timezone.utc)
    tickers = tuple(f'M{i:03d}' for i in range(markets))
    async def ignore(*args):
        pass
    async def forbidden(*args):
        raise AssertionError('missing account proof must block submission')
    with TemporaryDirectory() as directory:
        writer = await LedgerWriter(Path(directory)/'fixture.db').start()
        runtime = RecoveryRuntime(writer, None, None, tickers=tickers, subaccount=0,
            history_start=now-timedelta(hours=1), now=lambda: now, evaluate=ignore,
            deadline_handler=ignore, lifecycle_handler=ignore)
        snapshot = WriteQuotaSnapshot(dict(usage_tier='fixture', grants=[],
            read=dict(refill_rate=100, bucket_capacity=100),
            write=dict(refill_rate=100, bucket_capacity=100)),
            dict(default_cost=10, endpoint_costs=[]), scope=QuotaScope(), epoch=1,
            sequence=1, start=stamp, end=stamp, ttl=300)
        budget = WriteBudget(snapshot, shards=(0,), now=stamp, offline_fixture=True)
        source = InventoryDispatchSource(runtime, offline_fixture=True)
        dispatcher = source.dispatcher(budget, invoke=forbidden, clock_pair=lambda: stamp)
        service = runtime.attach_dispatch(source, dispatcher, offline_fixture=True)
        latency, lag = [], []
        original = dispatcher.run_one
        async def timed():
            start = time.perf_counter()
            result = await original()
            if result.ticker is not None:
                latency.append(time.perf_counter()-start)
            return result
        dispatcher.run_one = timed  # Measure a whole key turn, not just its source callback.
        running = True
        async def heartbeat():
            while running:
                start = time.perf_counter()
                await asyncio.sleep(.001)
                lag.append(max(0., time.perf_counter()-start-.001))
        pulse = asyncio.create_task(heartbeat())
        worker = asyncio.create_task(service.run())
        tracemalloc.start()
        cpu_start, wall_start = time.process_time(), time.perf_counter()
        try:
            for batch in range(10):
                for ticker in tickers:
                    assert service.request(ticker, PASSIVE_REDUCER)
                if batch == 0:
                    for _ in range(10000):
                        assert not service.request(tickers[0], PASSIVE_REDUCER)
                async with asyncio.timeout(5):
                    while service.last_state != 'IDLE' or dispatcher.status().queued:
                        await asyncio.sleep(.001)
                assert len(latency) == (batch+1)*markets
            turns = service.turns
            await asyncio.sleep(.05)
            idle_turns = service.turns-turns
            cpu, wall = time.process_time()-cpu_start, time.perf_counter()-wall_start
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
            service.stop()
            running = False
            try:
                await worker
            finally:
                try:
                    await pulse
                finally:
                    await writer.close()
        component, loop = percentiles(latency), percentiles(lag)
        passed = (len(latency) == markets*10 and idle_turns == 0
            and service.status()['high_water'] <= 128 and cpu < 1
            and peak < 8*1024*1024 and loop['p99_ms'] < 50 and component['p99_ms'] < 50)
        print(json.dumps(dict(markets=markets, blocked_evaluations=len(latency),
            duplicate_requests=10000, idle_turns=idle_turns, service_tasks=1,
            queue_high_water=service.status()['high_water'], evaluation=component, loop=loop,
            cpu_seconds=round(cpu, 4), wall_seconds=round(wall, 4), allocation_peak_bytes=peak,
            passed=passed), sort_keys=True))
        return passed


async def main():
    if not all([await run(markets) for markets in (30, 120)]):
        raise SystemExit('dispatch lifecycle resource acceptance failed')


if __name__ == '__main__':
    asyncio.run(main())
