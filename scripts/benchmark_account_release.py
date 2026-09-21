"""D-068 synthetic release scaling; run with -m scripts.benchmark_account_release.

Budgets: release p99 <500ms, loop p99 <50ms, measured peak allocation <32MiB,
cash check p99 <25ms; median hot-path history ratio <2 at fixed market count.
120 working markets stress bounded accounting only, not approved trading scale.
"""
import asyncio
from contextlib import closing
from decimal import Decimal as D
import json
from statistics import median
import time
import tracemalloc

from kalshi_bot.account import AccountCoordinator
from kalshi_bot.account_release import cash_limit
from kalshi_bot.accounting import _append, encode
from kalshi_bot.ledger import Ledger
from kalshi_bot.opening_account import parse_cash
from kalshi_bot.orders import OrderUpdate, record_order
from kalshi_bot.writer import LedgerWriter
from tests.test_bot_account_release import AccountReleaseTests, NOW, balance, request


def p99(samples):
    return sorted(samples)[min(len(samples)-1, int(len(samples)*.99))]


async def measure(markets, history):
    fixture = AccountReleaseTests()
    await fixture.asyncSetUp()
    try:
        await fixture.writer.close()
        orders = []
        with closing(Ledger(fixture.path)) as db:
            with db.transaction():
                for i in range(history):
                    _append(db, 'review', str(i), encode(dict(reference=str(i))), NOW)
                for i in range(markets):
                    key = 'stress'+str(i)
                    req = request(key) | dict(ticker='A'+str(i), price='0.01')
                    db.reserve_intent(key, req, NOW)
                    db.transition_intent(key, 'SENDING')
                    record_order(db, OrderUpdate(key, key, req['ticker'], 'bid', D('.01'),
                        D(10), D(0), D(10), 'resting', 0, 1, 1), NOW)
                    db.connection.execute('INSERT INTO accounting_fees VALUES (?,?)', (key, '.01'))
                    orders.append(dict(order_id=key, client_order_id=key, ticker=req['ticker'],
                        book_side='bid', yes_price_dollars='.01', remaining_count_fp='10',
                        status='resting', exchange_index=1))
        fixture.writer = await LedgerWriter(fixture.path).start()
        fixture.account = AccountCoordinator(fixture.writer, subaccount=0, clock=lambda: 0)
        fixture.account.connect_generation()
        await fixture.open_epoch()
        latencies, lags = [], []
        stop = asyncio.Event()
        async def pulse():
            while not stop.is_set():
                due = time.perf_counter()+.002
                await asyncio.sleep(.002)
                lags.append(max(0, time.perf_counter()-due))
        pulse_task = asyncio.create_task(pulse())
        tracemalloc.start()
        cpu = time.process_time()
        try:
            for _ in range(8):
                await fixture.refresh(orders=orders)
                start = time.perf_counter()
                result = await fixture.release()
                assert result.released, result.blockers
                latencies.append(time.perf_counter()-start)
            cpu_used = time.process_time()-cpu
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
            stop.set()
            await pulse_task
        await fixture.writer.close()
        with closing(Ledger(fixture.path)) as db:
            cash = parse_cash(balance(), subaccount=0)
            samples = []
            for _ in range(200):
                start = time.perf_counter()
                assert cash_limit(db, cash, 1) == D(200)-D('.2')*markets
                samples.append(time.perf_counter()-start)
        return dict(markets=markets, retained_events=history, release_p99_ms=1000*p99(latencies),
            loop_p99_ms=1000*p99(lags), cpu_seconds=cpu_used, peak_bytes=peak,
            cash_p99_ms=1000*p99(samples), cash_median_ms=1000*median(samples),
            passed=p99(latencies)<.5 and p99(lags)<.05 and peak<32*1024*1024 and p99(samples)<.025)
    finally:
        await fixture.asyncTearDown()


async def main():
    results = [await measure(markets, history) for markets in (30, 120) for history in (128, 50000)]
    ratios = [results[i+1]['cash_median_ms']/results[i]['cash_median_ms'] for i in (0, 2)]
    passed = all(r['passed'] for r in results) and max(ratios)<2
    print(json.dumps(dict(results=results, history_ratios=ratios, passed=passed), indent=2))
    if not passed:
        raise SystemExit(1)


if __name__ == '__main__':
    asyncio.run(main())
