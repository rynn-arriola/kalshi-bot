"""Fixed inert S2A child. It has no credential, network, account or order code."""
import argparse
import os
from pathlib import Path
import time

import kalshi_bot
from kalshi_bot.supervisor_control import ScopeSpec
from kalshi_bot.supervisor_fixture import build_fingerprint, config_fingerprint, source_path
from kalshi_bot.supervisor_protocol import (Envelope, MessageKind, PARENT_KINDS,
                                            SequenceTracker)
from kalshi_bot.supervisor_store import SupervisorStore
from kalshi_bot.values import InvalidData
from kalshi_bot.windows import (WindowsControlMutex, current_user_sid,
                                process_id_from_handle, wait_handle)
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
    parent_pid = process_id_from_handle(args.parent_handle)
    endpoint = connect_pipe(args.pipe_name, expected_server_pid=parent_pid)
    control_sequence = 1
    status_sequence = 0
    endpoint.send_control(envelope(args, MessageKind.HELLO, control_sequence,
        dict(build_fingerprint=build_fingerprint(),
             config_fingerprint=config_fingerprint(args.mode),
             fixture_mode=args.mode)))
    tracker = SequenceTracker()
    admitted = False
    last_pulse = time.monotonic()
    try:
        deadline = time.monotonic()+10
        while not admitted:
            if wait_handle(args.stop_handle) or wait_handle(args.parent_handle):
                return 24
            message = endpoint.receive(timeout=.1)
            if message is None:
                if time.monotonic() >= deadline:
                    return 25
                continue
            if message.kind not in PARENT_KINDS:
                raise InvalidData("child received invalid message direction")
            tracker.accept(message)
            if message.kind == MessageKind.PULSE:
                last_pulse = time.monotonic()
                continue
            if message.kind == MessageKind.STOP_HINT:
                return 24
            if message.kind != MessageKind.ADMIT:
                raise InvalidData("child expected admission")
            with WindowsControlMutex(scope.scope_id,
                    user_sid=scope.approved_user_sid) as mutex:
                if mutex.abandoned:
                    return 26
                revision, state, native = SupervisorStore.read_only_snapshot(
                    args.store_path, scope_id=scope.scope_id)
                if (revision != message.payload["control_revision"]
                        or state.stop_latched or not state.desired_armed
                        or state.child_id != args.child_id
                        or state.child_generation != args.child_generation
                        or native.parent_session != args.parent_session
                        or native.child_id != args.child_id
                        or native.stage != "bound"):
                    return 27
                if wait_handle(args.stop_handle):
                    return 24
            admitted = True

        if args.mode == "crash_after_admit":
            os._exit(7)
        if args.mode == "hang_after_admit":
            status_sequence += 1
            endpoint.publish_latest(envelope(args, MessageKind.STATUS,
                status_sequence, dict(phase="healthy",
                progress_sequence=status_sequence, work_remaining_ms=None,
                blockers=[])))
            while True:
                time.sleep(60)

        next_status = 0.0
        while True:
            now = time.monotonic()
            if wait_handle(args.parent_handle):
                return 28
            if wait_handle(args.stop_handle):
                control_sequence += 1
                endpoint.send_control(envelope(args, MessageKind.RESULT,
                    control_sequence, dict(outcome="clean", cleanup_complete=True,
                    cleanup_failed=False, unresolved_work=False, retry_holds=[])))
                return 0
            message = endpoint.receive(timeout=.05)
            if message is not None:
                if message.kind not in PARENT_KINDS:
                    raise InvalidData("child received invalid message direction")
                tracker.accept(message)
                if message.kind == MessageKind.PULSE:
                    last_pulse = now
                elif message.kind == MessageKind.STOP_HINT:
                    control_sequence += 1
                    endpoint.send_control(envelope(args, MessageKind.RESULT,
                        control_sequence, dict(outcome="clean", cleanup_complete=True,
                        cleanup_failed=False, unresolved_work=False, retry_holds=[])))
                    return 0
            if now-last_pulse > 6:
                return 29
            if now >= next_status:
                status_sequence += 1
                endpoint.publish_latest(envelope(args, MessageKind.STATUS,
                    status_sequence, dict(phase="healthy",
                    progress_sequence=status_sequence, work_remaining_ms=None,
                    blockers=[])))
                next_status = now+2
                if args.mode == "exit_after_status":
                    control_sequence += 1
                    endpoint.send_control(envelope(args, MessageKind.RESULT,
                        control_sequence, dict(outcome="transient_failure",
                        cleanup_complete=True, cleanup_failed=False,
                        unresolved_work=False, retry_holds=[])))
                    return 5
    finally:
        endpoint.close_and_join()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except InvalidData:
        raise SystemExit(30)
