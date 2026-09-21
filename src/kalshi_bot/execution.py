"""Durable fixture command handoff. No authenticated write transport."""
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import inspect
import json

from .command_capacity import (DEFAULT_POLICY, active_episode_evidence,
    consume_cancel_capacity, consume_reduction_capacity, ledger_id,
    episode_for_client, maybe_retire_episode, release_client_credits, status,
    validate_capacity)
from .command_types import (CancelEvidence, CommandDenied, PreparationResult,
    PreparedMutation, ReductionEvidence, SendResult)
from .values import InvalidData, count, identity, integer, price, utc
from .observability import NO_LOG


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
    q = count(request['count']); price(request['price'])
    passive = request['time_in_force'] == 'good_till_canceled' and request['post_only'] is True
    ioc = (request['time_in_force'] == 'immediate_or_cancel'
           and request['post_only'] is False and request['reduce_only'] is True
           and 'expiration_time' not in request)
    if (request['side'] not in {'bid', 'ask'} or not (passive or ioc)
            or request['cancel_order_on_pause'] is not True
            or type(request['reduce_only']) is not bool
            or request['self_trade_prevention_type'] != 'taker_at_cross'):
        raise InvalidData('only passive or exact reduce-only IOC mechanics supported')
    if not request['reduce_only'] and q != 10:
        raise InvalidData('entry quantity must be ten')
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
            and decision['mode'] == expected_mode
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
    if request['reduce_only'] is not True or not isinstance(evidence, ReductionEvidence):
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
    active_reducer = ledger.connection.execute(
        "SELECT 1 FROM intents WHERE state IN "
        "('RESERVED','SENDING','UNKNOWN','ACKNOWLEDGED') "
        "AND json_extract(payload,'$.ticker')=? "
        "AND json_extract(payload,'$.subaccount')=? "
        "AND json_extract(payload,'$.reduce_only')=1 LIMIT 1",
        (request['ticker'], request['subaccount'])).fetchone()
    if active_reducer:
        blockers.append('reduction_command_already_active')
    prior_intent = ledger.connection.execute(
        'SELECT * FROM intents WHERE client_id=?',
        (request['client_order_id'],)).fetchone()
    reusable = None
    if prior_intent is not None and prior_intent['state'] == 'ABORTED':
        reusable = ledger.connection.execute(
            "SELECT * FROM mutation_attempts WHERE kind='create' AND phase='NOT_SENT' "
            "AND json_extract(request,'$.client_order_id')=? "
            "AND json_extract(request,'$.reduce_only')=1 ORDER BY rowid DESC LIMIT 1",
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
    validate_capacity(ledger, policy, full=False)
    return PreparationResult(prepared, (), status(ledger), request['client_order_id'])


def begin_send(ledger, receipt, *, writer_epoch, writer_revision, post_revision):
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
        if receipt.request.get('reduce_only') is not True:
            from .accounting import entry_blockers
            restrictions = entry_blockers(ledger)
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
        if receipt.request.get('reduce_only') is not True:
            release_client_credits(ledger, receipt.subject_id)
            maybe_retire_episode(ledger, receipt.episode_id)
    return SendResult(False, ('prepared_aborted',), post_revision)


def record_outcome(ledger, operation, receipt, document, now, *, writer_epoch):
    if operation not in {'unknown', 'ack'} or not isinstance(receipt, PreparedMutation):
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
    ledger.connection.execute('UPDATE mutation_attempts SET phase=?,response=? WHERE id=?',
                              ('UNKNOWN' if operation == 'unknown' else 'ACK',
                               response, receipt.attempt_id))
    ledger.connection.execute(
        'UPDATE command_authorizations SET state=? WHERE id=?',
        ('UNKNOWN' if operation == 'unknown' else 'ACK', receipt.authorization_id))
    if receipt.kind == 'create':
        state = ledger.connection.execute('SELECT state FROM intents WHERE client_id=?',
                                          (receipt.subject_id,)).fetchone()
        if state is None:
            raise InvalidData('mutation create intent missing')
        if state[0] == 'SENDING':
            ledger.transition_intent(receipt.subject_id, 'UNKNOWN')


@dataclass(frozen=True)
class AttemptResult:
    attempt_id: str
    phase: str
    order_id: str | None
    reconciliation_required: bool = True


class InjectedExecutor:
    def __init__(self, writer, *, invoke, validate_proof, offline_fixture: bool,
                 now=lambda: datetime.now(timezone.utc), timeout=10, diagnostics=NO_LOG):
        self.diagnostics = diagnostics
        if offline_fixture is not True:
            raise InvalidData('live order transport is unavailable')
        if not callable(invoke) or not callable(validate_proof) or not 0 < timeout <= 30:
            raise InvalidData('bounded injected mutation dependencies required')
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
                await asyncio.shield(task)
            except asyncio.CancelledError:
                cancelled = True
        return task.result(), cancelled

    async def execute_prepared(self, receipt, *, before_invoke=None):
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
                        or self.validate_proof(receipt.kind, receipt.request) is not True):
                    _, outcome_cancelled = await self._retain(
                        self.writer.record_outcome('unknown', receipt, {}, self.now()))
                    finalized = True
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
                async with asyncio.timeout(self.timeout):
                    reply = await self.invoke(receipt.kind, dispatch_request)
                ack = acknowledgement(receipt.kind, durable_request, reply)
            except BaseException as exc:
                persistence_error = None
                if not finalized:
                    try:
                        await self._retain(
                            self.writer.record_outcome('unknown', receipt, {}, self.now()))
                        finalized = True
                    except BaseException as outcome_exc:
                        persistence_error = outcome_exc
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
