"""Command 1: explicit scoped cancel/flatten, wait for flat, then normal launch."""
import argparse
import asyncio
from datetime import datetime, timezone
import json
import time
from uuid import uuid4
from .emergency import create_request, flat_receipt
from .live import DATA
from .observability import safe_error
from .startup import save_result
from .supervised_live import _status, _stop, _launch, production_scope
from .values import InvalidData
from .windows import WindowsLease


def ready(status, *, previous_child, started, now):
    runtime = status.get('last_runtime') or {}
    native = status.get('native') or {}
    try:
        observed = datetime.fromisoformat(runtime['observed_at']).timestamp()
    except (KeyError, ValueError, TypeError):
        return False
    readers = (runtime.get('runtime') or {}).get('readers') or {}
    return (status.get('presence') == {'parent':True,'child':True}
        and native.get('child_id') not in (None, previous_child)
        and runtime.get('supervisor_child_id') == native['child_id']
        and runtime.get('pid') == native.get('diagnostic_pid')
        and started <= observed <= now and now-observed <= 5
        and runtime.get('state') == 'RUNNING' and runtime.get('recovery_only') is False
        and runtime.get('account_current') is True and runtime.get('risk_blockers') == []
        and runtime.get('accounting_blockers') == [] and len(readers) >= 3
        and all(value == 'subscribed' for value in readers.values())
        and ((runtime.get('runtime') or {}).get('logging') or {}).get('healthy') is True
        and (runtime.get('entry_allowed') is True or runtime.get('resting_entries', 0) > 0))


async def execute(args, *, status=_status, stop=_stop, launch=_launch,
                  scope_factory=production_scope, now=time.time,
                  sleep=asyncio.sleep, emit=None):
    operation = uuid4().hex
    last = None
    def report(stage, **details):
        value = dict(operation=operation, stage=stage, updated_at=now(), **details)
        if emit is not None:
            emit(value)
        return value
    def evidence(snapshot):
        runtime = snapshot.get('last_runtime') or {}
        return dict(resting_entries=runtime.get('resting_entries'),
            positions=runtime.get('positions'), account_current=runtime.get('account_current'),
            blockers=runtime.get('risk_blockers', [])+runtime.get('accounting_blockers', []),
            dispatch=((runtime.get('runtime') or {}).get('dispatch') or {}).get('last_outcome'))
    try:
        scope = scope_factory()
        first, code = await asyncio.to_thread(status)
        native = first.get('native') or {}
        child, pid = native.get('child_id'), native.get('diagnostic_pid')
        runtime = first.get('last_runtime') or {}
        if (code or first.get('presence') != {'parent':True,'child':True} or not child or not pid
                or runtime.get('supervisor_child_id') != child or runtime.get('pid') != pid
                or runtime.get('emergency_flatten_supported') is not True
                or first.get('last_runtime_file_age_seconds', float('inf')) > 5):
            return report('BLOCKED', reason='current_emergency_capable_owner_required'), 2
        started = now()
        await asyncio.to_thread(create_request, scope.control_root, scope_id=scope.scope_id,
            child_id=child, generation=native['child_generation'], operation=operation,
            now=started, timeout=args.timeout)
        receipt, code = await stop()
        if code or receipt.get('child_id') not in (None, child):
            return report('BLOCKED', reason='stop_owner_changed_or_unconfirmed'), 2
        report('CANCELING_AND_FLATTENING', child_id=child, pid=pid)
        while now()-started < args.timeout:
            last, code = await asyncio.to_thread(status)
            if code:
                return report('BLOCKED', reason='status_unavailable'), 2
            if flat_receipt(last, child_id=child, pid=pid, requested_at=started):
                break
            if (last.get('native') or {}).get('child_id') not in (None, child):
                return report('BLOCKED', reason='owner_changed_during_flatten_no_restart'), 2
            if last.get('presence') == {'parent':False,'child':False}:
                return report('BLOCKED', reason='owner_exited_without_correlated_flat_proof', **evidence(last)), 2
            await sleep(.5)
        else:
            return report('BLOCKED', reason='flatten_timeout_no_restart', **evidence(last)), 2
        report('FLAT_VERIFIED', child_id=child)
        launch_at = now()
        launched, code = await asyncio.to_thread(launch, args)
        if code:
            return report('BLOCKED', reason='launch_not_confirmed_inspect_before_retry', launch=launched), 2
        report('STARTING', launch=launched)
        while now()-launch_at < args.startup_timeout:
            last, code = await asyncio.to_thread(status)
            if not code and ready(last, previous_child=child, started=launch_at, now=now()):
                return report('COMPLETE', child_id=last['native']['child_id'], **evidence(last)), 0
            if code or last.get('presence') == {'parent':False,'child':False}:
                return report('BLOCKED', reason='new_owner_not_running', **evidence(last)), 2
            await sleep(1)
        return report('BLOCKED', reason='startup_readiness_timeout_inspect_running_owner', **evidence(last)), 2
    except (Exception, asyncio.CancelledError) as exc:
        report('INTERRUPTED' if isinstance(exc, asyncio.CancelledError) else 'BLOCKED',
            errors=safe_error(exc), reason='inspect_status_before_retry')
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--timeout', type=int, default=180)
    parser.add_argument('--startup-timeout', type=int, default=300)
    args = parser.parse_args(argv)
    args.initialize = False
    if not args.live or not 1 <= args.timeout <= 900 or not 1 <= args.startup_timeout <= 900:
        parser.error('explicit --live and bounded 1..900 second timeouts required')
    def emit(value):
        save_result(DATA/'supervisor'/'command1-status.json', value)
        print(json.dumps(value, default=str), flush=True)
    try:
        with WindowsLease('kalshi-primary-account-command1'):
            _, code = asyncio.run(execute(args, emit=emit))
            return code
    except (Exception, KeyboardInterrupt) as exc:
        print(json.dumps(dict(stage='BLOCKED',errors=safe_error(exc))))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
