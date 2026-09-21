"""Bounded synthetic cash-evidence normalization; no credentials or venue calls."""
import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import math
import time
import tracemalloc

from kalshi_bot.account import ReconciliationReport, Snapshot
from kalshi_bot.continuity import ContinuityAssessment
from kalshi_bot.opening_account import build_opening_evidence_async
from kalshi_bot.rest import PageSet
from kalshi_bot.verification import AccountAudit


def fixture(total):
    now = datetime(2026, 9, 21, 12, tzinfo=timezone.utc)
    stamp = int(now.timestamp())
    audit = AccountAudit('fixture', 1, True, 0, (), (), (), (), (), 0, ())
    report = ReconciliationReport(Snapshot((), (), Decimal(500), stamp, 0),
                                   now, True, 0, (), audit=audit)
    continuity = ContinuityAssessment(0, 1, 'fixture', 1, (), (), None,
        'unobserved', False, False, ('venue_history_stream_handoff_unproven',))
    names = ('settlements', 'subaccount_transfers', 'intra_exchange_transfers',
             'deposits', 'withdrawals')
    sources = {}
    for index, name in enumerate(names):
        size = total//5 + int(index < total%5)
        rows = []
        for i in range(size):
            if name == 'settlements':
                row = dict(ticker=f'M{i}', exchange_index=0, event_ticker=f'E{i}',
                    market_result='yes', yes_count_fp='10.00', no_count_fp='0.00',
                    yes_total_cost_dollars='4.0000', no_total_cost_dollars='0.0000',
                    revenue=1000, fee_cost='0.0100', settled_time=now.isoformat(), value=100)
            elif name == 'subaccount_transfers':
                row = dict(transfer_id=f'T{i}', from_subaccount=0, to_subaccount=1,
                           amount_cents=100, created_ts=stamp, exchange_index=0)
            elif name == 'intra_exchange_transfers':
                row = dict(transfer_id=f'I{i}', source='event_contract', destination='margined',
                    source_exchange_shard=0, destination_exchange_shard=1,
                    amount='1.0000', status='complete', created_ts=stamp)
            else:
                row = dict(id=f'F{i}', status='applied', type='ach', amount_cents=100,
                           fee_cents=0, created_ts=stamp, finalized_ts=stamp)
            rows.append(row)
        query = (('subaccount', 0), ('limit', 1000)) if name == 'settlements' else (('limit', 1000),)
        sources[name] = PageSet(tuple(rows), max(1, math.ceil(size/1000)),
                               len(json.dumps(rows).encode()), name, query, True)
    return dict(report=report, continuity=continuity, subaccount=0,
        proposed_boundary=now-timedelta(hours=1), writer_epoch='fixture', writer_revision=1,
        cash_document=dict(balance=50000, balance_dollars='500.0000', portfolio_value=0,
                           updated_ts=stamp), **sources)


async def measure(total):
    args = fixture(total)
    timings, cpus, lags = [], [], []
    stop = asyncio.Event()
    async def heartbeat():
        while not stop.is_set():
            due = time.perf_counter()+.002
            await asyncio.sleep(.002)
            lags.append(max(0, time.perf_counter()-due))
    timer = asyncio.create_task(heartbeat())
    try:
        await asyncio.sleep(0)  # Arm the heartbeat before the first worker job.
        for _ in range(3):
            started, cpu = time.perf_counter(), time.process_time()
            evidence = await build_opening_evidence_async(**args)
            timings.append(time.perf_counter()-started)
            cpus.append(time.process_time()-cpu)
            assert not evidence.approved and not evidence.ready_for_entry
            assert sum(source.rows for source in evidence.sources) == total
        stop.set()
        await timer
        # Trace allocations separately: tracing overhead is not normal latency.
        tracemalloc.start()
        evidence = await build_opening_evidence_async(**args)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        limit = .250 if total <= 4096 else 3.0
        lag99 = sorted(lags)[min(len(lags)-1, int(len(lags)*.99))]
        result = dict(rows=total, wall_max_ms=max(timings)*1000,
            cpu_max_ms=max(cpus)*1000, peak_bytes=peak, loop_lag_p99_ms=lag99*1000,
            loop_lag_max_ms=max(lags)*1000, heartbeat_samples=len(lags),
            samples=3, passed=max(timings)<limit and peak<40*1024*1024 and lag99<.050)
        return result
    finally:
        stop.set()
        await timer
        if tracemalloc.is_tracing():
            tracemalloc.stop()


async def main():
    results = [await measure(total) for total in (128, 4096, 50000)]
    print(json.dumps(results, indent=2))
    if not all(result['passed'] for result in results):
        raise SystemExit(1)


if __name__ == '__main__':
    asyncio.run(main())
