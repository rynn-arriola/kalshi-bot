"""Synthetic 5k/10k catalog with real pagination, shared reads and runtime owner."""
import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import tracemalloc
from urllib.parse import parse_qs, urlparse

from kalshi_bot.rest import RestReads, TokenBudget, WireResponse
from kalshi_bot.runtime import RecoveryRuntime
from kalshi_bot.writer import LedgerWriter
from benchmark_write_quota_source import percentiles


NOW = datetime(2026, 9, 21, 12, tzinfo=timezone.utc)


async def run(subscribed, rows):
    pages = []
    for offset in range(0, rows, 100):
        programs = [dict(id=f'p{i}', market_ticker=f'M{i:05}', incentive_type='liquidity',
            start_date=(NOW-timedelta(hours=1)).isoformat(),
            end_date=(NOW+timedelta(hours=1)).isoformat(), target_size_fp='1000',
            discount_factor_bps=5000, period_reward=1000000, paid_out=False)
            for i in range(offset, min(rows, offset+100))]
        pages.append(json.dumps(dict(incentive_programs=programs,
            next_cursor=str(offset//100+1) if offset+100 < rows else '')).encode())
    calls = 0
    def wire(url, headers, limit):
        nonlocal calls
        calls += 1
        index = int(parse_qs(urlparse(url).query).get('cursor', ['0'])[0])
        return WireResponse(200,pages[index])
    clock = time.monotonic
    started = clock()
    now = lambda: NOW+timedelta(seconds=clock()-started)
    reads = RestReads(TokenBudget(rate=10000, capacity=10000, default_cost=1, clock=clock), wire=wire)
    lag, turns = [], []
    running = True
    async def heartbeat():
        while running:
            start = time.perf_counter()
            await asyncio.sleep(.001)
            lag.append(max(0, time.perf_counter()-start-.001))
    async def noop(*args): pass
    with TemporaryDirectory() as directory:
        writer = await LedgerWriter(Path(directory)/'fixture.db').start()
        runtime = RecoveryRuntime(writer, reads, None, tickers=tuple(f'M{i:05}' for i in range(subscribed)),
            subaccount=0, history_start=NOW-timedelta(hours=1), now=now, clock=clock,
            evaluate=noop, deadline_handler=noop, lifecycle_handler=noop)
        selection = runtime.attach_selection(offline_fixture=True)
        service = runtime.attach_incentives(offline_fixture=True)
        pulse = asyncio.create_task(heartbeat())
        tracemalloc.start()
        cpu_start, wall_start = time.process_time(),time.perf_counter()
        try:
            service.step()
            await asyncio.wait((service.active,))
            before = time.perf_counter()
            service.step()
            turns.append(time.perf_counter()-before)
            assert service.current() is not None
            assert len(service.current().observations) == rows
            assert selection.status()['program_markets'] == subscribed
            assert service.current().pages == rows//100 and calls == rows//100
            before = time.perf_counter()
            service.request()
            turns.append(time.perf_counter()-before)
            assert service.current() is None
            cpu, wall = time.process_time()-cpu_start,time.perf_counter()-wall_start
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
            running = False
            await pulse
            runtime.stop()
            await service.close()
            await reads.close()
            await writer.close()
    loop = percentiles(lag)
    passed = cpu < 5 and peak < 32*1024*1024 and loop['p99_ms'] < 50
    return dict(subscribed=subscribed, catalog_rows=rows, requests=calls, cpu_seconds=round(cpu,4),
        wall_seconds=round(wall,4), peak_bytes=peak, loop=loop,
        publication_invalidation_ms=[round(t*1000,3) for t in turns], passed=passed)


async def main():
    results = [await run(30,5000), await run(120,10000)]
    print(json.dumps(results,indent=2))
    return 0 if all(r['passed'] for r in results) else 1


if __name__ == '__main__': raise SystemExit(asyncio.run(main()))
