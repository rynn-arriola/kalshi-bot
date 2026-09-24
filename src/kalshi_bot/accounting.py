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
import zlib

from .opening_account import OpeningAccountEvidence, assess_opening_accounting
from .values import InvalidData, identity, utc


MAX_ROWS = 65536
MAX_BYTES = 64 * 1024 * 1024
MAX_PAYLOAD = 1024 * 1024
ARCHIVE_TRIGGER_ROWS = 49152
ARCHIVE_TRIGGER_BYTES = 48 * 1024 * 1024
ARCHIVE_BATCH_ROWS = 2048
ARCHIVE_RETAIN_PER_KIND = 64
MAX_ARCHIVES = 64
MAX_ARCHIVE_BYTES = 32 * 1024 * 1024
MAX_ARCHIVE_COMPRESSED_BYTES = 16 * 1024 * 1024
ARCHIVABLE_KINDS = ('inspection', 'cash', 'operational_release')
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
    if (conn.execute('SELECT 1 FROM accounting_events WHERE digest=?', (fingerprint,)).fetchone()
            or conn.execute('SELECT 1 FROM accounting_event_archive_members WHERE digest=?',
                            (fingerprint,)).fetchone()):
        return fingerprint, False
    size = len(payload.encode())
    row = conn.execute('SELECT rows,bytes FROM accounting_state WHERE id=1').fetchone()
    if row is None:
        raise InvalidData('accounting counters missing')
    archived = False
    if conn.execute('SELECT 1 FROM accounting_baseline WHERE id=1').fetchone():
        while (row[0] >= ARCHIVE_TRIGGER_ROWS
                or row[1] + size > ARCHIVE_TRIGGER_BYTES):
            if not _archive_superseded(ledger):
                break
            archived = True
            row = conn.execute('SELECT rows,bytes FROM accounting_state WHERE id=1').fetchone()
        if archived and row[0] < MAX_ROWS and row[1] + size <= MAX_BYTES:
            conn.execute("DELETE FROM accounting_holds WHERE code='accounting_journal_full'")
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


def _archive_superseded(ledger):
    """Move superseded steady-state observations into exact compressed audit storage."""
    conn = ledger.connection
    if conn.execute('SELECT COUNT(*) FROM accounting_event_archives').fetchone()[0] >= MAX_ARCHIVES:
        _roll_archives(conn)
    cutoffs = []
    for kind in ARCHIVABLE_KINDS:
        recent = conn.execute(
            'SELECT rowid FROM accounting_events WHERE kind=? ORDER BY rowid DESC LIMIT ?',
            (kind, ARCHIVE_RETAIN_PER_KIND)).fetchall()
        if len(recent) == ARCHIVE_RETAIN_PER_KIND:
            cutoffs.append((kind, min(row[0] for row in recent)))
    if not cutoffs:
        return False
    predicate = ' OR '.join('(kind=? AND rowid<?)' for _ in cutoffs)
    parameters = tuple(value for pair in cutoffs for value in pair) + (ARCHIVE_BATCH_ROWS,)
    rows = conn.execute(
        'SELECT digest,kind,event_key,payload,first_seen_at FROM accounting_events WHERE '
        f'({predicate}) ORDER BY rowid LIMIT ?', parameters).fetchall()
    if not rows:
        return False
    exact = [[row['digest'], row['kind'], row['event_key'], row['payload'], row['first_seen_at']]
             for row in rows]
    encoded = json.dumps({'version': 1, 'events': exact},
                         sort_keys=True, separators=(',', ':')).encode('utf-8')
    if len(encoded) > MAX_ARCHIVE_BYTES:
        raise InvalidData('accounting archive exceeds byte capacity')
    archive_id = sha256(b'kalshi-accounting-archive-v1\0' + encoded).hexdigest()
    compressed = zlib.compress(encoded, level=6)
    if len(compressed) > MAX_ARCHIVE_COMPRESSED_BYTES:
        raise InvalidData('compressed accounting archive exceeds byte capacity')
    payload_bytes = sum(len(row['payload'].encode()) for row in rows)
    first_seen = min(row['first_seen_at'] for row in rows)
    last_seen = max(row['first_seen_at'] for row in rows)
    conn.execute('INSERT INTO accounting_event_archives VALUES (?,?,?,?,?,?)',
                 (archive_id, len(rows), payload_bytes, first_seen, last_seen, compressed))
    conn.executemany('INSERT INTO accounting_event_archive_members VALUES (?,?)',
                     ((row['digest'], archive_id) for row in rows))
    conn.executemany('DELETE FROM accounting_events WHERE digest=?',
                     ((row['digest'],) for row in rows))
    conn.execute('UPDATE accounting_state SET rows=rows-?,bytes=bytes-? WHERE id=1',
                 (len(rows), payload_bytes))
    state = conn.execute('SELECT rows,bytes FROM accounting_state WHERE id=1').fetchone()
    if state[0] < 0 or state[1] < 0:
        raise InvalidData('accounting archive counter underflow')
    return True


def _roll_archives(conn):
    """Bound exact snapshot retention with a cumulative hash-only commitment.

    Only already-archived superseded inspection/cash/release observations enter
    this rollup. Economic events, current hot observations and the next archive
    generation remain exact. Archive IDs already commit to every exact source
    byte, so chaining their immutable metadata preserves a corruption-detecting
    boundary without allowing repetitive snapshots to stop the bot forever.
    """
    archives = conn.execute(
        'SELECT * FROM accounting_event_archives ORDER BY rowid').fetchall()
    if not archives:
        raise InvalidData('accounting archive rollover has no source')
    prior = conn.execute('SELECT * FROM accounting_archive_rollup WHERE id=1').fetchone()
    prior_root = '0'*64 if prior is None else prior['root']
    source = [[row['id'], row['event_count'], row['payload_bytes'],
               row['first_seen_at'], row['last_seen_at']] for row in archives]
    archive_count = len(archives)+(0 if prior is None else prior['archive_count'])
    event_count = sum(row['event_count'] for row in archives)+(0 if prior is None else prior['event_count'])
    payload_bytes = sum(row['payload_bytes'] for row in archives)+(0 if prior is None else prior['payload_bytes'])
    first_seen = min([row['first_seen_at'] for row in archives]
        + ([] if prior is None else [prior['first_seen_at']]))
    last_seen = max([row['last_seen_at'] for row in archives]
        + ([] if prior is None else [prior['last_seen_at']]))
    payload = encode(dict(version=1, prior_root=prior_root, archives=source,
        archive_count=archive_count, event_count=event_count,
        payload_bytes=payload_bytes, first_seen_at=first_seen, last_seen_at=last_seen))
    root = digest(payload)
    conn.execute('INSERT OR REPLACE INTO accounting_archive_rollup VALUES (1,?,?,?,?,?,?,?)',
                 (root, archive_count, event_count, payload_bytes, first_seen, last_seen, payload))
    conn.execute('DELETE FROM accounting_event_archive_members')
    conn.execute('DELETE FROM accounting_event_archives')


def _decode_archive(blob):
    if not isinstance(blob, bytes) or len(blob) > MAX_ARCHIVE_COMPRESSED_BYTES:
        raise InvalidData('accounting archive compressed size invalid')
    decoder = zlib.decompressobj()
    encoded = decoder.decompress(blob, MAX_ARCHIVE_BYTES + 1)
    if (len(encoded) > MAX_ARCHIVE_BYTES or decoder.unconsumed_tail
            or not decoder.eof or decoder.unused_data):
        raise InvalidData('accounting archive compression invalid')
    try:
        source = json.loads(encoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidData('accounting archive payload invalid') from exc
    if (not isinstance(source, dict) or source.get('version') != 1
            or not isinstance(source.get('events'), list)):
        raise InvalidData('accounting archive schema invalid')
    return encoded, source['events']


def _validate_archives(conn):
    archives = conn.execute('SELECT * FROM accounting_event_archives ORDER BY rowid').fetchall()
    if len(archives) > MAX_ARCHIVES:
        raise InvalidData('accounting archive capacity invalid')
    members = conn.execute(
        'SELECT digest,archive_id FROM accounting_event_archive_members').fetchall()
    if len(members) > MAX_ARCHIVES * ARCHIVE_BATCH_ROWS:
        raise InvalidData('accounting archive member capacity invalid')
    indexed = {row['digest']: row['archive_id'] for row in members}
    if len(indexed) != len(members):
        raise InvalidData('accounting archive member identity invalid')
    seen = set()
    for archive in archives:
        encoded, events = _decode_archive(archive['payload'])
        expected_id = sha256(b'kalshi-accounting-archive-v1\0' + encoded).hexdigest()
        if expected_id != archive['id'] or not 0 < len(events) <= ARCHIVE_BATCH_ROWS:
            raise InvalidData('accounting archive digest or count invalid')
        payload_bytes, observed = 0, []
        for event in events:
            if (not isinstance(event, list) or len(event) != 5
                    or any(not isinstance(value, str) for value in event)):
                raise InvalidData('accounting archived event invalid')
            fingerprint, kind, key, payload, first_seen = event
            if (kind not in ARCHIVABLE_KINDS
                    or digest(encode([kind, key, payload])) != fingerprint
                    or fingerprint in seen or indexed.get(fingerprint) != archive['id']):
                raise InvalidData('accounting archived event digest invalid')
            seen.add(fingerprint)
            payload_bytes += len(payload.encode())
            observed.append(first_seen)
        if (archive['event_count'] != len(events)
                or archive['payload_bytes'] != payload_bytes
                or archive['first_seen_at'] != min(observed)
                or archive['last_seen_at'] != max(observed)):
            raise InvalidData('accounting archive metadata invalid')
    if set(indexed) != seen:
        raise InvalidData('accounting archive member index invalid')
    rollups = conn.execute('SELECT * FROM accounting_archive_rollup').fetchall()
    if len(rollups) > 1:
        raise InvalidData('accounting archive rollup cardinality invalid')
    if rollups:
        rollup = rollups[0]
        try:
            int(rollup['root'], 16)
            source = json.loads(rollup['payload'])
        except (TypeError, ValueError) as exc:
            raise InvalidData('accounting archive rollup root invalid') from exc
        except json.JSONDecodeError as exc:
            raise InvalidData('accounting archive rollup payload invalid') from exc
        if (rollup['id'] != 1 or len(rollup['root']) != 64
                or digest(rollup['payload']) != rollup['root']
                or min(rollup['archive_count'], rollup['event_count'],
                       rollup['payload_bytes']) <= 0
                or rollup['archive_count'] < 1
                or rollup['event_count'] < rollup['archive_count']
                or rollup['first_seen_at'] > rollup['last_seen_at']
                or not isinstance(source, dict) or source.get('version') != 1
                or source.get('archive_count') != rollup['archive_count']
                or source.get('event_count') != rollup['event_count']
                or source.get('payload_bytes') != rollup['payload_bytes']
                or source.get('first_seen_at') != rollup['first_seen_at']
                or source.get('last_seen_at') != rollup['last_seen_at']
                or not isinstance(source.get('archives'), list)
                or len(source['archives']) < 1):
            raise InvalidData('accounting archive rollup metadata invalid')
    return seen


def _cash_activity_rows(evidence):
    """Yield the canonical journal identity for every retained cash event."""
    for kind, rows in (('subaccount_transfer', evidence.subaccount_transfers),
                       ('intra_exchange_transfer', evidence.intra_exchange_transfers),
                       ('funding', evidence.funding)):
        for row in rows:
            key = ([row.kind, row.record_id] if kind == 'funding' else [row.transfer_id])
            payload = encode(row)
            event_key = encode(key)
            yield kind, event_key, payload, digest(encode([kind, event_key, payload]))


def cash_activity_matches_baseline(ledger, evidence):
    """Prove approved activity, including narrow lifecycle enrichment.

    Kalshi may later add ``finalized_ts`` to an already-approved, applied
    pre-boundary deposit. Such a row then leaves the relevant interval, but the
    complete exhausted funding source still proves its identity and economics.
    No other changed field, status, record, later timestamp or omission passes.
    """
    baseline = ledger.connection.execute(
        'SELECT payload FROM accounting_baseline WHERE id=1').fetchone()
    if baseline is None:
        return False
    approved = json.loads(baseline['payload']).get('attributed_cash_activity', ())
    approved = tuple((row.get('kind'), row.get('digest')) for row in approved)
    if (not approved or len(set(approved)) != len(approved)
            or any(kind not in {'funding', 'intra_exchange_transfer'}
                   for kind, _ in approved)):
        return False
    retained = {row['digest']: row for row in ledger.connection.execute(
        "SELECT digest,kind,event_key,payload FROM accounting_events WHERE kind IN "
        "('funding','intra_exchange_transfer','subaccount_transfer')")}
    if any(fingerprint not in retained or retained[fingerprint]['kind'] != kind
           for kind, fingerprint in approved):
        return False
    expected = {(kind, retained[fingerprint]['event_key']):
                (fingerprint, retained[fingerprint]['payload'])
                for kind, fingerprint in approved}
    if len(expected) != len(approved):
        return False
    cash_rows = tuple(_cash_activity_rows(evidence))
    current = {(kind, key): (fingerprint, payload)
               for kind, key, payload, fingerprint in cash_rows}
    if len(current) != len(cash_rows) or set(current)-set(expected):
        return False
    history = {('funding', encode([row.kind, row.record_id])): json.loads(encode(row))
               for row in evidence.funding_history}
    cutoff = int(utc(evidence.proposed_boundary).timestamp())
    for key, (fingerprint, old_payload) in expected.items():
        observed = current.get(key)
        if observed is not None:
            if observed[0] != fingerprint:
                return False
            continue
        if key[0] != 'funding' or key not in history:
            return False
        old, new = json.loads(old_payload), history[key]
        old_finalized = old.pop('finalized_ts', None)
        new_finalized = new.pop('finalized_ts', None)
        if (old != new or old_finalized is not None
                or type(new_finalized) is not int or new_finalized >= cutoff
                or new.get('kind') != 'deposit' or new.get('status') != 'applied'):
            return False
    return True


def validate_accounting(ledger):
    """Cold startup audit only; entry checks never scan journal history."""
    conn = ledger.connection
    counter = conn.execute('SELECT rows,bytes FROM accounting_state WHERE id=1').fetchone()
    actual = conn.execute('SELECT COUNT(*),COALESCE(SUM(length(CAST(payload AS BLOB))),0) '
                          'FROM accounting_events').fetchone()
    if (counter is None or tuple(counter) != tuple(actual)
            or not 0 <= actual[0] <= MAX_ROWS or not 0 <= actual[1] <= MAX_BYTES):
        raise InvalidData('accounting journal counters or capacity invalid')
    archived = _validate_archives(conn)
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
        if (row['digest'] in archived
                or digest(encode([row['kind'], row['event_key'], row['payload']])) != row['digest']):
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
    funding_source = evidence.funding_history or evidence.funding
    for rows in ((evidence.cash,), evidence.settlements, evidence.subaccount_transfers,
                 evidence.intra_exchange_transfers, funding_source):
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
        cash_activity = tuple(_cash_activity_rows(evidence))
        for kind, key, row_payload, _ in cash_activity:
            _append(ledger, kind, key, row_payload, at)
        if cash_activity and not cash_activity_matches_baseline(ledger, evidence):
            _hold(ledger, 'cash_activity_unattributed', fingerprint, at)
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
