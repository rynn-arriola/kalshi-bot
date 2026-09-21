"""Writer-owned accounting evidence and entry restrictions. No P&L invention.

An opening checkpoint starts as a candidate. D-068's separate operational
release never asserts global venue proof; a review acknowledgement cannot
clear economic restrictions or approve the actual opening boundary.
"""
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json

from .opening_account import OpeningAccountEvidence, assess_opening_accounting
from .values import InvalidData, identity, utc


MAX_ROWS = 65536
MAX_BYTES = 64 * 1024 * 1024
MAX_PAYLOAD = 1024 * 1024
HOLD_CODES = frozenset({
    'opening_proof_unresolved', 'opening_source_stale', 'opening_local_state_changed',
    'opening_ledger_not_empty', 'opening_boundary_changed', 'account_scope_conflict',
    'settlement_reconciliation_required', 'settlement_economics_conflict',
    'cash_activity_unattributed', 'cash_observation_changed', 'cash_clock_regressed',
    'cash_snapshot_disagrees', 'accounting_journal_full', 'accounting_review_required',
    'fill_boundary_unproven', 'accounting_source_failed', 'accounting_economics_failed',
})


def _default(value):
    if isinstance(value, Decimal):
        # Fixed-point canonicalization without Decimal context rounding.
        text = format(value, 'f')
        return '0' if value == 0 else text.rstrip('0').rstrip('.') if '.' in text else text
    if isinstance(value, datetime):
        return utc(value).isoformat()
    if is_dataclass(value):
        return {field.name: getattr(value, field.name) for field in fields(value)}
    raise InvalidData('unsupported accounting evidence type')


def encode(value):
    result = json.dumps(value, default=_default, sort_keys=True,
                        separators=(',', ':'), allow_nan=False)
    if len(result.encode()) > MAX_PAYLOAD:
        raise InvalidData('accounting payload exceeds bound')
    return result


def digest(value):
    return sha256(value.encode()).hexdigest()


@dataclass(frozen=True)
class AccountingStatus:
    checkpoint_digest: str | None
    proposed_boundary: datetime | None
    observed_cash: Decimal | None
    cash_observed_at: datetime | None
    event_count: int
    payload_bytes: int
    holds: tuple[str, ...]
    blockers: tuple[str, ...]
    ready_for_entry: bool = False


@dataclass(frozen=True)
class AccountingReceipt:
    writer_epoch: str
    writer_revision: int
    captured_digest: str
    checkpoint_created: bool
    status: AccountingStatus


def _hold(ledger, code, evidence_digest, at):
    if code not in HOLD_CODES:
        raise InvalidData('unknown accounting restriction')
    ledger.connection.execute('INSERT OR IGNORE INTO accounting_holds VALUES (?,?,?)',
                              (code, evidence_digest, utc(at).isoformat()))


def _append(ledger, kind, key, payload, at):
    """Capacity failure commits a restriction; it must not roll back the pause."""
    fingerprint = digest(encode([kind, key, payload]))
    conn = ledger.connection
    if conn.execute('SELECT 1 FROM accounting_events WHERE digest=?', (fingerprint,)).fetchone():
        return fingerprint, False
    size = len(payload.encode())
    row = conn.execute('SELECT rows,bytes FROM accounting_state WHERE id=1').fetchone()
    if row is None:
        raise InvalidData('accounting counters missing')
    if row[0] >= MAX_ROWS or row[1] + size > MAX_BYTES:
        _hold(ledger, 'accounting_journal_full', fingerprint, at)
        return fingerprint, False
    if kind == 'settlement' and conn.execute(
            'SELECT 1 FROM accounting_events WHERE kind=? AND event_key=? LIMIT 1',
            (kind, key)).fetchone():
        _hold(ledger, 'settlement_economics_conflict', fingerprint, at)
    conn.execute('INSERT INTO accounting_events VALUES (?,?,?,?,?)',
                 (fingerprint, kind, key, payload, utc(at).isoformat()))
    conn.execute('UPDATE accounting_state SET rows=rows+1,bytes=bytes+? WHERE id=1', (size,))
    return fingerprint, True


def validate_accounting(ledger):
    """Cold startup audit only; entry checks never scan journal history."""
    conn = ledger.connection
    counter = conn.execute('SELECT rows,bytes FROM accounting_state WHERE id=1').fetchone()
    actual = conn.execute('SELECT COUNT(*),COALESCE(SUM(length(CAST(payload AS BLOB))),0) '
                          'FROM accounting_events').fetchone()
    if (counter is None or tuple(counter) != tuple(actual)
            or not 0 <= actual[0] <= MAX_ROWS or not 0 <= actual[1] <= MAX_BYTES):
        raise InvalidData('accounting journal counters or capacity invalid')
    holds = conn.execute('SELECT code FROM accounting_holds LIMIT 32').fetchall()
    if any(row[0] not in HOLD_CODES for row in holds) or len(holds) > len(HOLD_CODES):
        raise InvalidData('accounting restrictions invalid')
    opening = conn.execute('SELECT * FROM opening_checkpoint WHERE id=1').fetchone()
    if opening is not None:
        if digest(opening['payload']) != opening['digest']:
            raise InvalidData('opening checkpoint digest invalid')
        source = json.loads(opening['payload'])
        owner = conn.execute("SELECT value FROM meta WHERE key='ledger_id'").fetchone()[0]
        if (source['ledger_id'] != owner or source['boundary'] != opening['boundary']
                or source['subaccount'] != opening['subaccount']):
            raise InvalidData('opening checkpoint identity invalid')
    released = conn.execute("SELECT 1 FROM accounting_events WHERE kind='operational_release' LIMIT 1").fetchone()
    if (actual[0] or opening is not None) and not holds and not released:
        raise InvalidData('accounting evidence lost its entry restrictions')
    for row in conn.execute('SELECT digest,kind,event_key,payload FROM accounting_events'):
        if digest(encode([row['kind'], row['event_key'], row['payload']])) != row['digest']:
            raise InvalidData('accounting observation digest invalid')


def entry_blockers(ledger, *, require_checkpoint=False):
    holds = tuple(row[0] for row in ledger.connection.execute(
        'SELECT code FROM accounting_holds ORDER BY code LIMIT 32'))
    if any(code not in HOLD_CODES for code in holds):
        raise InvalidData('accounting restrictions invalid')
    if require_checkpoint and ledger.connection.execute(
            'SELECT 1 FROM opening_checkpoint WHERE id=1').fetchone() is None:
        return holds + ('opening_checkpoint_missing',)
    if not holds and ledger.connection.execute('SELECT 1 FROM accounting_baseline WHERE id=1').fetchone():
        return ('accounting_lease_required',)
    return holds


def inspect(ledger):
    conn = ledger.connection
    opening = conn.execute('SELECT * FROM opening_checkpoint WHERE id=1').fetchone()
    counter = conn.execute('SELECT rows,bytes FROM accounting_state WHERE id=1').fetchone()
    cash = conn.execute("SELECT payload,first_seen_at FROM accounting_events "
                        "WHERE kind='cash' ORDER BY rowid DESC LIMIT 1").fetchone()
    holds = entry_blockers(ledger)
    blockers = list(holds)
    if not conn.execute('SELECT 1 FROM accounting_baseline WHERE id=1').fetchone():
        blockers.append('operator_boundary_not_approved')
    blockers.extend(('venue_history_stream_handoff_unproven', 'cash_snapshot_not_atomic',
                     'cash_hold_semantics_unverified',
                     'live_activation_not_authorized'))
    if opening is None:
        blockers.append('opening_checkpoint_missing')
    return AccountingStatus(opening['digest'] if opening else None,
        datetime.fromisoformat(opening['boundary']) if opening else None,
        Decimal(json.loads(cash['payload'])['available']) if cash else None,
        datetime.fromisoformat(cash['first_seen_at']) if cash else None,
        counter['rows'], counter['bytes'], holds, tuple(dict.fromkeys(blockers)))


def capture(ledger, evidence, report, *, writer_epoch, writer_revision,
            post_revision, capacity, source_current=True):
    """Atomically retain positive evidence even when its former authority expired."""
    if not isinstance(evidence, OpeningAccountEvidence) or type(source_current) is not bool:
        raise InvalidData('typed opening evidence required')
    assessment = assess_opening_accounting(evidence, report)
    at = evidence.observed_at
    source = dict(ledger_id=ledger.connection.execute(
        "SELECT value FROM meta WHERE key='ledger_id'").fetchone()[0],
        boundary=evidence.proposed_boundary, subaccount=evidence.subaccount,
        writer_epoch=evidence.writer_epoch, writer_revision=evidence.writer_revision,
        observed_at=at, snapshot_observed_at=evidence.snapshot_observed_at,
        cash=evidence.cash, snapshot=report.snapshot, audit=report.audit,
        sources=evidence.sources, blockers=evidence.blockers)
    # Bind every normalized observation without retaining a second large array.
    observations_hash = sha256()
    for rows in ((evidence.cash,), evidence.settlements, evidence.subaccount_transfers,
                 evidence.intra_exchange_transfers, evidence.funding):
        observations_hash.update(str(len(rows)).encode() + b':')
        for row in rows:
            observations_hash.update(digest(encode(row)).encode())
    source['observations_digest'] = observations_hash.hexdigest()
    payload = encode(source)
    fingerprint = digest(payload)
    created = False
    conn = ledger.connection
    with ledger.transaction():
        # Only the D-068 operational protocol may clear transient restrictions.
        _hold(ledger, 'opening_proof_unresolved', fingerprint, at)
        _append(ledger, 'inspection', fingerprint, payload, at)
        opening = conn.execute('SELECT * FROM opening_checkpoint WHERE id=1').fetchone()
        fresh = source_current and (evidence.writer_epoch, evidence.writer_revision) == (
            writer_epoch, writer_revision)
        if not fresh:
            _hold(ledger, 'opening_source_stale', fingerprint, at)
        if evidence.subaccount != 0:
            _hold(ledger, 'account_scope_conflict', fingerprint, at)
        if opening is not None and (opening['boundary'], opening['subaccount']) != (
                evidence.proposed_boundary.isoformat(), evidence.subaccount):
            _hold(ledger, 'opening_boundary_changed', fingerprint, at)
        if not assessment.cash_snapshot_agrees:
            _hold(ledger, 'cash_snapshot_disagrees', fingerprint, at)
        eligible_candidate = False
        if opening is None and fresh and evidence.subaccount == 0:
            from .verification import audit_snapshot
            audit = audit_snapshot(ledger, report.snapshot, epoch=writer_epoch,
                                   revision=writer_revision, capacity=capacity)
            virgin = not any(conn.execute(f'SELECT 1 FROM {table} LIMIT 1').fetchone()
                             for table in ('fills', 'lots', 'intents', 'realized_events',
                                           'mutation_attempts'))
            if not virgin:
                _hold(ledger, 'opening_ledger_not_empty', fingerprint, at)
            if not audit.consistent or not assessment.local_flat_candidate:
                _hold(ledger, 'opening_local_state_changed', fingerprint, at)
            if (virgin and audit.consistent and assessment.local_flat_candidate
                    and assessment.cash_snapshot_agrees):
                eligible_candidate = True
        last_cash = conn.execute("SELECT payload,first_seen_at FROM accounting_events WHERE kind='cash' "
                                 "ORDER BY rowid DESC LIMIT 1").fetchone()
        cash_kind = 'cash' if evidence.subaccount == 0 else 'cash_unscoped'
        if last_cash:
            previous = json.loads(last_cash[0])
            if (evidence.cash.updated_ts < previous['updated_ts']
                    or at < datetime.fromisoformat(last_cash[1])):
                _hold(ledger, 'cash_clock_regressed', fingerprint, at)
                cash_kind = 'cash_stale'
            if Decimal(previous['available']) != evidence.cash.available:
                _hold(ledger, 'cash_observation_changed', fingerprint, at)
        _append(ledger, cash_kind, encode([evidence.subaccount, at]), encode(evidence.cash), at)
        if evidence.settlements:
            _hold(ledger, 'settlement_reconciliation_required', fingerprint, at)
        for row in evidence.settlements:
            # Composite identity is local; changed versions remain evidence.
            _append(ledger, 'settlement', encode([evidence.subaccount, *row.key]), encode(row), at)
        for kind, rows in (('subaccount_transfer', evidence.subaccount_transfers),
                           ('intra_exchange_transfer', evidence.intra_exchange_transfers),
                           ('funding', evidence.funding)):
            if rows:
                _hold(ledger, 'cash_activity_unattributed', fingerprint, at)
            for row in rows:
                key = ([row.kind, row.record_id] if kind == 'funding' else [row.transfer_id])
                _append(ledger, kind, encode(key), encode(row), at)
        if eligible_candidate and cash_kind == 'cash' and not conn.execute(
                "SELECT 1 FROM accounting_holds WHERE code='accounting_journal_full'").fetchone():
            conn.execute('INSERT INTO opening_checkpoint VALUES (1,?,?,?,?,?)',
                (fingerprint, payload, evidence.proposed_boundary.isoformat(),
                 evidence.subaccount, at.isoformat()))
            created = True
        result = inspect(ledger)
    return AccountingReceipt(writer_epoch, post_revision, fingerprint, created, result)


def record_review(ledger, *, reference, checkpoint_digest, now):
    """Record operator review without claiming unresolved economics were repaired."""
    identity(reference)
    status = inspect(ledger)
    if checkpoint_digest != status.checkpoint_digest or checkpoint_digest is None:
        raise InvalidData('review requires exact opening checkpoint')
    payload = encode(dict(reference=reference, checkpoint_digest=checkpoint_digest,
                          event_count=status.event_count, holds=status.holds, at=utc(now)))
    with ledger.transaction():
        _hold(ledger, 'accounting_review_required', digest(payload), now)
        _append(ledger, 'review', reference, payload, now)
    return inspect(ledger)


def quarantine_fill(ledger, fill, received_at):
    """Unattributed boundary-crossing fills stay durable outside matched P&L."""
    row = ledger.connection.execute('SELECT boundary FROM opening_checkpoint WHERE id=1').fetchone()
    if row is None:
        return False  # Existing isolated component fixtures have no opening candidate.
    boundary = datetime.fromisoformat(row[0])
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    delta = boundary-epoch
    boundary_us = (delta.days*86400 + delta.seconds)*1000000 + delta.microseconds
    if fill.executed_us is not None and fill.executed_us >= boundary_us:
        return False
    payload = encode(fill)
    _hold(ledger, 'fill_boundary_unproven', digest(payload), received_at)
    _append(ledger, 'unattributed_fill', fill.key, payload, received_at)
    return True


def record_failure(ledger, command):
    """A failed reconciliation cannot silently regain entry permission on restart."""
    at = datetime.now(timezone.utc)
    with ledger.transaction():
        _hold(ledger, 'accounting_source_failed', digest(command), at)
        if command in {'fill', 'apply_pending', 'recover_fills', 'order', 'order_batch'}:
            _hold(ledger, 'accounting_economics_failed', digest(command), at)
