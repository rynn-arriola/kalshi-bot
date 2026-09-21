"""Offline archive recovery diagnostic; no keys/network or live SLA.

128/4096 synthetic canceled, zero-fill owned orders across 30/120 tickers.
Fresh temporary WAL/FULL ledgers, seeded outside measurement. Injected reads;
measure normalization + binding batches, CPU, Python peak, loop/batch p50/95/99.
Diagnostic budgets: completion within existing five-second token, loop p99 <50ms,
batch p99 <100ms, Python incremental peak <40MiB. Not live acceptance budgets.
"""
import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import tracemalloc

from kalshi_bot.account import AccountCoordinator
from kalshi_bot.ledger import Ledger
from kalshi_bot.rest import PageSet, ReadResult
from kalshi_bot.writer import LedgerWriter


def percentiles(values):
    values = sorted(values)
    return {f"p{p}_ms": round(values[min(len(values)-1, int((len(values)-1)*p/100))]*1000, 3)
            for p in (50, 95, 99)}


async def measure(size, markets):
    now = datetime(2026, 9, 20, 9, tzinfo=timezone.utc)
    rows = tuple(dict(order_id=f"o{i}", client_order_id=f"c{i}", ticker=f"A{i%markets}",
        book_side="bid", yes_price_dollars="0.5", initial_count_fp="10", fill_count_fp="0",
        remaining_count_fp="0", status="canceled", subaccount_number=0, exchange_index=0,
        last_update_time=(now-timedelta(days=2)).isoformat()) for i in range(size))
    class Reads:
        async def read(self, *args, **kwargs):
            return ReadResult({"orders_updated_ts": (now-timedelta(days=1)).isoformat()}, 100)
        async def collect(self, *args, **kwargs):
            return PageSet(rows, (size+99)//100, len(json.dumps(rows)))
    with TemporaryDirectory(prefix="kalshi-archive-check-") as folder:
        path = Path(folder)/"ledger.db"
        db = Ledger(path)
        try:
            with db.transaction():
                for i in range(size):
                    db.reserve_intent(f"c{i}", dict(ticker=f"A{i%markets}", side="bid",
                        price="0.5", count="10", subaccount=0, exchange_index=0), now)
                    db.transition_intent(f"c{i}", "SENDING")
        finally:
            db.close()
        async with LedgerWriter(path) as writer:
            lags, batches, backlogs = [], [], []
            stopped = asyncio.Event()
            async def heartbeat():
                while not stopped.is_set():
                    due = time.perf_counter()+.002
                    await asyncio.sleep(.002)
                    lags.append(max(0, time.perf_counter()-due))
                    backlogs.append(writer.backlog)
            original = writer.order_batch
            async def measured_batch(*args):
                start = time.perf_counter()
                result = await original(*args)
                batches.append(time.perf_counter()-start)
                return result
            writer.order_batch = measured_batch
            owner = AccountCoordinator(writer, subaccount=0)
            owner.connect_generation()
            timer = asyncio.create_task(heartbeat())
            await asyncio.sleep(0)
            tracemalloc.start()
            wall, cpu = time.perf_counter(), time.process_time()
            try:
                report = await owner.recover_archived_orders(Reads(), now=lambda: now)
                elapsed, used = time.perf_counter()-wall, time.process_time()-cpu
                peak = tracemalloc.get_traced_memory()[1]
            finally:
                tracemalloc.stop()
                stopped.set()
                await timer
            result = dict(orders=size, markets=markets, wall_seconds=round(elapsed, 4),
                cpu_seconds=round(used, 4), peak_traced_bytes=peak, batch_ack=percentiles(batches),
                loop_lag=percentiles(lags), heartbeat_samples=len(lags), max_sampled_backlog=max(backlogs),
                completed=report is not None)
            result["diagnostic_pass"] = bool(report and report.owned == size and not report.ready_for_entry
                and elapsed < 5 and result["batch_ack"]["p99_ms"] < 100
                and result["loop_lag"]["p99_ms"] < 50 and peak < 40*1024*1024)
            if report is not None:
                assert (await writer.inventory()).unresolved_intents == 0
            return result


async def main():
    for size, markets in ((128, 30), (4096, 120)):
        print(json.dumps(await measure(size, markets), sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
