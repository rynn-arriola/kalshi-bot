"""Explicit operator controls for the production Windows supervisor."""
import argparse
import asyncio
import json
import os
import time
from uuid import UUID, uuid4

from .detached_host import spawn_host
from .live import DATA, ROOT
from .observability import safe_error
from .process_supervisor import SupervisorHost
from .startup import read_text_shared, save_result
from .supervision import SupervisorState
from .supervisor_control import (ControlOwner, ScopeSpec, SupervisorController, retain)
from .supervisor_launch import ProductionLaunchProfile
from .supervisor_store import SupervisorStore
from .values import InvalidData
from .windows import current_user_sid, role_present


CONTROL_ROOT = DATA / "supervisor"


def production_scope(*, create_root=False):
    if create_root:
        CONTROL_ROOT.mkdir(parents=True, exist_ok=True)
    return ScopeSpec("production", "kalshi-primary-account",
                     current_user_sid(), CONTROL_ROOT, "production")


async def _start(args):
    scope = production_scope(create_root=True)
    if not scope.store_path.exists():
        ControlOwner.initialize_production(scope)
    profile = ProductionLaunchProfile(args.initialize)
    host = SupervisorHost(scope, launch_profile=profile, arm_on_start=True)
    if getattr(args, "launch_id", None):
        task = asyncio.create_task(host.run())
        ready = asyncio.create_task(host.started.wait())
        try:
            await asyncio.wait((task, ready), return_when=asyncio.FIRST_COMPLETED)
            if task.done():
                await task
            else:
                save_result(_launch_path(args.launch_id), dict(state="HOST_STARTED",
                    pid=os.getpid(), parent_session=host.parent_session,
                    observed_at=time.time(), trading_ready=False))
                await task
        finally:
            ready.cancel()
            if not task.done():
                # Receipt failure/caller cancellation must not abandon the host.
                # SupervisorHost.run retains and gracefully joins its exact child.
                task.cancel()
            await retain(asyncio.gather(task, ready, return_exceptions=True))
    else:
        await host.run()
    _, state, native = SupervisorStore.read_only_snapshot(scope.store_path,
        scope_id=scope.scope_id, security_sid=scope.approved_user_sid)
    result = dict(state=state.state.value, control=state.to_dict(),
                  native_stage=native.stage, launch_attempted=True,
                  parent_session=host.parent_session)
    if host.last_error is not None:
        result["errors"] = host.last_error
    save_result(CONTROL_ROOT / "last-result.json", result)
    return result, (0 if state.state == SupervisorState.DISARMED else 2)


def _launch_path(launch_id):
    if str(UUID(launch_id)) != launch_id:
        raise InvalidData("invalid launch identity")
    return CONTROL_ROOT / "launches" / (launch_id + ".json")


def _read_object(path, limit):
    raw = read_text_shared(path, limit=limit)
    if len(raw) > limit:
        raise InvalidData("oversized saved status")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise InvalidData("saved status must be an object")
    return value


def _launch(args):
    """Return a correlated host receipt, never a trading-health assertion."""
    launch_id = str(uuid4())
    path = _launch_path(launch_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    command = ["-m", "kalshi_bot.supervised_live", "start", "--live",
               "--launch-id", launch_id]
    if args.initialize:
        command.append("--initialize")
    process = spawn_host(command, cwd=ROOT)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        code = process.poll()
        if code is not None:
            return dict(state="BLOCKED", launch_id=launch_id, pid=process.pid,
                exit_code=code, receipt=str(path), trading_ready=False), 2
        if path.is_file():
            try:
                result = _read_object(path, 65536)
            except (OSError, ValueError) as exc:
                return dict(state="UNKNOWN", launch_id=launch_id, pid=process.pid,
                    receipt=str(path), trading_ready=False, errors=safe_error(exc),
                    blocker="host_ack_unreadable_inspect_status_before_retry"), 2
            if result.get("state") == "HOST_STARTED" and result.get("pid") == process.pid:
                return dict(result, launch_id=launch_id, receipt=str(path)), 0
            return dict(state="BLOCKED", launch_id=launch_id, pid=process.pid,
                receipt=str(path), trading_ready=False), 2
        time.sleep(.05)
    # Do not kill or retry a possibly live host after an acknowledgement timeout.
    return dict(state="UNKNOWN", launch_id=launch_id, pid=process.pid,
        receipt=str(path), trading_ready=False,
        blocker="host_ack_timeout_inspect_status_before_retry"), 2


async def _stop():
    scope = production_scope()
    owner = ControlOwner(scope)
    try:
        receipt, signaled = await SupervisorController(scope, owner).stop()
        return dict(state=receipt.state.state.value,
                    stop_latched=receipt.state.stop_latched,
                    child_id=receipt.state.child_id,
                    native_signal_delivered=signaled,
                    semantics="pause entries, cancel owned entries, manage inventory to verified flat"), 0
    finally:
        await owner.close()


def _status():
    scope = production_scope()
    revision, state, native = SupervisorStore.read_only_snapshot(scope.store_path,
        scope_id=scope.scope_id, security_sid=scope.approved_user_sid)
    presence = {}
    errors = []
    for role in ("parent", "child"):
        try:
            presence[role] = role_present(scope.scope_id, role,
                                         user_sid=scope.approved_user_sid)
        except Exception as exc:
            presence[role] = None
            errors.extend(safe_error(exc))
    # Protected handles prove presence only, not health or account flatness.
    # In particular, never advertise saved HEALTHY as a current process state.
    if None in presence.values():
        observed = "UNKNOWN"
    elif not any(presence.values()):
        observed = "STOPPED"
    elif presence["parent"] and presence["child"]:
        observed = "RUNNING_UNVERIFIED"
    else:
        observed = "TRANSITION_OR_ORPHAN"
    result = dict(state=observed, observed_at=time.time(), presence=presence,
        account_flat_verified=False, errors=errors,
        revision=revision, control=state.to_dict(),
        native=dict(parent_session=native.parent_session, child_id=native.child_id,
            child_generation=native.child_generation, stage=native.stage,
            diagnostic_pid=native.diagnostic_pid),
        saved_snapshot_only=False, control_and_runtime_are_historical=True)
    runtime_path = DATA / "status.json"
    if runtime_path.is_file():
        try:
            result["last_runtime"] = _read_object(runtime_path, 1024*1024)
            result["last_runtime_file_age_seconds"] = max(0, time.time()-runtime_path.stat().st_mtime)
        except (OSError, ValueError):
            result["last_runtime"] = {"state": "UNREADABLE"}
    return result, (2 if observed == "UNKNOWN" else 0)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("launch", "start", "stop", "status"))
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--initialize", action="store_true")
    parser.add_argument("--launch-id", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    launch_path = None
    try:
        if args.launch_id:
            if args.command != "start":
                raise InvalidData("launch identity only valid for internal start")
            launch_path = _launch_path(args.launch_id)
        if args.command in ("start", "launch"):
            if not args.live:
                raise InvalidData("explicit --live required")
            result, code = (_launch(args) if args.command == "launch"
                            else asyncio.run(_start(args)))
        elif args.command == "stop":
            result, code = asyncio.run(_stop())
        else:
            result, code = _status()
    except (Exception, KeyboardInterrupt) as exc:
        result, code = dict(state="BLOCKED", errors=safe_error(exc)), 2
    if launch_path is not None:
        try:
            save_result(launch_path, dict(result, pid=os.getpid(),
                        observed_at=time.time(), trading_ready=False))
        except (OSError, ValueError) as exc:
            result, code = dict(state="BLOCKED", errors=safe_error(exc)), 2
    print(json.dumps(result, indent=2, default=str))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
