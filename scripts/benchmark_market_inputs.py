"""Offline input-service diagnostic. No account/network/trading.

Predeclared: 30/120 markets sharing one event, cold then ten warm refreshes each,
one tick update/market; dependency GET count exactly markets+5, unchanged by warm
or supported stream refreshes. Budgets wall <3/10s, producer p99 <50ms,
loop-lag p99 <50ms, traced peak <16MiB; at most 2 read slots and 16 shared tasks.
"""
import asyncio
import json
from pathlib import Path
import sys
import time
import tracemalloc
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
from test_bot_market_inputs import Reads, review, NOW, FeeProfile, D, timedelta
from kalshi_bot.market_inputs import ExitInputService
from benchmark_archive import percentiles


async def run(markets):
    tickers=tuple('M'+str(i) for i in range(markets))
    reads=Reads(tickers)
    published={}
    service=ExitInputService(reads,tickers,now=lambda:NOW,ttl=60,
        timing_reviews=tuple(review(r) for r in reads.markets.values()),
        fee_profile=FeeProfile(D('.0001'),'offline-fixture',NOW+timedelta(hours=1)))
    service.bind(lambda t:published.__setitem__(t.ticker,t),lambda t:published.pop(t,None))
    service.begin(1); service.subscribed(1,7)
    samples,lags=[],[]
    stop=asyncio.Event()
    async def heartbeat():
        while not stop.is_set():
            due=time.perf_counter()+.002
            await asyncio.sleep(.002)
            lags.append(max(0,time.perf_counter()-due))
    task=asyncio.create_task(heartbeat())
    await asyncio.sleep(0)
    tracemalloc.start(); began=time.perf_counter(); cpu=time.process_time()
    try:
        for ticker in tickers: await service.refresh(ticker)
        for _ in range(10):
            for ticker in tickers:
                start=time.perf_counter()
                await service.refresh(ticker)
                samples.append(time.perf_counter()-start)
        for seq,ticker in enumerate(tickers,1):
            service.ingest(dict(type='market_lifecycle_v2',sid=7,seq=seq,msg=dict(market_ticker=ticker,
                event_type='price_level_structure_updated',price_ranges=[dict(start='0',end='1',step='.001')])),generation=1)
            await service.refresh(ticker)
            assert published[ticker].bands[0].step==D('.001')
        wall,used=time.perf_counter()-began,time.process_time()-cpu
        peak=tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop(); stop.set(); await task; await service.close()
    result=dict(markets=markets,read_calls=len(reads.calls),wall_seconds=round(wall,4),cpu_seconds=round(used,4),
                peak_bytes=peak,refresh=percentiles(samples),loop_lag=percentiles(lags))
    result['passed']=(len(reads.calls)==markets+5 and wall<(3 if markets==30 else 10)
        and peak<16*1024*1024 and result['refresh']['p99_ms']<50 and result['loop_lag']['p99_ms']<50)
    return result


async def main():
    results=[await run(n) for n in (30,120)]
    for result in results: print(json.dumps(result,sort_keys=True))
    if not all(r['passed'] for r in results): raise SystemExit(1)


if __name__=='__main__': asyncio.run(main())
