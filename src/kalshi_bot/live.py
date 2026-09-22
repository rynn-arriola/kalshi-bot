"""Foreground Windows composition of the original liquidity runtime.

Nothing starts at import. The operator must explicitly select `run --live`.
No background service, supervisor restart, or alternative quoting strategy.
"""
import argparse
import asyncio
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
from uuid import uuid4

from .config import BotConfig
from .dispatch_sources import InventoryDispatchSource
from .live_session import LiveSession
from .market_inputs import ExitInputService, FeeProfile, TimingReview, timestamp
from .mutation_transport import OrderMutationTransport
from .observability import Diagnostics, safe_error
from .quota import ProbeConfig, QuotaGuard, QuotaPolicy
from .quota_supervisor import QuotaSupervisor
from .rest import RestReads, TokenBudget
from .runtime import RecoveryRuntime, readonly_reader_factory
from .startup import load_signer, save_result, _noop
from .transport import MutationSigner
from .values import InvalidData, integer
from .windows import WindowsLease, WindowsStopEvent
from .write_quota_source import WriteQuotaSource
from .writer import LedgerWriter


IDENTITY = 'kalshi-primary-account-trader'
ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT/'data'/'trader'


@dataclass(frozen=True)
class LaunchInputs:
    reviews: tuple
    fee_profile: FeeProfile
    exchange_indices: tuple

    @property
    def tickers(self):
        return tuple(review.ticker for review in self.reviews)

    @classmethod
    def load(cls, path, now):
        if path.stat().st_size > 131072:
            raise InvalidData('launch inputs exceed size limit')
        raw = json.loads(path.read_text(encoding='utf-8-sig'))
        if type(raw) is not dict or set(raw) != {'timing_reviews', 'fee_profile', 'exchange_indices'}:
            raise InvalidData('exact launch input fields required')
        if type(raw['timing_reviews']) is not list or not 1 <= len(raw['timing_reviews']) <= 128:
            raise InvalidData('one to 128 reviewed markets required')
        reviews = tuple(TimingReview(**(row | {'valid_until': timestamp(row['valid_until'])}))
                        for row in raw['timing_reviews'])
        profile = FeeProfile(**(raw['fee_profile'] | {
            'valid_until': timestamp(raw['fee_profile']['valid_until'])}))
        shards = raw['exchange_indices']
        if (len({row.ticker for row in reviews}) != len(reviews)
                or any(row.valid_until <= now for row in reviews)
                or profile.valid_until <= now or type(shards) is not list
                or not 1 <= len(shards) <= 128 or len(set(shards)) != len(shards)
                or 0 not in shards):
            raise InvalidData('duplicate, expired or incomplete launch scope')
        return cls(reviews, profile, tuple(integer(v, 0, 2**31-1) for v in shards))


async def compose(writer, reads, reader_factory, transport, *, inputs, boundary,
                  now, clock, diagnostics, quota, initialize=False):
    """Actual owners and non-fixture execution. Injectable wires allow safe tests."""
    session = writer.live_session
    if session is None or session.tickers != frozenset(inputs.tickers):
        raise InvalidData('launch/session market scope differs')
    source = WriteQuotaSource(reads, shards=inputs.exchange_indices, live_session=session)
    await quota.bootstrap()
    metadata = ExitInputService(reads, inputs.tickers, now=now, clock=clock, ttl=60,
        diagnostics=diagnostics, timing_reviews=inputs.reviews, fee_profile=inputs.fee_profile)
    runtime = RecoveryRuntime(writer, reads, reader_factory, tickers=inputs.tickers,
        subaccount=0, history_start=boundary, accounting_boundary=boundary,
        opening_reference=('operator-launch-'+session.run_id) if initialize else None,
        now=now, clock=clock, evaluate=_noop, deadline_handler=_noop,
        lifecycle_handler=_noop, diagnostics=diagnostics, market_inputs=metadata,
        quota_supervisor=quota)
    runtime.attach_selection()
    runtime.attach_incentives()
    runtime.attach_rewards(scope='primary-account', checkpoint_path=Path(writer.path).with_suffix('.rewards.json'))
    producer = InventoryDispatchSource(runtime)
    dispatcher = producer.dispatcher(source.budget, invoke=transport, clock_pair=source.clock_pair)
    runtime.attach_dispatch(producer, dispatcher)
    # Rank within the explicitly reviewed scope. Unreviewed catalog additions
    # cannot have an inferred event-risk deadline; no automatic scope widening.
    return runtime


async def local_status(runtime):
    view = await runtime.risk_view()
    report = runtime.account.current_report(runtime.now())
    release = runtime.accounting_result
    window = release.window if release is not None else None
    return dict(observed_at=runtime.now().isoformat(), pid=os.getpid(),
        entries_paused=runtime.live_session.entries_paused,
        entry_allowed=runtime.entry_allowed, resting_entries=view.entry_count,
        positions={ticker: str(value) for ticker, value in view.positions if value},
        exposure_usd=str(view.total), risk_blockers=list(view.blockers),
        account_current=report is not None,
        accounting_blockers=list(release.blockers) if release is not None else ['accounting_not_released'],
        loss_window=asdict(window) if window is not None else None, runtime=runtime.status())


async def verified_flat(runtime):
    report = runtime.account.current_report(runtime.now())
    revision = runtime.writer.revision
    if report is None or runtime.last_reports is None or not report.audit.consistent:
        return False
    if report.snapshot.orders or any(p.quantity for p in report.snapshot.positions):
        return False
    inventory = await runtime.writer.inventory()
    # The current audit already checks every owned order (including terminal
    # fill gaps) against this empty venue snapshot. writer.orders() settles
    # evidence and advances its revision, so it is not a read-only flat check.
    view = await runtime.risk_view()
    return (runtime.writer.revision == revision
            and runtime.account.current_report(runtime.now()) is report
            and not inventory.unresolved_intents and not any(q for _,q in inventory.positions)
            and not view.blockers and not view.entry_count and not view.total)


async def supervise(runtime, *, stop, publish, interval=1):
    """A stop requests entry cancellation and existing inventory management.

    Stay alive while inventory/uncertainty remains. Do not label process exit
    or a cancel ACK as a flat account. No forced-liquidation rule is invented.
    """
    task = asyncio.create_task(runtime.run(), name='kalshi-live-runtime')
    result = None
    try:
        while not task.done():
            if stop():
                runtime.live_session.entries_paused = True
            if runtime.live_session.entries_paused:
                for ticker in runtime.engine.market_shard:
                    runtime.engine.dirty.mark(ticker)
                runtime.engine.wake.set()
            result = await local_status(runtime)
            result['state'] = 'DRAINING' if runtime.live_session.entries_paused else 'RUNNING'
            await asyncio.to_thread(publish, result)
            if (runtime.live_session.entries_paused and result['account_current']
                    and not result['positions'] and not result['resting_entries']
                    and not result['risk_blockers'] and runtime.last_reports is not None):
                if await verified_flat(runtime):
                    result['state'] = 'STOPPED_FLAT'
                    return result
            await asyncio.wait((task,), timeout=interval)
        task.result()
        raise InvalidData('runtime ended without verified flat shutdown')
    finally:
        runtime.stop()
        cancelled = False
        while not task.done():
            try:
                await asyncio.wait((task,))
            except asyncio.CancelledError:
                cancelled = True
        task.result()
        if cancelled:
            raise asyncio.CancelledError


async def run(args, inputs, session, diagnostics, stop):
    now, clock = lambda: datetime.now(timezone.utc), time.monotonic
    path = DATA/'account.db'
    if args.initialize and path.exists():
        raise InvalidData('initialize refuses an existing account ledger')
    if not args.initialize and not path.exists():
        raise InvalidData('first run requires explicit --initialize opening approval')
    signer = load_signer(args.key_id_file, args.private_key_file)
    # Separate restricted signer, never a key in a status document or log.
    mutation_signer = MutationSigner(signer._key_id, args.private_key_file.read_bytes())
    writer = LedgerWriter(path, diagnostics=diagnostics, live_session=session)
    reads = RestReads(TokenBudget(rate=1, capacity=20, default_cost=10,
        initial_tokens=20, clock=clock), signer, diagnostics=diagnostics)
    reads.attach_quota(QuotaGuard(QuotaPolicy(ProbeConfig(1, 20, 10, 10)),
        clock=clock, now=now, diagnostics=diagnostics))
    quota = QuotaSupervisor(reads)
    runtime = None
    try:
        await writer.start()
        status = await writer.accounting_status()
        if args.initialize:
            boundary = now()
        else:
            if (status.proposed_boundary is None
                    or 'operator_boundary_not_approved' in status.blockers):
                raise InvalidData('existing ledger lacks approved opening; no automatic reset')
            boundary = status.proposed_boundary
        runtime = await compose(writer, reads, readonly_reader_factory(signer),
            OrderMutationTransport(mutation_signer, activation=session),
            inputs=inputs, boundary=boundary, now=now, clock=clock,
            diagnostics=diagnostics, quota=quota, initialize=args.initialize)
        def publish(value):
            save_result(DATA/'status.json', value | {'run_id': session.run_id})
        return await supervise(runtime, stop=lambda: stop.requested, publish=publish)
    finally:
        session.close()
        try:
            await quota.close()
        finally:
            try:
                await reads.close()
            finally:
                await writer.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('run', 'status', 'stop', 'check-inputs'))
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--initialize', action='store_true')
    parser.add_argument('--inputs', type=Path, default=ROOT/'config'/'live-inputs.local.json')
    parser.add_argument('--key-id-file', type=Path, default=ROOT/'kalshi-bot.txt')
    parser.add_argument('--private-key-file', type=Path, default=ROOT/'Kalshi-Bot2.txt')
    args = parser.parse_args(argv)
    result, code = {}, 2
    launch_attempted = False
    try:
        if args.command == 'status':
            result = json.loads((DATA/'status.json').read_text(encoding='utf-8'))
            # A saved RUNNING snapshot is evidence from its timestamp, not a
            # process-liveness guarantee and never a request to restart.
            result['saved_snapshot_only'] = True
            code = 0
        elif args.command == 'stop':
            result = dict(stop_requested=WindowsStopEvent(IDENTITY).request(),
                          semantics='pause entries, cancel owned entries, manage inventory to flat')
            code = 0 if result['stop_requested'] else 2
        else:
            BotConfig.load(ROOT/'config'/'bot.json')  # Preserve approved risk configuration.
            inputs = LaunchInputs.load(args.inputs, datetime.now(timezone.utc))
            if args.command == 'check-inputs':
                result = dict(state='INPUTS_PARSED', tickers=inputs.tickers,
                              venue_inputs_verified=False, trading_started=False)
                code = 0
            else:
                if not args.live:
                    raise InvalidData('explicit --live required')
                with WindowsLease(IDENTITY), WindowsStopEvent(IDENTITY) as stop:
                    DATA.mkdir(parents=True, exist_ok=True)
                    session = LiveSession(run_id=uuid4().hex, tickers=inputs.tickers)
                    with Diagnostics(DATA/'logs') as diagnostics:
                        try:
                            launch_attempted = True
                            result = asyncio.run(run(args, inputs, session, diagnostics, stop))
                            code = 0 if result['state'] == 'STOPPED_FLAT' else 2
                        except (Exception, KeyboardInterrupt) as exc:
                            result = dict(state='NEEDS_ATTENTION', run_id=session.run_id,
                                errors=safe_error(exc), flat_verified=False,
                                hint='Inspect saved ledger and venue account; never assume orders were canceled.')
                        finally:
                            session.close()
                    result['logging'] = diagnostics.status()
                    if result['logging']['failure']:
                        result['state'], code = 'NEEDS_ATTENTION', 2
                    result['finished_at'] = datetime.now(timezone.utc).isoformat()
                    save_result(DATA/'status.json', result)
    except (Exception, KeyboardInterrupt) as exc:
        code = 2
        result = (dict(state='NEEDS_ATTENTION', errors=safe_error(exc),
                       trading_may_have_started=True, flat_verified=False)
                  if launch_attempted else
                  dict(state='BLOCKED', errors=safe_error(exc), trading_started=False))
    print(json.dumps(result, indent=2, default=str))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
