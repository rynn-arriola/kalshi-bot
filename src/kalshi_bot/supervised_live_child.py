"""Fixed production child for the Windows native supervisor.

The parent owns process policy only. This child owns credentials, the live
lease, runtime resources, and verified-flat shutdown.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import math
from pathlib import Path
from threading import Lock
import time
from types import SimpleNamespace
from uuid import uuid4

import kalshi_bot
from .config import BotConfig
from .live import (DATA, IDENTITY, ROOT, LaunchInputs, refresh_candidate_inputs,
                   recovery_launch_inputs, run as run_live)
from .live_session import LiveSession
from .observability import Diagnostics
from .recovery_fence import FenceCooldown, RecoveryFence
from .restriction_journal import RestrictionJournal
from .supervised_runtime import RuntimeRestrictions
from .supervisor_control import ScopeSpec
from .supervisor_launch import (PRODUCTION_MODE, ProductionLaunchProfile,
                                production_child_mode)
from .supervisor_protocol import Envelope, MessageKind, ParentProtocol
from .supervisor_store import SupervisorStore
from .values import InvalidData
from .windows import (WindowsControlMutex, WindowsLease, WindowsPowerMonitor,
                      current_user_sid, process_id_from_handle, wait_handle)
from .windows_ipc import connect_pipe


_LIFETIME_HANDLE = None  # Deliberately retained until process termination.


def _envelope(args, kind, sequence, payload):
    return Envelope(args.scope_digest, args.parent_session, args.child_id,
        args.child_generation, kind, sequence, time.monotonic_ns(), payload)


class _StopSignal:
    def __init__(self, args, power):
        self.args, self.power = args, power
        self.local = False

    @property
    def requested(self):
        return (self.local or self.power.changed.is_set()
                or wait_handle(self.args.stop_handle)
                or wait_handle(self.args.parent_handle))

    def request(self):
        self.local = True


class _LatestStatus:
    def __init__(self):
        self.lock = Lock()
        self.value = None
        self.revision = 0

    def publish(self, value):
        with self.lock:
            self.value = dict(value)
            self.revision += 1

    def read(self):
        with self.lock:
            return self.revision, None if self.value is None else dict(self.value)


def _status_projection(status, recovery_only):
    """Map runtime health without promoting temporary blockers to retry holds."""
    if status is None:
        return 'starting', ()
    health = tuple(dict.fromkeys(status.get('risk_blockers', [])
        + status.get('accounting_blockers', [])))[:32]
    if recovery_only or status.get('entries_paused'):
        phase = 'recovering'
    elif health:
        phase = 'degraded'
    else:
        phase = 'healthy'
    return phase, ()


def _parse(argv):
    parser = argparse.ArgumentParser(add_help=False)
    for name in ("pipe_name", "scope_digest", "scope_id", "parent_session",
                 "child_id", "store_path", "control_root", "environment",
                 "account_scope", "approved_user_sid", "source_path", "profile"):
        parser.add_argument("--"+name.replace("_", "-"), required=True)
    parser.add_argument("--child-generation", required=True, type=int)
    parser.add_argument("--lifetime-handle", required=True, type=int)
    parser.add_argument("--stop-handle", required=True, type=int)
    parser.add_argument("--parent-handle", required=True, type=int)
    parser.add_argument("--initialize-approved", action="store_true")
    parser.add_argument("--recovery-only", action="store_true")
    parser.add_argument("--explicit-retry", action="store_true")
    return parser.parse_args(argv)


def main(argv=None):
    args = _parse(argv)
    global _LIFETIME_HANDLE
    _LIFETIME_HANDLE = args.lifetime_handle
    if current_user_sid() != args.approved_user_sid:
        return 20
    if args.profile != PRODUCTION_MODE:
        return 21
    if Path(kalshi_bot.__file__).resolve() != Path(args.source_path).resolve():
        return 22
    scope = ScopeSpec(args.environment, args.account_scope,
                      args.approved_user_sid, Path(args.control_root), "production")
    if scope.scope_id != args.scope_id or scope.digest != args.scope_digest:
        return 23
    profile = ProductionLaunchProfile(args.initialize_approved)
    diagnostics = Diagnostics(scope.control_root / "child-logs",
                              max_bytes=262144, backups=2)
    endpoint = None
    child_started = False
    with WindowsPowerMonitor() as power:
        try:
            diagnostics.start()
            diagnostics.emit("supervisor_child_started", operation=args.child_id,
                             generation=args.child_generation)
            parent_pid = process_id_from_handle(args.parent_handle)
            if wait_handle(args.parent_handle) or power.changed.is_set():
                return 28
            endpoint = connect_pipe(args.pipe_name, expected_server_pid=parent_pid)
            child_started = True
            return _run_admitted(args, scope, profile, endpoint, power, diagnostics)
        except BaseException as exc:
            try:
                diagnostics.emit("supervisor_child_failed", error=exc,
                                 operation=args.child_id)
            except BaseException:
                pass
            # Once IPC/admission work begins, a reserved validation exit must
            # not misclassify possible runtime ownership as startup refusal.
            return 27 if child_started else 26
        finally:
            if endpoint is not None:
                while not endpoint.closed:
                    endpoint.close_and_join()
            diagnostics.close()
            while diagnostics.status()["worker_alive"]:
                diagnostics.close()


def _run_admitted(args, scope, profile, endpoint, power, diagnostics):
    protocol = ParentProtocol(args.scope_digest, args.parent_session,
                              args.child_id, args.child_generation)

    def guard():
        diagnostics.ensure_healthy()
        if power.changed.is_set():
            raise InvalidData("child power state invalidated")

    def control(message):
        guard()
        with WindowsControlMutex(scope.scope_id,
                user_sid=scope.approved_user_sid) as mutex:
            if mutex.abandoned:
                raise InvalidData("child control mutex abandoned")
            revision, state, native = SupervisorStore.read_only_snapshot(
                args.store_path, scope_id=scope.scope_id,
                security_sid=scope.approved_user_sid)
            accepted = protocol.accept(message, now_ns=time.monotonic_ns(),
                                       current_revision=revision)
            if _admission_revoked(args, message, state, native,
                    stop_signaled=wait_handle(args.stop_handle),
                    parent_signaled=wait_handle(args.parent_handle)):
                raise InvalidData("child admission revoked")
            return accepted

    endpoint.send_control(_envelope(args, MessageKind.HELLO, 1,
        dict(build_fingerprint=profile.build_fingerprint,
             config_fingerprint=profile.config_fingerprint,
             fixture_mode=profile.mode))).result(timeout=4)
    deadline = time.monotonic()+10
    while True:
        guard()
        if wait_handle(args.stop_handle) or wait_handle(args.parent_handle):
            return 24
        message = endpoint.receive(timeout=.1)
        if message is None:
            if time.monotonic() >= deadline:
                return 25
            continue
        control(message)
        if message.kind == MessageKind.STOP_HINT:
            return 24
        if message.kind != MessageKind.ADMIT:
            raise InvalidData("child expected admission")
        break
    return asyncio.run(_run_live(args, scope, endpoint, protocol, control,
                                 power, diagnostics))


def _admission_revoked(args, message, state, native, *, stop_signaled,
                       parent_signaled):
    """Keep identity binding strict while allowing terminal fence completion."""
    binding_revoked = (
        state.generation != args.child_generation
        or state.child_id != args.child_id
        or state.child_generation != args.child_generation
        or native.parent_session != args.parent_session
        or native.child_id != args.child_id
        or native.child_generation != args.child_generation
        or native.stage != "bound"
        or parent_signaled)
    authority_revoked = state.stop_latched or not state.desired_armed or stop_signaled
    # A stopped child retains no trading authority, but it must still receive
    # the exact terminal recovery-fence acknowledgement so it can report
    # verified-flat cleanup instead of a false shutdown timeout.
    return (binding_revoked or
        (message.kind not in {MessageKind.STOP_HINT, MessageKind.FENCE_ACK}
         and authority_revoked))


async def _send_result(args, endpoint, diagnostics, *, outcome,
                       cleanup_complete, unresolved_work, retry_holds=(),
                       control_sequence=None):
    diagnostics.emit("supervisor_child_stopped", operation=args.child_id)
    await asyncio.to_thread(diagnostics.close, 1)
    while diagnostics.status()["worker_alive"]:
        await asyncio.to_thread(diagnostics.close, 1)
    if diagnostics.status()["failure"] is not None:
        raise InvalidData("child diagnostic cleanup failed")
    sequence = 2 if control_sequence is None else control_sequence[0]+1
    if control_sequence is not None:
        control_sequence[0] = sequence
    receipt = endpoint.send_control(_envelope(args, MessageKind.RESULT, sequence,
        dict(outcome=outcome, cleanup_complete=cleanup_complete,
             cleanup_failed=False, unresolved_work=unresolved_work,
             retry_holds=list(retry_holds))))
    await asyncio.wait_for(asyncio.wrap_future(receipt), 4)


def _fence_payload(fence):
    now = time.time()
    return dict(fence_revision=fence.fence_revision,
        component_holds=list(fence.component_holds),
        cooldowns=[dict(name=item.name, remaining_ms=max(1, min(86400000,
            int((item.deadline_utc-now)*1000)))) for item in fence.cooldowns
            if item.deadline_utc > now],
        terminal_checkpoint_complete=fence.terminal_checkpoint_complete)


async def _publish_fence(args, endpoint, control, fence, control_sequence,
                         stop, pulse):
    control_sequence[0] += 1
    receipt = endpoint.send_control(_envelope(args, MessageKind.FENCE,
        control_sequence[0], _fence_payload(fence)))
    await asyncio.wait_for(asyncio.wrap_future(receipt), 4)
    deadline = time.monotonic()+10
    while True:
        message = await asyncio.to_thread(endpoint.receive, .1)
        if message is None:
            if time.monotonic() >= deadline:
                raise InvalidData('production recovery-fence acknowledgement timed out')
            continue
        accepted = control(message)
        if message.kind == MessageKind.PULSE and accepted:
            pulse[0] = time.monotonic()
            continue
        if message.kind == MessageKind.STOP_HINT:
            stop.request()
            continue
        if (message.kind != MessageKind.FENCE_ACK
                or message.payload['fence_revision'] != fence.fence_revision):
            raise InvalidData('production child expected matching fence acknowledgement')
        return


async def _prepare_candidates(args, endpoint, control, stop, pulse, diagnostics,
                              run_args, status_sequence):
    task = asyncio.create_task(refresh_candidate_inputs(
        run_args.inputs, datetime.now(timezone.utc), diagnostics),
        name='supervised-candidate-preparation')
    next_status = 0.0
    try:
        while not task.done():
            if (wait_handle(args.parent_handle) or wait_handle(args.stop_handle)):
                stop.request()
            message = await asyncio.to_thread(endpoint.receive, .05)
            if message is not None:
                accepted = control(message)
                if message.kind == MessageKind.PULSE and accepted:
                    pulse[0] = time.monotonic()
                elif message.kind == MessageKind.STOP_HINT:
                    stop.request()
            if stop.requested or time.monotonic()-pulse[0] > 6:
                task.cancel()
                while not task.done():
                    try:
                        await asyncio.wait((task,))
                    except asyncio.CancelledError:
                        pass
                try:
                    task.result()
                except asyncio.CancelledError:
                    pass
                return None
            now = time.monotonic()
            if now >= next_status:
                status_sequence[0] += 1
                endpoint.publish_latest(_envelope(args, MessageKind.STATUS,
                    status_sequence[0], dict(phase='starting',
                         progress_sequence=status_sequence[0],
                         work_remaining_ms=60000, blockers=[])))
                next_status = now+2
            await asyncio.sleep(0)
        return task.result()
    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


async def _wait_cooldowns(args, endpoint, control, stop, pulse, restrictions,
                          status_sequence):
    """Retain parent supervision while inherited process cooldowns elapse."""
    next_status = 0.0
    while True:
        remaining = max((item.deadline_utc-time.time()
                         for item in restrictions.cooldowns), default=0.)
        if remaining <= 0:
            return True
        if wait_handle(args.parent_handle) or wait_handle(args.stop_handle):
            stop.request()
        message = await asyncio.to_thread(endpoint.receive, .05)
        if message is not None:
            accepted = control(message)
            if message.kind == MessageKind.PULSE and accepted:
                pulse[0] = time.monotonic()
            elif message.kind == MessageKind.STOP_HINT:
                stop.request()
        if stop.requested or time.monotonic()-pulse[0] > 6:
            return False
        now = time.monotonic()
        if now >= next_status:
            status_sequence[0] += 1
            endpoint.publish_latest(_envelope(args, MessageKind.STATUS,
                status_sequence[0], dict(phase='recovering',
                    progress_sequence=status_sequence[0],
                    work_remaining_ms=max(1, min(60000,
                        int(remaining*1000))), blockers=[])))
            next_status = now+2
        await asyncio.sleep(0)


async def _send_early_stop(args, endpoint, diagnostics, control_sequence, ledger,
                           terminal_fence=None):
    """A pre-runtime stop is clean only before the first ledger exists."""
    unresolved = ledger.exists()
    if not unresolved:
        if terminal_fence is None:
            raise InvalidData('terminal fence required for clean pre-runtime stop')
        await terminal_fence()
    await _send_result(args, endpoint, diagnostics,
        outcome='unknown_failure' if unresolved else 'clean',
        cleanup_complete=not unresolved, unresolved_work=unresolved,
        control_sequence=control_sequence)
    return 31 if unresolved else 0


async def _run_live(args, scope, endpoint, protocol, control, power, diagnostics):
    stop = _StopSignal(args, power)
    latest = _LatestStatus()
    status_sequence = [0]
    progress_sequence = 0
    last_revision = 0
    pulse = [time.monotonic()]
    operator_stop = False
    control_sequence = [1]  # HELLO was child-control sequence one.
    fence_revision = 0

    # These checks happen before signer loading or network/runtime ownership.
    ledger = DATA / "account.db"
    try:
        mode = production_child_mode(initialize_approved=args.initialize_approved,
            ledger_exists=ledger.exists(), recovery_only=args.recovery_only)
    except InvalidData:
        await _send_result(args, endpoint, diagnostics, outcome="startup_refused",
                           cleanup_complete=True, unresolved_work=False,
                           control_sequence=control_sequence)
        return 20
    initialize = mode.initialize

    run_args = SimpleNamespace(initialize=initialize,
        resume_opening=mode.resume_opening,
        inputs=ROOT / "config" / "live-inputs.local.json",
        key_id_file=ROOT / "kalshi-bot.txt",
        private_key_file=ROOT / "Kalshi-Bot2.txt")
    session = None
    task = None
    lease = WindowsLease(IDENTITY)
    lease_acquired = False
    try:
        BotConfig.load(ROOT / "config" / "bot.json")
        lease.__enter__()
        lease_acquired = True
        with WindowsControlMutex(scope.scope_id,
                user_sid=scope.approved_user_sid) as mutex:
            if mutex.abandoned:
                raise InvalidData('child control mutex abandoned before fence load')
            prior = SupervisorStore.read_only_recovery_fence(args.store_path,
                scope_id=scope.scope_id, security_sid=scope.approved_user_sid)
        expected_explicit_retry = (prior is None
            or args.child_generation > prior.child_generation)
        if args.explicit_retry != expected_explicit_retry:
            raise InvalidData('production explicit retry generation mismatch')
        journal = RestrictionJournal(DATA/'recovery-restrictions.json')
        journal_holds, journal_cooldowns = journal.snapshot()
        prior_revision = 0 if prior is None else prior.fence_revision
        deadlines = {} if prior is None else {
            item.name:item.deadline_utc for item in prior.cooldowns}
        for item in journal_cooldowns:
            deadlines[item.name] = max(deadlines.get(item.name, 0), item.deadline_utc)
        inherited_holds = (() if prior is None else prior.component_holds)
        if mode.recovery_only and not args.explicit_retry:
            inherited_holds = tuple(dict.fromkeys(inherited_holds+journal_holds))
        prior = RecoveryFence(args.parent_session, args.child_id,
            args.child_generation, max(1, prior_revision), inherited_holds,
            tuple(FenceCooldown(name, deadline)
                  for name,deadline in sorted(deadlines.items())),
            False if prior is None else prior.terminal_checkpoint_complete)
        restrictions = RuntimeRestrictions()
        if not mode.recovery_only:
            # A new explicit arm is the retry authority for component exhaustion;
            # active shared cooldown deadlines remain in force.
            prior = RecoveryFence(args.parent_session, args.child_id,
                args.child_generation, prior.fence_revision, (), prior.cooldowns,
                prior.terminal_checkpoint_complete)
        restrictions.apply(prior, current_parent_session=args.parent_session)
        if mode.recovery_only and prior_revision == 0:
            restrictions.holds = ('recovery_fence_unknown',)
        fence_revision = prior_revision+1
        fence = RecoveryFence(args.parent_session, args.child_id,
            args.child_generation, fence_revision, restrictions.holds,
            restrictions.cooldowns, False)
        await _publish_fence(args, endpoint, control, fence, control_sequence,
                             stop, pulse)
        async def early_stop():
            nonlocal fence_revision
            async def terminal_fence():
                nonlocal fence_revision
                fence_revision += 1
                await _publish_fence(args, endpoint, control, RecoveryFence(
                    args.parent_session, args.child_id, args.child_generation,
                    fence_revision, restrictions.holds,
                    restrictions.cooldowns, True), control_sequence, stop, pulse)
            return await _send_early_stop(args, endpoint, diagnostics,
                control_sequence, ledger, terminal_fence=terminal_fence)
        if restrictions.holds:
            await _send_result(args, endpoint, diagnostics,
                outcome='retry_exhausted', cleanup_complete=False,
                unresolved_work=True, retry_holds=restrictions.blockers,
                control_sequence=control_sequence)
            return 31
        if not await _wait_cooldowns(args, endpoint, control, stop, pulse,
                                     restrictions, status_sequence):
            return await early_stop()
        progress_sequence = status_sequence[0]
        # Every explicit normal arm refreshes the public-only reviewed scope.
        # Saved candidates can expire between runs; failing before account
        # reconciliation would otherwise make a normal restart impossible.
        # Recovery-only stays narrow and never expands its owner scope.
        if not mode.recovery_only:
            refresh = await _prepare_candidates(args, endpoint, control, stop,
                                                 pulse, diagnostics, run_args,
                                                 status_sequence)
            if refresh is None:
                return await early_stop()
            diagnostics.emit("candidate_scope_prepared", **refresh)
            progress_sequence = status_sequence[0]
        if stop.requested:
            return await early_stop()
        if mode.recovery_only:
            inputs = await recovery_launch_inputs(run_args.inputs, ledger,
                datetime.now(timezone.utc), diagnostics)
        else:
            inputs = LaunchInputs.load(run_args.inputs, datetime.now(timezone.utc))
        if stop.requested or wait_handle(args.stop_handle) or wait_handle(args.parent_handle):
            return await early_stop()
        session = LiveSession(run_id=uuid4().hex, tickers=inputs.tickers)
        task = asyncio.create_task(run_live(run_args, inputs, session,
            diagnostics, stop, publish_override=latest.publish,
            recovery_only=mode.recovery_only,
            recovery_restrictions=restrictions,
            restriction_journal=journal,
            explicit_retry=args.explicit_retry), name="supervised-kalshi-live")
        next_status = 0.0
        last_fence = (tuple(restrictions.holds), tuple(restrictions.cooldowns))
        while not task.done():
            now = time.monotonic()
            if wait_handle(args.parent_handle) or power.changed.is_set():
                stop.request()
            if wait_handle(args.stop_handle):
                operator_stop = True
                stop.request()
            message = await asyncio.to_thread(endpoint.receive, .05)
            if message is not None:
                accepted = control(message)
                if message.kind == MessageKind.PULSE and accepted:
                    pulse[0] = now
                elif message.kind == MessageKind.STOP_HINT:
                    operator_stop = True
                    stop.request()
            if now-pulse[0] > 6:
                stop.request()
            revision, status = latest.read()
            if revision > last_revision:
                progress_sequence += 1
                last_revision = revision
                evidence = status.get('recovery_restrictions', {})
                holds = tuple(evidence.get('component_holds', ()))
                cooldowns = tuple(FenceCooldown(item['name'], math.ceil(time.time()
                    + max(0., item['remaining_seconds'])))
                    for item in evidence.get('cooldowns', ()))
                current_fence = (holds, cooldowns)
                if current_fence != last_fence:
                    fence_revision += 1
                    await _publish_fence(args, endpoint, control, RecoveryFence(
                        args.parent_session, args.child_id, args.child_generation,
                        fence_revision, holds, cooldowns, False), control_sequence,
                        stop, pulse)
                    last_fence = current_fence
            if now >= next_status:
                phase, blockers = _status_projection(status, mode.recovery_only)
                status_sequence[0] += 1
                endpoint.publish_latest(_envelope(args, MessageKind.STATUS,
                    status_sequence[0], dict(phase=phase,
                    progress_sequence=progress_sequence,
                    work_remaining_ms=None, blockers=list(blockers))))
                next_status = now+2
            await asyncio.sleep(0)
        result = task.result()
        if result.get("state") != "STOPPED_FLAT":
            raise InvalidData("live child ended without verified flat result")
        revision, status = latest.read()
        evidence = {} if status is None else status.get('recovery_restrictions', {})
        holds = tuple(evidence.get('component_holds', ()))
        cooldowns = tuple(FenceCooldown(item['name'], math.ceil(time.time()
            + max(0., item['remaining_seconds'])))
            for item in evidence.get('cooldowns', ()))
        fence_revision += 1
        await _publish_fence(args, endpoint, control, RecoveryFence(
            args.parent_session, args.child_id, args.child_generation,
            fence_revision, holds, cooldowns, True), control_sequence, stop, pulse)
        await _send_result(args, endpoint, diagnostics, outcome="clean",
                           cleanup_complete=True, unresolved_work=False,
                           control_sequence=control_sequence)
        return 0
    except BaseException as exc:
        if task is not None and not task.done():
            stop.request()
            try:
                await task
            except BaseException:
                pass
        try:
            diagnostics.emit("supervisor_child_failed", error=exc,
                             operation=args.child_id)
        except BaseException:
            pass
        outcome = "unexpected_death" if ledger.exists() else "startup_refused"
        try:
            await _send_result(args, endpoint, diagnostics,
                outcome=outcome, cleanup_complete=outcome == "startup_refused",
                unresolved_work=outcome == "unexpected_death",
                control_sequence=control_sequence)
        except BaseException:
            pass
        return 27 if outcome == "unexpected_death" else 20
    finally:
        if session is not None:
            session.close()
        if lease_acquired:
            lease.__exit__(None, None, None)


if __name__ == "__main__":
    raise SystemExit(main())
