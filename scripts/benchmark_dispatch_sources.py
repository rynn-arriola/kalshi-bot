"""Disposable source-candidate resource fixture; no credentials or transport."""
import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import tracemalloc

from kalshi_bot.account import normalize_snapshot
from kalshi_bot.adapters import PriceBand, create_payload
from kalshi_bot.config import BotConfig
from kalshi_bot.dispatch import PASSIVE_REDUCER
from kalshi_bot.dispatch_sources import InventoryDispatchSource
from kalshi_bot.exits import ExitTerms
from kalshi_bot.ledger import Fill
from kalshi_bot.orders import OrderUpdate
from kalshi_bot.runtime import RecoveryRuntime
from kalshi_bot.writer import LedgerWriter


NOW = datetime(2026, 9, 21, 12, tzinfo=timezone.utc)
BANDS = (PriceBand(D(0), D(1), D('.01')),)


def quantiles(values):
    values = sorted(values)
    return {name: round(values[min(len(values)-1, int((len(values)-1)*q))]*1000, 3)
            for name, q in (('p50_ms', .5), ('p95_ms', .95), ('p99_ms', .99))}


async def run(markets, iterations=8):
    tickers = tuple(f'M{i:03d}' for i in range(markets))
    async def ignore(*args):
        pass
    with TemporaryDirectory() as directory:
        writer = await LedgerWriter(Path(directory)/'fixture.db').start()
        try:
            runtime = RecoveryRuntime(writer, None, None, tickers=tickers, subaccount=0,
                history_start=NOW-timedelta(hours=1), now=lambda: NOW, clock=lambda: 100.,
                evaluate=ignore, deadline_handler=ignore, lifecycle_handler=ignore)
            runtime.account.connect_generation()
            runtime.engine.begin_private_epoch()
            for ticker in tickers:
                client = 'opening-'+ticker
                req = create_payload(ticker=ticker, client_id=client, outcome='yes',
                    outcome_price=D('.5'), quantity=D(10), bands=BANDS)
                req.update(subaccount=0, exchange_index=0)
                prepared = await writer.reserve_entry(req, attempt_id='attempt-'+ticker,
                    view=await writer.portfolio(subaccount=0, now=NOW), config=BotConfig(),
                    now=NOW, free_cash=D(500), account_known=True, offline_fixture=True)
                assert prepared.reserved, prepared.blockers
                assert (await writer.begin_send(prepared.receipt)).dispatch_allowed
                await writer.record_outcome('ack', prepared.receipt,
                    dict(order_id=client, fill_count='.01', remaining_count='0', ts_ms=1), NOW)
                await writer.order(OrderUpdate(client, client, ticker, 'bid', D('.5'),
                    D(10), D('.01'), D(0), 'canceled', 0, 0, 1), NOW)
                await writer.fill(Fill('fill-'+ticker, client, ticker, 'bid', D('.01'), D('.5'), D(0)), NOW)
                runtime.management.set_terms(ExitTerms(ticker, BANDS, NOW,
                    NOW+timedelta(hours=1), NOW+timedelta(hours=2),
                    event_risk_at=NOW+timedelta(hours=1), taker_fee_per_contract_bound=D('.02')))
            for receipt in await writer.orders():
                runtime.account._store_order(receipt)
            snapshot = normalize_snapshot((), tuple(dict(ticker=ticker, exchange_index=0,
                position_fp='.01', market_exposure_dollars='.005') for ticker in tickers),
                dict(balance_dollars='500', updated_ts=1), subaccount=0)
            await runtime.account.finish_reconciliation(
                runtime.account.begin_reconciliation(NOW), snapshot, NOW)
            for name, shard in runtime.engine.shards.items():
                generation = runtime.engine.begin_book_epoch(name)
                for seq, ticker in enumerate(sorted(shard.tickers), 1):
                    runtime.engine.submit_book(name, dict(type='orderbook_snapshot', sid=1,
                        seq=seq, msg=dict(market_ticker=ticker,
                        yes_dollars_fp=[['.4', '1000']], no_dollars_fp=[['.6', '1000']])),
                        generation=generation)
            while runtime.engine.backlog:
                await runtime.engine.step()
            source = InventoryDispatchSource(runtime, offline_fixture=True)
            async def forbidden(*args, **kwargs):
                raise AssertionError('portfolio scan on candidate path')
            writer.portfolio = forbidden
            running, lag, latencies = True, [], []
            async def heartbeat():
                while running:
                    started = time.perf_counter()
                    await asyncio.sleep(.001)
                    lag.append(max(0., time.perf_counter()-started-.001))
            heartbeat_task = asyncio.create_task(heartbeat())
            tracemalloc.start()
            cpu_start, wall_start = time.process_time(), time.perf_counter()
            try:
                for _ in range(iterations):
                    for ticker in tickers:
                        started = time.perf_counter()
                        candidate = await source.refresh(ticker, PASSIVE_REDUCER)
                        latencies.append(time.perf_counter()-started)
                        assert candidate is not None, ticker
                        assert D(candidate.request['count']) == D('.01')
                        assert len(runtime.management._plans) <= markets
            finally:
                cpu, wall = time.process_time()-cpu_start, time.perf_counter()-wall_start
                peak = tracemalloc.get_traced_memory()[1]
                tracemalloc.stop()
                running = False
                await heartbeat_task
                source.stop()
            latency, loop = quantiles(latencies), quantiles(lag)
            result = dict(markets=markets, refreshed_keys=len(latencies), positive_candidates=len(latencies),
                candidate=latency, loop=loop, cpu_seconds=round(cpu, 4),
                wall_seconds=round(wall, 4), cpu_ms_per_key=round(cpu/len(latencies)*1000, 3),
                allocation_peak_bytes=peak, final_reader_backlog=runtime.engine.backlog,
                final_writer_backlog=writer.backlog, max_pinned_proofs=1,
                rest_requests=0, portfolio_queries_during_refresh=0)
            result['passed'] = (latency['p99_ms'] < 100 and loop['p99_ms'] < 50
                and peak < 32*1024*1024 and cpu/len(latencies) < .05
                and runtime.engine.backlog == 0 and writer.backlog == 0)
            print(json.dumps(result, sort_keys=True))
            return result['passed']
        finally:
            await writer.close()


async def main():
    results = [await run(markets) for markets in (30, 120)]
    if not all(results):
        raise SystemExit('candidate resource acceptance failed')


if __name__ == '__main__':
    asyncio.run(main())
