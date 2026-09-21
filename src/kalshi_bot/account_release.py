"""D-068 operational reconciliation, not an atomic venue-history guarantee.

Database functions run only on the writer. A revocable source fence also
protects the no-await submission edge. There is no live transport here.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, localcontext
import json
from threading import Event
from uuid import uuid4

from .accounting import encode, digest, _append, _hold, entry_blockers
from .continuity import REQUIRED_PRIVATE_CHANNELS
from .orders import OrderUpdate, timestamp_us
from .values import InvalidData, decimal, identity, utc


TRANSIENT = frozenset({'opening_proof_unresolved', 'opening_source_stale',
    'opening_local_state_changed', 'cash_observation_changed',
    'cash_snapshot_disagrees', 'accounting_source_failed'})
ZERO = Decimal(0)


class SourceFence:
    """Created by the account owner; revoked synchronously before its awaits."""
    def __init__(self, *, generation, revision, observed_at, clock, now, started=None, revoked=None):
        self.generation, self.revision = generation, revision
        self.observed_at = utc(observed_at)
        self.clock, self.now = clock, now
        self.started = clock() if started is None else started
        self.revoked = Event() if revoked is None else revoked

    def current(self):
        return (not self.revoked.is_set()
            and 0 <= self.clock()-self.started <= 5
            and timedelta(0) <= utc(self.now())-self.observed_at <= timedelta(seconds=5))


@dataclass(frozen=True)
class AccountingLease:
    lease_id: str
    writer_epoch: str
    checkpoint_digest: str
    release_digest: str
    fence: SourceFence
    cash: object  # immutable CashObservation


@dataclass(frozen=True)
class ReleaseResult:
    released: bool
    blockers: tuple[str, ...]
    release_digest: str | None = None
    venue_handoff_proven: bool = False
    live_ready: bool = False


def approve_opening(ledger, checkpoint_digest, reference, now):
    """Explicit operator boundary approval, distinct from a review acknowledgement.

    Only exercised with synthetic approvals during this build. Never changes an
    existing baseline, imports history, resets P&L or clears an economic hold.
    """
    identity(reference)
    conn = ledger.connection
    with ledger.transaction():
        row = conn.execute('SELECT * FROM opening_checkpoint WHERE id=1').fetchone()
        if row is None or row['digest'] != checkpoint_digest:
            raise InvalidData('exact opening candidate required')
        old = conn.execute('SELECT payload FROM accounting_baseline WHERE id=1').fetchone()
        if old:
            if json.loads(old[0])['checkpoint'] != checkpoint_digest:
                raise InvalidData('opening baseline cannot change')
            return False
        if any(conn.execute(f'SELECT 1 FROM {table} LIMIT 1').fetchone()
               for table in ('fills', 'lots', 'intents', 'pending_fills', 'mutation_attempts')):
            raise InvalidData('opening approval requires unused flat ledger')
        if set(entry_blockers(ledger))-TRANSIENT:
            raise InvalidData('opening candidate has unresolved economic restrictions')
        source = json.loads(row['payload'])
        if (source['subaccount'] != 0 or source['snapshot']['orders']
                or any(decimal(p['quantity']) for p in source['snapshot']['positions'])
                or not timedelta(0) <= utc(now)-utc(datetime.fromisoformat(
                    source['observed_at'])) <= timedelta(seconds=5)):
            raise InvalidData('opening approval requires fresh flat primary evidence')
        cash = source['cash']
        if not cash['exchange_balances']:
            raise InvalidData('opening requires exchange-specific cash')
        payload = encode(dict(checkpoint=checkpoint_digest, reference=reference,
                              cash=cash, approved_at=utc(now)))
        fingerprint, inserted = _append(ledger, 'opening_approval', checkpoint_digest, payload, now)
        if not inserted:
            return False  # Commit saturation hold; install no baseline.
        conn.execute('INSERT INTO accounting_baseline VALUES (1,?,?)', (fingerprint, payload))
        for shard in cash['exchange_balances']:
            conn.execute('INSERT INTO accounting_cash VALUES (?,?)',
                         (shard['exchange_index'], shard['available']))
    return True


def apply_fill_cash(ledger, fill, matched, now):
    conn = ledger.connection
    if not conn.execute('SELECT 1 FROM accounting_baseline WHERE id=1').fetchone():
        return
    row = conn.execute('SELECT payload FROM order_evidence WHERE order_id=?', (fill.order_id,)).fetchone()
    if row is None:
        raise InvalidData('baseline cash requires owned fill scope')
    order = OrderUpdate.decode(row[0])
    shard = conn.execute('SELECT cash FROM accounting_cash WHERE exchange_index=?',
                         (order.exchange_index,)).fetchone()
    if order.subaccount != 0 or shard is None:
        raise InvalidData('fill cash scope has no opening baseline')
    # Buy either outcome; each contract matched against opposite inventory
    # releases $1 collateral. This is cash, not realized P&L.
    with localcontext() as ctx:
        ctx.prec = 40
        unit = fill.yes_price if fill.book_side == 'bid' else 1-fill.yes_price
        cash = decimal(Decimal(shard[0])) - fill.quantity*unit + matched - fill.fee
        conn.execute('UPDATE accounting_cash SET cash=? WHERE exchange_index=?',
                     (str(cash), order.exchange_index))
    if cash < 0:
        _hold(ledger, 'accounting_economics_failed', digest(fill.payload), now)


def obligations(ledger):
    from .portfolio import active_rows
    totals = {}
    for row in active_rows(ledger):
        request = json.loads(row['payload'])
        shard = request['exchange_index']
        quantity = decimal(request['count'])
        if row['order_payload'] is not None:
            order = OrderUpdate.decode(row['order_payload'])
            quantity = max(order.remaining, order.initial-ledger.filled_quantity(order.order_id))
        fee = ledger.connection.execute('SELECT fee FROM accounting_fees WHERE client_id=?',
                                         (row['client_id'],)).fetchone()
        if fee is None:
            raise InvalidData('working command has no fee cash bound')
        bound = decimal(fee[0])
        if bound < 0:
            raise InvalidData('negative fee cash bound')
        with localcontext() as ctx:
            ctx.prec = 40
            price = decimal(request['price'])
            unit = price if request['side'] == 'bid' else 1-price
            totals[shard] = totals.get(shard, ZERO)+quantity*(unit+bound)
    return totals


def cash_limit(ledger, cash, exchange_index):
    """Independent ceilings, not double subtraction of possible venue holds."""
    local = {r[0]: decimal(Decimal(r[1])) for r in ledger.connection.execute('SELECT * FROM accounting_cash')}
    venue = {r.exchange_index: r.available for r in cash.exchange_balances}
    if exchange_index not in local or exchange_index not in venue:
        raise InvalidData('entry cash exchange scope unavailable')
    held = obligations(ledger)
    with localcontext() as ctx:
        ctx.prec = 40
        global_free = sum(local.values(), ZERO)-sum(held.values(), ZERO)
        return max(ZERO, min(cash.available, global_free, venue[exchange_index],
                              local[exchange_index]-held.get(exchange_index, ZERO)))


def release(ledger, evidence, report, continuity, fence, *, epoch, revision, now, capacity):
    from .verification import audit_snapshot
    conn = ledger.connection
    blockers = []
    if not fence.current() or (evidence.writer_epoch, evidence.writer_revision) != (epoch, revision):
        blockers.append('accounting_source_stale')
    if (continuity.subaccount != 0 or continuity.writer_epoch != epoch
            or continuity.writer_revision != revision or continuity.generation != fence.generation):
        blockers.append('accounting_continuity_source_changed')
    # D-068 allows a fresh owned-order reconciliation after a historical private
    # gap; it does not erase the gap or certify globally complete history.
    allowed = {'venue_history_stream_handoff_unproven', 'persisted_private_epoch_gap'}
    blockers.extend(set(continuity.blockers)-allowed)
    if continuity.stream_span_state != 'open' or not continuity.receipt_ids:
        blockers.append('accounting_current_history_or_stream_missing')
    private = conn.execute('SELECT * FROM private_epochs WHERE id=?',
                            (continuity.stream_epoch_id,)).fetchone()
    if (private is None or private['closed_at'] is not None or private['writer_epoch'] != epoch
            or private['subaccount'] != 0 or private['generation'] != fence.generation
            or set(json.loads(private['payload'])['ack_channels']) != REQUIRED_PRIVATE_CHANNELS):
        blockers.append('accounting_private_epoch_invalid')
    opening = conn.execute('SELECT * FROM opening_checkpoint WHERE id=1').fetchone()
    baseline = conn.execute('SELECT payload FROM accounting_baseline WHERE id=1').fetchone()
    if not opening or not baseline:
        blockers.append('operator_boundary_not_approved')
    elif json.loads(baseline[0])['checkpoint'] != opening['digest']:
        raise InvalidData('approved boundary identity conflict')
    if len(continuity.receipt_ids) > 4096:
        raise InvalidData('accounting receipt scope exceeded')
    spans = []
    for receipt_id in continuity.receipt_ids:
        row = conn.execute('SELECT payload FROM history_enumerations WHERE id=?', (receipt_id,)).fetchone()
        if not row:
            blockers.append('accounting_history_receipt_missing')
            continue
        item = json.loads(row[0])
        spans.append((item['start_us'], min(item['end_us'], item['read_started_us'])))
        if (item['writer_epoch'] != epoch or item['generation'] != fence.generation
                or item['subaccount'] != 0 or item['remembered_count'] != item['row_count']
                or item['source_revision'] != fence.revision
                or (private and item['read_started_us'] < timestamp_us(private['opened_at']))
                or not 0 <= timestamp_us(utc(now).isoformat())-item['observed_us'] <= 5_000_000):
            blockers.append('accounting_history_receipt_invalid')
    if opening:
        cursor = timestamp_us(opening['boundary'])
        for left, right in sorted(spans):
            if left > cursor:
                break
            cursor = max(cursor, right)
        if (continuity.interval_gaps or not spans
                or cursor < timestamp_us(report.observed_at.isoformat())-5_000_000):
            blockers.append('accounting_history_interval_gap')
        if conn.execute('SELECT 1 FROM recovery_fills r LEFT JOIN fills f ON f.id=r.id '
                'WHERE r.subaccount=0 AND r.executed_us>=? AND f.id IS NULL LIMIT 1',
                (timestamp_us(opening['boundary']),)).fetchone():
            blockers.append('accounting_unaccounted_history_fill')
    audit = audit_snapshot(ledger, report.snapshot, epoch=epoch, revision=revision, capacity=capacity)
    blockers.extend(audit.blockers)
    uncertain = conn.execute("SELECT kind,request,phase FROM mutation_attempts "
                             "WHERE phase IN ('SENDING','UNKNOWN') LIMIT 8193").fetchall()
    if len(uncertain) > 8192:
        raise InvalidData('mutation reconciliation exceeds bound')
    for command in uncertain:
        request = json.loads(command['request'])
        if command['phase'] == 'SENDING':
            blockers.append('accounting_mutation_unresolved')
        elif command['kind'] == 'cancel':
            row = conn.execute('SELECT payload FROM order_evidence WHERE order_id=?',
                               (request['order_id'],)).fetchone()
            if row is None or not OrderUpdate.decode(row[0]).terminal:
                blockers.append('accounting_mutation_unresolved')
        else:
            # Exact owned order evidence can resolve an uncertain create; an
            # uncertain cancel needs terminal proof, not another resting read.
            row = conn.execute('SELECT state FROM intents WHERE client_id=?',
                               (request['client_order_id'],)).fetchone()
            if row is None or row[0] not in {'ACKNOWLEDGED', 'TERMINAL'}:
                blockers.append('accounting_mutation_unresolved')
    if (evidence.subaccount != 0 or report.snapshot.subaccount != 0
            or (report.audit.writer_epoch, report.audit.writer_revision) != (epoch, revision)
            or not timedelta(0) <= utc(now)-report.observed_at <= timedelta(seconds=5)
            or (evidence.cash.available, evidence.cash.updated_ts) !=
               (report.snapshot.available_balance, report.snapshot.balance_updated_ts)):
        blockers.append('accounting_cash_bracket_changed')
    if opening and evidence.proposed_boundary.isoformat() != opening['boundary']:
        blockers.append('opening_boundary_changed')
    holds = set(entry_blockers(ledger))-{'accounting_lease_required'}
    blockers.extend(holds-TRANSIENT)
    if baseline:
        local = {r[0]: decimal(Decimal(r[1])) for r in conn.execute('SELECT * FROM accounting_cash')}
        venue = {r.exchange_index: r.available for r in evidence.cash.exchange_balances}
        try:
            held = obligations(ledger)
        except InvalidData:
            blockers.append('accounting_fee_reservation_missing')
            held = {}
        if set(local) != set(venue) or any(
                venue.get(k, ZERO) > v or venue.get(k, ZERO) < max(ZERO, v-held.get(k, ZERO))
                for k, v in local.items()):
            blockers.append('accounting_cash_unexplained')
    if blockers:
        return ReleaseResult(False, tuple(sorted(set(blockers)))), None
    with ledger.transaction():
        # Recheck revocation immediately at the commit boundary.
        if not fence.current():
            return ReleaseResult(False, ('accounting_source_stale',)), None
        resolved = tuple(tuple(r) for r in conn.execute(
            'SELECT code,evidence_digest,first_seen_at FROM accounting_holds ORDER BY code'))
        payload = encode(dict(checkpoint=opening['digest'], writer_epoch=epoch,
            writer_revision=revision, generation=fence.generation, source_revision=fence.revision,
            history=continuity.receipt_ids, private_epoch=continuity.stream_epoch_id,
            resolved=resolved, cash=evidence.cash, at=utc(now), policy='D-068'))
        fingerprint, inserted = _append(ledger, 'operational_release', uuid4().hex, payload, now)
        if not inserted:
            return ReleaseResult(False, ('accounting_journal_full',)), None
        conn.executemany('DELETE FROM accounting_holds WHERE code=?', ((code,) for code in holds))
        lease = AccountingLease(uuid4().hex, epoch, opening['digest'], fingerprint, fence, evidence.cash)
    return ReleaseResult(True, (), fingerprint), lease


def validate_cash(ledger):
    """Cold startup: recompute exact cash from owned fills; never restore a lease."""
    conn = ledger.connection
    baseline = conn.execute('SELECT * FROM accounting_baseline WHERE id=1').fetchone()
    if baseline is None:
        if (conn.execute('SELECT 1 FROM accounting_cash LIMIT 1').fetchone()
                or conn.execute("SELECT 1 FROM accounting_events WHERE kind IN "
                                "('opening_approval','operational_release') LIMIT 1").fetchone()):
            raise InvalidData('cash without approved boundary')
        return
    if not conn.execute('SELECT 1 FROM accounting_events WHERE digest=? AND payload=? '
                        "AND kind='opening_approval'", (baseline['digest'], baseline['payload'])).fetchone():
        raise InvalidData('opening approval journal mismatch')
    source = json.loads(baseline['payload'])
    opening = conn.execute('SELECT digest FROM opening_checkpoint WHERE id=1').fetchone()
    if opening is None or opening[0] != source['checkpoint']:
        raise InvalidData('approved checkpoint mismatch')
    expected = {r['exchange_index']: decimal(r['available']) for r in source['cash']['exchange_balances']}
    with localcontext() as ctx:
        ctx.prec = 40
        for row in conn.execute('SELECT f.id,f.payload,o.payload AS owned FROM fills f LEFT JOIN '
                "order_evidence o ON o.order_id=json_extract(f.id,'$[0]') ORDER BY f.rowid"):
            if row['owned'] is None:
                raise InvalidData('cash fill lost ownership')
            order = OrderUpdate.decode(row['owned'])
            data = json.loads(row['payload'])
            if order.exchange_index not in expected or order.subaccount != 0:
                raise InvalidData('cash fill scope changed')
            matched = sum((decimal(r[0]) for r in conn.execute(
                'SELECT quantity FROM closes WHERE fill_id=?', (row['id'],))), ZERO)
            unit = decimal(data[3]) if data[1] == 'bid' else 1-decimal(data[3])
            expected[order.exchange_index] += matched-decimal(data[2])*unit-decimal(data[4])
    actual = {r[0]: decimal(Decimal(r[1])) for r in conn.execute('SELECT * FROM accounting_cash')}
    if actual != expected:
        raise InvalidData('derived cash differs from retained fills')
