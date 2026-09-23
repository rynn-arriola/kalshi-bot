"""Synthetic 1,024-book runtime burst/reconnect benchmark; no venue access.

Uses an empty disposable real writer and real engine/management/selector. Source
clocks are fixed fixtures. Timings use wall/CPU clocks; private messages and due
timers are scheduling sentinels, not claimed real fill/cancel round trips.
"""
import asyncio
import json
from pathlib import Path
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
from test_bot_broad_discovery import BroadTests
from probe_book_capacity import distribution, working_set


async def main():
    fixture = BroadTests('test_full_scope_ranked_with_unchanged_order_and_money_limits')
    await fixture.asyncSetUp()
    r = fixture.r
    original_read = fixture.writer.market_inventory
    read_count = 0
    async def counted(*args,**kwargs):
        nonlocal read_count
        read_count += 1
        return await original_read(*args,**kwargs)
    fixture.writer.market_inventory = counted
    loop_lags, private_lags, deadline_lags, rounds, proposal_times = [], [], [], [], []
    proposal_retries = 0
    pending_deadline = None
    stopped = False
    async def private(event, generation):
        private_lags.append((time.perf_counter()-event['queued'])*1000)
    async def deadline(ticker):
        nonlocal pending_deadline
        if pending_deadline is not None:
            deadline_lags.append((time.perf_counter()-pending_deadline)*1000)
            pending_deadline = None
    r.engine.private_handler = private
    r.engine.deadline_handler = deadline
    async def pulse():
        nonlocal pending_deadline
        while not stopped:
            due = time.perf_counter()+.01
            await asyncio.sleep(.01)
            loop_lags.append(max(0,time.perf_counter()-due)*1000)
            if not stopped:
                r.engine.submit_private({'queued':time.perf_counter()},
                    generation=r.engine.private_generation)
                if pending_deadline is None:
                    pending_deadline = time.perf_counter()
                    r.engine.schedule(fixture.tickers[0], r.clock())
    heartbeat = asyncio.create_task(pulse())
    cpu, started = time.process_time(), time.perf_counter()
    try:
        for _ in range(5):
            before = time.perf_counter()
            await fixture.populate()
            # Synthetic private sentinels can interrupt a first evaluation.
            # Model subsequent dirty-book refreshes without resetting epochs;
            # real quiet-book snapshots supply these ongoing evaluations.
            for _ in range(8):
                gate = fixture.s.initial_ranking
                if fixture.s.initial_ranking_ready():
                    break
                for ticker in set(gate.scope)-gate.evaluated:
                    r.engine.dirty.mark(ticker)
                while r.engine.dirty.pending or r.engine.private:
                    await r.engine.step()
            proposal_start = time.perf_counter()
            for attempt in range(8):
                await r.engine.step()
                proposal = await fixture.s.propose(window=fixture.window,free_cash=500)
                if not proposal.blockers:
                    break
                assert set(proposal.blockers) <= {'selection_sources_changed', 'selection_sources_unavailable'}
                proposal_retries += 1
            proposal_times.append(time.perf_counter()-proposal_start)
            assert len(proposal.additions)==15
            rounds.append(time.perf_counter()-before)
        # Drain the last sentinel without manufacturing another read or venue event.
        await r.engine.step()
        result = dict(markets=1024,burst_reconnect_rounds=5,
            initial_ranked_seconds=rounds[0],warm_ranked_seconds=rounds[1:],
            proposal_seconds=proposal_times,
            proposal_source_retries=proposal_retries,
            cpu_seconds=time.process_time()-cpu,wall_seconds=time.perf_counter()-started,
            inventory_reads=read_count,writer_capacity=fixture.writer.market_capacity,
            entry_pairs=len(proposal.additions),engine=r.engine.status(),
            initial_ranking=fixture.s.initial_ranking.status(),
            loop_lag_ms=distribution(loop_lags),private_sentinel_ms=distribution(private_lags),
            due_sentinel_ms=distribution(deadline_lags),working_set_bytes=working_set())
        result['passed']=(rounds[0]<5 and max(rounds[1:])<2 and read_count==1024
            and len(fixture.s.selector.board.markets)==1024
            and not r.engine.failed and not any(r.engine.book_failures.values())
            and result['loop_lag_ms']['p99']<100
            and result['private_sentinel_ms']['p99']<100
            and result['due_sentinel_ms']['p99']<100
            and result['working_set_bytes']<512*1024*1024)
    finally:
        stopped = True
        await heartbeat
        await fixture.asyncTearDown()
    print(json.dumps(result,indent=2))
    return 0 if result['passed'] else 1


if __name__=='__main__':
    raise SystemExit(asyncio.run(main()))
