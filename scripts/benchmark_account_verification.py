"""D-028 local snapshot diagnostic, disposable WAL/FULL. No network."""
import asyncio
from datetime import datetime, timezone
from decimal import Decimal as D
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import tracemalloc

from benchmark_archive import percentiles
from kalshi_bot.account import normalize_snapshot
from kalshi_bot.ledger import Fill, Ledger
from kalshi_bot.orders import OrderUpdate, record_order, settle_order
from kalshi_bot.writer import LedgerWriter


async def measure(markets):
    now = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)
    with TemporaryDirectory(prefix="kalshi-account-verification-") as folder:
        path = Path(folder)/"ledger.db"
        db = Ledger(path)
        positions, orders = [], []
        try:
            with db.transaction():
                for i in range(markets):
                    ticker = f"A{i}"
                    for side, filled, remaining, status in (("bid", 10, 0, "executed"), ("ask", 0, 10, "resting")):
                        key = f"{side}{i}"
                        db.reserve_intent(key, dict(ticker=ticker, side=side, price=".5", count="10",
                            subaccount=0, exchange_index=0, reduce_only=side == "ask"), now)
                        db.transition_intent(key, "SENDING")
                        record_order(db, OrderUpdate(key, key, ticker, side, D(".5"), D(10),
                            D(filled), D(remaining), status, 0, 0, 1), now)
                        if filled:
                            db.record_fill(Fill(f"f{i}", key, ticker, side, D(10), D(".5"), D(0)), now)
                            settle_order(db, key)
                        else:
                            orders.append(dict(order_id=key, client_order_id=key, ticker=ticker, status=status,
                                exchange_index=0, book_side=side, yes_price_dollars=".5", remaining_count_fp="10"))
                    positions.append(dict(ticker=ticker, exchange_index=0, position_fp="10", market_exposure_dollars="5"))
        finally:
            db.close()
        snapshot = normalize_snapshot(orders, positions, dict(balance_dollars="500", updated_ts=1), subaccount=0)
        async with LedgerWriter(path) as writer:
            lags, latencies = [], []
            stop = asyncio.Event()
            async def heartbeat():
                while not stop.is_set():
                    due = time.perf_counter()+.002
                    await asyncio.sleep(.002)
                    lags.append(max(0, time.perf_counter()-due))
            timer = asyncio.create_task(heartbeat())
            await asyncio.sleep(0)
            tracemalloc.start()
            wall, cpu = time.perf_counter(), time.process_time()
            try:
                for _ in range(markets):
                    start = time.perf_counter()
                    result = await writer.reconcile_snapshot(snapshot, now=now)
                    latencies.append(time.perf_counter()-start)
                    assert result.consistent and result.unresolved_intents == markets
                elapsed, used = time.perf_counter()-wall, time.process_time()-cpu
                peak = tracemalloc.get_traced_memory()[1]
            finally:
                tracemalloc.stop()
                stop.set()
                await timer
            result = dict(markets=markets, inspections=len(latencies), wall_seconds=round(elapsed, 4),
                cpu_seconds=round(used, 4), incremental_peak_bytes=peak,
                inspection=percentiles(latencies), loop_lag=percentiles(lags), heartbeat_samples=len(lags))
            result["diagnostic_pass"] = (result["inspection"]["p99_ms"] < 250
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
