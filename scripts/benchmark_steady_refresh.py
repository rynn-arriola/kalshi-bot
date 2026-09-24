"""Synthetic full-cap discovery suppression benchmark; no venue access.

The complete 1,024-market WebSocket scope remains present.  This compares one
ordinary dirty-market pass with the scheduling-only full-cap scope used after
initial ranking.  It does not simulate earnings or grant order authority.
"""
import asyncio
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tests'))

from kalshi_bot.runtime import _SteadyAccountScope
from test_bot_broad_discovery import BroadTests
from test_bot_engine import NOW


async def drain(runtime):
    while runtime.engine.dirty.pending or runtime.engine.private:
        await runtime.engine.step()


async def measured_pass(runtime, tickers):
    before_decisions = runtime.engine.decisions
    before_suppressed = runtime.suppressed_market_evaluations
    for ticker in tickers:
        runtime.engine.dirty.mark(ticker)
    cpu, wall = time.process_time(), time.perf_counter()
    await drain(runtime)
    return dict(cpu_seconds=time.process_time() - cpu,
        wall_seconds=time.perf_counter() - wall,
        decisions=runtime.engine.decisions - before_decisions,
        suppressed=runtime.suppressed_market_evaluations - before_suppressed)


async def main():
    fixture = BroadTests('test_full_scope_ranked_with_unchanged_order_and_money_limits')
    await fixture.asyncSetUp()
    try:
        await fixture.populate()
        runtime = fixture.r
        assert fixture.s.initial_ranking_ready()
        baseline = await measured_pass(runtime, fixture.tickers)
        owners = frozenset(fixture.tickers[:15])
        runtime._steady_account_scope = _SteadyAccountScope(
            runtime.account.generation, runtime.account.revision,
            runtime.writer.epoch, runtime.writer.revision,
            runtime.ingress_revision, NOW.replace(year=NOW.year + 1), (), owners)
        scope_before = runtime._current_steady_account_scope()
        scoped = await measured_pass(runtime, fixture.tickers)
        cpu_ratio = (scoped['cpu_seconds'] / baseline['cpu_seconds']
                     if baseline['cpu_seconds'] else None)
        wall_ratio = scoped['wall_seconds'] / baseline['wall_seconds']
        result = dict(markets=len(fixture.tickers), owner_markets=len(owners),
            scoped_markets_before=0 if scope_before is None else len(scope_before),
            baseline=baseline, full_cap_scoped=scoped,
            cpu_ratio=cpu_ratio, wall_ratio=wall_ratio,
            passed=(baseline['decisions'] == len(fixture.tickers)
                and scoped['decisions'] == len(fixture.tickers)
                and scoped['suppressed'] == len(fixture.tickers) - len(owners)
                and wall_ratio < .35
                and (cpu_ratio is None or cpu_ratio < .35)
                and not runtime.engine.failed))
    finally:
        await fixture.asyncTearDown()
    print(json.dumps(result, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
