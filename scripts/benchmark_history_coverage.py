"""D-035 bounded SQLite history diagnostics, no credentials/network/trading."""
import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import tracemalloc

from benchmark_archive import percentiles
from kalshi_bot.ledger import Fill
from kalshi_bot.orders import timestamp_us
from kalshi_bot.recovery import HistoricalFill, HistoryEvidence
from kalshi_bot.writer import LedgerWriter


async def measure(row_count, receipt_count):
    now = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)
    start = now-timedelta(hours=1)
    stamp = timestamp_us(start.isoformat())
    records = tuple(HistoricalFill(Fill(f'f{i}', f'o{i}', f'M{i%120}', 'bid', '1', '.5', '.01'),
                                  stamp, 0, i%2) for i in range(row_count))
    first = HistoryEvidence(stamp, stamp+10000000, stamp+1, 0, records, 1, 0)
    with TemporaryDirectory(prefix='kalshi-history-coverage-') as folder:
        async with LedgerWriter(Path(folder)/'ledger.db') as writer:
            lags, inspection_times, finalization_times = [], [], []
            stop = asyncio.Event()
            original = writer._execute
            def tracked(db, command, args):
                started = time.perf_counter()
                result = original(db, command, args)
                if command == 'history_complete':
                    finalization_times.append(time.perf_counter()-started)
                return result
            writer._execute = tracked
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
                await writer.audit_history(first, now)
                for i in range(receipt_count-1):
                    left = stamp+(10+i)*1000000
                    ev = HistoryEvidence(left, left+1000000, stamp+1, 0, (), 1, 0)
                    await writer.audit_history(ev, now)
                end = start+timedelta(seconds=10+receipt_count-1)
                for _ in range(receipt_count):
                    before = time.perf_counter()
                    result = await writer.history_coverage(subaccount=0, start=start, end=end)
                    inspection_times.append(time.perf_counter()-before)
                    assert not result.gaps and len(result.receipt_ids) == receipt_count
                    assert not result.ready_for_entry
                elapsed, used = time.perf_counter()-wall, time.process_time()-cpu
                peak = tracemalloc.get_traced_memory()[1]
            finally:
                tracemalloc.stop()
                stop.set()
                await timer
            result = dict(rows=row_count, receipts=receipt_count, inspections=receipt_count,
                wall_seconds=round(elapsed, 4), cpu_seconds=round(used, 4), peak_bytes=peak,
                inspection=percentiles(inspection_times), loop_lag=percentiles(lags),
                max_finalization_ms=round(max(finalization_times)*1000, 3))
            result['diagnostic_pass'] = (elapsed < (3 if row_count == 128 else 15)
                and result['inspection']['p99_ms'] < 250 and result['loop_lag']['p99_ms'] < 50
                and peak < 32*1024*1024)
            return result


async def main():
    results = [await measure(*size) for size in ((128, 30), (4096, 120))]
    for result in results:
        print(json.dumps(result, sort_keys=True))
    if not all(result['diagnostic_pass'] for result in results):
        raise SystemExit(1)


if __name__ == '__main__':
    asyncio.run(main())
