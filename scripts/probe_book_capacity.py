"""Explicit read-only WS capacity experiment; no account, ledger or trading.

Configured scopes and two/four-shard variants use the production book transport
and parser, not the production launcher. Logs contain aggregates only; saved
scope stays in data/.
"""
import argparse
import asyncio
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import time
from uuid import uuid4

from probe_reward_sources import Comparison, public_wire
from kalshi_bot.incentive_discovery import QUERY
from kalshi_bot.market_inputs import timestamp
from kalshi_bot.observability import safe_error
from kalshi_bot.quoting import parse_program
from kalshi_bot.rest import RestReads, TokenBudget
from kalshi_bot.startup import load_signer, save_result
from kalshi_bot.transport import WebSocketReaders, topology
from kalshi_bot.values import InvalidData, integer
from kalshi_bot.windows import WindowsLease


def utc():
    return datetime.now(timezone.utc)


def percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered)*fraction)-1)]


def distribution(values):
    return {name: percentile(values, fraction) for name, fraction in
            (('p50', .5), ('p95', .95), ('p99', .99), ('max', 1))}


def working_set():
    class Counters(ctypes.Structure):
        _fields_ = [('cb', wintypes.DWORD), ('faults', wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in ('peak', 'working', 'peak_paged',
            'paged', 'peak_nonpaged', 'nonpaged', 'pagefile', 'peak_pagefile')]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    psapi = ctypes.WinDLL('psapi', use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE,
        ctypes.POINTER(Counters), wintypes.DWORD]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    counters = Counters(cb=ctypes.sizeof(Counters))
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(),
                                    ctypes.byref(counters), counters.cb):
        raise RuntimeError('memory measurement unavailable')
    return counters.working


class Measurement(Comparison):
    def __init__(self, specs, programs):
        super().__init__(specs, programs)
        self.started = time.monotonic()
        self.first_snapshot = self.full_snapshot = None
        self.expected = sum(len(s.tickers) for s in specs)
        self.ingress_ms, self.callback_ms = [], []
        self.queue_peak = self.queue_bytes_peak = 0
        self.reader = None

    async def consume(self, name, event):
        before = time.monotonic()
        if self.reader is not None:
            self.queue_peak = max(self.queue_peak, self.reader.queue.qsize()+1)
            self.queue_bytes_peak = max(self.queue_bytes_peak, self.reader.queued_bytes)
        await super().consume(name, event)
        after = time.monotonic()
        self.callback_ms.append((after-before)*1000)
        if '_received_mono' in event:
            self.ingress_ms.append((before-event['_received_mono'])*1000)
        if self.refreshed and self.first_snapshot is None:
            self.first_snapshot = after-self.started
        if len(self.refreshed) == self.expected and self.full_snapshot is None:
            self.full_snapshot = after-self.started


def assess(summary):
    """Diagnostic comparison targets only; never trading authorization."""
    reasons = []
    if summary['unique_books'] != summary['markets']:
        reasons.append('incomplete_snapshot_coverage')
    if summary['full_snapshot_seconds'] is None or summary['full_snapshot_seconds'] > 15:
        reasons.append('initial_coverage_over_15_seconds')
    if summary['steady_samples'] == 0 or summary['minimum_fresh_fraction'] < .99:
        reasons.append('steady_freshness_below_99_percent')
    if summary['cpu_percent_one_core'] > 50:
        reasons.append('cpu_over_half_core')
    if summary['peak_sampled_working_set_bytes'] > 512*1024*1024:
        reasons.append('memory_over_512_mib')
    for field in ('event_loop_lag_ms', 'ingress_to_callback_ms'):
        if summary[field]['p99'] is None or summary[field]['p99'] > 100:
            reasons.append(field+'_over_100_ms')
    if summary['counts'].get('reference_mismatches', 0) or summary['counts'].get('unified_no_ladder_mismatches', 0):
        reasons.append('reference_mismatch')
    if summary['counts'].get('reference_program_snapshots', 0) == 0:
        reasons.append('no_reference_checks')
    return reasons


async def stage(signer, tickers, programs, seconds, *, book_shards=2):
    specs = tuple(s for s in topology(tickers, market_capacity=1024,
                                      book_connections=book_shards)
                  if s.channels == ('orderbook_delta',))
    measure = Measurement(specs, {t:programs[t] for t in tickers})
    reader = WebSocketReaders(signer, specs)
    measure.reader = reader
    samples, lag = [], []
    result = dict(state='FAILED', markets=len(tickers), sockets=len(specs),
                  per_socket_markets=[len(s.tickers) for s in specs], started_at=utc().isoformat())
    before, cpu_before = time.monotonic(), time.process_time()
    task = asyncio.create_task(reader.run(measure.consume))
    try:
        while time.monotonic()-before < seconds:
            deadline = time.monotonic()+.1
            done, _ = await asyncio.wait((task,), timeout=.1)
            if done:
                task.result()
                raise InvalidData('capacity reader ended')
            now = time.monotonic()
            lag.append(max(0, now-deadline)*1000)
            if not samples or now-before-samples[-1]['elapsed_seconds'] >= .5:
                sample = dict(elapsed_seconds=now-before,
                    working_set_bytes=working_set(), **measure.sample(now))
                samples.append(sample)
                if sample['working_set_bytes'] > 512*1024*1024:
                    raise InvalidData('capacity memory stop')
                if now-before > 10 and (time.process_time()-cpu_before)/(now-before) > .8:
                    raise InvalidData('capacity CPU stop')
        result['state'] = 'OBSERVED'
    except Exception as exc:
        result['errors'] = safe_error(exc)
    finally:
        elapsed, cpu = time.monotonic()-before, time.process_time()-cpu_before
        task.cancel()
        outcome = (await asyncio.gather(task, return_exceptions=True))[0]
        if isinstance(outcome, Exception):
            result.update(state='FAILED', errors=safe_error(outcome))
        result['reader_joined'] = task.done()
    steady = [s for s in samples if s['elapsed_seconds'] >= 10]
    fresh = [s['refreshed_fresh']/len(tickers) for s in steady]
    observed_at = time.monotonic()
    outcomes = []
    for spec in specs:
        feed = measure.feeds[spec.name]
        for ticker in spec.tickers:
            book = feed.books.get(ticker)
            stamp = measure.refreshed.get(ticker)
            reasons = []
            if stamp is None:
                reasons.append('initial_snapshot_missing')
            if book is None or not book.valid or feed.failed:
                reasons.append('book_invalid')
            if stamp is not None and not 0 <= observed_at-stamp <= 5:
                reasons.append('book_stale_over_5_seconds')
            outcomes.append(dict(ticker=ticker, shard=spec.name,
                                 reasons=reasons or ['fresh_valid_book']))
    result.update(seconds=elapsed, cpu_seconds=cpu, cpu_percent_one_core=100*cpu/elapsed,
        unique_books=len(measure.refreshed), first_snapshot_seconds=measure.first_snapshot,
        full_snapshot_seconds=measure.full_snapshot, steady_samples=len(steady),
        minimum_fresh_fraction=min(fresh, default=0),
        average_fresh_fraction=sum(fresh)/len(fresh) if fresh else 0,
        peak_sampled_working_set_bytes=max((s['working_set_bytes'] for s in samples), default=0),
        event_loop_lag_ms=distribution(lag), ingress_to_callback_ms=distribution(measure.ingress_ms),
        callback_ms=distribution(measure.callback_ms), queue_peak=measure.queue_peak,
        sampled_queue_bytes_peak=measure.queue_bytes_peak,
        normalized_bytes=measure.wire_bytes, counts=dict(measure.counts), samples=samples,
        market_outcomes=outcomes,
        finished_at=utc().isoformat())
    result['target_failures'] = assess(result)
    if result['state'] == 'OBSERVED' and result['target_failures']:
        result['state'] = 'TARGETS_NOT_MET'
    return result


async def run(args, output):
    result = dict(state='RUNNING', started_at=utc().isoformat(), stages=[],
        trading_started=False, orders_modified=0, private_rest_requests=0,
        economics_metadata_account_assessed=False, production_configuration_changed=False)
    save_result(output, result)
    try:
        path = args.source_root/'config'/'live-inputs.local.json'
        if path.stat().st_size > 1048576:
            raise InvalidData('saved input too large')
        document = json.loads(path.read_text(encoding='utf-8-sig'))
        reviewed = {r['ticker'] for r in document['timing_reviews']
                    if timestamp(r['valid_until']) > utc()}
        if not 1 <= len(reviewed) <= 1024:
            raise InvalidData('invalid reviewed universe')
        reads = RestReads(TokenBudget(rate=1,capacity=1,default_cost=1,initial_tokens=1),wire=public_wire)
        try:
            async with asyncio.timeout(30):
                pages = await reads.collect('incentives', reason='incentives',
                    max_pages=10,max_rows=10000,byte_limit=8388608,
                    coalesce_scope=object(), **dict(QUERY))
            if not pages.exhausted:
                raise InvalidData('catalog incomplete')
        finally:
            await reads.close()
        programs = {}
        for row in pages.rows:
            try:
                p = parse_program(row)
            except InvalidData:
                continue
            if p.ticker in reviewed and not p.paid_out and p.start <= utc() < p.end:
                programs.setdefault(p.ticker, []).append(p)
        if not programs:
            raise InvalidData('no current reviewed rewards')
        seeds = [t for t in document['initial_tickers'] if t in programs]
        tickers = tuple(dict.fromkeys(seeds+sorted(set(programs)-set(seeds))))
        sizes = sorted({min(n,len(tickers)) for n in args.markets})
        result.update(tickers=tickers, catalog_rows=len(pages.rows), catalog_pages=pages.pages,
                      reviewed_rewarded_markets=len(tickers), stage_sizes=sizes)
        signer = load_signer(args.source_root/'kalshi-bot.txt',args.source_root/'Kalshi-Bot2.txt')
        for repetition in range(1, args.repetitions+1):
            for shards in args.book_shards:
                for size in sizes:
                    print(json.dumps(dict(stage_start=size,seconds=args.seconds,
                        book_shards=shards,repetition=repetition)),flush=True)
                    row = await stage(signer,tickers[:size],programs,args.seconds,
                                      book_shards=shards)
                    row.update(repetition=repetition, configured_book_shards=shards)
                    result['stages'].append(row)
                    save_result(output,result)
                    print(json.dumps({k:v for k,v in row.items()
                        if k not in {'samples','market_outcomes'}}),flush=True)
        else:
            result['state'] = ('OBSERVED' if result['stages']
                and all(row['state']=='OBSERVED' for row in result['stages'])
                else 'TARGETS_NOT_MET')
    except Exception as exc:
        result.update(state='FAILED',errors=safe_error(exc))
    finally:
        result['finished_at'] = utc().isoformat()
        save_result(output,result)
    print(json.dumps(dict(result_file=str(output),state=result['state'])),flush=True)
    return 0 if result['state'] == 'OBSERVED' else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--read-only-live-check',required=True,action='store_true')
    parser.add_argument('--source-root',type=Path,required=True)
    parser.add_argument('--seconds',type=int,default=15)
    parser.add_argument('--markets',type=int,nargs='+',default=[1024])
    parser.add_argument('--book-shards',type=int,nargs='+',default=[2,4])
    parser.add_argument('--repetitions',type=int,default=2)
    args = parser.parse_args()
    integer(args.seconds,12,60)
    integer(args.repetitions,1,3)
    if any(integer(value,1,1024) is None for value in args.markets):
        raise InvalidData('invalid market stages')
    if any(integer(value,2,4) is None or value not in {2,4}
           for value in args.book_shards):
        raise InvalidData('book shards must be two or four')
    if not args.source_root.is_absolute():
        raise InvalidData('absolute source root required')
    output = Path(__file__).resolve().parents[1]/'data'/'book-capacity'/uuid4().hex/'result.json'
    output.parent.mkdir(parents=True,exist_ok=False)
    with WindowsLease('kalshi-reward-source-readonly-probe'):
        return asyncio.run(run(args,output))


if __name__ == '__main__':
    raise SystemExit(main())
