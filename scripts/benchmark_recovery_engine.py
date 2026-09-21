"""D-026 offline ingress/engine/writer diagnostic, no network or trading.

Predeclared budgets in BUILD_RECOVERY_ENGINE.md; setup excluded. Tracemalloc,
WAL/FULL, 2ms heartbeat, 128/1024 synthetic 1-contract fills on 30/120 markets.
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
from kalshi_bot.ledger import Ledger
from kalshi_bot.orders import OrderUpdate, record_order, timestamp_us
from kalshi_bot.runtime import RecoveryRuntime
from kalshi_bot.writer import LedgerWriter


async def measure(size, markets):
    now = datetime(2026, 9, 20, 9, tzinfo=timezone.utc)
    executed = now-timedelta(minutes=5)
    tickers = tuple(f"A{i}" for i in range(markets))
    with TemporaryDirectory(prefix="kalshi-engine-recovery-") as folder:
        path = Path(folder)/"ledger.db"
        db = Ledger(path)
        try:
            with db.transaction():
                for i in range(size):
                    ticker = tickers[i%markets]
                    db.reserve_intent(f"c{i}", dict(ticker=ticker, side="bid", price="0.5",
                        count="1", subaccount=0, exchange_index=0), executed)
                    db.transition_intent(f"c{i}", "SENDING")
                    record_order(db, OrderUpdate(f"o{i}", f"c{i}", ticker, "bid", D(".5"), D(1),
                        D(1), D(0), "executed", 0, 0, timestamp_us(executed.isoformat())), executed)
        finally:
            db.close()
        async with LedgerWriter(path) as writer:
            deadlines, evaluations = [], []
            async def evaluate(ticker, *_):
                evaluations.append(ticker)
            async def deadline(ticker):
                deadlines.append(ticker)
            async def lifecycle(event):
                pass
            runtime = RecoveryRuntime(writer, None, None, tickers=tickers, subaccount=0,
                history_start=executed, now=lambda: now, evaluate=evaluate,
                deadline_handler=deadline, lifecycle_handler=lifecycle)
            runtime.account.connect_generation()
            generation = runtime.engine.begin_private_epoch()
            runtime.account_subscribed = True
            account = next(s for s in runtime.specs if s.name == "account")
            sequences = {}
            for name, shard in runtime.engine.shards.items():
                book_generation = runtime.engine.begin_book_epoch(name)
                for seq, ticker in enumerate(sorted(shard.tickers), 1):
                    runtime.engine.submit_book(name, dict(type="orderbook_snapshot", sid=1, seq=seq,
                        msg=dict(market_ticker=ticker, yes_dollars_fp=[[".4", "1000"]],
                                 no_dollars_fp=[[".6", "1000"]])), generation=book_generation)
                sequences[name] = seq
            while runtime.engine.backlog or runtime.engine.dirty.pending:
                await runtime.engine.step()
            lags, latencies, backlogs = [], [], []
            stopped = asyncio.Event()
            async def heartbeat():
                while not stopped.is_set():
                    due = time.perf_counter()+.002
                    await asyncio.sleep(.002)
                    lags.append(max(0, time.perf_counter()-due))
                    backlogs.append(writer.backlog)
            timer = asyncio.create_task(heartbeat())
            await asyncio.sleep(0)
            tracemalloc.start()
            wall, cpu = time.perf_counter(), time.process_time()
            try:
                for i in range(size):
                    ticker = tickers[i%markets]
                    if i%16 == 0:
                        name = runtime.engine.market_shard[ticker]
                        sequences[name] += 1
                        runtime.engine.submit_book(name, dict(type="orderbook_delta", sid=1,
                            seq=sequences[name], msg=dict(market_ticker=ticker, side="yes",
                            price_dollars=".4", delta_fp="1")), generation=runtime.engine.shards[name].generation)
                        runtime.engine.schedule(ticker, time.monotonic())
                    event = dict(type="fill", msg=dict(trade_id=f"f{i}", order_id=f"o{i}",
                        market_ticker=ticker, book_side="bid", count_fp="1", yes_price_dollars=".5",
                        fee_cost=".00001", subaccount=0, exchange_index=0))
                    started = time.perf_counter()
                    await runtime._consume(account, event, generation, set())
                    await runtime.engine.step()
                    latencies.append(time.perf_counter()-started)
                elapsed, used = time.perf_counter()-wall, time.process_time()-cpu
                peak = tracemalloc.get_traced_memory()[1]
            finally:
                tracemalloc.stop()
                stopped.set()
                await timer
            assert not await writer.pending_fills(0)
            assert (await writer.observe(now)).realized_pnl == -D(size)*D(".00001")
            assert sum(q for _, q in (await writer.inventory()).positions) == size
            assert not runtime.entry_allowed and not runtime.recovery_requested.is_set()
            result = dict(fills=size, markets=markets, wall_seconds=round(elapsed, 4),
                cpu_seconds=round(used, 4), incremental_peak_bytes=peak, fill_ack=percentiles(latencies),
                loop_lag=percentiles(lags), heartbeat_samples=len(lags), deadlines=len(deadlines),
                max_sampled_writer_backlog=max(backlogs), engine_high_water=runtime.engine.high_water)
            result["diagnostic_pass"] = (elapsed < 10 and result["fill_ack"]["p99_ms"] < 100
                and result["loop_lag"]["p99_ms"] < 50 and peak < 40*1024*1024
                and len(deadlines) == (size+15)//16)
            return result


async def main():
    for size, markets in ((128, 30), (1024, 120)):
        print(json.dumps(await measure(size, markets), sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
