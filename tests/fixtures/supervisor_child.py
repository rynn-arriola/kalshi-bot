"""Fixed inert S2A child. It has no credential, network, account or order code."""
import argparse
import os
from pathlib import Path
import time

import kalshi_bot
from kalshi_bot.supervisor_control import ScopeSpec
from kalshi_bot.supervisor_fixture import build_fingerprint, config_fingerprint, source_path
from kalshi_bot.supervisor_protocol import (Envelope, MessageKind, PARENT_KINDS,
                                            ParentProtocol)
from kalshi_bot.observability import Diagnostics
from kalshi_bot.supervisor_store import SupervisorStore
from kalshi_bot.values import InvalidData
from kalshi_bot.windows import (WindowsControlMutex, current_user_sid,
                                WindowsPowerMonitor, process_id_from_handle, wait_handle)
from kalshi_bot.windows_ipc import connect_pipe


_LIFETIME_HANDLE = None  # Intentionally OS-owned until process termination.


def envelope(args, kind, sequence, payload):
    return Envelope(args.scope_digest, args.parent_session, args.child_id,
        args.child_generation, kind, sequence, time.monotonic_ns(), payload)


def main(argv=None):
    parser = argparse.ArgumentParser(add_help=False)
    for name in ("pipe_name", "scope_digest", "scope_id", "parent_session",
                 "child_id", "store_path", "control_root", "environment",
                 "account_scope", "approved_user_sid", "source_path", "mode"):
        parser.add_argument("--"+name.replace("_", "-"), required=True)
    parser.add_argument("--child-generation", required=True, type=int)
    parser.add_argument("--lifetime-handle", required=True, type=int)
    parser.add_argument("--stop-handle", required=True, type=int)
    parser.add_argument("--parent-handle", required=True, type=int)
    args = parser.parse_args(argv)

    global _LIFETIME_HANDLE
    _LIFETIME_HANDLE = args.lifetime_handle
    if current_user_sid() != args.approved_user_sid:
        return 20
    if Path(kalshi_bot.__file__).resolve() != Path(args.source_path).resolve():
        return 21
    if source_path() != Path(args.source_path).resolve():
        return 22
    scope = ScopeSpec(args.environment, args.account_scope,
                      args.approved_user_sid, Path(args.control_root))
    if scope.scope_id != args.scope_id or scope.digest != args.scope_digest:
        return 23
    diagnostics = Diagnostics(scope.control_root / "child-logs",
                              max_bytes=262144, backups=2)
    endpoint = None
    with WindowsPowerMonitor() as power:
        try:
            diagnostics.start()
            diagnostics.emit("supervisor_child_started", operation=args.child_id,
                             generation=args.child_generation)
            parent_pid = process_id_from_handle(args.parent_handle)
            if wait_handle(args.parent_handle) or power.changed.is_set():
                return 28
            endpoint = connect_pipe(args.pipe_name, expected_server_pid=parent_pid)
            return run_child(args, scope, endpoint, power, diagnostics)
        except BaseException as exc:
            diagnostics.emit("supervisor_child_failed", error=exc, operation=args.child_id)
            raise
        finally:
            if endpoint is not None:
                while not endpoint.closed:
                    endpoint.close_and_join()
            diagnostics.close()
            while diagnostics.status()["worker_alive"]:
                diagnostics.close()


def run_child(args, scope, endpoint, power, diagnostics):
    def guard():
        diagnostics.ensure_healthy()
        if power.changed.is_set():
            raise InvalidData("child power state invalidated")

    def control(message):
        guard()
        # Read under the same control mutex; no authority comes from a pulse alone.
        with WindowsControlMutex(scope.scope_id,
                user_sid=scope.approved_user_sid) as mutex:
            if mutex.abandoned:
                raise InvalidData("child control mutex abandoned")
            revision, state, native = SupervisorStore.read_only_snapshot(
                args.store_path, scope_id=scope.scope_id,
                security_sid=scope.approved_user_sid)
            guard()
            protocol.accept(message, now_ns=time.monotonic_ns(),
                            current_revision=revision)
            if message.kind != MessageKind.STOP_HINT and (
                    state.stop_latched or not state.desired_armed
                    or state.generation != args.child_generation
                    or state.child_id != args.child_id
                    or state.child_generation != args.child_generation
                    or native.parent_session != args.parent_session
                    or native.child_id != args.child_id
                    or native.child_generation != args.child_generation
                    or native.stage != "bound"
                    or wait_handle(args.stop_handle)
                    or wait_handle(args.parent_handle)):
                raise InvalidData("child admission revoked")

    def result(outcome):
        # Cleanup evidence is published only after the bounded diagnostic owner joins.
        diagnostics.emit("supervisor_child_stopped", operation=args.child_id)
        diagnostics.close()
        while diagnostics.status()["worker_alive"]:
            diagnostics.close()
        if diagnostics.status()["failure"] is not None:
            raise InvalidData("child diagnostic cleanup failed")
        receipt = endpoint.send_control(envelope(args, MessageKind.RESULT, 2,
            dict(outcome=outcome, cleanup_complete=True, cleanup_failed=False,
                 unresolved_work=False, retry_holds=[])))
        receipt.result(timeout=4)

    guard()
    control_sequence = 1
    status_sequence = 0
    endpoint.send_control(envelope(args, MessageKind.HELLO, control_sequence,
        dict(build_fingerprint=build_fingerprint(),
             config_fingerprint=config_fingerprint(args.mode),
             fixture_mode=args.mode)))
    protocol = ParentProtocol(args.scope_digest, args.parent_session,
                              args.child_id, args.child_generation)
    admitted = False
    last_pulse = time.monotonic()
    try:
        deadline = time.monotonic()+10
        while not admitted:
            guard()
            if wait_handle(args.stop_handle) or wait_handle(args.parent_handle):
                return 24
            message = endpoint.receive(timeout=.1)
            guard()
            if message is None:
                if time.monotonic() >= deadline:
                    return 25
                continue
            control(message)
            if message.kind == MessageKind.STOP_HINT:
                return 24
            if message.kind != MessageKind.ADMIT:
                raise InvalidData("child expected admission")
            guard()
            admitted = True

        if args.mode == "crash_after_admit":
            os._exit(7)
        if args.mode == "hang_after_admit":
            guard()
            status_sequence += 1
            endpoint.publish_latest(envelope(args, MessageKind.STATUS,
                status_sequence, dict(phase="healthy",
                progress_sequence=status_sequence, work_remaining_ms=None,
                blockers=[])))
            while True:
                time.sleep(60)

        next_status = 0.0
        while True:
            guard()
            now = time.monotonic()
            if wait_handle(args.parent_handle):
                return 28
            if wait_handle(args.stop_handle):
                result("clean")
                return 0
            message = endpoint.receive(timeout=.05)
            guard()
            if message is not None:
                control(message)
                if message.kind == MessageKind.PULSE:
                    last_pulse = now
                elif message.kind == MessageKind.STOP_HINT:
                    result("clean")
                    return 0
            if now-last_pulse > 6:
                return 29
            if now >= next_status:
                guard()
                status_sequence += 1
                endpoint.publish_latest(envelope(args, MessageKind.STATUS,
                    status_sequence, dict(phase="healthy",
                    progress_sequence=status_sequence, work_remaining_ms=None,
                    blockers=[])))
                next_status = now+2
                if args.mode == "exit_after_status":
                    result("transient_failure")
                    return 5
    finally:
        pass  # main retains transport, diagnostics, power and inherited lifetime.


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except InvalidData:
        raise SystemExit(30)
