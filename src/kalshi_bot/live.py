"""Foreground Windows composition of the original liquidity runtime.

Nothing starts at import. The operator must explicitly select `run --live`.
No background service, supervisor restart, or alternative quoting strategy.
"""
import argparse
import asyncio
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import json
import math
import os
from .risk import DAILY_LOSS_LIMIT, LOSS_LOOKBACK
from pathlib import Path
import shutil
import time
from uuid import uuid4

from .config import BotConfig, active as active_config, activate as activate_config
from .candidate_inputs import CandidateInputs
from .candidate_preparation import prepare_candidates
from .dispatch_sources import InventoryDispatchSource
from .live_session import LiveSession
from .market_inputs import ExitInputService, FeeProfile, TimingReview, timestamp
from .mutation_transport import OrderMutationTransport
from .observability import Diagnostics, NO_LOG, safe_error
from .quota import ProbeConfig, QuotaGuard, QuotaPolicy
from .quota_supervisor import QuotaSupervisor
from .recovery_fence import FenceCooldown, RecoveryFence
from .rest import RestReads, TokenBudget, PublicDiscoveryBudget
from .restriction_journal import RestrictionJournal
from .runtime import RecoveryRuntime, readonly_reader_factory
from .startup import load_signer, read_text_shared, save_result, _noop
from .supervised_runtime import RuntimeRestrictions
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

    @classmethod
    def load_recovery(cls, path, now, owner_tickers):
        """Load only current reviewed owners; unrelated expiry cannot block drain."""
        if type(owner_tickers) not in (tuple, set, frozenset):
            raise InvalidData('typed recovery owner scope required')
        owners = frozenset(owner_tickers)
        if any(type(ticker) is not str for ticker in owners):
            raise InvalidData('invalid recovery owner ticker')
        if path.stat().st_size > 1048576:
            raise InvalidData('launch inputs exceed size limit')
        raw = json.loads(path.read_text(encoding='utf-8-sig'))
        required = {'timing_reviews', 'fee_profile', 'exchange_indices'}
        if type(raw) is not dict or not required <= set(raw) or set(raw)-required-{'initial_tickers'}:
            raise InvalidData('exact launch input fields required')
        rows = raw['timing_reviews']
        if type(rows) is not list or not 1 <= len(rows) <= 1024:
            raise InvalidData('one to 1024 reviewed markets required')
        reviews = tuple(TimingReview(**(row | {'valid_until': timestamp(row['valid_until'])}))
                        for row in rows)
        if len({row.ticker for row in reviews}) != len(reviews):
            raise InvalidData('duplicate, expired or incomplete launch scope')
        by_ticker = {row.ticker: row for row in reviews}
        if (not owners <= set(by_ticker)
                or any(by_ticker[ticker].valid_until <= now for ticker in owners)):
            raise InvalidData('recovery owner review is missing or expired')
        current = tuple(row for row in reviews if row.valid_until > now)
        if not current:
            raise InvalidData('recovery has no current reviewed scope')
        if any(row.review_reference == 'automatic-primary-milestone-v1'
               and row.early_close_reviewed for row in current):
            raise InvalidData('duplicate, expired or incomplete launch scope')
        profile = FeeProfile(**(raw['fee_profile'] | {
            'valid_until': timestamp(raw['fee_profile']['valid_until'])}))
        shards = raw['exchange_indices']
        if (profile.valid_until <= now or type(shards) is not list
                or not 1 <= len(shards) <= 128 or len(set(shards)) != len(shards)
                or 0 not in shards):
            raise InvalidData('duplicate, expired or incomplete launch scope')
        # Recovery subscribes only durable owners. If the account is already
        # locally empty, retain one current reviewed member for bounded account
        # reconciliation; entries are paused before composition.
        seeds = tuple(sorted(owners)) or (current[0].ticker,)
        return cls(current, profile,
                   tuple(integer(v, 0, 2**31-1) for v in shards), seeds)


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


async def refresh_candidate_inputs(path, now, diagnostics, scan_path=None, projects_path=None):
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
    # Public endpoints do not expose an authenticated account entitlement.
    # Keep four I/O workers, but avoid a cold-start burst and retain adaptive
    # pacing across pages after a 429 instead of resetting at every URL.
    reads = RestReads(PublicDiscoveryBudget(), concurrency=4,
        diagnostics=diagnostics)
    # D-159: the latest saved full-market scan (beside the ledger) chooses the
    # watch list when fresh; missing, stale or corrupt falls back to the hint.
    from .full_scan import load_scan
    saved = load_scan(DATA/'market_scan.json' if scan_path is None else scan_path, now)
    # D-161: saved project contracts always stay in the watched scope.
    from .finish_line import FinishLine
    projects = FinishLine(None, DATA/'projects.json' if projects_path is None
                          else projects_path).load().tickers()
    try:
        prepared = await prepare_candidates(reads, now=now,
                                            scan_scores=saved[1] if saved else None,
                                            pinned=projects)
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
        scan_observed_at=saved[0].isoformat() if saved else None,
        scan_age_minutes=int((now-saved[0]).total_seconds()//60) if saved else None,
        scan_markets=prepared.scanned, pinned_markets=prepared.pinned, trading_started=False)


async def recovery_launch_inputs(path, ledger_path, now, diagnostics):
    """Read durable local owners without credentials or venue access."""
    writer = LedgerWriter(ledger_path, market_capacity=1024, diagnostics=diagnostics)
    try:
        await writer.start()
        view = await writer.portfolio(subaccount=0, now=now)
        owners = {ticker for ticker, quantity in view.positions if quantity}
        owners.update(ticker for ticker, _ in view.exposure)
        owners.update(row.fill.ticker for row in await writer.pending_fills(0))
    finally:
        await writer.close()
    return LaunchInputs.load_recovery(path, now, owners)


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
                  now, clock, diagnostics, quota, initialize=False,
                  book_connections=2):
    """Actual owners and non-fixture execution. Injectable wires allow safe tests."""
    session = writer.live_session
    seeds = await initial_scope(writer, inputs, now())
    # Validate existing ownership above, independently of public observation
    # capacity. Recovery-only retains its narrow, protected scope.
    broad = not session.entries_paused
    if broad:
        seeds = inputs.tickers
    source = WriteQuotaSource(reads, shards=inputs.exchange_indices, live_session=session)
    await quota.bootstrap()
    metadata = ExitInputService(reads, seeds, now=now, clock=clock, ttl=60,
        diagnostics=diagnostics, timing_reviews=tuple(r for r in inputs.reviews if r.ticker in seeds),
        fee_profile=inputs.fee_profile, candidate_reviews=inputs.reviews, bulk_events=broad)
    runtime = RecoveryRuntime(writer, reads, reader_factory, tickers=seeds,
        subaccount=0, history_start=boundary, accounting_boundary=boundary,
        opening_reference=('operator-launch-'+session.run_id) if initialize else None,
        now=now, clock=clock, evaluate=_noop, deadline_handler=_noop,
        lifecycle_handler=_noop, diagnostics=diagnostics, market_inputs=metadata,
        quota_supervisor=quota, broad_discovery=broad,
        book_connections=book_connections)
    runtime.attach_selection()
    runtime.attach_incentives()
    runtime.selection.candidate_inputs = CandidateInputs(runtime, inputs.exchange_indices)
    if not broad:
        runtime.attach_admission()
    runtime.attach_rewards(scope='primary-account', checkpoint_path=Path(writer.path).with_suffix('.rewards.json'))
    if not session.entries_paused:
        runtime.attach_maintenance()
        # D-154/D-155: no re-entry for 7 days in a market family that filled
        # us, and none for an hour after a big sweep anywhere in that market.
        runtime.maintenance.fill_cooldown_required = True
        runtime.maintenance.sweep_filter_required = True
        runtime.sweep_state_path = Path(writer.path).with_name('sweeps.json')
        # D-158: score every rewarded market every 30 minutes for discovery.
        from .full_scan import FullMarketScan
        runtime.full_scan = FullMarketScan(runtime)
        runtime.full_scan.state_path = Path(writer.path).with_name('market_scan.json')
        # Phase 3 measurement: per-market resting share, kept across restarts.
        from .resting_share import RestingShare
        runtime.resting_share = RestingShare(Path(writer.path).with_name('resting_share.json')).load()
        # D-161: real-time LIP meter per contract, kept across restarts.
        from .lip_meter import LipMeter
        runtime.lip_meter = LipMeter(Path(writer.path).with_name('lip_meter.json')).load()
        # D-161 phase 3: new entries finish contracts past the $1 floor first.
        from .finish_line import FinishLine
        runtime.finish_line = FinishLine(runtime.lip_meter,
                                         Path(writer.path).with_name('projects.json')).load()
    producer = InventoryDispatchSource(runtime)
    dispatcher = producer.dispatcher(source.budget, invoke=transport, clock_pair=source.clock_pair)
    runtime.attach_dispatch(producer, dispatcher)
    # D-151: research dataset beside the ledger; background writer only.
    from .research import ResearchStore
    runtime.research = ResearchStore(Path(writer.path).with_name('research.db')).start()
    if not session.entries_paused:
        # D-145: entries are capped by a Kalshi order group per shard.
        runtime.attach_order_groups(transport, inputs.exchange_indices)
    # Discovery is automatic within the reviewed universe. Fresh metadata and
    # snapshots still gate ranking; a catalog row never grants order authority.
    return runtime


async def local_status(runtime):
    view = await runtime.risk_view()
    report = runtime.account.current_report(runtime.now())
    release = runtime.accounting_result
    window = release.window if release is not None else None
    quota = runtime.quota_supervisor
    monotonic_now = runtime.clock()
    cooldowns = []
    read_delay = max(0., runtime.reads.budget.blocked_until-monotonic_now)
    if read_delay:
        cooldowns.append(dict(name='read_shared_429', remaining_seconds=read_delay))
    if quota is not None:
        quota_delay = max(0., quota.not_before-monotonic_now)
        if quota_delay:
            cooldowns.append(dict(name='quota_refresh', remaining_seconds=quota_delay))
    if runtime.dispatch_supervisor is not None:
        budget = runtime.dispatch_supervisor.dispatcher.budget
        budget_status = budget.status(now=runtime.dispatch_supervisor.dispatcher.clock_pair())
        write_delay = max((row[3] for row in budget_status.buckets), default=0.)
        if write_delay:
            cooldowns.append(dict(name='write_shared_429', remaining_seconds=write_delay))
    restrictions = dict(component_holds=(['quota_refresh_exhausted']
        if quota is not None and quota.exhausted else []), cooldowns=cooldowns)
    return dict(observed_at=runtime.now().isoformat(), pid=os.getpid(),
        entries_paused=runtime.entry_pause_active,
        entry_allowed=runtime.entry_allowed, resting_entries=view.entry_count,
        positions={ticker: str(value) for ticker, value in view.positions if value},
        exposure_usd=str(view.total), risk_blockers=list(view.blockers),
        account_current=report is not None,
        accounting_blockers=list(release.blockers) if release is not None else ['accounting_not_released'],
        # D-162: the rolling 24-hour loss limit (no six-hour windows to track).
        loss_window=(dict(lookback_hours=24, since=(window.observed_at-LOSS_LOOKBACK).isoformat(),
                          realized_pnl=str(window.realized_pnl), limit_usd=str(DAILY_LOSS_LIMIT),
                          cap=window.cap, held=window.held, observed_at=window.observed_at.isoformat())
                     if window is not None else None),
        recovery_restrictions=restrictions, runtime=runtime.status())


async def verified_flat(runtime):
    # A current flat snapshot is not terminal while reconciliation owns or has
    # queued more account work. Stopping there can cancel the opening/release
    # pass and convert a clean flat recovery into accounting_source_failed.
    if runtime.recovery_lock.locked() or runtime.recovery_requested.is_set():
        return False
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


async def supervise(runtime, *, stop, publish, interval=1, flatten=None):
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
                if flatten is not None and await asyncio.to_thread(flatten):
                    runtime.management.request_flatten(runtime.now())
            if runtime.entry_pause_active:
                runtime.request_entry_drain()
                for ticker in runtime.engine.market_shard:
                    runtime.engine.dirty.mark(ticker)
                runtime.engine.wake.set()
            result = await local_status(runtime)
            result['state'] = 'DRAINING' if runtime.entry_pause_active else 'RUNNING'
            result['emergency_flatten'] = runtime.management.flatten_at is not None
            result['emergency_flatten_supported'] = True
            await asyncio.to_thread(publish, result)
            if (runtime.entry_pause_active and result['account_current']
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
              recovery_only=False, recovery_restrictions=None,
              restriction_journal=None, explicit_retry=False):
    now, clock = lambda: datetime.now(timezone.utc), time.monotonic
    path = DATA/'account.db'
    resume_opening = getattr(args, 'resume_opening', False)
    if type(resume_opening) is not bool or (args.initialize and resume_opening):
        raise InvalidData('invalid opening initialization mode')
    if recovery_only and args.initialize:
        raise InvalidData('recovery-only cannot initialize an account ledger')
    if args.initialize and path.exists():
        raise InvalidData('initialize refuses an existing account ledger')
    if resume_opening and not path.exists():
        raise InvalidData('opening resume requires existing account ledger')
    if not args.initialize and not path.exists():
        raise InvalidData('first run requires explicit --initialize opening approval')
    if recovery_only:
        session.entries_paused = True
    journal = (RestrictionJournal(DATA/'recovery-restrictions.json')
               if restriction_journal is None else restriction_journal)
    if not isinstance(journal, RestrictionJournal):
        raise InvalidData('typed restriction journal required')
    journal_holds, journal_cooldowns = journal.snapshot()
    if type(explicit_retry) is not bool:
        raise InvalidData('explicit retry flag must be boolean')
    if explicit_retry:
        journal_holds = ()
    if recovery_restrictions is None:
        recovery_restrictions = RuntimeRestrictions()
        recovery_restrictions.apply(RecoveryFence('local-runtime', 'local-runtime',
            0, 1, journal_holds, journal_cooldowns, False))
    elif journal_holds or journal_cooldowns:
        deadlines = {item.name:item.deadline_utc
                     for item in recovery_restrictions.cooldowns}
        for item in journal_cooldowns:
            deadlines[item.name] = max(deadlines.get(item.name, 0), item.deadline_utc)
        merged = RuntimeRestrictions()
        merged.apply(RecoveryFence('local-runtime', 'local-runtime', 0, 1,
            tuple(dict.fromkeys(recovery_restrictions.holds+journal_holds)),
            tuple(FenceCooldown(name, deadline)
                  for name,deadline in sorted(deadlines.items())), False))
        recovery_restrictions = merged
    if (not isinstance(recovery_restrictions, RuntimeRestrictions)
            or not recovery_restrictions.applied):
        raise InvalidData('applied recovery restrictions required')
    if recovery_restrictions.holds:
        raise InvalidData('unresolved recovery restriction hold')
    signer = load_signer(args.key_id_file, args.private_key_file)
    # Separate restricted signer, never a key in a status document or log.
    mutation_signer = MutationSigner(signer._key_id, args.private_key_file.read_bytes())
    writer = LedgerWriter(path, diagnostics=diagnostics, live_session=session)
    reads = RestReads(TokenBudget(rate=1, capacity=20, default_cost=10,
        initial_tokens=20, clock=clock, restriction_sink=journal.cooldown),
        signer, diagnostics=diagnostics)
    reads.attach_quota(QuotaGuard(QuotaPolicy(ProbeConfig(1, 20, 10, 10)),
        clock=clock, now=now, diagnostics=diagnostics))
    def quota_restriction(name, seconds, hold):
        if hold:
            journal.hold(name, seconds)
        else:
            journal.cooldown(name, seconds)
    quota = QuotaSupervisor(reads, restriction_sink=quota_restriction)
    runtime = None
    result = None
    try:
        wall_now = time.time()
        for item in recovery_restrictions.cooldowns:
            remaining = max(0., item.deadline_utc-wall_now)
            if item.name == 'read_shared_429' and remaining:
                reads.budget.throttle(remaining)
            elif item.name == 'quota_refresh' and remaining:
                quota.not_before = max(quota.not_before, clock()+remaining)
            elif item.name != 'write_shared_429':
                raise InvalidData('unknown recovery cooldown')
        await writer.start()
        status = await writer.accounting_status()
        if args.initialize:
            boundary = now()
        else:
            if (status.proposed_boundary is None
                    or ('operator_boundary_not_approved' in status.blockers
                        and not resume_opening)):
                raise InvalidData('existing ledger lacks approved opening; no automatic reset')
            boundary = status.proposed_boundary
        runtime = await compose(writer, reads, readonly_reader_factory(signer),
            OrderMutationTransport(mutation_signer, activation=session),
            inputs=inputs, boundary=boundary, now=now, clock=clock,
            diagnostics=diagnostics, quota=quota,
            initialize=args.initialize or resume_opening,
            book_connections=BotConfig.load(ROOT/'config'/'bot.json').book_connections)
        runtime.dispatch_supervisor.dispatcher.budget.restriction_sink = journal.cooldown
        for item in recovery_restrictions.cooldowns:
            remaining = max(0., item.deadline_utc-time.time())
            if item.name == 'write_shared_429' and remaining:
                budget = runtime.dispatch_supervisor.dispatcher.budget
                for shard in inputs.exchange_indices:
                    budget.pause_429(shard=shard, seconds=remaining,
                                     now=runtime.dispatch_supervisor.dispatcher.clock_pair())
        # A successful fresh quota bootstrap is the proof required to clear an
        # explicitly retried exhaustion hold. Active inherited cooldowns remain.
        journal.replace((), recovery_restrictions.cooldowns)
        def publish(value):
            document = value | {'run_id': session.run_id,
                                'recovery_only': bool(recovery_only)}
            if getattr(args, 'supervisor_child_id', None) is not None:
                document['supervisor_child_id'] = args.supervisor_child_id
            evidence = document.get('recovery_restrictions', {})
            journal.replace(tuple(evidence.get('component_holds', ())), tuple(
                FenceCooldown(item['name'], math.ceil(
                    time.time()+max(0., item['remaining_seconds'])))
                for item in evidence.get('cooldowns', ())))
            save_result(DATA/'status.json', document)
            if publish_override is not None:
                publish_override(document)
        result = await supervise(runtime, stop=lambda: stop.requested, publish=publish,
                                 flatten=getattr(stop, 'flatten_requested', None))
    finally:
        session.close()
        try:
            await quota.close()
        finally:
            try:
                await reads.close()
            finally:
                await writer.close()
    # Persist the terminal state only after every retained runtime resource has
    # joined successfully. A cleanup error exits before this write.
    if result is None or result.get('state') != 'STOPPED_FLAT':
        raise InvalidData('live runtime ended without terminal flat result')
    terminal = result | {'run_id': session.run_id,
                         'recovery_only': bool(recovery_only)}
    if getattr(args, 'supervisor_child_id', None) is not None:
        terminal['supervisor_child_id'] = args.supervisor_child_id
    save_result(DATA/'status.json', terminal)
    if publish_override is not None:
        publish_override(terminal)
    return terminal


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
            result = json.loads(read_text_shared(DATA/'status.json'))
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
                    saved = json.loads(read_text_shared(DATA/'status.json'))
                except (OSError, ValueError):
                    saved = {}
                if saved.get('state') != 'STOPPED_FLAT':
                    raise InvalidData('candidate refresh requires no ledger or verified flat shutdown')
            with WindowsLease(IDENTITY):
                result = asyncio.run(refresh_candidate_inputs(
                    args.inputs, datetime.now(timezone.utc), NO_LOG))
            code = 0
        else:
            activate_config(BotConfig.load(ROOT/'config'/'bot.json'))  # D-142: run on approved file.
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
