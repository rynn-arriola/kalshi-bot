"""D-036 scheduler load fixture, injected reads only, no paper trading."""
import asyncio
from datetime import timedelta
from decimal import Decimal
import json
from pathlib import Path
import sys
import time
import tracemalloc

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
from test_bot_market_inputs import NOW, Reads, review
from benchmark_archive import percentiles
from kalshi_bot.market_inputs import ExitInputService, FeeProfile
from kalshi_bot.metadata_scheduler import MetadataScheduler


async def measure(count):
    tickers=tuple(f'M{i}' for i in range(count))
    reads=Reads(tickers)
    origin=time.perf_counter()
    clock=lambda:time.perf_counter()-origin
    service=ExitInputService(reads,tickers,now=lambda:NOW+timedelta(seconds=clock()),clock=clock,ttl=60,
        timing_reviews=tuple(review(row) for row in reads.markets.values()),
        fee_profile=FeeProfile(Decimal('.0001'),'fixture',NOW+timedelta(hours=1)))
    published={}
    service.bind(lambda terms:published.__setitem__(terms.ticker,terms),lambda ticker:published.pop(ticker,None))
    scheduler=MetadataScheduler(service)
    stop=asyncio.Event()
    lags=[]
    async def heartbeat():
        while not stop.is_set():
            due=time.perf_counter()+.002
            await asyncio.sleep(.002)
            lags.append(max(0,time.perf_counter()-due))
    tracemalloc.start()
    wall,cpu=time.perf_counter(),time.process_time()
    task=asyncio.create_task(scheduler.run())
    heartbeat_task=asyncio.create_task(heartbeat())
    try:
        service.begin(1)
        service.subscribed(1,1)
        async with asyncio.timeout(10):
            while scheduler.completed<count: await asyncio.sleep(.001)
            baseline=len(reads.calls)
            for i,ticker in enumerate(tickers,1):
                service.ingest(dict(type='market_lifecycle_v2',sid=1,seq=i,
                    msg=dict(market_ticker=ticker,event_type='deactivated')),generation=1)
                for _ in range(100): scheduler.request(ticker)
            while scheduler.completed<count*2: await asyncio.sleep(.001)
        assert len(published)==count and all(not terms.active for terms in published.values())
        elapsed,used=time.perf_counter()-wall,time.process_time()-cpu
        peak=tracemalloc.get_traced_memory()[1]
        stats=scheduler.status()
    finally:
        scheduler.stop()
        await task
        stop.set()
        await heartbeat_task
        tracemalloc.stop()
    result=dict(markets=count,reads=len(reads.calls),baseline_reads=baseline,
        wall_seconds=round(elapsed,4),cpu_seconds=round(used,4),peak_bytes=peak,
        loop_lag=percentiles(lags),scheduler=stats)
    result['diagnostic_pass']=(baseline==count+5 and len(reads.calls)==baseline and
        stats['high_water']<=2 and stats['heap']<=count*2 and elapsed<(3 if count==30 else 10)
        and result['loop_lag']['p99_ms']<50 and peak<16*1024*1024)
    return result


async def main():
    results=[await measure(n) for n in (30,120)]
    for result in results: print(json.dumps(result,sort_keys=True))
    if not all(row['diagnostic_pass'] for row in results): raise SystemExit(1)


if __name__=='__main__': asyncio.run(main())
