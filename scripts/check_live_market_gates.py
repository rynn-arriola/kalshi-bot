"""Explicit public market-gate census; no trader, private REST, ledger or orders.

Uses actual metadata/selection code and live WS books. --broad selects the new
shared bulk metadata path and up to 1,024 simultaneous books.
Account admission is NOT assessed: the selector receives an explicitly hypothetical
empty $500 account solely to isolate market gates. Results are sequential samples.
"""
import argparse
import asyncio
from collections import Counter
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import json
from pathlib import Path
import re
from threading import Lock
import time
from urllib.parse import urlsplit
from uuid import uuid4

from kalshi_bot.books import BookConnection
from kalshi_bot.incentive_discovery import QUERY
from kalshi_bot.market_inputs import ExitInputService, FeeProfile, TimingReview, timestamp
from kalshi_bot.observability import safe_error
from kalshi_bot.portfolio import PortfolioView
from kalshi_bot.quoting import parse_program
from kalshi_bot.rest import RestReads, TokenBudget, get_wire
from kalshi_bot.risk import WindowState, window_bounds
from kalshi_bot.runtime import readonly_reader_factory
from kalshi_bot.selection import MarketSelector
from kalshi_bot.startup import load_signer, save_result
from kalshi_bot.transport import WebSocketReaders, topology
from kalshi_bot.values import InvalidData, integer
from kalshi_bot.windows import WindowsLease


def now():
    return datetime.now(timezone.utc)


class PublicWire:
    def __init__(self):
        self.calls = self.bytes = 0
        self.failed = False
        self.lock = Lock()

    def __call__(self, url, headers, maximum):
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or parsed.netloc != 'external-api.kalshi.com'
                or not re.fullmatch(r'/trade-api/v2/(incentive_programs|events|'
                    r'(markets|events|series|milestones)/[A-Za-z0-9_.-]+)', parsed.path)
                or set(headers)-{'Accept', 'Accept-Encoding'}):
            raise InvalidData('census forbids private or unrelated REST')
        with self.lock:
            if self.failed:
                raise InvalidData('public census read stopped after refusal')
            self.calls += 1
            if self.calls > 6000 or self.bytes > 128*1024*1024:
                raise InvalidData('census REST bound exceeded')
        response = get_wire(url, headers, maximum)
        with self.lock:
            self.bytes += len(response.body)
        if response.status != 200:
            with self.lock:
                self.failed = True
            raise InvalidData('public read refused; no census retry')
        return response


def evaluate(book, programs, result, at):
    selector = MarketSelector(1)
    selector.update(book, programs, terms=result.terms, now=at,
        valid_until=min(result.terms.valid_until, at+timedelta(seconds=5)),
        blockers=result.blockers)
    start, end = window_bounds(at)
    # No writer/account exists here. This view does not authorize an order.
    view = PortfolioView('public-census', 0, 0, at, (), (), Decimal(0), 0, ())
    report = selector.propose(view=view,
        window=WindowState(start,end,Decimal(0),30,False,at), free_cash=Decimal(500),
        account_known=True, now=at, current=lambda _: True)
    entry = report.additions[0] if report.additions else None
    reasons = report.blockers or tuple(r for _,rs in report.exclusions for r in rs)
    return dict(passed=entry is not None, reasons=sorted(set(reasons)),
        reward_remaining_usd=str(entry.gross_remaining_usd) if entry else None,
        reward_hourly_usd=str(entry.gross_hourly_usd) if entry else None,
        bid_reference=str(entry.bid_reference) if entry else None,
        ask_reference=str(entry.ask_reference) if entry else None,
        retained_values=([str(v) for v in selector.entry_retained_value.get(
            (entry.ticker,entry.program_id), ())] if entry else None),
        metadata_blockers=list(result.blockers), observed_at=at.isoformat())


async def catalog(reads):
    pages = await reads.collect('incentives', reason='incentives',
        max_pages=10, max_rows=10000, byte_limit=8388608,
        coalesce_scope=object(), **dict(QUERY))
    if not pages.exhausted:
        raise InvalidData('incomplete reward enumeration')
    values = {}
    for row in pages.rows:
        try:
            p = parse_program(row)
        except InvalidData:
            continue
        if not p.paid_out and p.start <= now() < p.end:
            values.setdefault(p.ticker, []).append(p)
    return {t:tuple(ps) for t,ps in values.items()}


async def batch(reads, signer, reviews, profile, programs, rows, exchanges, *, broad=False):
    tickers = tuple(r.ticker for r in reviews)
    service = ExitInputService(reads, tickers, now=now, ttl=60,
                              timing_reviews=reviews, fee_profile=profile, bulk_events=broad)
    service.bind(lambda _: None, lambda _: None)
    service.begin(1)
    specs = tuple(s for s in topology(tickers, market_capacity=1024 if broad else 128)
                  if s.name != 'account')
    feeds = {s.name:BookConnection(s.tickers) for s in specs if s.name != 'lifecycle'}
    generations = {n:f.reconnect() for n,f in feeds.items()}
    stamps, books, ready = {}, {}, asyncio.Event()
    async def consume(name, event):
        if name == 'lifecycle':
            if event.get('type') == 'subscribed':
                service.subscribed(1,event['msg']['sid'])
                ready.set()
            else:
                service.ingest(event,generation=1)
        elif event.get('type') != 'subscribed':
            ticker = feeds[name].apply(event,generation=generations[name])
            if ticker is not None:
                stamps[ticker] = event['_received_mono']
                books[ticker] = feeds[name].books[ticker]
    async def read_books():
        if not broad:
            await WebSocketReaders(signer,specs).run(consume)
            return
        # Exercise the same per-connection buffering as normal composition.
        factory = readonly_reader_factory(signer)
        tasks = [asyncio.create_task(factory(spec).run(consume)) for spec in specs]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for done_task in done:
                done_task.result()
            raise InvalidData('public reader ended')
        finally:
            for owned_task in tasks:
                owned_task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
    task = asyncio.create_task(read_books())
    jobs = asyncio.Queue()
    for t in tickers:
        jobs.put_nowait(t)
    async def worker():
        while not jobs.empty():
            ticker = jobs.get_nowait()
            try:
                if task.done():
                    task.result()
                    raise InvalidData('public reader ended')
                for attempt in range(3 if broad else 1):
                    try:
                        result = await service.refresh(ticker)
                        break
                    except InvalidData:
                        if not broad or attempt == 2:
                            raise
                        # Bounded source-convergence retry; PublicWire still
                        # latches HTTP refusal and never retries that network.
                        await asyncio.sleep(1)
                deadline = time.monotonic()+4
                while (ticker not in books or time.monotonic()-stamps[ticker] > 5) and time.monotonic()<deadline:
                    await asyncio.sleep(.1)
                if ticker not in books or not books[ticker].valid or time.monotonic()-stamps[ticker]>5:
                    row = dict(passed=False,reasons=['book_missing_or_stale'])
                elif service.results.get(ticker) is not result or not service.connected:
                    row = dict(passed=False,reasons=['metadata_revoked'])
                elif service.values[('market',ticker)].value.exchange not in exchanges:
                    row = dict(passed=False,reasons=['exchange_not_configured'])
                else:
                    row = evaluate(books[ticker], programs.get(ticker,()), result, now())
                rows.append(dict(ticker=ticker, **row))
            except (InvalidData, TimeoutError) as exc:
                rows.append(dict(ticker=ticker, passed=False,
                    reasons=['metadata_or_source_error'], error=safe_error(exc)))
            if len(rows)%16 == 0:
                print(json.dumps(dict(progress=len(rows), passed=sum(r['passed'] for r in rows))),flush=True)
    workers = []
    try:
        async with asyncio.timeout(15):
            await ready.wait()
        workers = [asyncio.create_task(worker()) for _ in range(2)]
        async with asyncio.timeout(150):
            await asyncio.gather(*workers)
        if task.done():
            task.result()
            raise InvalidData('public reader ended')
    finally:
        for worker_task in workers:
            worker_task.cancel()
        await asyncio.gather(*workers,return_exceptions=True)
        task.cancel()
        outcome = (await asyncio.gather(task,return_exceptions=True))[0]
        await service.close()
        if isinstance(outcome,Exception):
            raise InvalidData('public reader failed') from outcome


async def run(args, output):
    result = dict(state='RUNNING', started_at=now().isoformat(), rows=[],
        account_admission_assessed=False, hypothetical_flat_capital_usd='500',
        orders_modified=0, private_rest_requests=0, trading_started=False,
        simultaneous_census=False, broad_books_bulk_metadata=bool(args.broad),
        source='saved reviews, fresh REST metadata and live WS books')
    wire = PublicWire()
    reads = RestReads(TokenBudget(rate=10,capacity=10,default_cost=1,initial_tokens=2),wire=wire)
    try:
        path = args.source_root/'config'/'live-inputs.local.json'
        if path.stat().st_size > 1048576:
            raise InvalidData('launch input size exceeds bound')
        raw = json.loads(path.read_text(encoding='utf-8-sig'))
        profile = FeeProfile(**(raw['fee_profile'] | {'valid_until':timestamp(raw['fee_profile']['valid_until'])}))
        if profile.valid_until <= now():
            raise InvalidData('reviewed fee profile expired')
        reviews = tuple(TimingReview(**(r | {'valid_until':timestamp(r['valid_until'])})) for r in raw['timing_reviews'])
        signer = load_signer(args.source_root/'kalshi-bot.txt',args.source_root/'Kalshi-Bot2.txt')
        programs = await catalog(reads)
        current = {r.ticker:r for r in reviews if r.valid_until>now() and r.ticker in programs}
        seeds = tuple(t for t in raw['initial_tickers'] if t in current)
        ordered = seeds+tuple(t for t in current if t not in seeds)
        if args.broad:
            # Match MetadataScheduler's connected bootstrap order; seed-first
            # batching was a property of the former rotating diagnostic only.
            ordered = tuple(sorted(current))
        ordered = ordered[:args.markets]
        result.update(reviewed=len(reviews), active_reward_markets=len(programs),
                      eligible_review_scope=len(current), requested=len(ordered), seed_tickers=seeds)
        save_result(output,result)
        async with asyncio.timeout(900):
            width = 1024 if args.broad else 128
            for offset in range(0,len(ordered),width):
                if offset:
                    programs = await catalog(reads)
                scope = tuple(current[t] for t in ordered[offset:offset+width])
                await batch(reads,signer,scope,profile,programs,result['rows'],
                            frozenset(raw['exchange_indices']),broad=args.broad)
                save_result(output,result)
        result['state'] = 'OBSERVED'
        if any('metadata_or_source_error' in r['reasons'] or 'book_missing_or_stale' in r['reasons']
               for r in result['rows']):
            result['state'] = 'PARTIALLY_COMPLETE'
    except Exception as exc:
        result.update(state='PARTIALLY_COMPLETE' if result['rows'] else 'FAILED',error=safe_error(exc))
    finally:
        await reads.close()
        result.update(finished_at=now().isoformat(),public_rest_requests=wire.calls,
                      public_rest_bytes=wire.bytes)
        passed = [r for r in result['rows'] if r['passed']]
        priority = [r for r in passed if Decimal(r['reward_remaining_usd'])>=2]
        result['summary'] = dict(examined=len(result['rows']), passed_one_dollar=len(passed),
            priority_two_dollars=len(priority), fallback_only=len(passed)-len(priority),
            exclusions=dict(Counter(reason for r in result['rows'] if not r['passed'] for reason in r['reasons'])))
        save_result(output,result)
        print(json.dumps(dict(result_file=str(output), **{k:v for k,v in result.items() if k not in {'rows','seed_tickers'}}),indent=2))
    return 0 if result['state']=='OBSERVED' else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--read-only-live-check',required=True,action='store_true')
    parser.add_argument('--source-root',required=True,type=Path)
    parser.add_argument('--markets',type=int,default=128)
    parser.add_argument('--broad',action='store_true')
    args = parser.parse_args()
    integer(args.markets,1,1024)
    if not args.source_root.is_absolute():
        raise InvalidData('absolute source root required')
    output = Path(__file__).resolve().parents[1]/'data'/'market-gate-census'/uuid4().hex/'result.json'
    output.parent.mkdir(parents=True,exist_ok=False)
    with WindowsLease('kalshi-reward-source-readonly-probe'):
        return asyncio.run(run(args,output))


if __name__=='__main__':
    raise SystemExit(main())
