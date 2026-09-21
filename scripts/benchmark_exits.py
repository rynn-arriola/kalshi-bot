"""Offline bounded planner diagnostic; never a trading or reward simulation.

Predeclared workloads: 30/120 markets, 64 levels/side, ten evaluations/market.
Budgets: total wall <=2/8 seconds, per-plan p99 <=50ms. No new network/writer.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
import json
import time

from kalshi_bot.adapters import PriceBand
from kalshi_bot.books import Book, Ladder
from kalshi_bot.exits import ExitTerms, ExitJournal, plan_exit


def run(markets):
    now=datetime(2026,9,20,tzinfo=timezone.utc)
    bands=(PriceBand(D(0),D(1),D('.001')),)
    books=[]
    for i in range(markets):
        b=Book('M'+str(i),Ladder(64),Ladder(64),True)
        for j in range(64):
            b.bids.set(D('.49')-D(j)/1000,D('.2'))
            b.asks.set(D('.51')+D(j)/1000,D('.2'))
        t=ExitTerms(b.ticker,bands,now,now+timedelta(hours=1),now+timedelta(hours=2),
                    event_risk_at=now+timedelta(hours=1),taker_fee_per_contract_bound=D('.02'))
        books.append((b,t))
    samples=[]; start=time.perf_counter(); cpu=time.process_time()
    for _ in range(10):
        for b,t in books:
            began=time.perf_counter()
            result=plan_exit(ticker=b.ticker,position=D(10),basis=D('.5'),
                first_seen_at=now-timedelta(seconds=900),orders=(),book=b,terms=t,journal=ExitJournal(),now=now,complete_scope=True)
            assert result.mode=='passive_deferred' and not result.authorized
            samples.append((time.perf_counter()-began)*1000)
    elapsed=time.perf_counter()-start; cpu=time.process_time()-cpu; samples.sort()
    p99=samples[min(len(samples)-1,int(len(samples)*.99))]
    output=dict(markets=markets,levels_per_side=64,evaluations=len(samples),wall_seconds=round(elapsed,6),
        cpu_seconds=round(cpu,6),p50_ms=round(samples[len(samples)//2],6),p99_ms=round(p99,6),
        passed=elapsed<=(2 if markets==30 else 8) and p99<=50)
    print(json.dumps(output))
    return output['passed']


if __name__=='__main__':
    raise SystemExit(0 if all([run(30),run(120)]) else 1)
