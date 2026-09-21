"""Disposable structured-log diagnostic, never a bot or paper run.

Predeclared: 30/120 markets x100 events, 5% exceptions, 32-event batches, real
rotating local sink. Producer p99 <5ms, loop-lag p99 <50ms, traced peak <24MiB,
wall <8/20s and CPU <4/12s; zero losses and all accepted events drained.
"""
import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import tracemalloc

from kalshi_bot.observability import Diagnostics
from kalshi_bot.values import InvalidData
from benchmark_archive import percentiles


async def measure(markets):
    with TemporaryDirectory(prefix='kalshi-log-diagnostic-') as folder:
        log = await asyncio.to_thread(Diagnostics(Path(folder), max_bytes=1024*1024, backups=2).start)
        latency, lags = [], []
        stop = asyncio.Event()
        async def heartbeat():
            while not stop.is_set():
                due = time.perf_counter()+.002
                await asyncio.sleep(.002)
                lags.append(max(0, time.perf_counter()-due))
        task = asyncio.create_task(heartbeat())
        await asyncio.sleep(0)
        tracemalloc.start()
        wall, cpu = time.perf_counter(), time.process_time()
        try:
            for i in range(markets*100):
                began = time.perf_counter()
                log.emit('reader_failed' if i%20==0 else 'inventory_plan_changed',
                    error=InvalidData('withheld') if i%20==0 else None,
                    market='M'+str(i%markets), stream='book-0', generation=2, mode='blocked',
                    blockers=('exit_terms_missing',), blocker_count=1)
                latency.append(time.perf_counter()-began)
                if i%32==31:
                    await asyncio.sleep(.002)
            await asyncio.to_thread(log.close)
            elapsed, used = time.perf_counter()-wall, time.process_time()-cpu
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
            stop.set()
            await task
            await asyncio.to_thread(log.close)
        status = log.status()
        result = dict(markets=markets, events=markets*100, wall_seconds=round(elapsed,4),
            cpu_seconds=round(used,4), peak_bytes=peak, producer=percentiles(latency),
            loop_lag=percentiles(lags), high_water=status['high_water'], dropped=status['dropped'])
        result['passed'] = (status['failure'] is None and status['accepted']==status['written']
            and status['dropped']==0 and result['producer']['p99_ms']<5
            and result['loop_lag']['p99_ms']<50 and peak<24*1024*1024
            and elapsed<(8 if markets==30 else 20) and used<(4 if markets==30 else 12))
        return result


async def main():
    results = [await measure(n) for n in (30, 120)]
    for result in results: print(json.dumps(result, sort_keys=True))
    if not all(r['passed'] for r in results): raise SystemExit(1)


if __name__=='__main__': asyncio.run(main())
