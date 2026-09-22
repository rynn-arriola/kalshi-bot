"""Bounded real-runtime startup check. GET/WS only; no trading entry point.

This composes the existing owners, not a paper trader or the REST canary.
No mutation signer, dispatcher, opening approval, or production ledger is used.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
from uuid import UUID, uuid4

from .market_inputs import ExitInputService
from .observability import Diagnostics, safe_error
from .quota import ProbeConfig, QuotaGuard, QuotaPolicy
from .quota_supervisor import QuotaSupervisor
from .rest import RestReads, TokenBudget
from .runtime import RecoveryRuntime, readonly_reader_factory
from .transport import Signer
from .values import InvalidData, identity, integer
from .windows import WindowsLease, WindowsStopEvent
from .writer import LedgerWriter


IDENTITY = 'kalshi-original-runtime-startup-check'


async def _noop(*_):
    pass


def compose(writer, reads, reader_factory, *, tickers, now, history_start,
            diagnostics, clock=time.monotonic, quota_supervisor=None):
    """Shared read budget, original stream/recovery/selection/telemetry owners."""
    inputs = ExitInputService(reads, tickers, now=now, clock=clock, ttl=60,
                             diagnostics=diagnostics)
    runtime = RecoveryRuntime(writer, reads, reader_factory, tickers=tickers,
        subaccount=0, history_start=history_start, now=now, clock=clock,
        evaluate=_noop, deadline_handler=_noop, lifecycle_handler=_noop,
        market_inputs=inputs, diagnostics=diagnostics,
        quota_supervisor=quota_supervisor, observation_only=True)
    runtime.attach_selection()
    runtime.attach_incentives()
    runtime.attach_rewards(scope='startup-'+writer.epoch)
    # Check only the explicit seed scope. Rotating a test scope is unnecessary;
    # production admission remains the existing, separately tested owner.
    return runtime


def inspect_runtime(runtime):
    """Local snapshot only; never makes another venue request."""
    status = runtime.status()
    books = {ticker: bool(shard.books.get(ticker) and shard.books[ticker].valid)
             for shard in runtime.engine.shards.values() for ticker in shard.tickers}
    inputs = runtime.market_inputs
    metadata = {ticker: list(inputs.results[ticker].blockers)
                if ticker in inputs.results else ['market_inputs_missing']
                for ticker in sorted(runtime.engine.market_shard)}
    connected = all(value == 'subscribed' for value in runtime.reader_states.values())
    recovered = runtime.recovery_state == 'repaired_entries_blocked'
    catalog = runtime.incentives.current()
    ready = (runtime.running and connected and all(books.values()) and recovered
             and runtime.account.current_report(runtime.now()) is not None
             and catalog is not None and all(t in inputs.results for t in books)
             and not runtime.writer.failed and not runtime.engine.failed
             and not runtime.stop_requested.is_set())
    return dict(startup_verified=ready, trading_ready=False,
        blockers=['read_only_check_no_dispatch', 'opening_baseline_not_approved']
                 + sorted({code for row in metadata.values() for code in row}),
        books=books, market_inputs=metadata, runtime=status)


def save_result(path, value):
    """One local writer; readers see either the old or the new whole document."""
    temporary = path.with_suffix('.json.tmp')
    with temporary.open('w', encoding='utf-8') as output:
        json.dump(value, output, indent=2, default=str, allow_nan=False)
        output.write('\n')
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)


async def supervise(runtime, *, seconds, stopped=lambda: False, publish=lambda _: None):
    """Start, observe, then join all original owners. No detached job."""
    integer(seconds, 1, 300)
    task = asyncio.create_task(runtime.run(), name='kalshi-startup-runtime')
    deadline = time.monotonic()+seconds
    latest = None
    try:
        while time.monotonic() < deadline and not stopped():
            if task.done():
                task.result()
                raise InvalidData('runtime ended before startup check finished')
            latest = inspect_runtime(runtime)
            await asyncio.to_thread(publish, latest)
            if latest['startup_verified']:
                break
            await asyncio.wait((task,), timeout=min(.5, max(0, deadline-time.monotonic())))
        latest = inspect_runtime(runtime)
        return latest
    finally:
        runtime.stop()
        # RecoveryRuntime retains its own reader/dispatch/writer-command drains.
        cancelled = False
        while not task.done():
            try:
                await asyncio.wait((task,))
            except asyncio.CancelledError:
                cancelled = True
        task.result()
        if cancelled:
            raise asyncio.CancelledError


def load_signer(key_id_path, private_key_path):
    if key_id_path.stat().st_size > 256 or private_key_path.stat().st_size > 16384:
        raise InvalidData('credential file size invalid')
    key_id = key_id_path.read_text(encoding='utf-8-sig').strip()
    UUID(key_id)
    return Signer(key_id, private_key_path.read_bytes())


async def run_check(args, directory, diagnostics, stop):
    now = lambda: datetime.now(timezone.utc)
    clock = time.monotonic
    signer = load_signer(args.key_id_file, args.private_key_file)
    # Conservative bootstrap already verified against current account costs;
    # the first complete pair replaces this, using the existing quota owner.
    reads = RestReads(TokenBudget(rate=1, capacity=20, default_cost=10,
        initial_tokens=20, clock=clock), signer, diagnostics=diagnostics)
    reads.attach_quota(QuotaGuard(QuotaPolicy(ProbeConfig(1, 20, 10, 10)),
        clock=clock, now=now, diagnostics=diagnostics))
    quota = QuotaSupervisor(reads)
    writer = LedgerWriter(directory/'startup.db', diagnostics=diagnostics)
    started = False
    try:
        await writer.start()
        started = True
        runtime = compose(writer, reads, readonly_reader_factory(signer),
            tickers=tuple(args.ticker), now=now, clock=clock,
            # This is a fresh startup scope, not ownership of old manual trades.
            history_start=now(),
            diagnostics=diagnostics, quota_supervisor=quota)
        def publish(value):
            save_result(directory/'status.json', dict(state='RUNNING', pid=os.getpid(),
                run_id=directory.name, observed_at=now().isoformat(), **value))
        return await supervise(runtime, seconds=args.seconds,
                               stopped=lambda: stop.requested, publish=publish)
    finally:
        try:
            await quota.close()
        finally:
            try:
                await reads.close()
            finally:
                if started:
                    await writer.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--read-only-live-check', action='store_true', required=True)
    parser.add_argument('--key-id-file', type=Path, required=True)
    parser.add_argument('--private-key-file', type=Path, required=True)
    parser.add_argument('--ticker', action='append', required=True)
    parser.add_argument('--seconds', type=int, default=60)
    parser.add_argument('--output-root', type=Path, required=True)
    args = parser.parse_args(argv)
    directory = None
    result = dict(state='FAILED', startup_verified=False, trading_ready=False)
    code = 2
    try:
        integer(args.seconds, 1, 300)
        if not 1 <= len(args.ticker) <= 128 or len(set(args.ticker)) != len(args.ticker):
            raise InvalidData('bounded unique startup market scope required')
        for ticker in args.ticker:
            identity(ticker)
        root = args.output_root.resolve()
        if not args.output_root.is_absolute() or 'onedrive' in str(root).casefold():
            raise InvalidData('absolute local non-OneDrive output root required')
        with WindowsLease(IDENTITY), WindowsStopEvent(IDENTITY) as stop:
            directory = root/uuid4().hex
            directory.mkdir(parents=True, exist_ok=False)
            with Diagnostics(directory/'logs') as diagnostics:
                try:
                    result = asyncio.run(run_check(args, directory, diagnostics, stop))
                    code = 0 if result['startup_verified'] else 2
                    result['state'] = 'CHECKED' if code == 0 else 'BLOCKED'
                except BaseException as exc:
                    if not isinstance(exc, (Exception, KeyboardInterrupt)):
                        raise
                    result['errors'] = safe_error(exc)
                    result['state'] = 'INTERRUPTED' if isinstance(exc, KeyboardInterrupt) else 'FAILED'
                result['logging'] = diagnostics.status()
            result['logging'] = diagnostics.status()
            if result['logging']['failure']:
                result.update(state='FAILED', startup_verified=False)
                code = 2
            result.update(run_id=directory.name, finished_at=datetime.now(timezone.utc).isoformat(),
                          process_stopped=True, directory=str(directory))
            save_result(directory/'status.json', result)
    except (Exception, KeyboardInterrupt) as exc:
        result = dict(state='FAILED', startup_verified=False, trading_ready=False,
                      errors=safe_error(exc), directory=str(directory) if directory else None)
        code = 2
    print(json.dumps(result, indent=2, default=str))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
