"""Explicit, bounded, generation-scoped emergency request; no venue I/O."""
import json
import math
from pathlib import Path
from .startup import read_text_shared, save_result
from .values import InvalidData, identity, integer


def request_path(root):
    return Path(root) / 'flatten-request.json'


def create_request(root, *, scope_id, child_id, generation, operation, now, timeout):
    identity(scope_id); identity(child_id); identity(operation)
    integer(generation, 1, 2**63-1)
    if not 1 <= timeout <= 900 or not math.isfinite(now) or now <= 0:
        raise InvalidData('invalid emergency request lifetime')
    value = dict(version=1, scope_id=scope_id, child_id=child_id,
        generation=generation, operation=operation, created_at=now, expires_at=now+timeout)
    save_result(request_path(root), value)
    return value


def requested(root, *, scope_id, child_id, generation, now):
    path = request_path(root)
    if not path.exists():
        return False
    value = json.loads(read_text_shared(path, limit=4096))
    fields = {'version','scope_id','child_id','generation','operation','created_at','expires_at'}
    if not isinstance(value, dict) or set(value) != fields or value['version'] != 1:
        raise InvalidData('invalid emergency request')
    for key in ('scope_id','child_id','operation'):
        identity(value[key])
    integer(value['generation'], 1, 2**63-1)
    start, end = value['created_at'], value['expires_at']
    if (type(start) not in (int,float) or type(end) not in (int,float)
            or not math.isfinite(start) or not math.isfinite(end) or not 0 < end-start <= 900):
        raise InvalidData('invalid emergency request clock')
    return ((value['scope_id'],value['child_id'],value['generation']) ==
            (scope_id,child_id,generation) and start <= now < end)


def flat_receipt(status, *, child_id, pid, requested_at):
    """Require terminal cleanup from the requested child, not a saved old run."""
    runtime = status.get('last_runtime') or {}
    from datetime import datetime
    try:
        observed = datetime.fromisoformat(runtime['observed_at']).timestamp()
    except (KeyError, TypeError, ValueError):
        return False
    return (status.get('presence') == {'parent':False,'child':False}
        and runtime.get('supervisor_child_id') == child_id and runtime.get('pid') == pid
        and observed >= requested_at and runtime.get('state') == 'STOPPED_FLAT'
        and runtime.get('account_current') is True and runtime.get('positions') == {}
        and runtime.get('resting_entries') == 0 and runtime.get('risk_blockers') == []
        and runtime.get('accounting_blockers') == [])
