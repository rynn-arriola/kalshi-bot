"""Disposable D-067 accounting workload; no account APIs or runtime database."""
import asyncio
from dataclasses import replace
import json
from statistics import median
from pathlib import Path
from tempfile import TemporaryDirectory
import time

from benchmark_opening_account import fixture
from kalshi_bot.accounting import entry_blockers
from kalshi_bot.ledger import Ledger
from kalshi_bot.opening_account import build_opening_evidence_async
from kalshi_bot.writer import LedgerWriter


async def measure(rows):
    with TemporaryDirectory() as directory:
        path = Path(directory)/'fixture.db'
        writer = await LedgerWriter(path).start()
        args = fixture(rows)
        args['writer_epoch'], args['writer_revision'] = writer.epoch, writer.revision
        args['report'] = replace(args['report'], audit=replace(args['report'].audit,
            writer_epoch=writer.epoch, writer_revision=writer.revision))
        args['continuity'] = replace(args['continuity'], writer_epoch=writer.epoch,
                                     writer_revision=writer.revision)
        evidence = await build_opening_evidence_async(**args)
        lags, stop = [], asyncio.Event()
        async def pulse():
            while not stop.is_set():
                due = time.perf_counter()+.002
                await asyncio.sleep(.002)
                lags.append(max(0, time.perf_counter()-due))
        heartbeat = asyncio.create_task(pulse())
        await asyncio.sleep(0)
        start, cpu = time.perf_counter(), time.process_time()
        try:
            result = await writer.capture_accounting(evidence, args['report'])
            wall, cpu_used = time.perf_counter()-start, time.process_time()-cpu
            assert result.checkpoint_created and not result.status.ready_for_entry
            assert result.status.event_count == rows+2
        finally:
            stop.set()
            await heartbeat
            await writer.close()
        ledger = Ledger(path)
        hot = {}
        hot_samples = {}
        try:
            for _ in range(100):
                entry_blockers(ledger)
            for markets in (30, 120):
                samples = []
                for _ in range(5):
                    started = time.perf_counter()
                    for _ in range(markets*100):
                        assert 'settlement_reconciliation_required' in entry_blockers(ledger)
                    samples.append((time.perf_counter()-started)/(markets*100))
                hot_samples[str(markets)] = samples
                hot[str(markets)] = median(samples)
        finally:
            ledger.close()
        p99 = sorted(lags)[min(len(lags)-1, int(len(lags)*.99))]
        return dict(rows=rows, wall_seconds=wall, cpu_seconds=cpu_used,
            loop_p99_ms=p99*1000, loop_max_ms=max(lags)*1000,
            payload_bytes=result.status.payload_bytes, hot_seconds_per_check=hot,
            hot_samples_seconds=hot_samples,
            passed=wall<5 and p99<.05 and result.status.payload_bytes<64*1024*1024)


async def main():
    results = [await measure(rows) for rows in (128, 50000)]
    ratios = {key: results[1]['hot_seconds_per_check'][key]/results[0]['hot_seconds_per_check'][key]
              for key in ('30', '120')}
    passed = all(row['passed'] for row in results) and max(ratios.values())<2
    print(json.dumps(dict(results=results, history_scaling_ratios=ratios, passed=passed), indent=2))
    if not passed:
        raise SystemExit(1)


if __name__ == '__main__':
    asyncio.run(main())
