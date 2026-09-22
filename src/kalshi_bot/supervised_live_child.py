"""Fixed production child for the Windows native supervisor.

The parent owns process policy only. This child owns credentials, the live
lease, runtime resources, and verified-flat shutdown.
"""
import argparse
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
import time
from types import SimpleNamespace
from uuid import uuid4

import kalshi_bot
from .config import BotConfig
from .live import (DATA, IDENTITY, ROOT, LaunchInputs, refresh_candidate_inputs,
                   run as run_live)
from .live_session import LiveSession
from .observability import Diagnostics
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
            if message.kind != MessageKind.STOP_HINT and (
                    state.stop_latched or not state.desired_armed
                    or state.generation != args.child_generation
                    or state.child_id != args.child_id
                    or native.parent_session != args.parent_session
                    or native.child_id != args.child_id
                    or native.stage != "bound"
                    or wait_handle(args.stop_handle)
                    or wait_handle(args.parent_handle)):
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


async def _send_result(args, endpoint, diagnostics, *, outcome,
                       cleanup_complete, unresolved_work, retry_holds=()):
    diagnostics.emit("supervisor_child_stopped", operation=args.child_id)
    await asyncio.to_thread(diagnostics.close, 1)
    while diagnostics.status()["worker_alive"]:
        await asyncio.to_thread(diagnostics.close, 1)
    if diagnostics.status()["failure"] is not None:
        raise InvalidData("child diagnostic cleanup failed")
    receipt = endpoint.send_control(_envelope(args, MessageKind.RESULT, 2,
        dict(outcome=outcome, cleanup_complete=cleanup_complete,
             cleanup_failed=False, unresolved_work=unresolved_work,
             retry_holds=list(retry_holds))))
    await asyncio.wait_for(asyncio.wrap_future(receipt), 4)


async def _run_live(args, scope, endpoint, protocol, control, power, diagnostics):
    stop = _StopSignal(args, power)
    latest = _LatestStatus()
    status_sequence = progress_sequence = 0
    last_revision = 0
    last_pulse = time.monotonic()
    operator_stop = False

    # These checks happen before signer loading or network/runtime ownership.
    ledger = DATA / "account.db"
    try:
        mode = production_child_mode(initialize_approved=args.initialize_approved,
            ledger_exists=ledger.exists(), recovery_only=args.recovery_only)
    except InvalidData:
        await _send_result(args, endpoint, diagnostics, outcome="startup_refused",
                           cleanup_complete=True, unresolved_work=False)
        return 20
    initialize = mode.initialize

    run_args = SimpleNamespace(initialize=initialize,
        inputs=ROOT / "config" / "live-inputs.local.json",
        key_id_file=ROOT / "kalshi-bot.txt",
        private_key_file=ROOT / "Kalshi-Bot2.txt")
    session = None
    task = None
    try:
        BotConfig.load(ROOT / "config" / "bot.json")
        with WindowsLease(IDENTITY):
            if initialize:
                refresh = await refresh_candidate_inputs(
                    run_args.inputs, datetime.now(timezone.utc), diagnostics)
                diagnostics.emit("candidate_scope_prepared", **refresh)
            inputs = LaunchInputs.load(run_args.inputs, datetime.now(timezone.utc))
            session = LiveSession(run_id=uuid4().hex, tickers=inputs.tickers)
            task = asyncio.create_task(run_live(run_args, inputs, session,
                diagnostics, stop, publish_override=latest.publish,
                recovery_only=mode.recovery_only), name="supervised-kalshi-live")
            next_status = 0.0
            while not task.done():
                now = time.monotonic()
                if wait_handle(args.parent_handle) or power.changed.is_set():
                    stop.request()
                if wait_handle(args.stop_handle):
                    operator_stop = True
                    stop.request()
                message = await asyncio.to_thread(endpoint.receive, .05)
                if message is not None:
                    control(message)
                    if message.kind == MessageKind.PULSE:
                        last_pulse = now
                    elif message.kind == MessageKind.STOP_HINT:
                        operator_stop = True
                        stop.request()
                if now-last_pulse > 6:
                    stop.request()
                revision, status = latest.read()
                if now >= next_status:
                    if revision > last_revision:
                        progress_sequence += 1
                        last_revision = revision
                    blockers = [] if status is None else list(dict.fromkeys(
                        status.get("risk_blockers", [])
                        + status.get("accounting_blockers", [])))[:32]
                    if status is None:
                        phase = "starting"
                    elif mode.recovery_only or status.get("entries_paused"):
                        phase = "recovering"
                    elif blockers:
                        phase = "degraded"
                    else:
                        phase = "healthy"
                    status_sequence += 1
                    endpoint.publish_latest(_envelope(args, MessageKind.STATUS,
                        status_sequence, dict(phase=phase,
                        progress_sequence=progress_sequence,
                        work_remaining_ms=None, blockers=blockers)))
                    next_status = now+2
                await asyncio.sleep(0)
            result = task.result()
        if result.get("state") != "STOPPED_FLAT":
            raise InvalidData("live child ended without verified flat result")
        await _send_result(args, endpoint, diagnostics, outcome="clean",
                           cleanup_complete=True, unresolved_work=False)
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
                unresolved_work=outcome == "unexpected_death")
        except BaseException:
            pass
        return 27 if outcome == "unexpected_death" else 20
    finally:
        if session is not None:
            session.close()


if __name__ == "__main__":
    raise SystemExit(main())
