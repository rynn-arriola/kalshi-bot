"""Single-writer durable local private-reader markers; not a venue replay log."""
from dataclasses import asdict, replace
from datetime import datetime
import json

from .continuity import PrivateEpoch
from .values import InvalidData, identity, integer, utc

MAX_EPOCHS = 4096


def _encoded(epoch):
    data = asdict(epoch)
    data['opened_at'] = epoch.opened_at.isoformat()
    data['closed_at'] = epoch.closed_at.isoformat() if epoch.closed_at else None
    return json.dumps(data, sort_keys=True, separators=(',', ':'))


def _decoded(payload):
    data = json.loads(payload)
    data['ack_channels'] = tuple(data['ack_channels'])
    data['opened_at'] = datetime.fromisoformat(data['opened_at'])
    if data['closed_at'] is not None:
        data['closed_at'] = datetime.fromisoformat(data['closed_at'])
    return PrivateEpoch(**data)


def open_epoch(ledger, epoch):
    if not isinstance(epoch, PrivateEpoch) or epoch.closed_at is not None:
        raise InvalidData('validated open private epoch required')
    with ledger.transaction():
        count = ledger.connection.execute('SELECT COUNT(*) FROM private_epochs').fetchone()[0]
        if count >= MAX_EPOCHS:
            raise InvalidData('private epoch capacity reached; explicit archival required')
        ledger.connection.execute('INSERT INTO private_epochs VALUES (?,?,?,?,?,?,?)',
            (epoch.epoch_id, epoch.subaccount, epoch.writer_epoch, epoch.generation,
             epoch.opened_at.isoformat(), None, _encoded(epoch)))
    return epoch


def close_epoch(ledger, epoch_id, *, writer_epoch, closed_at, ingress_count,
                durable_fill_count, terminal_reason, clean_local_delivery):
    identity(epoch_id)
    identity(writer_epoch)
    closed = utc(closed_at)
    integer(ingress_count, 0, 2**63-1)
    integer(durable_fill_count, 0, 2**63-1)
    with ledger.transaction():
        row = ledger.connection.execute('SELECT * FROM private_epochs WHERE id=?', (epoch_id,)).fetchone()
        if row is None:
            raise InvalidData('private epoch marker missing')
        prior = _decoded(row['payload'])
        if prior.writer_epoch != writer_epoch:
            raise InvalidData('private epoch writer changed')
        finished = replace(prior, closed_at=closed, ingress_count=ingress_count,
            durable_fill_count=durable_fill_count, terminal_reason=terminal_reason,
            clean_local_delivery=clean_local_delivery)
        if prior.closed_at is not None:
            if prior != finished:
                raise InvalidData('private epoch terminal conflict')
            return prior
        ledger.connection.execute('UPDATE private_epochs SET closed_at=?,payload=? WHERE id=?',
            (closed.isoformat(), _encoded(finished), epoch_id))
    return finished


def gap_count(ledger, *, subaccount, exclude_epoch_id=None):
    scope = integer(subaccount, 0, 63)
    if exclude_epoch_id is not None:
        identity(exclude_epoch_id)
    return ledger.connection.execute(
        "SELECT COUNT(*) FROM private_epochs WHERE subaccount=? AND "
        "(closed_at IS NULL OR json_extract(payload,'$.clean_local_delivery')=0) "
        "AND (? IS NULL OR id<>?)",
        (scope, exclude_epoch_id, exclude_epoch_id)).fetchone()[0]


def inspect_epochs(ledger, *, subaccount, limit):
    scope = integer(subaccount, 0, 63)
    limit = integer(limit, 1, 128)
    rows = ledger.connection.execute(
        'SELECT * FROM private_epochs WHERE subaccount=? ORDER BY rowid DESC LIMIT ?',
        (scope, limit)).fetchall()
    result = []
    for row in rows:
        epoch = _decoded(row['payload'])
        if (epoch.epoch_id, epoch.subaccount, epoch.writer_epoch, epoch.generation,
                epoch.opened_at.isoformat(),
                epoch.closed_at.isoformat() if epoch.closed_at else None) != tuple(row)[:6]:
            raise InvalidData('private epoch index conflicts with payload')
        result.append(epoch)
    return tuple(result)
