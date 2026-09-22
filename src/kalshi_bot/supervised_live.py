"""Foreground operator controls for the production Windows supervisor."""
import argparse
import asyncio
import json

from .live import DATA
from .observability import safe_error
from .process_supervisor import SupervisorHost
from .startup import save_result
from .supervision import SupervisorState
from .supervisor_control import (ControlOwner, ScopeSpec, SupervisorController)
from .supervisor_launch import ProductionLaunchProfile
from .supervisor_store import SupervisorStore
from .values import InvalidData
from .windows import current_user_sid


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
    result = dict(revision=revision, control=state.to_dict(),
        native=dict(parent_session=native.parent_session, child_id=native.child_id,
            child_generation=native.child_generation, stage=native.stage,
            diagnostic_pid=native.diagnostic_pid), saved_snapshot_only=True)
    runtime_path = DATA / "status.json"
    if runtime_path.is_file():
        try:
            result["last_runtime"] = json.loads(runtime_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            result["last_runtime"] = {"state": "UNREADABLE"}
    return result, 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("start", "stop", "status"))
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--initialize", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "start":
            if not args.live:
                raise InvalidData("explicit --live required")
            result, code = asyncio.run(_start(args))
        elif args.command == "stop":
            result, code = asyncio.run(_stop())
        else:
            result, code = _status()
    except (Exception, KeyboardInterrupt) as exc:
        result, code = dict(state="BLOCKED", errors=safe_error(exc)), 2
    print(json.dumps(result, indent=2, default=str))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
