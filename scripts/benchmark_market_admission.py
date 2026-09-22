"""Synthetic scope-commit resource check; no sockets, credentials or ledger."""
import asyncio
import json
import time
import tracemalloc

from kalshi_bot.books import BookConnection
from kalshi_bot.engine import EventEngine
from benchmark_write_quota_source import percentiles


async def run(markets):
    async def noop(*args): pass
    owned = tuple(f'OWN{i:03}' for i in range(markets//2))
    peers = tuple(f'PEER{i:03}' for i in range(markets//2))
    engine = EventEngine({'book-0':BookConnection(owned),'book-1':BookConnection(peers)},
        private_handler=noop,evaluate=noop,deadline_handler=noop)
    engine.begin_book_epoch('book-0')
    engine.begin_book_epoch('book-1')
    retained = engine.shards['book-0']
    for ticker in owned: engine.schedule(ticker,1e9)
    lag,operations = [],[]
    running = True
    async def pulse():
        while running:
            started = time.perf_counter()
            await asyncio.sleep(.001)
            lag.append(max(0,time.perf_counter()-started-.001))
    heartbeat = asyncio.create_task(pulse())
    tracemalloc.start()
    cpu_start,wall_start = time.process_time(),time.perf_counter()
    try:
        for cycle in range(10):
            before = engine.shards['book-1'].tickers
            remove = tuple(sorted(before))[:16]
            after = tuple(sorted((before-set(remove)) | {f'NEW{cycle}-{i}' for i in range(len(remove))}))
            for ticker in remove: engine.schedule(ticker,1e9)
            started = time.perf_counter()
            engine.replace_book_scope('book-1',after,capacity=markets)
            operations.append(time.perf_counter()-started)
            assert engine.shards['book-0'] is retained
            assert set(owned) <= set(engine.market_shard)
            assert len(engine.market_shard) == markets
            assert len(engine.deadlines._heap) <= 2*markets
            assert not (set(remove) & engine.deadlines.managed)
            await asyncio.sleep(.002)
        cpu,wall = time.process_time()-cpu_start,time.perf_counter()-wall_start
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
        running = False
        await heartbeat
    operation,loop = percentiles(operations),percentiles(lag)
    passed = cpu<5 and peak<16*1024*1024 and operation['p99_ms']<50 and loop['p99_ms']<50
    return dict(markets=markets,cycles=10,cpu_seconds=round(cpu,4),wall_seconds=round(wall,4),
        peak_bytes=peak,scope_commit=operation,loop=loop,passed=passed,
        excludes='reader teardown, writer, metadata, network and account latency')


async def main():
    results = [await run(n) for n in (30,120)]
    print(json.dumps(results,indent=2))
    return 0 if all(r['passed'] for r in results) else 1


if __name__=='__main__': raise SystemExit(asyncio.run(main()))
