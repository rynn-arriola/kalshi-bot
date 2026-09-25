"""Transactional command storage credits and exact proven-unsent archival."""
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
from uuid import uuid4
import zlib

from .command_types import CapacityStatus
from .values import InvalidData, identity, integer, utc

MUTATION = 'mutation'
INTENT = 'intent'
ORDER = 'order'
RESOURCES = (MUTATION, INTENT, ORDER)
ARCHIVE_BATCH_ROWS = 512
MAX_ARCHIVES = 128
MAX_ARCHIVE_BYTES = 16 * 1024 * 1024
MAX_ARCHIVE_DECOMPRESSED_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True)
class CapacityPolicy:
    entry_mutation_limit: int = 4096
    mutation_limit: int = 8192
    intent_limit: int = 4096
    order_limit: int = 4096
    ioc_slots: int = 3
    reauthorization_limit: int = 8

    def __post_init__(self):
        integer(self.mutation_limit, 16, 65536)
        integer(self.intent_limit, 8, 32768)
        integer(self.order_limit, 8, 32768)
        integer(self.entry_mutation_limit, 1, self.mutation_limit)
        integer(self.ioc_slots, 1, 8)
        integer(self.reauthorization_limit, 1, 32)

    @property
    def limits(self):
        return {MUTATION: self.mutation_limit, INTENT: self.intent_limit,
                ORDER: self.order_limit}


DEFAULT_POLICY = CapacityPolicy()


def ledger_id(ledger):
    row = ledger.connection.execute("SELECT value FROM meta WHERE key='ledger_id'").fetchone()
    if row is None:
        raise InvalidData('ledger identity missing')
    return identity(row[0])


def _used(ledger, resource):
    row = ledger.connection.execute(
        'SELECT used FROM command_capacity_counters WHERE resource=?', (resource,)).fetchone()
    if row is None:
        raise InvalidData('command capacity counter missing')
    return row[0]


def _held(ledger, resource):
    row = ledger.connection.execute(
        'SELECT held FROM command_capacity_counters WHERE resource=?', (resource,)).fetchone()
    if row is None:
        raise InvalidData('command capacity counter missing')
    return row[0]


def status(ledger):
    rows = {row['resource']: row for row in ledger.connection.execute(
        'SELECT resource,used,held FROM command_capacity_counters')}
    if set(rows) != set(RESOURCES):
        raise InvalidData('command capacity counter missing')
    return CapacityStatus(rows[MUTATION]['used'], rows[MUTATION]['held'],
        rows[INTENT]['used'], rows[INTENT]['held'],
        rows[ORDER]['used'], rows[ORDER]['held'])


def _decode_archive(blob):
    if not isinstance(blob, bytes) or not 0 < len(blob) <= MAX_ARCHIVE_BYTES:
        raise InvalidData('command archive compressed size invalid')
    try:
        decoder = zlib.decompressobj()
        encoded = decoder.decompress(blob, MAX_ARCHIVE_DECOMPRESSED_BYTES+1)
        if (len(encoded) > MAX_ARCHIVE_DECOMPRESSED_BYTES or not decoder.eof
                or decoder.unused_data or decoder.unconsumed_tail):
            raise InvalidData('command archive decompressed size invalid')
        source = json.loads(encoded)
    except InvalidData:
        raise
    except (zlib.error, UnicodeDecodeError, json.JSONDecodeError, TypeError):
        raise InvalidData('command archive payload invalid') from None
    if (not isinstance(source, dict) or source.get('version') != 1
            or not isinstance(source.get('records'), list)
            or not 0 < len(source['records']) <= ARCHIVE_BATCH_ROWS):
        raise InvalidData('command archive schema invalid')
    return encoded, source['records']


def _validate_archives(ledger):
    rows = ledger.connection.execute(
        'SELECT * FROM command_history_archives ORDER BY rowid').fetchall()
    if len(rows) > MAX_ARCHIVES:
        raise InvalidData('command archive capacity invalid')
    seen_attempts, seen_clients = set(), set()
    for row in rows:
        encoded, records = _decode_archive(row['payload'])
        if row['id'] != sha256(b'kalshi-command-archive-v1\0'+encoded).hexdigest():
            raise InvalidData('command archive digest invalid')
        attempts, clients, episodes, authorizations, credits, stamps = [], [], set(), 0, 0, []
        for record in records:
            if not isinstance(record, dict) or set(record) != {
                    'mutation', 'intent', 'authorizations', 'credits'}:
                raise InvalidData('command archive record invalid')
            mutation, intent = record['mutation'], record['intent']
            auths, owned_credits = record['authorizations'], record['credits']
            client = None
            try:
                client = json.loads(mutation['request'])['client_order_id']
                valid = (mutation['kind'] == 'create' and mutation['phase'] == 'NOT_SENT'
                    and mutation['response'] is None and intent['client_id'] == client
                    and intent['state'] == 'ABORTED' and intent['payload'] == mutation['request']
                    and len(auths) == 1 and auths[0]['request'] == mutation['request']
                    and auths[0]['mutation_id'] == mutation['id']
                    and auths[0]['kind'] == 'create' and auths[0]['subject_id'] == client
                    and auths[0]['state'] == 'ABORTED'
                    and all(credit['owner_id'] == client
                            and credit['state'] in {'SPENT', 'RELEASED'}
                            for credit in owned_credits))
            except (KeyError, TypeError, json.JSONDecodeError):
                valid = False
            if not valid or mutation['id'] in seen_attempts or client in seen_clients:
                raise InvalidData('command archive evidence invalid')
            attempts.append(mutation['id']); clients.append(client)
            episodes.add(auths[0]['episode_id'])
            authorizations += len(auths); credits += len(owned_credits)
            stamps.append(mutation['created_at'])
            seen_attempts.add(mutation['id']); seen_clients.add(client)
        if (row['attempt_count'] != len(attempts)
                or row['intent_count'] != len(clients)
                or row['authorization_count'] != authorizations
                or row['credit_count'] != credits
                or row['first_created_at'] != min(stamps)
                or row['last_created_at'] != max(stamps)):
            raise InvalidData('command archive metadata invalid')
        marks = ','.join('?' for _ in episodes)
        retired = ledger.connection.execute(
            f"SELECT COUNT(*) FROM command_episodes WHERE id IN ({marks}) AND state='RETIRED'",
            tuple(episodes)).fetchone()[0]
        if retired != len(episodes):
            raise InvalidData('command archive episode is not retired')
        marks = ','.join('?' for _ in attempts)
        if ledger.connection.execute(
                f'SELECT 1 FROM mutation_attempts WHERE id IN ({marks}) LIMIT 1',
                attempts).fetchone():
            raise InvalidData('command archive overlaps hot mutation evidence')
        marks = ','.join('?' for _ in clients)
        if ledger.connection.execute(
                f'SELECT 1 FROM intents WHERE client_id IN ({marks}) LIMIT 1',
                clients).fetchone():
            raise InvalidData('command archive overlaps hot intent evidence')


def _archive_proven_unsent(ledger):
    """Reclaim only creates durably proven never submitted to the venue."""
    count = ledger.connection.execute(
        'SELECT COUNT(*) FROM command_history_archives').fetchone()[0]
    if count >= MAX_ARCHIVES:
        return 0
    candidates = ledger.connection.execute(
        "SELECT m.*,i.payload intent_payload,i.state intent_state,"
        "i.created_at intent_created_at,json_extract(m.request,'$.client_order_id') client_id "
        "FROM mutation_attempts m JOIN intents i ON "
        "i.client_id=json_extract(m.request,'$.client_order_id') "
        "WHERE m.kind='create' AND m.phase='NOT_SENT' AND i.state='ABORTED' "
        "ORDER BY m.rowid LIMIT ?", (ARCHIVE_BATCH_ROWS,)).fetchall()
    if not candidates:
        return 0
    candidate_clients = [row['client_id'] for row in candidates]
    candidate_attempts = [row['id'] for row in candidates]
    client_marks = ','.join('?' for _ in candidate_clients)
    attempt_marks = ','.join('?' for _ in candidate_attempts)
    mutation_counts = {row['client_id']: row['n'] for row in ledger.connection.execute(
        f"SELECT json_extract(request,'$.client_order_id') client_id,COUNT(*) n "
        f"FROM mutation_attempts WHERE json_extract(request,'$.client_order_id') "
        f"IN ({client_marks}) GROUP BY client_id", candidate_clients)}
    orders = {row[0] for row in ledger.connection.execute(
        f'SELECT client_id FROM order_evidence WHERE client_id IN ({client_marks})',
        candidate_clients)}
    auths = {}
    for row in ledger.connection.execute(
            f'SELECT * FROM command_authorizations WHERE mutation_id IN ({attempt_marks}) '
            'ORDER BY rowid', candidate_attempts):
        auths.setdefault(row['mutation_id'], []).append(row)
    episode_ids = tuple({row['episode_id'] for rows in auths.values() for row in rows})
    episode_states = dict(ledger.connection.execute(
        f'SELECT id,state FROM command_episodes WHERE id IN '
        f'({",".join("?" for _ in episode_ids)})', episode_ids)) if episode_ids else {}
    credits = {}
    for row in ledger.connection.execute(
            f'SELECT * FROM command_credits WHERE owner_id IN ({client_marks}) ORDER BY rowid',
            candidate_clients):
        credits.setdefault(row['owner_id'], []).append(row)
    records, attempts, clients = [], [], []
    for candidate in candidates:
        mutation = {name: candidate[name] for name in
                    ('id', 'kind', 'request', 'phase', 'response', 'created_at')}
        client = candidate['client_id']
        owned_auths, owned_credits = auths.get(mutation['id'], []), credits.get(client, [])
        if (client in orders or mutation_counts.get(client) != 1
                or len(owned_auths) != 1
                or owned_auths[0]['kind'] != 'create'
                or owned_auths[0]['subject_id'] != client
                or owned_auths[0]['state'] != 'ABORTED'
                or owned_auths[0]['request'] != mutation['request']
                or candidate['intent_payload'] != mutation['request']
                or episode_states.get(owned_auths[0]['episode_id']) != 'RETIRED'
                or any(row['state'] == 'HELD' for row in owned_credits)):
            continue
        intent = dict(client_id=client, payload=candidate['intent_payload'],
                      state=candidate['intent_state'],
                      created_at=candidate['intent_created_at'])
        records.append(dict(mutation=mutation, intent=intent,
                            authorizations=[dict(row) for row in owned_auths],
                            credits=[dict(row) for row in owned_credits]))
        attempts.append(mutation['id']); clients.append(client)
    if not records:
        return 0
    source = dict(version=1, records=records)
    encoded = json.dumps(source, sort_keys=True, separators=(',', ':'),
                         allow_nan=False).encode()
    payload = zlib.compress(encoded, 9)
    if len(payload) > MAX_ARCHIVE_BYTES:
        raise InvalidData('command archive exceeds byte capacity')
    archive_id = sha256(b'kalshi-command-archive-v1\0'+encoded).hexdigest()
    ledger.connection.execute(
        'INSERT INTO command_history_archives VALUES (?,?,?,?,?,?,?,?)',
        (archive_id, len(records), len(clients),
         sum(len(row['authorizations']) for row in records),
         sum(len(row['credits']) for row in records),
         min(row['mutation']['created_at'] for row in records),
         max(row['mutation']['created_at'] for row in records), payload))
    marks = ','.join('?' for _ in attempts)
    ledger.connection.execute(
        f'DELETE FROM command_authorizations WHERE mutation_id IN ({marks})', attempts)
    marks = ','.join('?' for _ in clients)
    ledger.connection.execute(
        f'DELETE FROM command_credits WHERE owner_id IN ({marks})', clients)
    ledger.connection.execute(
        f'DELETE FROM mutation_attempts WHERE id IN ({",".join("?" for _ in attempts)})',
        attempts)
    ledger.connection.execute(
        f'DELETE FROM intents WHERE client_id IN ({marks})', clients)
    return len(records)


def validate_capacity(ledger, policy=DEFAULT_POLICY, *, full=True):
    if full:
        _validate_archives(ledger)
        malformed = ledger.connection.execute(
            "SELECT 1 FROM command_credits c LEFT JOIN command_episodes e "
            "ON e.id=c.episode_id WHERE e.id IS NULL "
            "OR c.resource NOT IN ('mutation','intent','order') "
            "OR c.state NOT IN ('HELD','SPENT','RELEASED') LIMIT 1").fetchone()
        malformed_auth = ledger.connection.execute(
            "SELECT 1 FROM command_authorizations a LEFT JOIN mutation_attempts m "
            "ON m.id=a.mutation_id WHERE m.id IS NULL OR a.kind NOT IN ('create','cancel') "
            "OR a.state NOT IN ('PREPARED','SENDING','ACK','UNKNOWN','ABORTED','REJECTED') LIMIT 1").fetchone()
        missing_active_auth = ledger.connection.execute(
            "SELECT 1 FROM mutation_attempts m LEFT JOIN command_authorizations a "
            "ON a.mutation_id=m.id AND a.state=m.phase "
            "WHERE m.phase IN ('PREPARED','SENDING') AND a.id IS NULL LIMIT 1").fetchone()
        if malformed or malformed_auth or missing_active_auth:
            raise InvalidData('command capacity credit integrity conflict')
        actual_held = dict(ledger.connection.execute(
            "SELECT resource,COUNT(*) FROM command_credits WHERE state='HELD' GROUP BY resource"))
        tables = {MUTATION: 'mutation_attempts', INTENT: 'intents', ORDER: 'order_evidence'}
        actual_used = {resource: ledger.connection.execute(
            f'SELECT COUNT(*) FROM {table}').fetchone()[0]
            for resource, table in tables.items()}
    snapshot = status(ledger)
    values = {MUTATION: (snapshot.mutation_used, snapshot.mutation_held),
              INTENT: (snapshot.intent_used, snapshot.intent_held),
              ORDER: (snapshot.order_used, snapshot.order_held)}
    for resource in RESOURCES:
        used, held = values[resource]
        if used < 0 or held < 0:
            raise InvalidData('negative command capacity counter')
        if full and (held != actual_held.get(resource, 0)
                     or used != actual_used[resource]):
            raise InvalidData('command capacity counter conflicts with durable evidence')
        if used+held > policy.limits[resource]:
            raise InvalidData('command capacity invariant exceeded')
    return snapshot


def _change_held(ledger, resource, change):
    ledger.connection.execute(
        'UPDATE command_capacity_counters SET held=held+? WHERE resource=?',
        (change, resource))
    if _held(ledger, resource) < 0:
        raise InvalidData('negative command capacity counter')


def _hold(ledger, episode_id, resource, purpose, owner_id, now):
    key = uuid4().hex
    ledger.connection.execute(
        "INSERT INTO command_credits VALUES (?,?,?,?,?,'HELD',?)",
        (key, episode_id, resource, purpose, owner_id, utc(now).isoformat()))
    _change_held(ledger, resource, 1)
    return key


def _credit(ledger, *, episode_id=None, resource, purpose, owner_id=None):
    clauses, args = ["resource=?", "purpose=?", "state='HELD'"], [resource, purpose]
    if episode_id is not None:
        clauses.append('episode_id=?'); args.append(episode_id)
    if owner_id is None:
        clauses.append('owner_id IS NULL')
    else:
        clauses.append('owner_id=?'); args.append(owner_id)
    rows = ledger.connection.execute(
        'SELECT * FROM command_credits WHERE '+' AND '.join(clauses)+' ORDER BY rowid LIMIT 2',
        tuple(args)).fetchall()
    if len(rows) > 1:
        raise InvalidData('ambiguous command capacity credit')
    return rows[0] if rows else None


def _spend(ledger, row, owner_id=None):
    if row is None:
        raise InvalidData('required command capacity credit missing')
    changed = ledger.connection.execute(
        "UPDATE command_credits SET state='SPENT',owner_id=coalesce(?,owner_id) "
        "WHERE id=? AND state='HELD'", (owner_id, row['id'])).rowcount
    if changed != 1:
        raise InvalidData('command capacity credit already consumed')
    _change_held(ledger, row['resource'], -1)


def _release(ledger, row):
    if row is None:
        return False
    changed = ledger.connection.execute(
        "UPDATE command_credits SET state='RELEASED' WHERE id=? AND state='HELD'",
        (row['id'],)).rowcount
    if changed:
        _change_held(ledger, row['resource'], -1)
    return bool(changed)


def _active_episode(ledger, subaccount, ticker):
    return ledger.connection.execute(
        "SELECT * FROM command_episodes WHERE subaccount=? AND ticker=? AND state='ACTIVE'",
        (subaccount, ticker)).fetchone()


def _requirements(policy, new_episode):
    slots = 1+policy.ioc_slots
    return ({MUTATION: 1+1+(2*slots if new_episode else 0),
             INTENT: 1+(slots if new_episode else 0),
             ORDER: 1+(slots if new_episode else 0)},
            {MUTATION: 1+(2*slots if new_episode else 0),
             INTENT: slots if new_episode else 0,
             ORDER: 1+(slots if new_episode else 0)})


def reserve_entry_capacity(ledger, policy, request, now):
    """Reserve actual create plus future evidence/cancel/drain headroom."""
    validate_capacity(ledger, policy, full=False)
    ticker, scope, client = request['ticker'], request['subaccount'], request['client_order_id']
    episode = _active_episode(ledger, scope, ticker)
    total_need, _ = _requirements(policy, episode is None)
    if _used(ledger, MUTATION) >= policy.entry_mutation_limit:
        _archive_proven_unsent(ledger)
    current = {resource: (_used(ledger, resource), _held(ledger, resource))
               for resource in RESOURCES}
    blockers = []
    if current[MUTATION][0] >= policy.entry_mutation_limit:
        blockers.append('capacity_entries_held')
    for resource in RESOURCES:
        used, held = current[resource]
        if used+held+total_need[resource] > policy.limits[resource]:
            blockers.append('capacity_entries_held')
    if blockers:
        return None, tuple(dict.fromkeys(blockers))
    if episode is None:
        episode_id = uuid4().hex
        ledger.connection.execute("INSERT INTO command_episodes VALUES (?,?,?,'ACTIVE',?)",
                                  (episode_id, scope, ticker, utc(now).isoformat()))
        for slot in ('passive',)+(tuple(f'ioc-{i+1}' for i in range(policy.ioc_slots))):
            _hold(ledger, episode_id, MUTATION, slot+':create', None, now)
            _hold(ledger, episode_id, MUTATION, slot+':cancel', None, now)
            _hold(ledger, episode_id, INTENT, slot+':intent', None, now)
            _hold(ledger, episode_id, ORDER, slot+':order', None, now)
    else:
        episode_id = episode['id']
    _hold(ledger, episode_id, MUTATION, 'cancel', client, now)
    _hold(ledger, episode_id, ORDER, 'order', client, now)
    validate_capacity(ledger, policy, full=False)
    return episode_id, ()


def consume_reduction_capacity(ledger, policy, request, episode_id, now):
    validate_capacity(ledger, policy, full=False)
    episode = ledger.connection.execute(
        "SELECT * FROM command_episodes WHERE id=? AND state='ACTIVE'", (episode_id,)).fetchone()
    if episode is None or (episode['subaccount'], episode['ticker']) != (
            request['subaccount'], request['ticker']):
        return None, ('capacity_episode_missing',)
    wanted = ('passive',) if request['time_in_force'] == 'good_till_canceled' else tuple(
        f'ioc-{i+1}' for i in range(policy.ioc_slots))
    selected = None
    for slot in wanted:
        if _credit(ledger, episode_id=episode_id, resource=INTENT,
                   purpose=slot+':intent', owner_id=None) is not None:
            selected = slot; break
    # A terminal passive reducer may be replaced from genuinely free bounded
    # capacity. The protected three-IOC bundle is never replenished this way.
    if selected is None and request['time_in_force'] == 'good_till_canceled':
        needed = {MUTATION: 2, INTENT: 1, ORDER: 1}
        if any(_used(ledger, resource)+_held(ledger, resource)+needed[resource]
               > policy.limits[resource] for resource in RESOURCES):
            return None, ('capacity_reduction_held',)
        selected = 'passive-replacement-'+uuid4().hex
        client = request['client_order_id']
        create = _hold(ledger, episode_id, MUTATION, selected+':create', None, now)
        intent = _hold(ledger, episode_id, INTENT, selected+':intent', None, now)
        _hold(ledger, episode_id, ORDER, 'order', client, now)
        _hold(ledger, episode_id, MUTATION, 'cancel', client, now)
        _spend(ledger, ledger.connection.execute(
            'SELECT * FROM command_credits WHERE id=?', (create,)).fetchone(), client)
        _spend(ledger, ledger.connection.execute(
            'SELECT * FROM command_credits WHERE id=?', (intent,)).fetchone(), client)
        validate_capacity(ledger, policy, full=False)
        return selected, ()
    if selected is None:
        return None, ('capacity_reduction_held',)
    client = request['client_order_id']
    for resource, suffix in ((INTENT, ':intent'), (MUTATION, ':create')):
        _spend(ledger, _credit(ledger, episode_id=episode_id, resource=resource,
                              purpose=selected+suffix, owner_id=None), client)
    for resource, suffix, purpose in ((ORDER, ':order', 'order'),
                                      (MUTATION, ':cancel', 'cancel')):
        row = _credit(ledger, episode_id=episode_id, resource=resource,
                      purpose=selected+suffix, owner_id=None)
        if row is None:
            raise InvalidData('reduction safety capacity missing')
        ledger.connection.execute(
            'UPDATE command_credits SET purpose=?,owner_id=? WHERE id=? AND state=\'HELD\'',
            (purpose, client, row['id']))
    validate_capacity(ledger, policy, full=False)
    return selected, ()


def consume_cancel_capacity(ledger, policy, client_id):
    validate_capacity(ledger, policy, full=False)
    row = _credit(ledger, resource=MUTATION, purpose='cancel', owner_id=client_id)
    if row is None:
        return None, ('cancel_capacity_unfunded',)
    _spend(ledger, row)
    validate_capacity(ledger, policy, full=False)
    return row['episode_id'], ()


def bind_order_evidence(ledger, client_id):
    row = _credit(ledger, resource=ORDER, purpose='order', owner_id=client_id)
    if row is None:
        command = ledger.connection.execute(
            "SELECT 1 FROM mutation_attempts WHERE kind='create' "
            "AND json_extract(request,'$.client_order_id')=? LIMIT 1", (client_id,)).fetchone()
        if command:
            raise InvalidData('prepared create lacks order evidence capacity')
        return None
    _spend(ledger, row)
    return row['episode_id']


def episode_for_client(ledger, client_id):
    row = ledger.connection.execute(
        'SELECT episode_id FROM command_credits WHERE owner_id=? ORDER BY rowid LIMIT 1',
        (client_id,)).fetchone()
    return row[0] if row else None


def release_client_credits(ledger, client_id):
    rows = ledger.connection.execute(
        "SELECT * FROM command_credits WHERE owner_id=? AND state='HELD' "
        "AND purpose IN ('order','cancel')", (client_id,)).fetchall()
    for row in rows:
        _release(ledger, row)


def maybe_retire_episode(ledger, episode_id):
    if episode_id is None:
        return False
    episode = ledger.connection.execute(
        "SELECT * FROM command_episodes WHERE id=? AND state='ACTIVE'", (episode_id,)).fetchone()
    if episode is None or ledger.position(episode['ticker']):
        return False
    owners = tuple(row[0] for row in ledger.connection.execute(
        'SELECT DISTINCT owner_id FROM command_credits WHERE episode_id=? AND owner_id IS NOT NULL',
        (episode_id,)))
    if owners:
        marks = ','.join('?' for _ in owners)
        if ledger.connection.execute(
            f"SELECT 1 FROM intents WHERE client_id IN ({marks}) AND state IN "
            "('RESERVED','SENDING','UNKNOWN','ACKNOWLEDGED') LIMIT 1", owners).fetchone():
            return False
        if ledger.connection.execute(
            f"SELECT 1 FROM order_evidence WHERE client_id IN ({marks}) "
            "AND json_extract(payload,'$.status')='resting' LIMIT 1", owners).fetchone():
            return False
    if ledger.connection.execute(
        "SELECT 1 FROM pending_fills WHERE json_extract(payload,'$.ticker')=? LIMIT 1",
        (episode['ticker'],)).fetchone():
        return False
    rows = ledger.connection.execute(
        "SELECT * FROM command_credits WHERE episode_id=? AND state='HELD'", (episode_id,)).fetchall()
    for row in rows:
        _release(ledger, row)
    ledger.connection.execute("UPDATE command_episodes SET state='RETIRED' WHERE id=?", (episode_id,))
    return True


def active_episode_evidence(ledger, ticker, subaccount):
    episode = _active_episode(ledger, subaccount, ticker)
    return episode['id'] if episode else None
