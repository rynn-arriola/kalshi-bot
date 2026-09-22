"""Synthetic selection CPU/latency fixture, no venue or credentials."""
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
import json
import time
import tracemalloc

from kalshi_bot.adapters import PriceBand
from kalshi_bot.books import Book, Ladder
from kalshi_bot.exits import ExitTerms
from kalshi_bot.portfolio import PortfolioView
from kalshi_bot.quoting import Program
from kalshi_bot.risk import WindowState, window_bounds
from kalshi_bot.selection import MarketSelector
from benchmark_write_quota_source import percentiles


NOW = datetime(2026, 9, 21, 12, tzinfo=timezone.utc)


def inputs(ticker, levels=20, programs=1):
    b = Book(ticker, Ladder(4096), Ladder(4096), True)
    for i in range(levels):
        b.bids.set(D('.4999')-D(i)/10000, D(100))
        b.asks.set(D('.5001')+D(i)/10000, D(100))
    ps = tuple(Program(str(i),ticker,NOW-timedelta(hours=1),NOW+timedelta(hours=1),
                       D(1000),5000,1000000,False) for i in range(programs))
    terms = ExitTerms(ticker,(PriceBand(D(0),D(1),D('.0001')),),NOW,NOW+timedelta(minutes=30),
        NOW+timedelta(hours=4),event_risk_at=NOW+timedelta(hours=2),taker_fee_per_contract_bound=D('.02'))
    return b, ps, terms


async def run(markets):
    selector = MarketSelector()
    data = [inputs(f'M{i:03d}') for i in range(markets)]
    latencies, lag = [], []
    running = True
    async def heartbeat():
        while running:
            start=time.perf_counter()
            await asyncio.sleep(.001)
            lag.append(max(0.,time.perf_counter()-start-.001))
    pulse=asyncio.create_task(heartbeat())
    tracemalloc.start()
    cpu_start, wall_start = time.process_time(),time.perf_counter()
    try:
        for _ in range(10):
            for book, ps, terms in data:
                started=time.perf_counter()
                selector.update(book,ps,terms=terms,now=NOW,valid_until=NOW+timedelta(seconds=5))
                latencies.append(time.perf_counter()-started)
                await asyncio.sleep(0)
            result=selector.propose(view=PortfolioView('fixture',1,0,NOW,(),(),D(0),0,()),
                window=WindowState(*window_bounds(NOW),D(0),30,False,NOW),free_cash=D(500),
                account_known=True,now=NOW,current=lambda _:True)
            assert len(result.additions)==15 and not result.authorized
        cpu,wall=time.process_time()-cpu_start,time.perf_counter()-wall_start
        peak=tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
        running=False
        await pulse
    update,loop=percentiles(latencies),percentiles(lag)
    passed=cpu<5 and peak<16*1024*1024 and update['p99_ms']<50 and loop['p99_ms']<50
    print(json.dumps(dict(markets=markets,updates=len(latencies),update=update,loop=loop,
        cpu_seconds=round(cpu,4),wall_seconds=round(wall,4),allocation_peak_bytes=peak,
        rows=len(selector.board.markets),auxiliary_rows=len(selector._fees),passed=passed)))
    return passed


def maximum_input():
    selector=MarketSelector(1)
    book, ps, terms=inputs('BOUND',4096,16)
    started=time.perf_counter()
    selector.update(book,ps,terms=terms,now=NOW,valid_until=NOW+timedelta(seconds=5))
    print(json.dumps(dict(boundary_levels_per_side=4096,boundary_programs=16,
        update_ms=round((time.perf_counter()-started)*1000,3),
        rows=len(selector.board.markets['BOUND']),representative_latency_gate=False)))
    assert len(selector.board.markets['BOUND'])==16


async def main():
    if not all([await run(n) for n in (30,120)]):
        raise SystemExit('selection resource target failed')
    maximum_input()


if __name__=='__main__': asyncio.run(main())
