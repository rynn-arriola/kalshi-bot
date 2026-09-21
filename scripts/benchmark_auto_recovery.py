"""Offline D-025 backfill diagnostic. No network/keys/trading or live SLA.

128/1024 owned fills across 30/120 synthetic markets. Fresh seeded temporary
WAL/FULL ledger, injected paginated evidence, tracemalloc + 2ms heartbeat.
Diagnostic budgets: finish <5s (existing token), replay batch p99 <100ms,
loop lag p99 <50ms, incremental Python peak <40MiB. Setup is excluded.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import tracemalloc

from benchmark_archive import percentiles
from kalshi_bot.account import AccountCoordinator
from kalshi_bot.ledger import Ledger
from kalshi_bot.orders import OrderUpdate, record_order, timestamp_us
from kalshi_bot.rest import PageSet, ReadResult
from kalshi_bot.writer import LedgerWriter


async def measure(size, markets):
    now = datetime(2026, 9, 20, 9, tzinfo=timezone.utc)
    executed = now-timedelta(minutes=5)
    records = tuple(dict(fill_id=f"f{i}", trade_id=f"f{i}", order_id=f"o{i}", ticker=f"A{i%markets}",
        market_ticker=f"A{i%markets}", book_side="bid", count_fp="1", yes_price_dollars="0.5",
        fee_cost="0.00001", created_time=(executed+timedelta(microseconds=i)).isoformat(),
        subaccount_number=0, exchange_index=0) for i in range(size))
    class Reads:
        async def read(self, *args, **kwargs):
            return ReadResult({"trades_created_ts": (now-timedelta(days=1)).isoformat()}, 100)
        async def collect(self, *args, **kwargs):
            return PageSet(records, (size+99)//100, len(json.dumps(records)))
    with TemporaryDirectory(prefix="kalshi-backfill-check-") as folder:
        path = Path(folder)/"ledger.db"
        db = Ledger(path)
        try:
            with db.transaction():
                for i in range(size):
                    db.reserve_intent(f"c{i}", dict(ticker=f"A{i%markets}", side="bid", price="0.5",
                        count="1", subaccount=0, exchange_index=0), executed)
                    db.transition_intent(f"c{i}", "SENDING")
                    record_order(db, OrderUpdate(f"o{i}", f"c{i}", f"A{i%markets}", "bid", D("0.5"),
                        D(1), D(1), D(0), "executed", 0, 0, timestamp_us(executed.isoformat())), executed)
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
            original = writer.recover_fills
            async def tracked(*args, **kwargs):
                start = time.perf_counter()
                result = await original(*args, **kwargs)
                batches.append(time.perf_counter()-start)
                return result
            writer.recover_fills = tracked
            owner = AccountCoordinator(writer, subaccount=0)
            owner.connect_generation()
            timer = asyncio.create_task(heartbeat())
            await asyncio.sleep(0)
            tracemalloc.start()
            wall, cpu = time.perf_counter(), time.process_time()
            try:
                report = await owner.recover_history(Reads(), start=executed-timedelta(seconds=1),
                                                    end=now, now=lambda: now)
                elapsed, used = time.perf_counter()-wall, time.process_time()-cpu
                peak = tracemalloc.get_traced_memory()[1]
            finally:
                tracemalloc.stop()
                stopped.set()
                await timer
            result = dict(fills=size, markets=markets, wall_seconds=round(elapsed, 4),
                cpu_seconds=round(used, 4), incremental_peak_bytes=peak, batch_ack=percentiles(batches),
                loop_lag=percentiles(lags), heartbeat_samples=len(lags), max_sampled_backlog=max(backlogs),
                completed=report is not None)
            result["diagnostic_pass"] = bool(report and report.imported == size and elapsed < 5
                and result["batch_ack"]["p99_ms"] < 100 and result["loop_lag"]["p99_ms"] < 50
                and peak < 40*1024*1024)
            if report:
                assert not report.ready_for_entry
                assert (await writer.observe(now)).realized_pnl == -D(size)*D("0.00001")
            return result


async def main():
    for size, markets in ((128, 30), (1024, 120)):
        print(json.dumps(await measure(size, markets), sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
