"""Offline native-Windows SQLite/async latency fixture, not trading simulation.

Workload: 30 and 120 synthetic tickers, 4 open/close cycles each, one durable
fill acknowledgement at a time, WAL/FULL in a fresh local temporary directory.
2ms event-loop heartbeat; report CPU/wall, ack and scheduling p50/p95/p99, traced
memory and backlog. No pass/fail live SLA is implied; no keys/network/old data.
"""
import asyncio
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import tracemalloc

from kalshi_bot.ledger import Fill
from kalshi_bot.writer import LedgerWriter


def percentiles(values):
    data = sorted(values)
    return {f"p{p}_ms": round(data[min(len(data)-1, int((len(data)-1)*p/100))]*1000, 3)
            for p in (50, 95, 99)}


async def measure(markets):
    stamp = datetime(2026, 9, 19, 5, tzinfo=timezone.utc)
    latencies, lags, stop = [], [], asyncio.Event()
    async def heartbeat():
        while not stop.is_set():
            due = time.perf_counter()+0.002
            await asyncio.sleep(0.002)
            lags.append(max(0, time.perf_counter()-due))
    with TemporaryDirectory(prefix="kalshi-writer-check-") as directory:
        async with LedgerWriter(Path(directory)/"ledger.db") as writer:
            timer = asyncio.create_task(heartbeat())
            tracemalloc.start()
            wall, cpu, backlog = time.perf_counter(), time.process_time(), 0
            try:
                for cycle in range(4):
                    for side in ("bid", "ask"):
                        for ticker in range(markets):
                            key = f"{cycle}-{side}-{ticker}"
                            f = Fill(key, "o-"+key, f"FIXTURE-{ticker}", side,
                                     Decimal(10), Decimal("0.5"), Decimal(0))
                            started = time.perf_counter()
                            await writer.fill(f, stamp)
                            latencies.append(time.perf_counter()-started)
                            backlog = max(backlog, writer.backlog)
                elapsed, used = time.perf_counter()-wall, time.process_time()-cpu
                _, peak = tracemalloc.get_traced_memory()
            finally:
                tracemalloc.stop()
                stop.set()
                await timer
            inventory = await writer.inventory()
            assert inventory.positions == ()
            return dict(markets=markets, fills=len(latencies), wall_seconds=round(elapsed, 4),
                        cpu_seconds=round(used, 4), fills_per_second=round(len(latencies)/elapsed, 1),
                        durable_ack=percentiles(latencies), event_loop_lag=percentiles(lags),
                        heartbeat_samples=len(lags), max_backlog_at_ack=backlog,
                        peak_traced_bytes=peak)


async def main():
    for markets in (30, 120):
        print(json.dumps(await measure(markets), sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
