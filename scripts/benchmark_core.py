"""Offline CPU/memory fixture; no network, credentials, fills or trading simulation."""
import json
import time
import tracemalloc

from kalshi_bot.books import BookConnection
from kalshi_bot.scheduler import DirtyScheduler


def measure(markets: int, events: int = 30000) -> dict:
    names = tuple(f"fixture-{index}" for index in range(markets))
    feed = BookConnection(names)
    generation = feed.reconnect()
    scheduler = DirtyScheduler(markets)
    for seq, ticker in enumerate(names, 1):
        scheduler.register(ticker)
        feed.apply({"type":"orderbook_snapshot","sid":1,"seq":seq,"msg":{
            "market_ticker":ticker,"yes_dollars_fp":[["0.40","100.00"]],
            "no_dollars_fp":[["0.60","100.00"]]}},generation=generation)
    samples = []
    tracemalloc.start()
    cpu_start, start = time.process_time(), time.perf_counter()
    for index in range(events):
        before = time.perf_counter_ns()
        ticker = names[index % markets]
        feed.apply({"type":"orderbook_delta","sid":1,"seq":markets+index+1,"msg":{
            "market_ticker":ticker,"side":"yes","price_dollars":"0.40",
            "delta_fp":"0.01" if (index//markets)%2 == 0 else "-0.01"}},generation=generation)
        scheduler.mark(ticker)
        if index % 100 == 0:
            scheduler.take(time.monotonic())
        if index % 10 == 0:
            samples.append((time.perf_counter_ns()-before)/1000)
    elapsed, cpu = time.perf_counter()-start, time.process_time()-cpu_start
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    samples.sort()
    return dict(markets=markets,events=events,wall_seconds=round(elapsed,4),
                cpu_seconds=round(cpu,4),events_per_second=round(events/elapsed),
                incremental_peak_bytes=peak,current_traced_bytes=current,
                sampled_processing_us={str(p):round(samples[min(len(samples)-1,int(len(samples)*p))],2)
                                       for p in (.5,.95,.99)},
                note="sparse two-level fixture with tracemalloc; excludes network, ledger and live decision latency")


if __name__ == "__main__":
    print(json.dumps({"kind":"offline core microbenchmark", "results":[measure(30),measure(120)]},indent=2))
