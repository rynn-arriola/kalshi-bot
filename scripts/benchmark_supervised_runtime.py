"""Disposable 30/120-market S2B adapter resource acceptance.

No credential, network, venue or mutation dependency is constructed.  This
measures the offline runtime itself; native S2A process overhead remains in the
separate supervisor benchmark and is not double-counted here.
"""
import asyncio
import gc
import json
from pathlib import Path
import tempfile
import threading
import time
import tracemalloc

from benchmark_supervisor_native import process_metrics
from kalshi_bot.supervised_runtime import (RuntimeContext, RuntimeRestrictions,
                                           create_offline_runtime_adapter)
from kalshi_bot.writer import LedgerWriter


def percentile(values, fraction):
    ordered = sorted(values)
    return ordered[min(len(ordered)-1, int(len(ordered)*fraction))]


async def measure(markets):
    await asyncio.to_thread(lambda: None)
    baseline = process_metrics(-1)
    baseline_threads = threading.active_count()
    baseline_tasks = len(asyncio.all_tasks())
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder)/"runtime.db"
        restrictions = RuntimeRestrictions()
        restrictions.apply(None)
        tracemalloc.start()
        began = time.perf_counter()
        adapter = await create_offline_runtime_adapter(path, restrictions,
                                                       market_count=markets)
        await adapter.start(RuntimeContext("fixture-test-resource", "child", 1))
        async with asyncio.timeout(10):
            while (not adapter.runtime.account_subscribed
                    or any(state != "subscribed"
                           for state in adapter.runtime.reader_states.values())):
                await asyncio.sleep(.001)
        startup_ms = (time.perf_counter()-began)*1000
        await asyncio.sleep(.25)
        gc.collect()
        active = process_metrics(-1)
        cpu_start = time.process_time()
        sample_start = time.perf_counter()
        delays = []
        due = time.perf_counter()+.01
        for _ in range(500):
            await asyncio.sleep(max(0, due-time.perf_counter()))
            now = time.perf_counter()
            delays.append(max(0, now-due)*1000)
            due += .01
        elapsed = max(.001, time.perf_counter()-sample_start)
        cpu_percent = (time.process_time()-cpu_start)*100/elapsed
        stopped = time.perf_counter()
        adapter.request_stop("resource_fixture_complete")
        evidence = await adapter.join()
        shutdown_ms = (time.perf_counter()-stopped)*1000
        traced_peak = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
        reopened = await LedgerWriter(path, market_capacity=markets).start()
        try:
            gaps = await reopened.private_epoch_gap_count(subaccount=0)
        finally:
            await reopened.close()
    await asyncio.sleep(0)
    final = process_metrics(-1)
    result = dict(markets=markets, startup_ms=startup_ms,
        shutdown_ms=shutdown_ms, cpu_percent=cpu_percent,
        event_loop_p99_ms=percentile(delays, .99),
        added_working_set_bytes=max(0, active["working_set_bytes"]-
                                    baseline["working_set_bytes"]),
        traced_peak_bytes=traced_peak, fake_read_calls=adapter.runtime.reads.calls,
        private_epoch_gaps=gaps, cleanup_complete=evidence.cleanup_complete,
        handle_delta=final["handles"]-baseline["handles"],
        native_thread_delta=final["native_threads"]-baseline["native_threads"],
        python_thread_delta=threading.active_count()-baseline_threads,
        task_delta=len(asyncio.all_tasks())-baseline_tasks)
    result["targets"] = dict(event_loop_p99_under_50_ms=
        result["event_loop_p99_ms"] < 50,
        runtime_memory_under_40_mib=result["added_working_set_bytes"] < 40*1024*1024,
        cleanup_complete=result["cleanup_complete"] and gaps == 0,
        owners_returned=result["python_thread_delta"] == 0
            and result["task_delta"] == 0 and result["native_thread_delta"] <= 0
            and result["handle_delta"] <= 0)
    return result


async def warm(markets):
    with tempfile.TemporaryDirectory() as folder:
        restrictions = RuntimeRestrictions()
        restrictions.apply(None)
        adapter = await create_offline_runtime_adapter(
            Path(folder)/"runtime.db", restrictions, market_count=markets)
        await adapter.start(RuntimeContext("fixture-test-warm", "child", 1))
        async with asyncio.timeout(10):
            while not adapter.runtime.account_subscribed:
                await asyncio.sleep(.001)
        adapter.request_stop("warm_complete")
        evidence = await adapter.join()
        if not evidence.cleanup_complete:
            raise RuntimeError("S2B warmup cleanup failed")
    gc.collect()


async def main():
    for markets in (1, 30, 120):
        await warm(markets)
    results = [await measure(markets) for markets in (30, 120)]
    print(json.dumps({"workload": "offline S2B runtime; no external I/O",
                      "results": results}, sort_keys=True, indent=2))
    if not all(all(item["targets"].values()) for item in results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
