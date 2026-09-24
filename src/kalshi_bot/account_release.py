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

from .accounting import (encode, digest, _append, _hold, entry_blockers,
                         cash_activity_matches_baseline)
from .continuity import REQUIRED_PRIVATE_CHANNELS
from .opening_account import cash_snapshot_agrees
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
    window: object = None  # writer-owned WindowState captured with the lease
    venue_handoff_proven: bool = False
    live_ready: bool = False
    audit: object = None  # Writer-issued post-release audit, never a caller rebase.


def _approval_source(conn, opening, captured_digest):
    """Return the fresh inspection approved for an immutable checkpoint."""
    captured_digest = identity(captured_digest)
    row = conn.execute("SELECT payload FROM accounting_events WHERE kind='inspection' "
                       "AND event_key=? ORDER BY rowid DESC LIMIT 1",
                       (captured_digest,)).fetchone()
    if row is None or digest(row['payload']) != captured_digest:
        raise InvalidData('exact current opening inspection required')
    source = json.loads(row['payload'])
    checkpoint = json.loads(opening['payload'])
    # An interrupted initialization may refresh clocks, never its boundary,
    # source cardinality/account scope, or economic opening cash. Kalshi's
    # balance updated_ts advances on otherwise unchanged balance observations.
    current_cash, checkpoint_cash = source['cash'], checkpoint['cash']
    current_economics = {key:value for key,value in current_cash.items()
                         if key != 'updated_ts'}
    checkpoint_economics = {key:value for key,value in checkpoint_cash.items()
                            if key != 'updated_ts'}
    source_scope = [(item['name'], item['pages'], item['rows'], item['query'])
                    for item in source['sources']]
    checkpoint_scope = [(item['name'], item['pages'], item['rows'], item['query'])
                        for item in checkpoint['sources']]
    if (source['boundary'] != opening['boundary']
            or source['subaccount'] != opening['subaccount']
            or source_scope != checkpoint_scope
            or current_economics != checkpoint_economics
            or current_cash['updated_ts'] < checkpoint_cash['updated_ts']):
        raise InvalidData('opening inspection changed immutable candidate')
    return source


def _approved_personal_cash_activity(conn, boundary):
    """Bind the narrow D-084 personal-account attribution to retained rows."""
    rows = conn.execute("SELECT digest,kind,payload FROM accounting_events WHERE kind IN "
                        "('funding','intra_exchange_transfer','subaccount_transfer') "
                        "ORDER BY digest").fetchall()
    if not rows:
        raise InvalidData('cash activity attribution evidence missing')
    cutoff = int(utc(datetime.fromisoformat(boundary)).timestamp())
    approved = []
    for row in rows:
        item = json.loads(row['payload'])
        created = item.get('created_ts')
        if type(created) is not int or created >= cutoff:
            raise InvalidData('cash activity is not pre-boundary')
        if row['kind'] == 'funding':
            # The operator identified the account's original personal funding.
            # Do not generalize that approval to withdrawals, pending/returned
            # records, or later deposits.
            if item.get('kind') != 'deposit' or item.get('status') != 'applied':
                raise InvalidData('cash activity is not approved personal funding')
        elif row['kind'] == 'intra_exchange_transfer':
            if item.get('status') != 'complete':
                raise InvalidData('cash activity transfer is not complete')
        else:
            raise InvalidData('subaccount cash activity is not attributable')
        approved.append(dict(digest=row['digest'], kind=row['kind']))
    return tuple(approved)


def approve_opening(ledger, checkpoint_digest, reference, now, captured_digest=None):
    """Explicit operator boundary approval, distinct from a review acknowledgement.

    Never changes an existing baseline, imports trading history, resets P&L or
    clears an economic hold outside D-084's exact opening-cash attribution.
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
        restrictions = set(entry_blockers(ledger))-TRANSIENT
        if restrictions-{'cash_activity_unattributed'}:
            raise InvalidData('opening candidate has unresolved economic restrictions')
        source = _approval_source(conn, row, captured_digest or checkpoint_digest)
        if (source['subaccount'] != 0 or source['snapshot']['orders']
                or any(decimal(p['quantity']) for p in source['snapshot']['positions'])
                or not timedelta(0) <= utc(now)-utc(datetime.fromisoformat(
                    source['observed_at'])) <= timedelta(seconds=5)):
            raise InvalidData('opening approval requires fresh flat primary evidence')
        cash = source['cash']
        if not cash['exchange_balances']:
            raise InvalidData('opening requires exchange-specific cash')
        attributed = (_approved_personal_cash_activity(conn, row['boundary'])
                      if restrictions else ())
        payload = encode(dict(checkpoint=checkpoint_digest, reference=reference,
                              cash=cash, approved_at=utc(now),
                              attributed_cash_activity=attributed))
        fingerprint, inserted = _append(ledger, 'opening_approval', checkpoint_digest, payload, now)
        if not inserted:
            return False  # Commit saturation hold; install no baseline.
        if attributed:
            conn.execute("DELETE FROM accounting_holds WHERE code='cash_activity_unattributed'")
        conn.execute('INSERT INTO accounting_baseline VALUES (1,?,?)', (fingerprint, payload))
        for shard in cash['exchange_balances']:
            conn.execute('INSERT INTO accounting_cash VALUES (?,?)',
                         (shard['exchange_index'], shard['available']))
    return True


def apply_fill_cash(ledger, fill, matched, now):
    conn = ledger.connection
    if not conn.execute('SELECT 1 FROM accounting_baseline WHERE id=1').fetchone():
        return
    row = conn.execute('SELECT payload,NULL AS fill_id FROM order_evidence WHERE order_id=?',
                       (fill.order_id,)).fetchone()
    if row is None:
        row = conn.execute('SELECT order_payload AS payload,fill_id FROM operator_fill_scopes '
                           'WHERE order_id=?', (fill.order_id,)).fetchone()
    if row is None:
        raise InvalidData('baseline cash requires owned fill scope')
    if row['fill_id'] is not None and row['fill_id'] != fill.key:
        raise InvalidData('operator fill scope identity changed')
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


def record_operator_close(ledger, fill, order, *, reference, now):
    """Explicit stopped-owner adoption of one exact external flattening fill.

    Ordinary stream/history recovery never calls this function.  The caller
    must separately hold process ownership and fresh venue evidence.  This
    primitive only accepts a terminal full-fill that exactly flattens one local
    position and retains its non-bot origin for cold cash verification.
    """
    from .ledger import Fill
    if not isinstance(fill, Fill) or not isinstance(order, OrderUpdate):
        raise InvalidData('typed operator close evidence required')
    reference, now = identity(reference), utc(now)
    if (order.order_id != fill.order_id or order.ticker != fill.ticker
            or order.side != fill.book_side or order.subaccount != 0
            or not order.terminal or order.remaining != 0
            or order.initial != fill.quantity or order.filled != fill.quantity
            or order.yes_price != fill.yes_price):
        raise InvalidData('operator close order/fill terms differ')
    expected = fill.quantity if fill.book_side == 'ask' else -fill.quantity
    conn = ledger.connection
    with ledger.transaction():
        existing = conn.execute('SELECT * FROM operator_fill_scopes WHERE order_id=? OR fill_id=?',
                                (order.order_id, fill.key)).fetchone()
        if existing is not None:
            raise InvalidData('operator close was already reconciled')
        if ledger.position(fill.ticker) != expected:
            raise InvalidData('operator fill does not exactly flatten local position')
        if (conn.execute('SELECT 1 FROM order_evidence WHERE order_id=? OR client_id=?',
                         (order.order_id, order.client_id)).fetchone()
                or conn.execute('SELECT 1 FROM intents WHERE client_id=?',
                                (order.client_id,)).fetchone()):
            raise InvalidData('operator close conflicts with bot-owned identity')
        if conn.execute('SELECT COUNT(*) FROM operator_fill_scopes').fetchone()[0] >= 128:
            raise InvalidData('operator fill scope capacity reached')
        conn.execute('INSERT INTO operator_fill_scopes VALUES (?,?,?,?,?)',
                     (order.order_id, fill.key, order.encode(), reference,
                      now.isoformat()))
        if not ledger.record_fill(fill, now):
            raise InvalidData('operator close fill already exists')
    return True


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


def _closed_settlement_proof(ledger, settlements, snapshot, opening):
    """Prove that current settlement rows describe already-closed owned fills.

    This is deliberately narrower than general settlement accounting. It never
    books revenue or P&L: the retained fills already did that. Any missing,
    external, open, ambiguous, corrected, or economically different evidence
    leaves the settlement hold in place for operator reconciliation.
    """
    if (opening is None or not settlements or len(settlements) > 2048
            or snapshot.subaccount != 0):
        return None
    by_ticker = {}
    expected_payloads = set()
    for settlement in settlements:
        if (settlement.result not in {'yes', 'no'} or settlement.ticker in by_ticker
                or settlement.revenue_cents != 0
                or (settlement.value_cents is not None
                    and settlement.value_cents != (100 if settlement.result == 'yes' else 0))):
            return None
        by_ticker[settlement.ticker] = settlement
        event_key = encode([0, *settlement.key])
        payload = encode(settlement)
        expected_payloads.add(payload)
        if ledger.connection.execute(
                "SELECT 1 FROM accounting_events WHERE kind='settlement' "
                "AND event_key=? AND payload=? LIMIT 1", (event_key, payload)).fetchone() is None:
            return None
    retained = ledger.connection.execute(
        "SELECT payload FROM accounting_events WHERE kind='settlement' LIMIT 2049").fetchall()
    if len(retained) != len(settlements) or {row['payload'] for row in retained} != expected_payloads:
        return None
    tickers = tuple(sorted(by_ticker))
    if (any(position.quantity and position.ticker in by_ticker
            for position in snapshot.positions)
            or any(order.ticker in by_ticker for order in snapshot.orders)):
        return None
    ticker_scope = json.dumps(tickers, separators=(',', ':'))
    scope_sql = 'SELECT value FROM json_each(?)'
    conn = ledger.connection
    if (conn.execute(f"SELECT 1 FROM lots WHERE ticker IN ({scope_sql}) LIMIT 1",
                     (ticker_scope,)).fetchone()
            or conn.execute(f"SELECT 1 FROM position_clocks WHERE ticker IN ({scope_sql}) LIMIT 1",
                            (ticker_scope,)).fetchone()
            or conn.execute(f"SELECT 1 FROM pending_fills WHERE "
                            f"json_extract(payload,'$.ticker') IN ({scope_sql}) LIMIT 1",
                            (ticker_scope,)).fetchone()
            or conn.execute(f"SELECT 1 FROM mutation_attempts WHERE phase IN ('SENDING','UNKNOWN') "
                            f"AND coalesce(json_extract(request,'$.ticker'),"
                            f"json_extract(request,'$.market_ticker')) IN ({scope_sql}) LIMIT 1",
                            (ticker_scope,)).fetchone()):
        return None
    for row in conn.execute(f"SELECT ticker,exchange_index,quantity,cost FROM venue_costs "
                            f"WHERE subaccount=0 AND ticker IN ({scope_sql})", (ticker_scope,)):
        settlement = by_ticker[row['ticker']]
        if (row['exchange_index'] != settlement.exchange_index
                or decimal(row['quantity']) != ZERO or decimal(row['cost']) != ZERO):
            return None

    rows = conn.execute(f"SELECT f.id,f.payload,f.executed_us,o.payload AS owned,"
        "x.order_payload AS external,x.fill_id AS external_fill_id,"
        "r.gross_pnl,r.fee AS realized_fee,r.pnl FROM fills f "
        "LEFT JOIN order_evidence o ON o.order_id=json_extract(f.id,'$[0]') "
        "LEFT JOIN operator_fill_scopes x ON x.order_id=json_extract(f.id,'$[0]') "
        "LEFT JOIN realized_events r ON r.fill_id=f.id "
        f"WHERE json_extract(f.payload,'$[0]') IN ({scope_sql}) ORDER BY f.rowid LIMIT 4097",
        (ticker_scope,)).fetchall()
    closes = conn.execute(f"SELECT c.fill_id,c.quantity,c.pnl FROM closes c JOIN fills f "
        "ON f.id=c.fill_id "
        f"WHERE json_extract(f.payload,'$[0]') IN ({scope_sql}) ORDER BY c.rowid LIMIT 4097",
        (ticker_scope,)).fetchall()
    if not rows or len(rows) > 4096 or len(closes) > 4096:
        return None
    close_by_fill = {}
    for row in closes:
        if row['fill_id'] in close_by_fill:
            return None
        close_by_fill[row['fill_id']] = row

    totals = {ticker: dict(yes_count=ZERO, yes_cost=ZERO, no_count=ZERO,
                           no_cost=ZERO, fee=ZERO, matched=ZERO, fills=[])
              for ticker in tickers}
    order_quantities, orders = {}, {}
    boundary_us = timestamp_us(opening['boundary'])
    with localcontext() as ctx:
        ctx.prec = 40
        for row in rows:
            data = json.loads(row['payload'])
            if (not isinstance(data, list) or len(data) != 5
                    or (row['owned'] is None) == (row['external'] is None)
                    or row['executed_us'] is None or row['gross_pnl'] is None
                    or row['realized_fee'] is None or row['pnl'] is None):
                return None
            ticker, side = data[0], data[1]
            settlement = by_ticker.get(ticker)
            if settlement is None or side not in {'bid', 'ask'}:
                return None
            try:
                order_id = json.loads(row['id'])[0]
                quantity, yes_price, fee = map(decimal, data[2:5])
                order = OrderUpdate.decode(row['owned'] or row['external'])
            except (InvalidData, ValueError, TypeError, KeyError, IndexError):
                return None
            if (row['external'] is not None and row['external_fill_id'] != row['id']
                    or order.order_id != order_id or order.ticker != ticker
                    or order.side != side or order.yes_price != yes_price
                    or order.subaccount != 0 or order.exchange_index != settlement.exchange_index
                    or not order.terminal or row['executed_us'] < boundary_us
                    or row['executed_us'] > timestamp_us(settlement.settled_at.isoformat())):
                return None
            if row['owned'] is not None:
                intent = conn.execute('SELECT state FROM intents WHERE client_id=?',
                                      (order.client_id,)).fetchone()
                if intent is None or intent[0] != 'TERMINAL':
                    return None
            close = close_by_fill.get(row['id'])
            gross = decimal(close['pnl']) if close is not None else ZERO
            matched = decimal(close['quantity']) if close is not None else ZERO
            if (decimal(row['gross_pnl']) != gross or decimal(row['realized_fee']) != fee
                    or decimal(row['pnl']) != gross-fee):
                return None
            prior = orders.get(order_id)
            if prior is not None and prior != order:
                return None
            orders[order_id] = order
            order_quantities[order_id] = order_quantities.get(order_id, ZERO)+quantity
            total = totals[ticker]
            if side == 'bid':
                total['yes_count'] += quantity
                total['yes_cost'] += quantity*yes_price
            else:
                total['no_count'] += quantity
                total['no_cost'] += quantity*(1-yes_price)
            total['fee'] += fee
            total['matched'] += matched
            total['fills'].append((row['id'], row['payload'], row['executed_us']))
        if any(order_quantities[key] != order.filled for key, order in orders.items()):
            return None

    proof = []
    for ticker in tickers:
        settlement, total = by_ticker[ticker], totals[ticker]
        if (not total['fills'] or total['yes_count'] != total['no_count']
                or total['matched'] != total['yes_count']
                or total['yes_count'] != settlement.yes_count
                or total['yes_cost'] != settlement.yes_cost
                or total['no_count'] != settlement.no_count
                or total['no_cost'] != settlement.no_cost
                or total['fee'] != settlement.fee):
            return None
        proof.append(dict(ticker=ticker, exchange_index=settlement.exchange_index,
            settled_at=settlement.settled_at, result=settlement.result,
            settlement_digest=digest(encode(settlement)),
            fills_digest=digest(encode(sorted(total['fills']))),
            fill_count=len(total['fills'])))
    return tuple(proof)


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
            or not cash_snapshot_agrees(evidence.cash, report.snapshot)):
        blockers.append('accounting_cash_bracket_changed')
    if opening and evidence.proposed_boundary.isoformat() != opening['boundary']:
        blockers.append('opening_boundary_changed')
    holds = set(entry_blockers(ledger))-{'accounting_lease_required'}
    attributed_cash_hold = ({'cash_activity_unattributed'}
        if ('cash_activity_unattributed' in holds
            and cash_activity_matches_baseline(ledger, evidence)) else set())
    settlement_proof = (_closed_settlement_proof(ledger, evidence.settlements,
        report.snapshot, opening) if 'settlement_reconciliation_required' in holds else None)
    attributed_settlement_hold = ({'settlement_reconciliation_required'}
        if settlement_proof is not None else set())
    blockers.extend(holds-TRANSIENT-attributed_cash_hold-attributed_settlement_hold)
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
            resolved=resolved, cash=evidence.cash, settlements=settlement_proof,
            at=utc(now), policy='D-068'))
        fingerprint, inserted = _append(ledger, 'operational_release', uuid4().hex, payload, now)
        if not inserted:
            return ReleaseResult(False, ('accounting_journal_full',)), None
        conn.executemany('DELETE FROM accounting_holds WHERE code=?', ((code,) for code in holds))
        from .risk import WindowRisk
        window = WindowRisk(ledger).observe(now)
        lease = AccountingLease(uuid4().hex, epoch, opening['digest'], fingerprint, fence, evidence.cash)
    return ReleaseResult(True, (), fingerprint, window), lease


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
    scopes = conn.execute('SELECT * FROM operator_fill_scopes LIMIT 129').fetchall()
    if len(scopes) > 128:
        raise InvalidData('operator fill scope capacity exceeded')
    for scope in scopes:
        order = OrderUpdate.decode(scope['order_payload'])
        fill = conn.execute('SELECT payload FROM fills WHERE id=?',
                            (scope['fill_id'],)).fetchone()
        if (fill is None or json.loads(scope['fill_id'])[0] != scope['order_id']
                or order.order_id != scope['order_id'] or not order.terminal
                or conn.execute('SELECT 1 FROM order_evidence WHERE order_id=? OR client_id=?',
                                (order.order_id, order.client_id)).fetchone()
                or conn.execute('SELECT 1 FROM intents WHERE client_id=?',
                                (order.client_id,)).fetchone()):
            raise InvalidData('operator fill scope is invalid')
    with localcontext() as ctx:
        ctx.prec = 40
        for row in conn.execute('SELECT f.id,f.payload,o.payload AS owned,'
                'x.order_payload AS external,x.fill_id AS external_fill_id FROM fills f LEFT JOIN '
                "order_evidence o ON o.order_id=json_extract(f.id,'$[0]') LEFT JOIN "
                "operator_fill_scopes x ON x.order_id=json_extract(f.id,'$[0]') ORDER BY f.rowid"):
            if (row['owned'] is None) == (row['external'] is None):
                raise InvalidData('cash fill lost ownership')
            if row['external'] is not None and row['external_fill_id'] != row['id']:
                raise InvalidData('operator fill scope identity changed')
            order = OrderUpdate.decode(row['owned'] or row['external'])
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
