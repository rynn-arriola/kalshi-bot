"""D-044 Phase 1 offline continuity resource fixtures; no venue/account traffic."""
import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import tracemalloc

from benchmark_archive import percentiles
from kalshi_bot.account import PositionRow, ReconciliationReport, Snapshot
from kalshi_bot.continuity import PrivateEpoch, assess_continuity, starting_candidate
from kalshi_bot.history_coverage import EnumerationCoverage, EnumerationReceipt
from kalshi_bot.recovery import RecoveryReport
from kalshi_bot.verification import AccountAudit
from kalshi_bot.writer import LedgerWriter


async def measure(markets, receipts):
    now = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)
    channels = ('fill', 'market_positions', 'order_group_updates', 'user_orders')
    with TemporaryDirectory(prefix='kalshi-continuity-') as folder:
        async with LedgerWriter(Path(folder)/'ledger.db') as writer:
            lags, latencies, reconnect_latencies, assessments = [], [], [], []
            stop = asyncio.Event()
            async def heartbeat():
                while not stop.is_set():
                    due = time.perf_counter()+.002
                    await asyncio.sleep(.002)
                    lags.append(max(0, time.perf_counter()-due))
            timer = asyncio.create_task(heartbeat())
            await asyncio.sleep(0)
            tracemalloc.start()
            wall = time.perf_counter()
            try:
                reconnect_wall = time.perf_counter()
                for i in range(8):
                    started = time.perf_counter()
                    marker = PrivateEpoch(f'epoch-{i}', 0, i+1, writer.epoch, channels, now)
                    await writer.open_private_epoch(marker)
                    await writer.close_private_epoch(marker.epoch_id,
                        closed_at=now+timedelta(seconds=1), ingress_count=1,
                        durable_fill_count=0,
                        terminal_reason='stopped' if i%4 else 'reader_error',
                        clean_local_delivery=i%4 != 0)
                    reconnect_latencies.append(time.perf_counter()-started)
                    await asyncio.sleep(0)
                assert await writer.private_epoch_gap_count(subaccount=0) == 2
                reconnect_elapsed = time.perf_counter()-reconnect_wall
                positions = tuple(PositionRow(f'M{i}', 0, Decimal(1), Decimal('.5'))
                                  for i in range(markets))
                audit = AccountAudit(writer.epoch, writer.revision, True, 0, (), (), (), (), (), 0, ())
                report = ReconciliationReport(Snapshot(positions, (), Decimal(500), 1, 0), now,
                    True, 0, (), audit=audit)
                receipt = EnumerationReceipt('current', 0, 0, 10, 1, 10, 10, writer.epoch,
                    8, 0, 1, 0, 0, 0, '0'*64)
                recovery = RecoveryReport(0, 0, 0, (), (), start_us=0, end_us=10,
                    subaccount=0, generation=8, enumeration=receipt)
                coverage = EnumerationCoverage(0, 0, 10, ((0, 10),), (),
                    tuple(f'receipt-{i}' for i in range(receipts)), 0, 10)
                epoch = PrivateEpoch('current-epoch', 0, 8, writer.epoch, channels, now)
                args = dict(subaccount=0, generation=8, writer_epoch=writer.epoch,
                    writer_revision=writer.revision, report=report, recovery=recovery,
                    coverage=coverage, epoch=epoch, history_ingress_revision=0,
                    ingress_revision=0, persisted_gap_count=2)
                for _ in range(markets):
                    started = time.perf_counter()
                    assessment = assess_continuity(**args)
                    candidate = starting_candidate(report, proposed_boundary=now-timedelta(seconds=1),
                        subaccount=0, writer_epoch=writer.epoch, writer_revision=writer.revision)
                    latencies.append(time.perf_counter()-started)
                    assessments.append((assessment, candidate))
                    assert len(assessment.receipt_ids) == receipts
                    assert not assessment.venue_handoff_proven and not candidate.approved
                    assert not assessment.local_evidence_consistent
                    await asyncio.sleep(0)
                elapsed = time.perf_counter()-wall
                peak = tracemalloc.get_traced_memory()[1]
            finally:
                tracemalloc.stop()
                stop.set()
                await timer
            result = dict(markets=markets, cached_assessments=len(assessments),
                reconnect_epochs=8, synthetic_receipt_ids=receipts,
                enumeration_receipt_objects=1,
                elapsed_seconds=round(elapsed, 4),
                reconnect_elapsed_seconds=round(reconnect_elapsed, 4),
                incremental_peak_bytes=peak, reconnect=percentiles(reconnect_latencies),
                assessment=percentiles(latencies), loop_lag=percentiles(lags))
            result['diagnostic_pass'] = (peak < 40*1024*1024
                and result['reconnect']['p99_ms'] < 250
                and result['assessment']['p99_ms'] < 250
                and result['loop_lag']['p99_ms'] < 50)
            return result


async def main():
    results = [await measure(*size) for size in ((30, 128), (120, 4096))]
    for result in results:
        print(json.dumps(result, sort_keys=True))
    if not all(result['diagnostic_pass'] for result in results):
        raise SystemExit(1)


if __name__ == '__main__':
    asyncio.run(main())
