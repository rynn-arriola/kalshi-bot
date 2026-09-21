"""Offline resource fixture, no market/paper run or live performance acceptance.

30/120 owned synthetic orders: stream order -> partial fill -> terminal order.
Measure serial durable acknowledgement/loop lag with no backlog by construction.
Then stage 1,000/4,000 missing historical fills separately (never apply to P&L).
All databases are fresh local temporary files. No keys or network calls.
"""
import asyncio
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import tracemalloc

from kalshi_bot.account import AccountCoordinator
from kalshi_bot.ledger import Fill
from kalshi_bot.orders import timestamp_us
from kalshi_bot.recovery import HistoricalFill, HistoryEvidence
from kalshi_bot.writer import LedgerWriter


def percentiles(values):
    values = sorted(values)
    return {f"p{p}_ms": round(values[int((len(values)-1)*p/100)]*1000, 3) for p in (50, 95, 99)}


async def run_case(markets, historical_rows):
    now = datetime(2026, 9, 20, 5, tzinfo=timezone.utc)
    with TemporaryDirectory(prefix="kalshi-recovery-check-") as directory:
        async with LedgerWriter(Path(directory)/"ledger.db") as writer:
            owner = AccountCoordinator(writer, subaccount=0)
            generation = owner.connect_generation()
            for n in range(markets):
                await writer.reserve_intent(f"c-{n}", dict(ticker=f"A-{n}", side="bid", price="0.5",
                    count="10", subaccount=0, exchange_index=0), now)
                await writer.transition_intent(f"c-{n}", "SENDING")
            lags, latencies, stop = [], [], asyncio.Event()
            async def heartbeat():
                while not stop.is_set():
                    due = time.perf_counter()+0.002
                    await asyncio.sleep(0.002)
                    lags.append(max(0, time.perf_counter()-due))
            timer = asyncio.create_task(heartbeat())
            tracemalloc.start()
            wall, cpu = time.perf_counter(), time.process_time()
            try:
                for n in range(markets):
                    msg = dict(order_id=f"o-{n}", client_order_id=f"c-{n}", ticker=f"A-{n}", book_side="bid",
                        yes_price_dollars="0.5", initial_count_fp="10", fill_count_fp="0", remaining_count_fp="10",
                        status="resting", subaccount_number=0, exchange_index=0, last_updated_ts_ms=1)
                    fill = dict(trade_id=f"t-{n}", order_id=f"o-{n}", market_ticker=f"A-{n}", book_side="bid",
                                yes_price_dollars="0.5", count_fp="5", fee_cost="0", subaccount=0)
                    terminal = msg | dict(status="canceled", fill_count_fp="5", remaining_count_fp="0", last_updated_ts_ms=2)
                    for kind, payload in (("user_order", msg), ("fill", fill), ("user_order", terminal)):
                        started = time.perf_counter()
                        await owner.on_event(dict(type=kind, msg=payload), generation=generation, received_at=now)
                        latencies.append(time.perf_counter()-started)
                elapsed, used = time.perf_counter()-wall, time.process_time()-cpu
                _, peak = tracemalloc.get_traced_memory()
            finally:
                tracemalloc.stop()
                stop.set()
                await timer
            inventory = await writer.inventory()
            assert len(inventory.positions) == markets and inventory.unresolved_intents == 0
            print(json.dumps(dict(case="account_events", markets=markets, events=len(latencies),
                wall_seconds=round(elapsed, 4), cpu_seconds=round(used, 4), events_per_second=round(len(latencies)/elapsed, 1),
                durable_event_ack=percentiles(latencies), loop_lag=percentiles(lags), heartbeat_samples=len(lags),
                incremental_peak_bytes=peak), sort_keys=True))
            stamp = timestamp_us(now.isoformat())
            records = tuple(HistoricalFill(Fill(f"history-{n}", f"external-{n}", "ARCHIVE", "bid",
                        Decimal(1), Decimal("0.5"), Decimal(0)), stamp, 0, 0) for n in range(historical_rows))
            evidence = HistoryEvidence(stamp-1, stamp+1, stamp, 0, records, 1, 0)
            tracemalloc.start()
            wall, cpu = time.perf_counter(), time.process_time()
            try:
                audit = await writer.audit_history(evidence, now)
                elapsed, used = time.perf_counter()-wall, time.process_time()-cpu
                _, peak = tracemalloc.get_traced_memory()
            finally:
                tracemalloc.stop()
            assert len(audit.missing_fill_keys) == historical_rows
            assert (await writer.inventory()).positions == inventory.positions
            print(json.dumps(dict(case="history_staging", rows=historical_rows, wall_seconds=round(elapsed, 4),
                cpu_seconds=round(used, 4), incremental_peak_bytes=peak, changes_trading_positions=False), sort_keys=True))


async def main():
    for markets, historical_rows in ((30, 1000), (120, 4000)):
        await run_case(markets, historical_rows)


if __name__ == "__main__":
    asyncio.run(main())
