"""Offline event/ranking resource check, not a market or paper-trading run.

Workloads: 30/120 synthetic markets, 40 levels/side, two shards, 20 bursts
of one ordered delta per market plus one private durable risk observation.
Bounds: <=8192 queued messages per lane, <=128 ranked markets, <=32 MiB traced
incremental memory. Diagnostic budgets: p99 event-to-rank <=500 ms, loop lag
<=100 ms and private-event-to-durable-risk <=100 ms. These are development
regression budgets, not approved live capacity or a production SLA.
"""
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import tracemalloc

from kalshi_bot.adapters import PriceBand
from kalshi_bot.books import BookConnection
from kalshi_bot.engine import EventEngine
from kalshi_bot.quoting import Program
from kalshi_bot.ranking import RankingBoard
from kalshi_bot.writer import LedgerWriter


def percentile(values, percentile):
    return sorted(values)[int((len(values)-1)*percentile/100)]*1000 if values else 0


def summary(values):
    return {f"p{p}_ms": round(percentile(values, p), 3) for p in (50, 95, 99)}


async def measure(markets):
    tickers = tuple(f"M-{i}" for i in range(markets))
    now = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)
    program = Program("P", "M", now-timedelta(hours=1), now+timedelta(hours=1), D(1000), 5000, 1000000, False)
    bands = (PriceBand(D(0), D(1), D(".001")),)
    rank_latencies, private_latencies, lags, queued_at = [], [], [], {}
    board = RankingBoard(128)
    with TemporaryDirectory(prefix="kalshi-engine-check-") as directory:
        async with LedgerWriter(Path(directory)/"ledger.db") as writer:
            async def private(event, generation):
                await writer.observe(now)
                private_latencies.append(time.perf_counter()-event["queued"])

            async def evaluate(ticker, book, generation):
                board.update(book, (replace(program, ticker=ticker),), bands, now=now,
                             valid_until=now+timedelta(seconds=10), market_open=True)
                rank_latencies.append(time.perf_counter()-queued_at[ticker])

            async def deadline(ticker): await writer.observe(now)

            engine = EventEngine({"a": BookConnection(tickers[::2]), "b": BookConnection(tickers[1::2])},
                                 private_handler=private, evaluate=evaluate, deadline_handler=deadline,
                                 invalidate=board.invalidate)
            private_epoch = engine.begin_private_epoch()
            epochs = {n: engine.begin_book_epoch(n) for n in ("a", "b")}
            seq = {"a": 0, "b": 0}
            stop = asyncio.Event()
            async def heartbeat():
                while not stop.is_set():
                    due = time.perf_counter()+.002
                    await asyncio.sleep(.002)
                    lags.append(max(0, time.perf_counter()-due))
            task = asyncio.create_task(heartbeat())
            tracemalloc.start()
            wall, cpu = time.perf_counter(), time.process_time()
            try:
                for burst in range(21):
                    for i, ticker in enumerate(tickers):
                        name = "a" if i % 2 == 0 else "b"
                        seq[name] += 1
                        msg = dict(market_ticker=ticker)
                        if burst == 0:
                            msg.update(yes_dollars_fp=[[str(D(".49")-D(j)/1000), "100"] for j in range(40)],
                                       no_dollars_fp=[[str(D(".51")+D(j)/1000), "100"] for j in range(40)])
                            kind = "orderbook_snapshot"
                        else:
                            msg.update(side="yes", price_dollars=".49", delta_fp="1")
                            kind = "orderbook_delta"
                        queued_at[ticker] = time.perf_counter()
                        engine.submit_book(name, dict(type=kind, sid=1, seq=seq[name], msg=msg), generation=epochs[name])
                    engine.submit_private(dict(queued=time.perf_counter()), generation=private_epoch)
                    while engine.backlog or engine.dirty.pending:
                        await engine.step()
                        await asyncio.sleep(0)
                rows = board.ranked(now=now, by="remaining_reward")
                assert len(rows) == markets and all(not r.blockers and not r.trade_ready for r in rows)
                elapsed, used = time.perf_counter()-wall, time.process_time()-cpu
                _, peak = tracemalloc.get_traced_memory()
            finally:
                tracemalloc.stop()
                stop.set()
                await task
                engine.stop()
            result = dict(markets=markets, events=engine.processed, rankings=engine.decisions,
                          wall_seconds=round(elapsed, 4), cpu_seconds=round(used, 4),
                          event_to_rank=summary(rank_latencies), private_to_durable_risk=summary(private_latencies),
                          loop_lag=summary(lags), heartbeat_samples=len(lags), queue_high_water=engine.high_water,
                          incremental_peak_bytes=peak)
            result["diagnostic_budgets_pass"] = (percentile(rank_latencies, 99) <= 500
                and percentile(private_latencies, 99) <= 100 and percentile(lags, 99) <= 100 and peak <= 32*1024*1024)
            print(json.dumps(result, sort_keys=True))
            return result["diagnostic_budgets_pass"]


async def main():
    results = [await measure(markets) for markets in (30, 120)]
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
