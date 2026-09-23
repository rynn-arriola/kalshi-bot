"""Synthetic controller budget only; no venue, sockets, keys or ledger.

120 half-second scheduler turns (60 virtual seconds), 128 and 1024 tickers.
Gates: CPU <1 second, peak allocations <2 MiB, max scheduling turn <20 ms.
This measures bounded request bookkeeping, not snapshot depth/engine throughput.
"""
import json
import time
import tracemalloc

from kalshi_bot.book_refresh import BookRefresh


def run(size):
    tracemalloc.start()
    started = time.process_time()
    refresh = BookRefresh(tuple(f'M{i:04}' for i in range(size)))
    refresh.observe(dict(type='subscribed', id=1,
        msg=dict(channel='orderbook_delta', sid=1)), 0.)
    requests, replies, turns = 0, 0, []
    seen = set()
    for step in range(1, 121):
        now = step/2
        start = time.perf_counter()
        command = refresh.next_command(now)
        turns.append(time.perf_counter()-start)
        if command is None:
            continue
        requests += 1
        tickers = command['params']['market_tickers']
        assert len(tickers) <= 100 and refresh.pending == set(tickers)
        assert refresh.next_command(now) is None
        for ticker in tickers:
            refresh.observe(dict(type='orderbook_snapshot', id=command['id'],
                sid=1, msg=dict(market_ticker=ticker)), now)
            replies += 1
            seen.add(ticker)
        assert not refresh.pending
    cpu = time.process_time()-started
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    assert len(seen) == size
    maximum = max(turns)*1000
    return dict(markets=size, virtual_seconds=60, requests=requests,
        replies=replies, cpu_seconds=round(cpu,4), peak_bytes=peak,
        max_scheduler_turn_ms=round(maximum,3),
        passed=cpu < 1 and peak < 2*1024*1024 and maximum < 20)


if __name__ == '__main__':
    results = [run(128), run(1024)]
    print(json.dumps(results, indent=2))
    raise SystemExit(0 if all(r['passed'] for r in results) else 1)
