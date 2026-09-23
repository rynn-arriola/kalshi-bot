"""Explicit, bounded live market-data comparison; never a trading runtime.

Public incentive GETs plus authenticated public-book WS only. No private REST,
account stream, financial ledger, order client, candidate-file write or restart.
"""
import argparse
import asyncio
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from uuid import uuid4

from kalshi_bot.books import BookConnection
from kalshi_bot.incentive_discovery import QUERY
from kalshi_bot.observability import safe_error
from kalshi_bot.quoting import parse_program
from kalshi_bot.rest import RestReads, TokenBudget, get_wire
from kalshi_bot.startup import load_signer, save_result
from kalshi_bot.transport import WebSocketReaders, topology
from kalshi_bot.values import InvalidData, integer
from kalshi_bot.windows import WindowsLease


class Comparison:
    def __init__(self, specs):
        self.feeds = {s.name: BookConnection(s.tickers) for s in specs}
        self.generations = {name: feed.reconnect() for name, feed in self.feeds.items()}
        self.baseline, self.refreshed = {}, {}
        self.counts = Counter()
        self.wire_bytes = 0

    async def consume(self, name, event):
        self.wire_bytes += len(json.dumps(event).encode())
        self.counts['messages'] += 1
        if self.wire_bytes > 32*1024*1024 or self.counts['messages'] > 50000:
            raise InvalidData('probe traffic bound exceeded')
        kind = event.get('type')
        if kind == 'subscribed':
            self.counts['acknowledgments'] += 1
            return
        ticker = self.feeds[name].apply(event, generation=self.generations[name])
        if ticker is None:
            return
        received = event['_received_mono']
        initial = ticker not in self.refreshed
        if initial or kind == 'orderbook_delta':
            self.baseline[ticker] = received
        self.refreshed[ticker] = received
        self.counts['initial_snapshots' if initial else kind] += 1
        if kind == 'orderbook_snapshot' and 'id' in event:
            self.counts['correlated_refresh_snapshots'] += 1

    def sample(self, now):
        valid = {t for f in self.feeds.values() if not f.failed
                 for t, b in f.books.items() if b.valid}
        fresh = lambda times: sum(t in valid and 0 <= now-stamp <= 5
                                  for t, stamp in times.items())
        return dict(valid_books=len(valid), baseline_fresh=fresh(self.baseline),
                    refreshed_fresh=fresh(self.refreshed))


def public_wire(url, headers, maximum):
    if (not url.startswith('https://external-api.kalshi.com/trade-api/v2/incentive_programs?')
            or set(headers)-{'Accept', 'Accept-Encoding'}):
        raise InvalidData('probe forbids private or unrelated REST requests')
    response = get_wire(url, headers, maximum)
    if response.status != 200:
        raise InvalidData('public catalog refused; probe stops without retry')
    return response


async def probe(args):
    started = datetime.now(timezone.utc)
    result = dict(state='FAILED', observed_at=started.isoformat(),
        trading_started=False, private_rest_requests=0, orders_modified=0,
        economic_eligibility_verified=False, live_deployment=False)
    reads = RestReads(TokenBudget(rate=1, capacity=1, default_cost=1,
        initial_tokens=1), wire=public_wire)
    try:
        before = time.monotonic()
        async with asyncio.timeout(30):
            pages = await reads.collect('incentives', reason='incentives',
                max_pages=10, max_rows=10000, byte_limit=8388608,
                coalesce_scope=object(), **dict(QUERY))
        active, ids = set(), set()
        for row in pages.rows:
            if row['id'] in ids:
                raise InvalidData('duplicate catalog program')
            ids.add(row['id'])
            if row.get('incentive_type') != 'liquidity':
                raise InvalidData('catalog type mismatch')
            try:
                program = parse_program(row)
            except InvalidData:
                continue
            if not program.paid_out and program.start <= started < program.end:
                active.add(program.ticker)
        result['catalog'] = dict(rows=len(pages.rows), pages=pages.pages,
            wire_bytes=pages.wire_bytes, elapsed_seconds=round(time.monotonic()-before,3),
            active_supported_markets=len(active), complete=pages.exhausted,
            unauthenticated=True, local_request_pacing_per_second=1)
    finally:
        await reads.close()
    inputs = args.source_root/'config'/'live-inputs.local.json'
    if inputs.stat().st_size > 1048576:
        raise InvalidData('input size exceeds bound')
    document = json.loads(inputs.read_text(encoding='utf-8-sig'))
    # Same saved seed, only still-current reward definitions; no candidate rewrite.
    seeds = tuple(document['initial_tickers'])
    if len(seeds) > 128 or len(set(seeds)) != len(seeds):
        raise InvalidData('invalid saved seed scope')
    tickers = tuple(t for t in seeds if t in active)[:args.markets]
    if not tickers:
        raise InvalidData('no currently rewarded saved seeds')
    result['sample_scope'] = dict(saved_seed_markets=len(seeds),
        current_rewarded_seeds=len(tickers), tickers=tickers,
        selection='saved initial seed intersected with current public rewards',
        timing_fee_account_and_economic_gates='not assessed')
    signer = load_signer(args.source_root/'kalshi-bot.txt',
                         args.source_root/'Kalshi-Bot2.txt')
    specs = tuple(s for s in topology(tickers) if s.channels == ('orderbook_delta',))
    comparison = Comparison(specs)
    readers = [WebSocketReaders(signer, (spec,)) for spec in specs]
    tasks = [asyncio.create_task(r.run(comparison.consume)) for r in readers]
    samples = []
    before = time.monotonic()
    try:
        while time.monotonic()-before < args.seconds:
            done, _ = await asyncio.wait(tasks, timeout=.5, return_when=asyncio.FIRST_COMPLETED)
            if done:
                for task in done: task.result()
                raise InvalidData('probe reader ended')
            elapsed = time.monotonic()-before
            samples.append(dict(elapsed_seconds=round(elapsed,3),
                                **comparison.sample(time.monotonic())))
        result['state'] = ('OBSERVED' if len(comparison.refreshed) == len(tickers)
                           and comparison.counts['correlated_refresh_snapshots'] > 0
                           else 'BLOCKED')
    except Exception as exc:
        result['errors'] = safe_error(exc)
    finally:
        for task in tasks: task.cancel()
        outcomes = await asyncio.gather(*tasks, return_exceptions=True)
        # A reader fault racing the observation deadline is not a clean result.
        failed = next((value for value in outcomes if isinstance(value, Exception)), None)
        if failed is not None:
            result.update(state='FAILED', errors=safe_error(failed))
    result.update(readers_joined=all(t.done() for t in tasks),
        seconds=round(time.monotonic()-before,3), counts=dict(comparison.counts),
        normalized_bytes=comparison.wire_bytes, samples=samples)
    steady = [s for s in samples if s['elapsed_seconds'] >= 6]
    if steady:
        result['comparison'] = dict(
            samples=len(steady), baseline_average_fresh=round(sum(s['baseline_fresh'] for s in steady)/len(steady),2),
            refreshed_average_fresh=round(sum(s['refreshed_fresh'] for s in steady)/len(steady),2),
            final_baseline_fresh=steady[-1]['baseline_fresh'],
            final_refreshed_fresh=steady[-1]['refreshed_fresh'])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--read-only-live-check', required=True, action='store_true')
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--seconds', type=int, default=30)
    parser.add_argument('--markets', type=int, default=128)
    args = parser.parse_args()
    integer(args.seconds, 10, 60)
    integer(args.markets, 1, 128)
    if not args.source_root.is_absolute():
        raise InvalidData('absolute source path required')
    output = Path(__file__).resolve().parents[1]/'data'/'source-probe'/uuid4().hex/'result.json'
    with WindowsLease('kalshi-reward-source-readonly-probe'):
        try:
            result = asyncio.run(probe(args))
        except Exception as exc:
            result = dict(state='FAILED', errors=safe_error(exc), trading_started=False)
        output.parent.mkdir(parents=True, exist_ok=False)
        save_result(output, result)
    print(json.dumps(dict(result_file=str(output), **{k:v for k,v in result.items()
        if k not in {'samples','sample_scope'}}), indent=2))
    return 0 if result['state'] == 'OBSERVED' else 2


if __name__ == '__main__':
    raise SystemExit(main())
