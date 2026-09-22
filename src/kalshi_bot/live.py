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
import shutil
import time
from uuid import uuid4

from .config import BotConfig
from .candidate_inputs import CandidateInputs
from .candidate_preparation import prepare_candidates
from .dispatch_sources import InventoryDispatchSource
from .live_session import LiveSession
from .market_inputs import ExitInputService, FeeProfile, TimingReview, timestamp
from .mutation_transport import OrderMutationTransport
from .observability import Diagnostics, NO_LOG, safe_error
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
    initial_tickers: tuple = ()

    @property
    def tickers(self):
        return tuple(review.ticker for review in self.reviews)

    @property
    def seed_tickers(self):
        return self.initial_tickers or self.tickers

    @classmethod
    def load(cls, path, now):
        if path.stat().st_size > 1048576:
            raise InvalidData('launch inputs exceed size limit')
        raw = json.loads(path.read_text(encoding='utf-8-sig'))
        required = {'timing_reviews', 'fee_profile', 'exchange_indices'}
        if type(raw) is not dict or not required <= set(raw) or set(raw)-required-{'initial_tickers'}:
            raise InvalidData('exact launch input fields required')
        if type(raw['timing_reviews']) is not list or not 1 <= len(raw['timing_reviews']) <= 1024:
            raise InvalidData('one to 1024 reviewed markets required')
        reviews = tuple(TimingReview(**(row | {'valid_until': timestamp(row['valid_until'])}))
                        for row in raw['timing_reviews'])
        profile = FeeProfile(**(raw['fee_profile'] | {
            'valid_until': timestamp(raw['fee_profile']['valid_until'])}))
        shards = raw['exchange_indices']
        if (len({row.ticker for row in reviews}) != len(reviews)
                or any(row.valid_until <= now for row in reviews)
                or any(row.review_reference == 'automatic-primary-milestone-v1'
                       and row.early_close_reviewed for row in reviews)
                or profile.valid_until <= now or type(shards) is not list
                or not 1 <= len(shards) <= 128 or len(set(shards)) != len(shards)
                or 0 not in shards):
            raise InvalidData('duplicate, expired or incomplete launch scope')
        seeds = raw.get('initial_tickers', [row.ticker for row in reviews])
        if (type(seeds) is not list or not seeds or len(seeds) > 128
                or any(type(t) is not str for t in seeds) or len(set(seeds)) != len(seeds)
                or not set(seeds) <= {row.ticker for row in reviews}):
            raise InvalidData('initial subscriptions must be a nonempty reviewed subset')
        return cls(reviews, profile, tuple(integer(v, 0, 2**31-1) for v in shards), tuple(seeds))


def _input_document(inputs):
    def stamp(value):
        return value.isoformat().replace('+00:00', 'Z')
    return dict(
        timing_reviews=[dict(ticker=r.ticker, event=r.event, milestone_id=r.milestone_id,
            milestone_type=r.milestone_type, rules_hash=r.rules_hash,
            review_reference=r.review_reference, valid_until=stamp(r.valid_until),
            early_close_reviewed=r.early_close_reviewed) for r in inputs.reviews],
        fee_profile=dict(balance_quantum=str(inputs.fee_profile.balance_quantum),
            review_reference=inputs.fee_profile.review_reference,
            valid_until=stamp(inputs.fee_profile.valid_until)),
        exchange_indices=list(inputs.exchange_indices),
        initial_tickers=list(inputs.initial_tickers))


async def refresh_candidate_inputs(path, now, diagnostics):
    """Replace only the ignored candidate scope; preserve reviewed member fees."""
    if path.stat().st_size > 1048576:
        raise InvalidData('launch inputs exceed size limit')
    raw = json.loads(path.read_text(encoding='utf-8-sig'))
    if type(raw) is not dict or 'fee_profile' not in raw:
        raise InvalidData('launch fee profile required')
    profile = FeeProfile(**(raw['fee_profile'] | {
        'valid_until':timestamp(raw['fee_profile']['valid_until'])}))
    if profile.valid_until <= now:
        raise InvalidData('launch fee profile expired')
    # Public-only launch preparation is request-latency bound. This local
    # scheduler still caps concurrency at RestReads' default two workers.
    reads = RestReads(TokenBudget(rate=50, capacity=100, default_cost=1,
        initial_tokens=100, clock=time.monotonic), diagnostics=diagnostics)
    try:
        prepared = await prepare_candidates(reads, now=now)
    finally:
        await reads.close()
    inputs = LaunchInputs(prepared.reviews, profile,
                          prepared.exchange_indices, prepared.initial_tickers)
    document = _input_document(inputs)
    if len(json.dumps(document, indent=2, allow_nan=False).encode('utf-8'))+1 > 1048576:
        raise InvalidData('prepared launch inputs exceed size limit')
    staging = path.with_name(path.stem+'.candidate.local.json')
    save_result(staging, document)
    try:
        checked = LaunchInputs.load(staging, now)
        if checked != inputs:
            raise InvalidData('saved candidate scope does not match prepared scope')
    except BaseException:
        staging.unlink(missing_ok=True)
        raise
    backup = ROOT/'backups'/'live-inputs.before-automatic-candidates.json'
    if not backup.exists():
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, backup)
    os.replace(staging, path)
    return dict(state='CANDIDATES_PREPARED', reviewed_markets=len(inputs.reviews),
        initial_websocket_markets=len(inputs.seed_tickers),
        incentive_rows=prepared.incentive_rows, market_rows=prepared.market_rows,
        milestone_rows=prepared.milestone_rows, excluded=dict(prepared.excluded),
        trading_started=False)


async def initial_scope(writer, inputs, now):
    """Seed subscriptions plus durable owners; does not approve their account state."""
    session = writer.live_session
    if session is None or session.tickers != frozenset(inputs.tickers):
        raise InvalidData('launch/session market scope differs')
    # Restart scope gives every durable owner priority over optional discovery
    # seeds, including pending fills not yet reflected in portfolio exposure.
    # Portfolio blockers still block entries; they do not turn all 1,024
    # reviewed candidates into supposed owners and make recovery impossible.
    view = await writer.portfolio(subaccount=0, now=now)
    protected = {t for t, v in view.positions if v} | {t for t, _ in view.exposure}
    protected.update(row.fill.ticker for row in await writer.pending_fills(0))
    if not protected <= session.tickers or len(protected) > writer.market_capacity:
        raise InvalidData('startup owners exceed reviewed subscription scope')
    room = writer.market_capacity-len(protected)
    optional = tuple(t for t in inputs.seed_tickers if t not in protected)[:room]
    return tuple(sorted(protected | set(optional)))


async def compose(writer, reads, reader_factory, transport, *, inputs, boundary,
                  now, clock, diagnostics, quota, initialize=False):
    """Actual owners and non-fixture execution. Injectable wires allow safe tests."""
    session = writer.live_session
    seeds = await initial_scope(writer, inputs, now())
    source = WriteQuotaSource(reads, shards=inputs.exchange_indices, live_session=session)
    await quota.bootstrap()
    metadata = ExitInputService(reads, seeds, now=now, clock=clock, ttl=60,
        diagnostics=diagnostics, timing_reviews=tuple(r for r in inputs.reviews if r.ticker in seeds),
        fee_profile=inputs.fee_profile, candidate_reviews=inputs.reviews)
    runtime = RecoveryRuntime(writer, reads, reader_factory, tickers=seeds,
        subaccount=0, history_start=boundary, accounting_boundary=boundary,
        opening_reference=('operator-launch-'+session.run_id) if initialize else None,
        now=now, clock=clock, evaluate=_noop, deadline_handler=_noop,
        lifecycle_handler=_noop, diagnostics=diagnostics, market_inputs=metadata,
        quota_supervisor=quota)
    runtime.attach_selection()
    runtime.attach_incentives()
    runtime.selection.candidate_inputs = CandidateInputs(runtime, inputs.exchange_indices)
    runtime.attach_admission()
    runtime.attach_rewards(scope='primary-account', checkpoint_path=Path(writer.path).with_suffix('.rewards.json'))
    producer = InventoryDispatchSource(runtime)
    dispatcher = producer.dispatcher(source.budget, invoke=transport, clock_pair=source.clock_pair)
    runtime.attach_dispatch(producer, dispatcher)
    # Discovery is automatic within the reviewed universe. Fresh metadata and
    # snapshots still gate ranking; a catalog row never grants order authority.
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


async def run(args, inputs, session, diagnostics, stop, *, publish_override=None,
              recovery_only=False):
    now, clock = lambda: datetime.now(timezone.utc), time.monotonic
    path = DATA/'account.db'
    if args.initialize and path.exists():
        raise InvalidData('initialize refuses an existing account ledger')
    if not args.initialize and not path.exists():
        raise InvalidData('first run requires explicit --initialize opening approval')
    if recovery_only:
        if args.initialize:
            raise InvalidData('recovery-only cannot initialize an account ledger')
        session.entries_paused = True
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
            document = value | {'run_id': session.run_id,
                                'recovery_only': bool(recovery_only)}
            save_result(DATA/'status.json', document)
            if publish_override is not None:
                publish_override(document)
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
    parser.add_argument('command', choices=('run', 'status', 'stop', 'check-inputs',
                                            'refresh-candidates'))
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
        elif args.command == 'refresh-candidates':
            BotConfig.load(ROOT/'config'/'bot.json')
            if (DATA/'account.db').exists():
                try:
                    saved = json.loads((DATA/'status.json').read_text(encoding='utf-8'))
                except (OSError, ValueError):
                    saved = {}
                if saved.get('state') != 'STOPPED_FLAT':
                    raise InvalidData('candidate refresh requires no ledger or verified flat shutdown')
            with WindowsLease(IDENTITY):
                result = asyncio.run(refresh_candidate_inputs(
                    args.inputs, datetime.now(timezone.utc), NO_LOG))
            code = 0
        else:
            BotConfig.load(ROOT/'config'/'bot.json')  # Preserve approved risk configuration.
            if args.command == 'check-inputs':
                inputs = LaunchInputs.load(args.inputs, datetime.now(timezone.utc))
                result = dict(state='INPUTS_PARSED', tickers=inputs.tickers,
                              initial_tickers=inputs.seed_tickers, automatic_admission=True,
                              venue_inputs_verified=False, trading_started=False)
                code = 0
            else:
                if not args.live:
                    raise InvalidData('explicit --live required')
                with WindowsLease(IDENTITY), WindowsStopEvent(IDENTITY) as stop:
                    DATA.mkdir(parents=True, exist_ok=True)
                    with Diagnostics(DATA/'logs') as diagnostics:
                        # A first approved opening prepares the broad public
                        # reward scope before any signer/session/order authority.
                        if args.initialize and not (DATA/'account.db').exists():
                            refresh = asyncio.run(refresh_candidate_inputs(
                                args.inputs, datetime.now(timezone.utc), diagnostics))
                            diagnostics.emit('candidate_scope_prepared', **refresh)
                        inputs = LaunchInputs.load(args.inputs, datetime.now(timezone.utc))
                        session = LiveSession(run_id=uuid4().hex, tickers=inputs.tickers)
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
