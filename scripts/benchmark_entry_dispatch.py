"""Disposable 30/120-market entry-pair handoff resource fixture."""
import asyncio
from datetime import datetime, timezone
from decimal import Decimal as D
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import tracemalloc

from kalshi_bot.config import BotConfig
from kalshi_bot.writer import LedgerWriter


NOW = datetime(2026, 9, 21, 12, tzinfo=timezone.utc)


def request(ticker, client, side):
    return dict(ticker=ticker, client_order_id=client, side=side, count='10',
        price='.4' if side == 'bid' else '.6',
        time_in_force='good_till_canceled',
        self_trade_prevention_type='taker_at_cross', post_only=True,
        reduce_only=False, cancel_order_on_pause=True, subaccount=0,
        exchange_index=1)


def quantiles(values):
    rows = sorted(values)
    return {name: round(rows[min(len(rows)-1, int((len(rows)-1)*q))]*1000, 3)
            for name, q in (('p50_ms', .5), ('p95_ms', .95), ('p99_ms', .99))}


async def run(markets):
    with TemporaryDirectory() as directory:
        writer = await LedgerWriter(Path(directory)/'entry.db',
                                    market_capacity=markets).start()
        running, lag, prepare, abort = True, [], [], []
        async def heartbeat():
            while running:
                start = time.perf_counter()
                await asyncio.sleep(.001)
                lag.append(max(0., time.perf_counter()-start-.001))
        task = asyncio.create_task(heartbeat())
        tracemalloc.start()
        cpu_start = time.process_time()
        try:
            for index in range(markets):
                ticker = f'M{index:03d}'
                requests = (request(ticker, f'{ticker}-bid', 'bid'),
                            request(ticker, f'{ticker}-ask', 'ask'))
                view = await writer.portfolio(subaccount=0, now=NOW)
                start = time.perf_counter()
                result = await writer.reserve_entry_pair(requests,
                    batch_id=f'batch-{ticker}', view=view, config=BotConfig(),
                    now=NOW, free_cash=D(500), account_known=True,
                    offline_fixture=True, fee_per_contract_bound=D(0))
                prepare.append(time.perf_counter()-start)
                assert result.reserved, result.blockers
                start = time.perf_counter()
                await writer.abort_batch(result.batch)
                abort.append(time.perf_counter()-start)
            cpu = time.process_time()-cpu_start
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
            running = False
            await task
        rows = await writer.mutations()
        capacity = await writer.command_capacity()
        result = dict(markets=markets, pairs=markets, mutations=len(rows),
            prepare=quantiles(prepare), abort=quantiles(abort),
            loop=quantiles(lag), cpu_seconds=round(cpu, 4),
            cpu_ms_per_pair=round(cpu/markets*1000, 3),
            allocation_peak_bytes=peak, writer_backlog=writer.backlog,
            max_writer_backlog=writer.max_backlog_observed,
            active_entries=(await writer.portfolio(subaccount=0, now=NOW)).entry_count,
            held_capacity=(capacity.mutation_held+capacity.intent_held+capacity.order_held))
        result['passed'] = (result['prepare']['p99_ms'] < 100
            and result['abort']['p99_ms'] < 100 and result['loop']['p99_ms'] < 50
            and peak < 16*1024*1024 and result['active_entries'] == 0
            and result['held_capacity'] == 0 and writer.backlog == 0)
        print(json.dumps(result, sort_keys=True))
        await writer.close()
        return result['passed']


async def main():
    if not all([await run(markets) for markets in (30, 120)]):
        raise SystemExit('entry dispatch resource acceptance failed')


if __name__ == '__main__':
    asyncio.run(main())
