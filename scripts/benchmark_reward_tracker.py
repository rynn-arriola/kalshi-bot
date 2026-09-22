"""Synthetic reward telemetry load. No account, credentials, sockets or ledger."""
import asyncio
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
import json
import time
import tracemalloc
from types import MappingProxyType

from kalshi_bot.discovery_candidates import CandidateDiscovery
from kalshi_bot.incentive_discovery import IncentiveCatalog
from kalshi_bot.quoting import Quote
from kalshi_bot.reward_tracker import RewardTracker
from kalshi_bot.selection_runtime import ProgramObservation
from benchmark_market_selection import inputs, NOW
from benchmark_write_quota_source import percentiles


async def run(markets):
    tracker = RewardTracker(scope='offline-fixture')
    data = [inputs(f'M{i:03}') for i in range(markets)]
    updates,lag = [],[]
    running = True
    async def heartbeat():
        while running:
            begin = time.perf_counter()
            await asyncio.sleep(.001)
            lag.append(max(0,time.perf_counter()-begin-.001))
    pulse = asyncio.create_task(heartbeat())
    tracemalloc.start()
    cpu_start,wall_start = time.process_time(),time.perf_counter()
    try:
        for i in range(10):
            now = NOW+timedelta(seconds=i)
            for b, ps, terms in data:
                p = replace(ps[0],program_id=b.ticker)
                q = (Quote('bid',max(b.bids.levels),D(10)),Quote('ask',min(b.asks.levels),D(10)))
                before = time.perf_counter()
                tracker.observe(p,book=b,bands=terms.bands,quotes=q,reflected_known=True,
                    at=now,valid_until=now+timedelta(seconds=5),continuity=('epoch',1))
                result = tracker.progress(p.program_id,now=now,exit_at=terms.deadline)
                assert not result.authorized and result.paid_usd is None
                updates.append(time.perf_counter()-before)
                await asyncio.sleep(0)
        checkpoint = tracker.checkpoint()
        restored = RewardTracker(scope=tracker.scope)
        restored.restore(checkpoint)
        assert len(restored.records) == markets
        assert all(row.estimate > 0 and row.sample is None for row in restored.records.values())
        cpu,wall = time.process_time()-cpu_start,time.perf_counter()-wall_start
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
        running = False
        await pulse
    update,loop = percentiles(updates),percentiles(lag)
    passed = cpu < 5 and peak < 16*1024*1024 and update['p99_ms'] < 50 and loop['p99_ms'] < 50
    return dict(markets=markets,updates=len(updates),cpu_seconds=round(cpu,4),wall_seconds=round(wall,4),
                peak_bytes=peak,update=update,loop=loop,passed=passed)


def discovery():
    base = inputs('BASE')[1][0]
    rows = {f'M{i:05}':ProgramObservation((replace(base,program_id=str(i),ticker=f'M{i:05}'),),
              NOW,NOW+timedelta(minutes=5)) for i in range(10000)}
    catalog = IncentiveCatalog(1,MappingProxyType(rows),frozenset(),NOW,NOW+timedelta(minutes=5),
                              100,400,100,10000,1000000)
    before = time.perf_counter()
    result = CandidateDiscovery().choose(catalog,now=NOW,budget=128,protected=('OWNED',))
    elapsed = (time.perf_counter()-before)*1000
    assert len(result.tickers) == 128 and 'OWNED' in result.tickers and not result.authorized
    return dict(programs=10000,budget=128,elapsed_ms=round(elapsed,3),passed=elapsed < 50)


def maximum_input():
    b, programs, terms = inputs('BOUND',4096,16)
    tracker = RewardTracker(scope='offline-fixture')
    quotes = (Quote('bid',max(b.bids.levels),D(10)),Quote('ask',min(b.asks.levels),D(10)))
    before = time.perf_counter()
    tracker.observe_many(programs,book=b,bands=terms.bands,quotes=quotes,reflected_known=True,
        at=NOW,valid_until=NOW+timedelta(seconds=5),continuity=('epoch',1))
    elapsed = (time.perf_counter()-before)*1000
    assert len(tracker.records) == 16
    return dict(levels_per_side=4096,programs=16,elapsed_ms=round(elapsed,3),
                representative_latency_gate=False)


async def main():
    result = dict(tracker=[await run(30),await run(120)],discovery=discovery(),maximum=maximum_input())
    print(json.dumps(result,indent=2))
    return 0 if all(r['passed'] for r in result['tracker']) and result['discovery']['passed'] else 1


if __name__ == '__main__': raise SystemExit(asyncio.run(main()))
