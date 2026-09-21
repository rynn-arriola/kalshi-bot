"""Token-only bounded load diagnostic; no credentials/network/mutations."""
import asyncio
import json
import time
import tracemalloc

from benchmark_archive import percentiles
from kalshi_bot.rest import TokenBudget


async def measure(count):
    budget=TokenBudget(rate=200,capacity=600,default_cost=10,initial_tokens=0,background_reserve=10)
    stop=asyncio.Event()
    lags,waits=[],[]
    async def heartbeat():
        while not stop.is_set():
            due=time.perf_counter()+.002
            await asyncio.sleep(.002)
            lags.append(max(0,time.perf_counter()-due))
    async def request(i):
        start=time.perf_counter()
        await budget.acquire('/fixture',budget.clock()+10,priority=i%2)
        waits.append(time.perf_counter()-start)
    tracemalloc.start()
    wall,cpu=time.perf_counter(),time.process_time()
    timer=asyncio.create_task(heartbeat())
    try:
        await asyncio.gather(*(request(i) for i in range(count)))
        elapsed,used=time.perf_counter()-wall,time.process_time()-cpu
        peak=tracemalloc.get_traced_memory()[1]
    finally:
        stop.set()
        await timer
        tracemalloc.stop()
    result=dict(requests=count,spent=budget.spent,wall_seconds=round(elapsed,4),
        cpu_seconds=round(used,4),peak_bytes=peak,token_wait=percentiles(waits),loop_lag=percentiles(lags))
    result['diagnostic_pass']=(budget.spent==count*10 and budget.spent<=200*elapsed+1
        and elapsed<(3 if count==30 else 10) and used<(1 if count==30 else 3)
        and result['loop_lag']['p99_ms']<50 and peak<8*1024*1024 and not budget.waiters)
    return result


async def main():
    results=[await measure(n) for n in (30,120)]
    for result in results: print(json.dumps(result,sort_keys=True))
    if not all(row['diagnostic_pass'] for row in results): raise SystemExit(1)


if __name__=='__main__': asyncio.run(main())
