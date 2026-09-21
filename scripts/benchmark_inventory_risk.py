"""D-027 disposable WAL/FULL diagnostic. No network or trading authority."""
import asyncio
from datetime import datetime, timezone
from decimal import Decimal as D
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import tracemalloc

from benchmark_archive import percentiles
from kalshi_bot.ledger import Fill, Ledger
from kalshi_bot.orders import OrderUpdate, record_order
from kalshi_bot.writer import LedgerWriter


async def measure(markets):
    now = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)
    with TemporaryDirectory(prefix="kalshi-risk-diagnostic-") as folder:
        path = Path(folder)/"ledger.db"
        db = Ledger(path)
        try:
            with db.transaction():
                for i in range(markets):
                    ticker = f"A{i}"
                    db.record_fill(Fill(f"fill{i}", f"executed{i}", ticker, "bid", D(4), D(".5"), D(0)), now)
                    db.reserve_intent(f"c{i}", dict(ticker=ticker, side="ask", price=".6", count="4",
                        subaccount=0, exchange_index=0, reduce_only=True), now)
                    db.transition_intent(f"c{i}", "SENDING")
                    record_order(db, OrderUpdate(f"o{i}", f"c{i}", ticker, "ask", D(".6"), D(4),
                        D(0), D(4), "resting", 0, 0, 1), now)
        finally:
            db.close()
        async with LedgerWriter(path) as writer:
            lags, local, global_reads = [], [], []
            stopped = asyncio.Event()
            async def heartbeat():
                while not stopped.is_set():
                    due = time.perf_counter()+.002
                    await asyncio.sleep(.002)
                    lags.append(max(0, time.perf_counter()-due))
            task = asyncio.create_task(heartbeat())
            await asyncio.sleep(0)
            tracemalloc.start()
            wall, cpu = time.perf_counter(), time.process_time()
            try:
                for i in range(markets*4):
                    start = time.perf_counter()
                    inventory = await writer.market_inventory(f"A{i%markets}", subaccount=0)
                    local.append(time.perf_counter()-start)
                    assert inventory.position == 4 and len(inventory.orders) == 1
                    if i % 4 == 0:
                        start = time.perf_counter()
                        view = await writer.portfolio(subaccount=0, now=now)
                        global_reads.append(time.perf_counter()-start)
                        assert view.total == D("3.6")*markets and view.entry_count == 0
                elapsed, used = time.perf_counter()-wall, time.process_time()-cpu
                peak = tracemalloc.get_traced_memory()[1]
            finally:
                tracemalloc.stop()
                stopped.set()
                await task
            result = dict(markets=markets, market_reads=len(local), portfolio_reads=len(global_reads),
                wall_seconds=round(elapsed, 4), cpu_seconds=round(used, 4), incremental_peak_bytes=peak,
                market_read=percentiles(local), portfolio_read=percentiles(global_reads),
                loop_lag=percentiles(lags), heartbeat_samples=len(lags))
            result["diagnostic_pass"] = (result["market_read"]["p99_ms"] < 100
                and result["portfolio_read"]["p99_ms"] < 250
                and result["loop_lag"]["p99_ms"] < 50 and peak < 40*1024*1024)
            return result


async def main():
    results = [await measure(markets) for markets in (30, 120)]
    for result in results:
        print(json.dumps(result, sort_keys=True))
    if not all(result["diagnostic_pass"] for result in results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
