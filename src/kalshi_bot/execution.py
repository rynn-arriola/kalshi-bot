"""Durable injected command handoff; live activation remains unavailable."""
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import inspect
import json

from .command_capacity import (DEFAULT_POLICY, active_episode_evidence,
    consume_cancel_capacity, consume_reduction_capacity, ledger_id,
    episode_for_client, maybe_retire_episode, release_client_credits, status,
    validate_capacity)
from .command_types import (CancelEvidence, CommandDenied, MutationHTTPFailure,
    PreparationResult, PreparedBatch, PreparedMutation, ReductionEvidence, SendResult)
from .values import InvalidData, count, decimal, identity, integer, price, utc
from .observability import NO_LOG

REJECTED_REDUCTION_RETRY_BASE_SECONDS = 10
REJECTED_REDUCTION_RETRY_MAX_SECONDS = 60


def validate_request(kind, request):
    if kind not in {'create', 'cancel'} or not isinstance(request, dict):
        raise InvalidData('invalid command request')
    integer(request['subaccount'], 0, 63)
    integer(request['exchange_index'], 0, 2**31-1)
    if kind == 'cancel':
        if set(request) != {'order_id', 'subaccount', 'exchange_index', 'market_ticker'}:
            raise InvalidData('cancel requires exact ownership/routing scope')
        identity(request['order_id']); identity(request['market_ticker'])
        return
    required = {'ticker', 'client_order_id', 'side', 'count', 'price', 'time_in_force',
                'self_trade_prevention_type', 'post_only', 'reduce_only',
                'cancel_order_on_pause', 'subaccount', 'exchange_index'}
    if not required <= set(request) or set(request)-required-{'expiration_time'}:
        raise InvalidData('unsupported create fields')
    identity(request['ticker']); identity(request['client_order_id'])
    count(request['count']); price(request['price'])
    passive = (request['time_in_force'] == 'good_till_canceled'
               and request['post_only'] is True
               and request['reduce_only'] is False)
    ioc = (request['time_in_force'] == 'immediate_or_cancel'
           and request['post_only'] is False and request['reduce_only'] is True
           and 'expiration_time' not in request)
    if (request['side'] not in {'bid', 'ask'} or not (passive or ioc)
            or request['cancel_order_on_pause'] is not True
            or type(request['reduce_only']) is not bool
            or request['self_trade_prevention_type'] != 'taker_at_cross'):
        raise InvalidData('only passive or exact reduce-only IOC mechanics supported')
    if 'expiration_time' in request:
        integer(request['expiration_time'], 1, 2**63-1)


def acknowledgement(kind, request, response):
    """Validate the V2 flat response without pretending it is a full Order."""
    if not isinstance(response, dict):
        raise InvalidData('invalid mutation response')
    try:
        result = {'order_id': identity(response['order_id']),
                  'ts_ms': integer(response['ts_ms'], 0, (2**63-1)//1000)}
        client = response.get('client_order_id')
        if client is not None:
            result['client_order_id'] = identity(client)
        if kind == 'create':
            if client is not None and client != request['client_order_id']:
                raise InvalidData('create acknowledgement client mismatch')
            filled = count(response['fill_count'], zero=True)
            remaining = count(response['remaining_count'], zero=True)
            if filled+remaining > count(request['count']):
                raise InvalidData('create acknowledgement quantity mismatch')
            result.update(fill_count=str(filled), remaining_count=str(remaining))
        else:
            if result['order_id'] != request['order_id']:
                raise InvalidData('cancel acknowledgement order mismatch')
            result['reduced_by'] = str(count(response['reduced_by'], zero=True))
        return result
    except (KeyError, TypeError) as exc:
        raise InvalidData('incomplete V2 acknowledgement') from exc


def validate_entry_pair(requests):
    if type(requests) is not tuple or len(requests) != 2:
        raise InvalidData('entry pair requires exactly two requests')
    for request in requests:
        validate_request('create', request)
    if (len({row['ticker'] for row in requests}) != 1
            or len({row['subaccount'] for row in requests}) != 1
            or len({row['exchange_index'] for row in requests}) != 1
            or len({row['client_order_id'] for row in requests}) != 2
            or {row['side'] for row in requests} != {'bid', 'ask'}
            or any(row['reduce_only'] is not False for row in requests)):
        raise InvalidData('entry pair scope conflicts')
    return requests


def batch_acknowledgement(requests, response):
    """Validate a two-row V2 batch response without assuming row ordering."""
    validate_entry_pair(requests)
    if not isinstance(response, dict) or type(response.get('orders')) is not list:
        raise InvalidData('invalid batch mutation response')
    rows = response['orders']
    if len(rows) != 2 or any(not isinstance(row, dict) for row in rows):
        raise InvalidData('incomplete batch mutation response')
    expected = {row['client_order_id']: row for row in requests}
    indexed = {}
    for row in rows:
        client = row.get('client_order_id')
        if client is None:
            # The schema permits a missing client id on errors. Position is not
            # documented as an identity contract, so the whole outcome is unknown.
            raise InvalidData('batch row lacks client identity')
        client = identity(client)
        if client not in expected or client in indexed:
            raise InvalidData('batch client identity conflicts')
        error = row.get('error')
        if error is not None:
            if not isinstance(error, dict) or not isinstance(error.get('code'), str):
                raise InvalidData('invalid batch rejection evidence')
            if any(row.get(field) is not None for field in (
                    'order_id', 'fill_count', 'remaining_count', 'ts_ms')):
                raise InvalidData('batch row mixes order and rejection evidence')
            code = identity(error['code'])
            # Persist only the bounded code; human text/details can contain
            # arbitrary venue data and are not needed for exact no-order proof.
            indexed[client] = {'state': 'rejected', 'client_order_id': client,
                               'error_code': code}
        else:
            indexed[client] = {'state': 'ack', **acknowledgement(
                'create', expected[client], row)}
    return tuple(indexed[row['client_order_id']] for row in requests)


def encoded_request(request):
    result = json.dumps(request, sort_keys=True, separators=(',', ':'), allow_nan=False)
    if len(result.encode()) > 16384:
        raise InvalidData('mutation journal document too large')
    return result


def check_new_attempt(ledger, attempt_id, kind, encoded):
    row = ledger.connection.execute(
        'SELECT kind,request FROM mutation_attempts WHERE id=?', (attempt_id,)).fetchone()
    authorization = ledger.connection.execute(
        'SELECT kind,request FROM command_authorizations WHERE id=?', (attempt_id,)).fetchone()
    existing = authorization if authorization is not None else row
    if existing is None:
        return ()
    if (existing['kind'], existing['request']) != (kind, encoded):
        raise InvalidData('attempt identity conflicts with immutable command terms')
    return ('attempt_already_prepared',)


def prepared_receipt(ledger, *, writer_epoch, writer_revision, attempt_id,
                     authorization_id, kind, subject_id, episode_id, encoded,
                     proof, now):
    return PreparedMutation(ledger_id(ledger), writer_epoch, writer_revision,
        attempt_id, authorization_id, kind, subject_id, episode_id, encoded,
        proof, utc(now))


def insert_prepared(ledger, *, mutation_id, authorization_id, kind, encoded,
                    writer_epoch, writer_revision, subject_id, episode_id, now,
                    proof, reauthorize=False):
    stamp = utc(now).isoformat()
    if reauthorize:
        changed = ledger.connection.execute(
            "UPDATE mutation_attempts SET kind=?,request=?,phase='PREPARED',response=NULL,created_at=? "
            "WHERE id=? AND phase='NOT_SENT'", (kind, encoded, stamp, mutation_id)).rowcount
        if changed != 1:
            raise InvalidData('proven-unsent mutation is no longer reusable')
    else:
        ledger.connection.execute(
            "INSERT INTO mutation_attempts VALUES (?,?,?,'PREPARED',NULL,?)",
            (mutation_id, kind, encoded, stamp))
    ledger.connection.execute(
        "INSERT INTO command_authorizations VALUES (?,?,?,?,?,?,?,?,?, 'PREPARED',?)",
        (authorization_id, mutation_id, writer_epoch, writer_revision, kind,
         subject_id, episode_id, encoded, proof, stamp))
    return prepared_receipt(ledger, writer_epoch=writer_epoch,
        writer_revision=writer_revision, attempt_id=mutation_id,
        authorization_id=authorization_id, kind=kind, subject_id=subject_id,
        episode_id=episode_id, encoded=encoded, proof=proof, now=now)


def validate_prepared_identity(ledger, receipt, row):
    authorization = ledger.connection.execute(
        'SELECT * FROM command_authorizations WHERE id=?',
        (receipt.authorization_id,)).fetchone()
    if authorization is None:
        raise InvalidData('prepared authorization evidence missing')
    if ((authorization['mutation_id'], authorization['writer_epoch'],
         authorization['writer_revision'], authorization['kind'],
         authorization['subject_id'], authorization['episode_id'],
         authorization['request'], authorization['proof'], authorization['prepared_at']) !=
            (receipt.attempt_id, receipt.writer_epoch, receipt.writer_revision,
             receipt.kind, receipt.subject_id, receipt.episode_id,
             receipt.request_json, receipt.proof_json, receipt.prepared_at.isoformat())):
        raise InvalidData('prepared mutation evidence conflicts')
    request = receipt.request
    if receipt.kind == 'create':
        client = request.get('client_order_id')
        if client != receipt.subject_id or episode_for_client(ledger, client) != receipt.episode_id:
            raise InvalidData('prepared create identity conflicts')
    else:
        if request.get('order_id') != receipt.subject_id:
            raise InvalidData('prepared cancel identity conflicts')
        order = ledger.connection.execute(
            'SELECT client_id FROM order_evidence WHERE order_id=?',
            (receipt.subject_id,)).fetchone()
        if order is None or episode_for_client(ledger, order[0]) != receipt.episode_id:
            raise InvalidData('prepared cancel ownership conflicts')
    return authorization


def _reauthorization_blocker(ledger, mutation_id, policy):
    count_rows = ledger.connection.execute(
        'SELECT COUNT(*) FROM command_authorizations WHERE mutation_id=?',
        (mutation_id,)).fetchone()[0]
    return ('command_reauthorization_limit',) if count_rows >= policy.reauthorization_limit else ()


def reduction_authority(ledger, request):
    """Recompute exact local inventory, ownership, routing and drain eligibility."""
    episode_id = active_episode_evidence(
        ledger, request['ticker'], request['subaccount'])
    blockers = []
    if episode_id is None:
        blockers.append('capacity_episode_changed')
    position = ledger.position(request['ticker'])
    expected_side = 'ask' if position > 0 else 'bid'
    if (not position or request['side'] != expected_side
            or count(request['count']) != abs(position)):
        blockers.append('reduction_not_exact_current_inventory')
    rows = []
    if episode_id is not None:
        rows = ledger.connection.execute(
            "SELECT DISTINCT o.payload FROM order_evidence o JOIN command_credits c "
            "ON c.owner_id=o.client_id WHERE c.episode_id=?", (episode_id,)).fetchall()
    from .orders import OrderUpdate
    orders = [OrderUpdate.decode(row[0]) for row in rows]
    if not orders:
        blockers.append('reduction_route_unknown')
        route = None
    else:
        routes = {order.exchange_index for order in orders}
        route = next(iter(routes)) if len(routes) == 1 else None
        if route is None:
            blockers.append('reduction_route_conflict')
        if any((order.ticker, order.subaccount) !=
               (request['ticker'], request['subaccount']) for order in orders):
            blockers.append('reduction_order_scope_conflict')
        if any(not order.terminal for order in orders):
            blockers.append('reduction_working_order_present')
        if any(ledger.filled_quantity(order.order_id) != order.filled for order in orders):
            blockers.append('reduction_fill_evidence_incomplete')
    if ledger.connection.execute(
        "SELECT 1 FROM pending_fills WHERE json_extract(payload,'$.ticker')=? LIMIT 1",
        (request['ticker'],)).fetchone():
        blockers.append('reduction_pending_fills')
    if route is not None and request['exchange_index'] != route:
        blockers.append('reduction_route_changed')
    return episode_id, position, route, tuple(dict.fromkeys(blockers))


def reduction_decision_blockers(evidence, request, *, writer_epoch,
                                writer_revision, now):
    """Validate the exact management decision bound to reducer preparation."""
    try:
        decision = json.loads(evidence.decision_json)
        observed = utc(datetime.fromisoformat(decision['observed_at']))
        terms_observed = utc(datetime.fromisoformat(decision['terms_observed_at']))
        terms_valid = utc(datetime.fromisoformat(decision['terms_valid_until']))
        for key in ('account_generation', 'account_revision', 'book_generation',
                    'book_revision', 'writer_revision', 'attempts'):
            integer(decision[key], 0, 2**63-1)
        identity(decision['ticker'])
        expected_mode = ('passive' if request['time_in_force'] ==
                         'good_till_canceled' else 'ioc')
        exact = (decision['type'] == 'managed_exit'
            and decision['ticker'] == request['ticker']
            and decision['writer_epoch'] == writer_epoch
            and decision['writer_revision'] == writer_revision
            and (decision['mode'] == expected_mode
                 or (expected_mode == 'passive' and decision['mode'] == 'passive_deferred'))
            and price(decision['limit_price']) == price(request['price'])
            and count(decision['quantity']) == count(request['count']))
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidData('invalid managed reduction decision') from exc
    blockers = []
    now = utc(now)
    if not exact:
        blockers.append('reduction_management_decision_changed')
    if observed > now or now-observed > timedelta(seconds=5):
        blockers.append('reduction_management_decision_stale')
    if not terms_observed <= now < terms_valid:
        blockers.append('reduction_terms_stale')
    return tuple(blockers)


def prepare_cancel(ledger, *, attempt_id, request, evidence, writer_epoch,
                   writer_revision, post_revision, now, policy=DEFAULT_POLICY):
    validate_request('cancel', request)
    identity(attempt_id)
    if not isinstance(evidence, CancelEvidence):
        raise InvalidData('typed cancel evidence required')
    encoded = encoded_request(request)
    blockers = list(check_new_attempt(ledger, attempt_id, 'cancel', encoded))
    if (evidence.writer_epoch, evidence.writer_revision) != (writer_epoch, writer_revision):
        blockers.append('stale_writer_evidence')
    if (evidence.order_id, evidence.ticker, evidence.subaccount, evidence.exchange_index) != (
            request['order_id'], request['market_ticker'], request['subaccount'],
            request['exchange_index']):
        blockers.append('cancel_evidence_scope_changed')
    from .orders import settle_order
    receipt = settle_order(ledger, request['order_id'])
    if (receipt is None or not receipt.owned or receipt.order.terminal or
            (receipt.order.ticker, receipt.order.subaccount, receipt.order.exchange_index) !=
            (request['market_ticker'], request['subaccount'], request['exchange_index'])):
        blockers.append('cancel_target_not_working')
    previous = ledger.connection.execute(
        "SELECT * FROM mutation_attempts WHERE kind='cancel' "
        "AND json_extract(request,'$.order_id')=? ORDER BY rowid LIMIT 2",
        (request['order_id'],)).fetchall()
    reusable = previous[0] if len(previous) == 1 and previous[0]['phase'] == 'NOT_SENT' else None
    if previous and reusable is None:
        blockers.append('cancel_already_attempted')
    if reusable is not None:
        blockers.extend(_reauthorization_blocker(ledger, reusable['id'], policy))
    if blockers:
        return PreparationResult(None, tuple(dict.fromkeys(blockers)), status(ledger),
                                 request['order_id'])
    if reusable is None:
        episode_id, capacity_blockers = consume_cancel_capacity(
            ledger, policy, receipt.order.client_id)
        if capacity_blockers:
            return PreparationResult(None, capacity_blockers, status(ledger), request['order_id'])
        mutation_id = attempt_id
    else:
        mutation_id = reusable['id']
        episode_id = episode_for_client(ledger, receipt.order.client_id)
        if episode_id is None:
            raise InvalidData('proven-unsent cancellation lost its episode')
    prepared = insert_prepared(ledger, mutation_id=mutation_id,
        authorization_id=attempt_id, kind='cancel', encoded=encoded,
        writer_epoch=writer_epoch, writer_revision=post_revision,
        subject_id=request['order_id'], episode_id=episode_id, now=now,
        proof=encoded_request({'type': 'cancel_evidence',
            'writer_epoch': evidence.writer_epoch,
            'writer_revision': evidence.writer_revision,
            'order_id': evidence.order_id}),
        reauthorize=reusable is not None)
    validate_capacity(ledger, policy, full=False)
    return PreparationResult(prepared, (), status(ledger), request['order_id'])


def prepare_reduction(ledger, *, attempt_id, request, evidence, writer_epoch,
                      writer_revision, post_revision, now,
                      management_current=False, policy=DEFAULT_POLICY):
    validate_request('create', request)
    identity(attempt_id)
    passive = (request['time_in_force'] == 'good_till_canceled'
               and request['post_only'] is True
               and request['reduce_only'] is False)
    ioc = (request['time_in_force'] == 'immediate_or_cancel'
           and request['post_only'] is False
           and request['reduce_only'] is True)
    if not (passive or ioc) or not isinstance(evidence, ReductionEvidence):
        raise InvalidData('typed reducing preparation required')
    encoded = encoded_request(request)
    blockers = list(check_new_attempt(ledger, attempt_id, 'create', encoded))
    if management_current is not True:
        blockers.append('reduction_management_decision_changed')
    if (evidence.writer_epoch, evidence.writer_revision) != (writer_epoch, writer_revision):
        blockers.append('stale_writer_evidence')
    if (evidence.ticker, evidence.subaccount, evidence.exchange_index,
            evidence.request_json) != (
            request['ticker'], request['subaccount'], request['exchange_index'], encoded):
        blockers.append('reduction_evidence_scope_changed')
    blockers.extend(reduction_decision_blockers(evidence, request,
        writer_epoch=writer_epoch, writer_revision=writer_revision, now=now))
    active, position, route, authority_blockers = reduction_authority(ledger, request)
    blockers.extend(authority_blockers)
    if active != evidence.episode_id:
        blockers.append('capacity_episode_changed')
    if position != evidence.position or route != evidence.exchange_index:
        blockers.append('reduction_evidence_state_changed')
    if active is not None:
        prior = ledger.connection.execute(
            "SELECT m.phase,m.created_at FROM mutation_attempts m "
            "JOIN command_authorizations a ON a.mutation_id=m.id "
            "WHERE a.episode_id=? AND m.kind='create' "
            "AND m.phase IN ('ACK','REJECTED') "
            "AND json_extract(a.proof,'$.type')='managed_exit' "
            "AND json_remove(m.request,'$.client_order_id')="
            "json_remove(?,'$.client_order_id') ORDER BY m.created_at DESC LIMIT 5",
            (active, encoded)).fetchall()
        consecutive = 0
        for row in prior:
            if row['phase'] != 'REJECTED':
                break
            consecutive += 1
        if consecutive:
            # A scalar HTTP 400 is exact proof that this create made no order.
            # A new client id does not make the same rejected reducer valid.
            # Follow the Poly reducer principle (a separate short safety
            # circuit, never permanent entry-style denial), but increase the
            # durable delay for repeated identical Kalshi 400s.
            rejected_at = utc(datetime.fromisoformat(prior[0]['created_at']))
            delay = min(REJECTED_REDUCTION_RETRY_MAX_SECONDS,
                        REJECTED_REDUCTION_RETRY_BASE_SECONDS*(2**(consecutive-1)))
            age = utc(now)-rejected_at
            if age < timedelta(seconds=delay):
                blockers.append('identical_reduction_rejection_cooldown')
    active_reducer = ledger.connection.execute(
        "SELECT 1 FROM intents i JOIN command_authorizations a "
        "ON a.subject_id=i.client_id AND a.kind='create' "
        "WHERE i.state IN ('RESERVED','SENDING','UNKNOWN','ACKNOWLEDGED') "
        "AND json_extract(i.payload,'$.ticker')=? "
        "AND json_extract(i.payload,'$.subaccount')=? "
        "AND json_extract(a.proof,'$.type')='managed_exit' LIMIT 1",
        (request['ticker'], request['subaccount'])).fetchone()
    if active_reducer:
        blockers.append('reduction_command_already_active')
    prior_intent = ledger.connection.execute(
        'SELECT * FROM intents WHERE client_id=?',
        (request['client_order_id'],)).fetchone()
    reusable = None
    if prior_intent is not None and prior_intent['state'] == 'ABORTED':
        reusable = ledger.connection.execute(
            "SELECT m.* FROM mutation_attempts m JOIN command_authorizations a "
            "ON a.mutation_id=m.id WHERE m.kind='create' AND m.phase='NOT_SENT' "
            "AND json_extract(m.request,'$.client_order_id')=? "
            "AND json_extract(a.proof,'$.type')='managed_exit' "
            "ORDER BY m.rowid DESC LIMIT 1",
            (request['client_order_id'],)).fetchone()
    if prior_intent is not None and reusable is None:
        blockers.append('client_identity_already_reserved')
    if reusable is not None:
        blockers.extend(_reauthorization_blocker(ledger, reusable['id'], policy))
    if blockers:
        return PreparationResult(None, tuple(dict.fromkeys(blockers)), status(ledger),
                                 request['client_order_id'])
    if reusable is None:
        _, capacity_blockers = consume_reduction_capacity(
            ledger, policy, request, evidence.episode_id, now)
        if capacity_blockers:
            return PreparationResult(None, capacity_blockers, status(ledger),
                                     request['client_order_id'])
        ledger.reserve_intent(request['client_order_id'], request, now)
        mutation_id = attempt_id
    else:
        mutation_id = reusable['id']
        ledger.connection.execute(
            "UPDATE intents SET payload=?,state='RESERVED',created_at=? "
            "WHERE client_id=? AND state='ABORTED'",
            (encoded, utc(now).isoformat(), request['client_order_id']))
    prepared = insert_prepared(ledger, mutation_id=mutation_id,
        authorization_id=attempt_id, kind='create', encoded=encoded,
        writer_epoch=writer_epoch, writer_revision=post_revision,
        subject_id=request['client_order_id'], episode_id=evidence.episode_id,
        now=now, proof=evidence.decision_json,
        reauthorize=reusable is not None)
    if ledger.connection.execute('SELECT 1 FROM accounting_baseline WHERE id=1').fetchone():
        bound = json.loads(evidence.decision_json)['fee_per_contract_bound']
        ledger.connection.execute('DELETE FROM accounting_fees WHERE client_id=?',
                                  (request['client_order_id'],))
        # Preserve existing exit safety. Missing passive fee metadata blocks new
        # entry cash proof; it does not add a new restriction to inventory exits.
        if bound is not None:
            fee = decimal(bound)
            if fee < 0:
                raise InvalidData('reduction fee cash bound invalid')
            ledger.connection.execute('INSERT INTO accounting_fees VALUES (?,?)',
                                      (request['client_order_id'], str(fee)))
    validate_capacity(ledger, policy, full=False)
    return PreparationResult(prepared, (), status(ledger), request['client_order_id'])


def begin_send(ledger, receipt, *, writer_epoch, writer_revision, post_revision, accounting_current=False):
    if not isinstance(receipt, PreparedMutation):
        raise InvalidData('typed prepared mutation required')
    if receipt.ledger_id != ledger_id(ledger) or receipt.writer_epoch != writer_epoch:
        return SendResult(False, ('prepared_receipt_owner_changed',), writer_revision)
    if receipt.writer_revision != writer_revision:
        return SendResult(False, ('stale_writer_evidence',), writer_revision)
    row = ledger.connection.execute('SELECT * FROM mutation_attempts WHERE id=?',
                                    (receipt.attempt_id,)).fetchone()
    if row is None:
        raise InvalidData('prepared mutation evidence missing')
    authorization = validate_prepared_identity(ledger, receipt, row)
    if authorization['state'] != 'PREPARED':
        return SendResult(False, ('prepared_receipt_already_used',), writer_revision)
    if ((row['kind'], row['request'], row['created_at'], row['phase']) !=
            (receipt.kind, receipt.request_json, receipt.prepared_at.isoformat(), 'PREPARED')):
        raise InvalidData('current prepared mutation conflicts with authorization')
    if receipt.kind == 'create':
        if not receipt.reduction:
            from .accounting import entry_blockers
            restrictions = entry_blockers(ledger)
            if accounting_current:
                restrictions = tuple(code for code in restrictions if code != 'accounting_lease_required')
            if not accounting_current and json.loads(receipt.proof_json).get('accounting_release'):
                restrictions += ('accounting_lease_stale',)
            if restrictions:
                return SendResult(False, restrictions, writer_revision)
        state = ledger.connection.execute('SELECT state,payload FROM intents WHERE client_id=?',
                                          (receipt.subject_id,)).fetchone()
        if state is None or state['payload'] != receipt.request_json or state['state'] != 'RESERVED':
            raise InvalidData('prepared create intent conflicts')
        ledger.transition_intent(receipt.subject_id, 'SENDING')
    ledger.connection.execute("UPDATE mutation_attempts SET phase='SENDING' WHERE id=?",
                              (receipt.attempt_id,))
    changed = ledger.connection.execute(
        "UPDATE command_authorizations SET state='SENDING' "
        "WHERE id=? AND state='PREPARED'", (receipt.authorization_id,)).rowcount
    if changed != 1:
        raise InvalidData('prepared authorization consumption conflict')
    return SendResult(True, (), post_revision)


def abort_prepared(ledger, receipt, *, writer_epoch, writer_revision, post_revision):
    if not isinstance(receipt, PreparedMutation):
        raise InvalidData('typed prepared mutation required')
    if receipt.ledger_id != ledger_id(ledger) or receipt.writer_epoch != writer_epoch:
        return SendResult(False, ('prepared_receipt_owner_changed',), writer_revision)
    row = ledger.connection.execute('SELECT * FROM mutation_attempts WHERE id=?',
                                    (receipt.attempt_id,)).fetchone()
    if row is None:
        raise InvalidData('prepared mutation evidence missing')
    authorization = validate_prepared_identity(ledger, receipt, row)
    if authorization['state'] != 'PREPARED':
        return SendResult(False, ('prepared_receipt_already_used',), writer_revision)
    if ((row['kind'], row['request'], row['created_at'], row['phase']) !=
            (receipt.kind, receipt.request_json, receipt.prepared_at.isoformat(), 'PREPARED')):
        raise InvalidData('current prepared mutation conflicts with authorization')
    ledger.connection.execute("UPDATE mutation_attempts SET phase='NOT_SENT' WHERE id=?",
                              (receipt.attempt_id,))
    ledger.connection.execute(
        "UPDATE command_authorizations SET state='ABORTED' WHERE id=?",
        (receipt.authorization_id,))
    if receipt.kind == 'create':
        ledger.transition_intent(receipt.subject_id, 'ABORTED')
        if not receipt.reduction:
            release_client_credits(ledger, receipt.subject_id)
            maybe_retire_episode(ledger, receipt.episode_id)
    return SendResult(False, ('prepared_aborted',), post_revision)


def abort_sending_before_submission(ledger, receipt, *, writer_epoch,
                                    writer_revision, post_revision):
    """Durably release a SENDING command proven not to have reached transport."""
    if not isinstance(receipt, PreparedMutation):
        raise InvalidData('typed prepared mutation required')
    if receipt.ledger_id != ledger_id(ledger) or receipt.writer_epoch != writer_epoch:
        return SendResult(False, ('prepared_receipt_owner_changed',), writer_revision)
    row = ledger.connection.execute('SELECT * FROM mutation_attempts WHERE id=?',
                                    (receipt.attempt_id,)).fetchone()
    if row is None:
        raise InvalidData('sending mutation evidence missing')
    authorization = validate_prepared_identity(ledger, receipt, row)
    if authorization['state'] != 'SENDING':
        return SendResult(False, ('prepared_receipt_already_used',), writer_revision)
    if ((row['kind'], row['request'], row['created_at'], row['phase']) !=
            (receipt.kind, receipt.request_json, receipt.prepared_at.isoformat(), 'SENDING')):
        raise InvalidData('current sending mutation conflicts with authorization')
    changed = ledger.connection.execute(
        "UPDATE mutation_attempts SET phase='NOT_SENT' WHERE id=? AND phase='SENDING'",
        (receipt.attempt_id,)).rowcount
    authorized = ledger.connection.execute(
        "UPDATE command_authorizations SET state='ABORTED' "
        "WHERE id=? AND state='SENDING'", (receipt.authorization_id,)).rowcount
    if (changed, authorized) != (1, 1):
        raise InvalidData('sending mutation abort conflict')
    if receipt.kind == 'create':
        intent = ledger.connection.execute(
            'SELECT payload,state FROM intents WHERE client_id=?',
            (receipt.subject_id,)).fetchone()
        if (intent is None or intent['payload'] != receipt.request_json
                or intent['state'] != 'SENDING'):
            raise InvalidData('sending create intent conflicts')
        changed = ledger.connection.execute(
            "UPDATE intents SET state='ABORTED' WHERE client_id=? AND state='SENDING'",
            (receipt.subject_id,)).rowcount
        if changed != 1:
            raise InvalidData('sending create intent abort conflict')
        if not receipt.reduction:
            release_client_credits(ledger, receipt.subject_id)
            maybe_retire_episode(ledger, receipt.episode_id)
    return SendResult(False, ('not_submitted_aborted',), post_revision)


def begin_batch_send(ledger, batch, *, writer_epoch, writer_revision,
                     post_revision, accounting_current=False):
    if not isinstance(batch, PreparedBatch):
        raise InvalidData('typed prepared batch required')
    if batch.writer_revision != writer_revision:
        return SendResult(False, ('stale_writer_evidence',), writer_revision)
    try:
        with ledger.transaction():
            for receipt in batch.receipts:
                result = begin_send(ledger, receipt, writer_epoch=writer_epoch,
                    writer_revision=writer_revision, post_revision=post_revision,
                    accounting_current=accounting_current)
                if not result.dispatch_allowed:
                    raise CommandDenied(result.blockers)
    except CommandDenied as exc:
        return SendResult(False, exc.blockers, writer_revision)
    return SendResult(True, (), post_revision)


def abort_batch(ledger, batch, *, writer_epoch, writer_revision, post_revision):
    if not isinstance(batch, PreparedBatch):
        raise InvalidData('typed prepared batch required')
    with ledger.transaction():
        results = tuple(abort_prepared(ledger, receipt,
            writer_epoch=writer_epoch, writer_revision=writer_revision,
            post_revision=post_revision) for receipt in batch.receipts)
    blockers = tuple(dict.fromkeys(code for row in results for code in row.blockers))
    return SendResult(False, blockers or ('prepared_aborted',), post_revision)


def abort_sending_batch_before_submission(ledger, batch, *, writer_epoch,
                                          writer_revision, post_revision):
    if not isinstance(batch, PreparedBatch):
        raise InvalidData('typed prepared batch required')
    with ledger.transaction():
        results = tuple(abort_sending_before_submission(ledger, receipt,
            writer_epoch=writer_epoch, writer_revision=writer_revision,
            post_revision=post_revision) for receipt in batch.receipts)
        if any(row.blockers != ('not_submitted_aborted',) for row in results):
            raise InvalidData('sending batch abort was not all-or-none')
    blockers = tuple(dict.fromkeys(code for row in results for code in row.blockers))
    return SendResult(False, blockers or ('not_submitted_aborted',), post_revision)


def record_outcome(ledger, operation, receipt, document, now, *, writer_epoch):
    if operation not in {'unknown', 'ack', 'rejected'} or not isinstance(receipt, PreparedMutation):
        raise InvalidData('invalid mutation outcome')
    if receipt.ledger_id != ledger_id(ledger) or receipt.writer_epoch != writer_epoch:
        raise InvalidData('mutation outcome belongs to another ledger')
    row = ledger.connection.execute('SELECT * FROM mutation_attempts WHERE id=?',
                                    (receipt.attempt_id,)).fetchone()
    if row is None:
        raise InvalidData('mutation outcome evidence missing')
    authorization = validate_prepared_identity(ledger, receipt, row)
    if row['phase'] != 'SENDING' or authorization['state'] != 'SENDING':
        raise InvalidData('mutation outcome lacks sending evidence')
    response = None
    if operation == 'ack':
        response = json.dumps(acknowledgement(receipt.kind, receipt.request, document),
                              sort_keys=True)
    elif operation == 'rejected':
        if (not isinstance(document, dict)
                or set(document)-{'state', 'status', 'error_code'}
                or document.get('state') != 'rejected'
                or (receipt.kind, document.get('status'))
                   not in {('create', 400), ('cancel', 404)}):
            raise InvalidData('unsupported deterministic mutation rejection')
        code = document.get('error_code')
        if code is not None:
            MutationHTTPFailure(document['status'], code)
        response = json.dumps(document, sort_keys=True, separators=(',', ':'))
    phase = {'unknown':'UNKNOWN', 'ack':'ACK', 'rejected':'REJECTED'}[operation]
    ledger.connection.execute('UPDATE mutation_attempts SET phase=?,response=? WHERE id=?',
                              (phase, response, receipt.attempt_id))
    ledger.connection.execute(
        'UPDATE command_authorizations SET state=? WHERE id=?',
        (phase, receipt.authorization_id))
    if receipt.kind == 'create':
        state = ledger.connection.execute('SELECT state FROM intents WHERE client_id=?',
                                          (receipt.subject_id,)).fetchone()
        if state is None:
            raise InvalidData('mutation create intent missing')
        if state[0] == 'SENDING' and operation == 'unknown':
            ledger.transition_intent(receipt.subject_id, 'UNKNOWN')
        elif state[0] == 'SENDING' and operation == 'rejected':
            ledger.transition_intent(receipt.subject_id, 'REJECTED')
            release_client_credits(ledger, receipt.subject_id)
            maybe_retire_episode(ledger, receipt.episode_id)


def record_batch_outcome(ledger, batch, document, now, *, writer_epoch):
    if not isinstance(batch, PreparedBatch):
        raise InvalidData('typed prepared batch required')
    if document is None:
        rows = tuple({'state': 'unknown'} for _ in batch.receipts)
    else:
        rows = batch_acknowledgement(batch.requests, document)
    with ledger.transaction():
        for receipt, outcome in zip(batch.receipts, rows):
            if outcome['state'] == 'ack':
                record_outcome(ledger, 'ack', receipt, outcome, now,
                               writer_epoch=writer_epoch)
            elif outcome['state'] == 'unknown':
                record_outcome(ledger, 'unknown', receipt, {}, now,
                               writer_epoch=writer_epoch)
            elif outcome['state'] == 'rejected':
                row = ledger.connection.execute(
                    'SELECT * FROM mutation_attempts WHERE id=?',
                    (receipt.attempt_id,)).fetchone()
                if row is None:
                    raise InvalidData('batch rejection mutation missing')
                authorization = validate_prepared_identity(ledger, receipt, row)
                if row['phase'] != 'SENDING' or authorization['state'] != 'SENDING':
                    raise InvalidData('batch rejection lacks sending evidence')
                response = json.dumps(outcome, sort_keys=True, separators=(',', ':'))
                ledger.connection.execute(
                    "UPDATE mutation_attempts SET phase='REJECTED',response=? WHERE id=?",
                    (response, receipt.attempt_id))
                ledger.connection.execute(
                    "UPDATE command_authorizations SET state='REJECTED' WHERE id=?",
                    (receipt.authorization_id,))
                ledger.transition_intent(receipt.subject_id, 'REJECTED')
                release_client_credits(ledger, receipt.subject_id)
            else:
                raise InvalidData('unsupported batch outcome')
        for episode in {row.episode_id for row in batch.receipts}:
            maybe_retire_episode(ledger, episode)
    return rows


@dataclass(frozen=True)
class AttemptResult:
    attempt_id: str
    phase: str
    order_id: str | None
    reconciliation_required: bool = True


@dataclass(frozen=True)
class BatchAttemptResult:
    batch_id: str
    phase: str
    order_ids: tuple[str, ...]
    rejected_clients: tuple[str, ...]
    reconciliation_required: bool = True


class InjectedExecutor:
    def __init__(self, writer, *, invoke, validate_proof, offline_fixture: bool,
                 now=lambda: datetime.now(timezone.utc), timeout=10, diagnostics=NO_LOG,
                 after_outcome=None):
        self.diagnostics = diagnostics
        from .live_session import permits
        if offline_fixture is not True and not permits(writer.live_session, writer):
            raise InvalidData('live order transport is unavailable')
        if not callable(invoke) or not callable(validate_proof) or not 0 < timeout <= 30:
            raise InvalidData('bounded injected mutation dependencies required')
        if after_outcome is not None and (not callable(after_outcome)
                                         or inspect.iscoroutinefunction(after_outcome)):
            raise InvalidData('synchronous outcome notification required')
        self.after_outcome = after_outcome
        self.offline_fixture = offline_fixture is True
        self.writer, self.invoke, self.validate_proof, self.now = writer, invoke, validate_proof, now
        self.timeout = timeout
        self.lock = asyncio.Lock()
        self.failed = False
        writer.claim_executor(self)

    @staticmethod
    async def _retain(awaitable):
        task = asyncio.create_task(awaitable)
        cancelled = False
        while not task.done():
            try:
                await asyncio.wait((task,))
            except asyncio.CancelledError:
                cancelled = True
        return task.result(), cancelled

    async def execute_prepared(self, receipt, *, before_invoke=None):
        completed = False
        try:
            result = await self._execute_prepared(receipt, before_invoke=before_invoke)
            completed = True
            return result
        except CommandDenied:
            # A denial may durably prove a SENDING command was never submitted.
            # Re-signal the owner so the fresh command can be planned promptly.
            completed = not self.failed
            raise
        finally:
            # Recovery may consume an ingress notification while persistence is
            # awaited. Revoke/re-signal AFTER retained outcome recording too,
            # including UNKNOWN or a failed writer; never release authority.
            if self.after_outcome is not None and (completed or self.failed or self.writer.failed):
                try:
                    notification = self.after_outcome()
                    if inspect.isawaitable(notification):
                        if inspect.iscoroutine(notification):
                            notification.close()
                        raise InvalidData('outcome notification must not await')
                except BaseException:
                    self.failed = True
                    raise

    async def _execute_prepared(self, receipt, *, before_invoke=None):
        self.diagnostics.ensure_healthy()
        if before_invoke is not None and (not callable(before_invoke)
                                         or inspect.iscoroutinefunction(before_invoke)):
            raise InvalidData('synchronous send-edge check required')
        if not isinstance(receipt, PreparedMutation):
            raise InvalidData('typed prepared mutation required')
        if self.lock.locked() or self.failed:
            raise CommandDenied(('mutation_owner_busy_or_recovery_required',))
        durable_request = receipt.request
        validate_request(receipt.kind, durable_request)
        async with self.lock:
            if self.validate_proof(receipt.kind, receipt.request) is not True:
                raise CommandDenied(('risk_account_book_proof_stale',))
            send, cancelled = await self._retain(self.writer.begin_send(receipt))
            if cancelled:
                if send.dispatch_allowed:
                    self.failed = True
                    await self._retain(self.writer.record_outcome('unknown', receipt, {}, self.now()))
                raise asyncio.CancelledError
            if not send.dispatch_allowed:
                raise CommandDenied(send.blockers)
            # From SENDING until fully durable ACK plus healthy diagnostics, this
            # owner is held fail-closed. Every exceptional path retains the hold.
            self.failed = True
            finalized = False
            try:
                self.diagnostics.emit('mutation_sending', operation=receipt.authorization_id)
                self.diagnostics.ensure_healthy()
                if (self.writer.revision != send.writer_revision
                        or not self.writer.entry_accounting_current(receipt)
                        or self.validate_proof(receipt.kind, receipt.request) is not True):
                    aborted, outcome_cancelled = await self._retain(
                        self.writer.abort_sending_before_submission(receipt, self))
                    if aborted.blockers != ('not_submitted_aborted',):
                        raise InvalidData('proven-unsent mutation abort was not committed')
                    finalized = True
                    self.failed = False
                    try:
                        self.diagnostics.emit('mutation_not_submitted',
                                              operation=receipt.authorization_id)
                        self.diagnostics.ensure_healthy()
                    except BaseException:
                        self.failed = True
                        raise
                    if outcome_cancelled:
                        raise asyncio.CancelledError
                    raise CommandDenied(('proof_changed_before_submission',))
                dispatch_request = receipt.request
                validate_request(receipt.kind, dispatch_request)
                if encoded_request(dispatch_request) != receipt.request_json:
                    raise InvalidData('dispatch terms differ from durable authorization')
                # Synchronous: no await may separate quota consumption from
                # entering the injected transport. An exception is durably
                # UNKNOWN after SENDING, never a permission to retry blindly.
                if before_invoke is not None:
                    edge_result = before_invoke()
                    if inspect.isawaitable(edge_result):
                        if inspect.iscoroutine(edge_result):
                            edge_result.close()
                        raise InvalidData('send-edge check must not await')
                # D-129: a lease lost at the send edge is proven unsent, exactly
                # like the batch path; never record it as an UNKNOWN submission.
                if (not self.writer.entry_accounting_current(receipt)
                        or self.writer.revision != send.writer_revision
                        or self.validate_proof(receipt.kind, receipt.request) is not True):
                    aborted, outcome_cancelled = await self._retain(
                        self.writer.abort_sending_before_submission(receipt, self))
                    if aborted.blockers != ('not_submitted_aborted',):
                        raise InvalidData('proven-unsent mutation abort was not committed')
                    finalized = True
                    self.failed = False
                    try:
                        self.diagnostics.emit('mutation_not_submitted',
                                              operation=receipt.authorization_id)
                        self.diagnostics.ensure_healthy()
                    except BaseException:
                        self.failed = True
                        raise
                    if outcome_cancelled:
                        raise asyncio.CancelledError
                    raise CommandDenied(('proof_changed_before_submission',))
                session = self.writer.live_session
                if self.offline_fixture is not True and receipt.kind == 'create':
                    session.arm_single_create(receipt)
                try:
                    async with asyncio.timeout(self.timeout):
                        if receipt.kind == 'cancel':
                            # After final synchronous fences; an invocation
                            # attempt, not proof the venue received the request.
                            self.diagnostics.emit('cancel_submit_attempt',
                                operation=receipt.authorization_id,
                                order=dispatch_request['order_id'])
                            self.diagnostics.ensure_healthy()
                        reply = await self.invoke(receipt.kind, dispatch_request)
                finally:
                    if self.offline_fixture is not True and receipt.kind == 'create':
                        session.disarm_single_create()
                ack = acknowledgement(receipt.kind, durable_request, reply)
            except BaseException as exc:
                persistence_error = None
                rejected = (type(exc) is MutationHTTPFailure
                            and (receipt.kind, exc.status)
                                in {('create', 400), ('cancel', 404)})
                if not finalized:
                    try:
                        rejection = {}
                        if rejected:
                            rejection = {'state':'rejected', 'status':exc.status}
                            if exc.error_code is not None:
                                rejection['error_code'] = exc.error_code
                        await self._retain(
                            self.writer.record_outcome('rejected' if rejected else 'unknown',
                                receipt, rejection if rejected else {},
                                self.now()))
                        finalized = True
                    except BaseException as outcome_exc:
                        persistence_error = outcome_exc
                if rejected and persistence_error is None:
                    self.failed = False
                    self.diagnostics.emit('mutation_rejected', operation=receipt.authorization_id,
                                          http_status=exc.status, venue_code=exc.error_code)
                    self.diagnostics.ensure_healthy()
                    return AttemptResult(receipt.authorization_id, 'REJECTED', None)
                if self.failed:
                    try:
                        self.diagnostics.emit('mutation_unknown', error=exc,
                                              operation=receipt.authorization_id)
                        self.diagnostics.ensure_healthy()
                    except BaseException:
                        # Durable outcome has priority; unhealthy diagnostics still
                        # leave the executor held and runtime authority revoked.
                        pass
                if persistence_error is not None:
                    raise persistence_error from exc
                raise
            try:
                _, cancelled = await self._retain(
                    self.writer.record_outcome('ack', receipt, ack, self.now()))
                finalized = True
                self.diagnostics.emit('mutation_ack', operation=receipt.authorization_id,
                                      order=ack['order_id'])
                self.diagnostics.ensure_healthy()
                if cancelled:
                    raise asyncio.CancelledError
            except BaseException as exc:
                if not finalized:
                    try:
                        await self._retain(
                            self.writer.record_outcome('unknown', receipt, {}, self.now()))
                    except BaseException:
                        pass
                try:
                    self.diagnostics.emit('mutation_unknown', error=exc,
                                          operation=receipt.authorization_id)
                except BaseException:
                    pass
                raise
            self.failed = False
            return AttemptResult(receipt.authorization_id, 'ACK', ack['order_id'])

    async def execute_prepared_batch(self, batch, *, before_invoke=None):
        completed = False
        try:
            result = await self._execute_prepared_batch(
                batch, before_invoke=before_invoke)
            completed = True
            return result
        except CommandDenied:
            completed = not self.failed
            raise
        finally:
            if self.after_outcome is not None and (completed or self.failed or self.writer.failed):
                notification = self.after_outcome()
                if inspect.isawaitable(notification):
                    if inspect.iscoroutine(notification):
                        notification.close()
                    self.failed = True
                    raise InvalidData('outcome notification must not await')

    async def _execute_prepared_batch(self, batch, *, before_invoke=None):
        self.diagnostics.ensure_healthy()
        if before_invoke is not None and (not callable(before_invoke)
                                         or inspect.iscoroutinefunction(before_invoke)):
            raise InvalidData('synchronous send-edge check required')
        if not isinstance(batch, PreparedBatch):
            raise InvalidData('typed prepared batch required')
        requests = batch.requests
        validate_entry_pair(requests)
        invoke_batch = getattr(self.invoke, 'batch', None)
        if not callable(invoke_batch):
            raise CommandDenied(('batch_transport_unavailable',))
        if self.lock.locked() or self.failed:
            raise CommandDenied(('mutation_owner_busy_or_recovery_required',))
        async with self.lock:
            if self.validate_proof('batch_create', requests) is not True:
                raise CommandDenied(('risk_account_book_proof_stale',))
            send, cancelled = await self._retain(self.writer.begin_batch_send(batch))
            if cancelled:
                if send.dispatch_allowed:
                    self.failed = True
                    await self._retain(self.writer.record_batch_outcome(batch, None, self.now()))
                raise asyncio.CancelledError
            if not send.dispatch_allowed:
                raise CommandDenied(send.blockers)
            self.failed = True
            finalized = False
            try:
                self.diagnostics.emit('mutation_sending', operation=batch.batch_id)
                self.diagnostics.ensure_healthy()
                if (self.writer.revision != send.writer_revision
                        or not self.writer.entry_accounting_current(batch)
                        or self.validate_proof('batch_create', requests) is not True):
                    aborted, outcome_cancelled = await self._retain(
                        self.writer.abort_sending_batch_before_submission(batch, self))
                    if aborted.blockers != ('not_submitted_aborted',):
                        raise InvalidData('proven-unsent batch abort was not committed')
                    finalized = True
                    self.failed = False
                    try:
                        self.diagnostics.emit('mutation_not_submitted', operation=batch.batch_id)
                        self.diagnostics.ensure_healthy()
                    except BaseException:
                        self.failed = True
                        raise
                    if outcome_cancelled:
                        raise asyncio.CancelledError
                    raise CommandDenied(('proof_changed_before_submission',))
                if tuple(encoded_request(row) for row in requests) != tuple(
                        receipt.request_json for receipt in batch.receipts):
                    raise InvalidData('batch dispatch terms differ from durable authorization')
                if before_invoke is not None:
                    edge_result = before_invoke()
                    if inspect.isawaitable(edge_result):
                        if inspect.iscoroutine(edge_result):
                            edge_result.close()
                        raise InvalidData('send-edge check must not await')
                if (not self.writer.entry_accounting_current(batch)
                        or self.writer.revision != send.writer_revision
                        or self.validate_proof('batch_create', requests) is not True):
                    aborted, outcome_cancelled = await self._retain(
                        self.writer.abort_sending_batch_before_submission(batch, self))
                    if aborted.blockers != ('not_submitted_aborted',):
                        raise InvalidData('proven-unsent batch abort was not committed')
                    finalized = True
                    self.failed = False
                    try:
                        self.diagnostics.emit('mutation_not_submitted', operation=batch.batch_id)
                        self.diagnostics.ensure_healthy()
                    except BaseException:
                        self.failed = True
                        raise
                    if outcome_cancelled:
                        raise asyncio.CancelledError
                    raise CommandDenied(('proof_changed_before_submission',))
                async with asyncio.timeout(self.timeout):
                    reply = await invoke_batch(requests)
                outcomes = batch_acknowledgement(requests, reply)
            except BaseException as exc:
                if not finalized:
                    try:
                        await self._retain(
                            self.writer.record_batch_outcome(batch, None, self.now()))
                        finalized = True
                    except BaseException as persistence_error:
                        raise persistence_error from exc
                if self.failed:
                    try:
                        self.diagnostics.emit('mutation_unknown', error=exc,
                                              operation=batch.batch_id)
                    except BaseException:
                        pass
                raise
            try:
                persisted, cancelled = await self._retain(
                    self.writer.record_batch_outcome(batch, reply, self.now()))
                finalized = True
                rejected = tuple(row['client_order_id'] for row in persisted
                                 if row['state'] == 'rejected')
                order_ids = tuple(row['order_id'] for row in persisted
                                  if row['state'] == 'ack')
                self.diagnostics.emit('mutation_ack', operation=batch.batch_id,
                    order_count=len(order_ids), rejected_count=len(rejected))
                self.diagnostics.ensure_healthy()
                if cancelled:
                    raise asyncio.CancelledError
            except BaseException as exc:
                if not finalized:
                    try:
                        await self._retain(
                            self.writer.record_batch_outcome(batch, None, self.now()))
                    except BaseException:
                        pass
                try:
                    self.diagnostics.emit('mutation_unknown', error=exc,
                                          operation=batch.batch_id)
                except BaseException:
                    pass
                raise
            phase = 'PARTIAL' if rejected else 'ACK'
            self.failed = bool(rejected)
            return BatchAttemptResult(batch.batch_id, phase, order_ids, rejected)
