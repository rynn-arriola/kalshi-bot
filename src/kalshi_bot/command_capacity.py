"""Transactional command storage credits and exact bounded command archival.

D-125 archives creates proven never sent. D-129 additionally archives every
row of a retired, flat, zero-fill episode whose orders are terminal. Any fill,
position, pending fill, held credit or active command keeps the episode hot.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
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
MAX_ARCHIVES = 256
ROLL_ARCHIVES = MAX_ARCHIVES // 2
MAX_ARCHIVE_BYTES = 16 * 1024 * 1024
MAX_ARCHIVE_DECOMPRESSED_BYTES = 64 * 1024 * 1024
# D-129 terminal-episode reclamation. Pressure starts well before the entry
# boundary; the check itself is rate limited so reservations stay cheap.
EPISODE_BATCH = 128
EPISODE_SCAN_LIMIT = 512
EPISODE_MIN_BATCH = 32
EPISODE_QUIET_SECONDS = 600
RECLAIM_PRESSURE = 0.75
RECLAIM_FORCE = 0.90
RECLAIM_CHECK_SECONDS = 60
UNSENT_MIN_BATCH = 128
_CREATE_PHASES = frozenset({'ACK', 'REJECTED', 'NOT_SENT'})
_CANCEL_PHASES = frozenset({'ACK', 'REJECTED', 'UNKNOWN', 'NOT_SENT'})
_INTENT_STATES = frozenset({'TERMINAL', 'REJECTED', 'ABORTED'})
_AUTH_STATES = frozenset({'ACK', 'REJECTED', 'UNKNOWN', 'ABORTED'})
_CREDIT_STATES = frozenset({'SPENT', 'RELEASED'})
_PREFIX = {1: b'kalshi-command-archive-v1\0', 2: b'kalshi-command-archive-v2\0'}


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
    if not isinstance(source, dict):
        raise InvalidData('command archive schema invalid')
    version = source.get('version')
    key, limit = {1: ('records', ARCHIVE_BATCH_ROWS), 2: ('episodes', EPISODE_BATCH)}.get(
        version, (None, 0))
    if (key is None or not isinstance(source.get(key), list)
            or not 0 < len(source[key]) <= limit):
        raise InvalidData('command archive schema invalid')
    return encoded, version, source[key]


def _marks(values):
    return ','.join('?' for _ in values)


def _any_hot(ledger, table, column, values):
    values = tuple(values)
    for offset in range(0, len(values), 512):
        chunk = values[offset:offset+512]
        if ledger.connection.execute(
                f'SELECT 1 FROM {table} WHERE {column} IN ({_marks(chunk)}) LIMIT 1',
                chunk).fetchone():
            return True
    return False


def _validate_episode_archive(ledger, row, episodes, seen):
    """Exact D-129 terminal-episode archive; never current order authority."""
    from .orders import OrderUpdate
    attempts, clients, orders, auth_ids, credit_ids, stamps = [], [], [], [], [], []
    authorization_count = credit_count = 0
    for record in episodes:
        try:
            if not isinstance(record, dict) or set(record) != {
                    'episode', 'mutations', 'authorizations', 'intents', 'orders',
                    'credits', 'fees'}:
                raise InvalidData('command episode archive record invalid')
            episode = record['episode']
            episode_id, ticker = identity(episode['id']), identity(episode['ticker'])
            hot = ledger.connection.execute(
                'SELECT * FROM command_episodes WHERE id=?', (episode_id,)).fetchone()
            if (hot is None or hot['state'] != 'ARCHIVED' or episode_id in seen['episodes']
                    or (hot['subaccount'], hot['ticker'], hot['created_at']) !=
                       (episode['subaccount'], ticker, episode['created_at'])):
                raise InvalidData('command archive episode invalid')
            seen['episodes'].add(episode_id)
            credits = record['credits']
            owners = set()
            for credit in credits:
                if (credit['episode_id'] != episode_id or credit['state'] not in _CREDIT_STATES
                        or credit['resource'] not in RESOURCES):
                    raise InvalidData('command archive credit invalid')
                credit_ids.append(identity(credit['id']))
                stamps.append(credit['created_at'])
                if credit['owner_id'] is not None:
                    owners.add(identity(credit['owner_id']))
            intents = {item['client_id']: item for item in record['intents']}
            if (set(intents) != owners or len(intents) != len(record['intents'])
                    or any(item['state'] not in _INTENT_STATES
                           or json.loads(item['payload']).get('ticker') != ticker
                           for item in intents.values())):
                raise InvalidData('command archive intent invalid')
            order_ids = set()
            for item in record['orders']:
                order = OrderUpdate.decode(item['payload'])
                if (item['client_id'] not in owners or order.client_id != item['client_id']
                        or order.order_id != item['order_id'] or order.ticker != ticker
                        or not order.terminal or order.filled != 0
                        or intents[item['client_id']]['state'] != 'TERMINAL'):
                    raise InvalidData('command archive order invalid')
                order_ids.add(order.order_id)
            mutation_ids = set()
            for mutation in record['mutations']:
                request = json.loads(mutation['request'])
                if mutation['kind'] == 'create':
                    valid = (request.get('client_order_id') in owners
                             and mutation['phase'] in _CREATE_PHASES)
                elif mutation['kind'] == 'cancel':
                    valid = (request.get('order_id') in order_ids
                             and mutation['phase'] in _CANCEL_PHASES)
                else:
                    valid = False
                if not valid or mutation['id'] in mutation_ids:
                    raise InvalidData('command archive mutation invalid')
                mutation_ids.add(identity(mutation['id']))
                stamps.append(mutation['created_at'])
            authorized = set()
            for auth in record['authorizations']:
                if (auth['episode_id'] != episode_id or auth['state'] not in _AUTH_STATES
                        or auth['mutation_id'] not in mutation_ids):
                    raise InvalidData('command archive authorization invalid')
                authorized.add(auth['mutation_id'])
                auth_ids.append(identity(auth['id']))
            if authorized != mutation_ids or any(
                    fee['client_id'] not in owners for fee in record['fees']):
                raise InvalidData('command archive authorization coverage invalid')
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise InvalidData('command episode archive record invalid') from exc
        for values, name in ((mutation_ids, 'attempts'), (owners, 'clients'),
                             (order_ids, 'orders')):
            if values & seen[name]:
                raise InvalidData('command archive evidence duplicated')
            seen[name].update(values)
        attempts.extend(mutation_ids); clients.extend(owners); orders.extend(order_ids)
        authorization_count += len(record['authorizations'])
        credit_count += len(credits)
    if (row['attempt_count'] != len(attempts) or row['intent_count'] != len(clients)
            or row['authorization_count'] != authorization_count
            or row['credit_count'] != credit_count or not stamps
            or row['first_created_at'] != min(stamps) or row['last_created_at'] != max(stamps)
            or len(set(credit_ids)) != len(credit_ids) or len(set(auth_ids)) != len(auth_ids)):
        raise InvalidData('command archive metadata invalid')
    for table, column, values in (('mutation_attempts', 'id', attempts),
                                  ('intents', 'client_id', clients),
                                  ('order_evidence', 'order_id', orders),
                                  ('command_credits', 'id', credit_ids),
                                  ('command_authorizations', 'id', auth_ids)):
        if _any_hot(ledger, table, column, values):
            raise InvalidData('command archive overlaps hot evidence')


def _validate_rollup(ledger, retained_ids):
    rows = ledger.connection.execute('SELECT * FROM command_archive_rollup').fetchall()
    if len(rows) > 1:
        raise InvalidData('command archive rollup cardinality invalid')
    if not rows:
        return
    rollup = rows[0]
    try:
        source = json.loads(rollup['payload'])
        valid = (rollup['id'] == 1
            and sha256(rollup['payload'].encode()).hexdigest() == rollup['root']
            and isinstance(source, dict) and source.get('version') == 1
            and isinstance(source.get('archives'), list) and source['archives']
            and source.get('archive_count') == rollup['archive_count']
            and source.get('attempt_count') == rollup['attempt_count']
            and source.get('intent_count') == rollup['intent_count']
            and source.get('first_created_at') == rollup['first_created_at']
            and source.get('last_created_at') == rollup['last_created_at']
            and rollup['archive_count'] >= len(source['archives'])
            and rollup['first_created_at'] <= rollup['last_created_at']
            and not {item[0] for item in source['archives']} & set(retained_ids))
    except (TypeError, ValueError, IndexError, AttributeError):
        valid = False
    if not valid:
        raise InvalidData('command archive rollup invalid')


def _validate_archives(ledger):
    rows = ledger.connection.execute(
        'SELECT * FROM command_history_archives ORDER BY rowid').fetchall()
    if len(rows) > MAX_ARCHIVES:
        raise InvalidData('command archive capacity invalid')
    seen_attempts, seen_clients = set(), set()
    seen = dict(attempts=seen_attempts, clients=seen_clients, orders=set(), episodes=set())
    for row in rows:
        encoded, version, records = _decode_archive(row['payload'])
        if row['id'] != sha256(_PREFIX[version]+encoded).hexdigest():
            raise InvalidData('command archive digest invalid')
        if version == 2:
            _validate_episode_archive(ledger, row, records, seen)
            continue
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
            f"SELECT COUNT(*) FROM command_episodes WHERE id IN ({marks}) "
            "AND state IN ('RETIRED','ARCHIVED')",
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
    _validate_rollup(ledger, [row['id'] for row in rows])


def _roll_archives(ledger):
    """Bound exact archive retention with a cumulative hash commitment.

    The oldest half of the exact, already-validated archives becomes one
    chained digest of their immutable metadata. Hot evidence and the newest
    archives stay exact; no fill/economic evidence is ever archived here.
    """
    conn = ledger.connection
    rows = conn.execute('SELECT id,attempt_count,intent_count,authorization_count,'
                        'credit_count,first_created_at,last_created_at '
                        'FROM command_history_archives ORDER BY rowid LIMIT ?',
                        (ROLL_ARCHIVES,)).fetchall()
    if not rows:
        raise InvalidData('command archive rollover has no source')
    prior = conn.execute('SELECT * FROM command_archive_rollup WHERE id=1').fetchone()
    first = min([row['first_created_at'] for row in rows]
                + ([] if prior is None else [prior['first_created_at']]))
    last = max([row['last_created_at'] for row in rows]
               + ([] if prior is None else [prior['last_created_at']]))
    totals = dict(
        archive_count=len(rows)+(0 if prior is None else prior['archive_count']),
        attempt_count=sum(row['attempt_count'] for row in rows)
            +(0 if prior is None else prior['attempt_count']),
        intent_count=sum(row['intent_count'] for row in rows)
            +(0 if prior is None else prior['intent_count']))
    payload = json.dumps(dict(version=1, prior_root='0'*64 if prior is None else prior['root'],
                              archives=[list(row) for row in rows], first_created_at=first,
                              last_created_at=last, **totals),
                         sort_keys=True, separators=(',', ':'))
    root = sha256(payload.encode()).hexdigest()
    conn.execute('INSERT OR REPLACE INTO command_archive_rollup VALUES (1,?,?,?,?,?,?,?)',
                 (root, totals['archive_count'], totals['attempt_count'],
                  totals['intent_count'], first, last, payload))
    conn.executemany('DELETE FROM command_history_archives WHERE id=?',
                     ((row['id'],) for row in rows))


def _insert_archive(ledger, version, key, items, counts, stamps):
    if ledger.connection.execute(
            'SELECT COUNT(*) FROM command_history_archives').fetchone()[0] >= MAX_ARCHIVES:
        _roll_archives(ledger)
    encoded = json.dumps({'version': version, key: items}, sort_keys=True,
                         separators=(',', ':'), allow_nan=False).encode()
    payload = zlib.compress(encoded, 9)
    if (len(encoded) > MAX_ARCHIVE_DECOMPRESSED_BYTES
            or len(payload) > MAX_ARCHIVE_BYTES):
        raise InvalidData('command archive exceeds byte capacity')
    archive_id = sha256(_PREFIX[version]+encoded).hexdigest()
    ledger.connection.execute(
        'INSERT INTO command_history_archives VALUES (?,?,?,?,?,?,?,?)',
        (archive_id, *counts, min(stamps), max(stamps), payload))


def _archive_proven_unsent(ledger, min_batch=1):
    """Reclaim only creates durably proven never submitted to the venue."""
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
    if not records or len(records) < min_batch:
        return 0
    _insert_archive(ledger, 1, 'records', records,
        (len(records), len(clients),
         sum(len(row['authorizations']) for row in records),
         sum(len(row['credits']) for row in records)),
        [row['mutation']['created_at'] for row in records])
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


def _episode_record(ledger, episode, cutoff):
    """Return every hot row of one eligible episode, or None to keep it hot."""
    from .orders import OrderUpdate
    conn, episode_id, ticker = ledger.connection, episode['id'], episode['ticker']
    if ledger.position(ticker):
        return None
    credits = conn.execute('SELECT * FROM command_credits WHERE episode_id=? ORDER BY rowid',
                           (episode_id,)).fetchall()
    if any(row['state'] not in _CREDIT_STATES for row in credits):
        return None
    clients = tuple(sorted({row['owner_id'] for row in credits if row['owner_id'] is not None}))
    intents = conn.execute(f'SELECT * FROM intents WHERE client_id IN ({_marks(clients)})',
                           clients).fetchall() if clients else []
    if (len(intents) != len(clients)
            or any(row['state'] not in _INTENT_STATES for row in intents)):
        return None
    orders = conn.execute(f'SELECT * FROM order_evidence WHERE client_id IN ({_marks(clients)})',
                          clients).fetchall() if clients else []
    states = {row['client_id']: row['state'] for row in intents}
    order_ids = []
    for row in orders:
        order = OrderUpdate.decode(row['payload'])
        if (not order.terminal or order.filled != 0 or order.ticker != ticker
                or states.get(order.client_id) != 'TERMINAL'):
            return None
        order_ids.append(order.order_id)
    order_ids = tuple(order_ids)
    if order_ids and (
            conn.execute(f"SELECT 1 FROM fills WHERE json_extract(id,'$[0]') IN "
                         f"({_marks(order_ids)}) LIMIT 1", order_ids).fetchone()
            or conn.execute(f"SELECT 1 FROM pending_fills WHERE json_extract(payload,"
                            f"'$.order_id') IN ({_marks(order_ids)}) LIMIT 1",
                            order_ids).fetchone()
            or conn.execute(f"SELECT 1 FROM recovery_fills WHERE json_extract(id,'$[0]') IN "
                            f"({_marks(order_ids)}) LIMIT 1", order_ids).fetchone()
            or conn.execute(f'SELECT 1 FROM operator_fill_scopes WHERE order_id IN '
                            f'({_marks(order_ids)}) LIMIT 1', order_ids).fetchone()):
        return None
    auths = conn.execute('SELECT * FROM command_authorizations WHERE episode_id=? '
                         'ORDER BY rowid', (episode_id,)).fetchall()
    mutation_ids = tuple(sorted({row['mutation_id'] for row in auths}))
    mutations = conn.execute(f'SELECT * FROM mutation_attempts WHERE id IN '
                             f'({_marks(mutation_ids)}) ORDER BY rowid',
                             mutation_ids).fetchall() if mutation_ids else []
    # Completeness: no create/cancel for these identities may live outside
    # the episode's authorizations, and no foreign authorization may share them.
    related = set()
    for client in clients:
        related.update(row[0] for row in conn.execute(
            "SELECT id FROM mutation_attempts WHERE kind='create' "
            "AND json_extract(request,'$.client_order_id')=?", (client,)))
    for order_id in order_ids:
        related.update(row[0] for row in conn.execute(
            "SELECT id FROM mutation_attempts WHERE kind='cancel' "
            "AND json_extract(request,'$.order_id')=?", (order_id,)))
    if (len(mutations) != len(mutation_ids) or not related <= set(mutation_ids)
            or any(row['state'] not in _AUTH_STATES for row in auths)
            or (mutation_ids and conn.execute(
                f'SELECT 1 FROM command_authorizations WHERE mutation_id IN '
                f'({_marks(mutation_ids)}) AND episode_id<>? LIMIT 1',
                (*mutation_ids, episode_id)).fetchone())):
        return None
    for row in mutations:
        request = json.loads(row['request'])
        if not ((row['kind'] == 'create' and row['phase'] in _CREATE_PHASES
                 and request.get('client_order_id') in clients)
                or (row['kind'] == 'cancel' and row['phase'] in _CANCEL_PHASES
                    and request.get('order_id') in order_ids)):
            return None
    stamps = ([row['created_at'] for row in mutations] + [row['created_at'] for row in credits]
              + [row['created_at'] for row in intents] + [row['observed_at'] for row in orders])
    if not stamps or max(stamps) > cutoff:
        return None
    fees = conn.execute(f'SELECT * FROM accounting_fees WHERE client_id IN ({_marks(clients)})',
                        clients).fetchall() if clients else []
    return dict(episode={name: episode[name] for name in ('id', 'subaccount', 'ticker',
                                                         'created_at')},
                mutations=[dict(row) for row in mutations],
                authorizations=[dict(row) for row in auths],
                intents=[dict(row) for row in intents],
                orders=[dict(row) for row in orders],
                credits=[dict(row) for row in credits],
                fees=[dict(row) for row in fees])


def _archive_terminal_episodes(ledger, now, *, min_batch=EPISODE_MIN_BATCH):
    """D-129: archive exact evidence of retired zero-fill terminal episodes."""
    cutoff = (utc(now)-timedelta(seconds=EPISODE_QUIET_SECONDS)).isoformat()
    records = []
    for episode in ledger.connection.execute(
            "SELECT * FROM command_episodes WHERE state='RETIRED' AND created_at<=? "
            "ORDER BY created_at DESC LIMIT ?", (cutoff, EPISODE_SCAN_LIMIT)).fetchall():
        record = _episode_record(ledger, episode, cutoff)
        if record is not None:
            records.append(record)
            if len(records) >= EPISODE_BATCH:
                break
    if not records or len(records) < min_batch:
        return 0
    stamps = [row['created_at'] for record in records
              for row in record['mutations']+record['credits']]
    _insert_archive(ledger, 2, 'episodes', records,
        (sum(len(r['mutations']) for r in records), sum(len(r['intents']) for r in records),
         sum(len(r['authorizations']) for r in records), sum(len(r['credits']) for r in records)),
        stamps)
    conn = ledger.connection
    for record in records:
        rows = {name: tuple(item[key] for item in record[name]) for name, key in (
            ('authorizations', 'id'), ('credits', 'id'), ('mutations', 'id'),
            ('intents', 'client_id'), ('orders', 'order_id'), ('fees', 'client_id'))}
        for table, column, name in (('command_authorizations', 'id', 'authorizations'),
                                    ('command_credits', 'id', 'credits'),
                                    ('mutation_attempts', 'id', 'mutations'),
                                    ('order_evidence', 'order_id', 'orders'),
                                    ('intents', 'client_id', 'intents'),
                                    ('accounting_fees', 'client_id', 'fees')):
            values = rows[name]
            if values:
                conn.execute(f'DELETE FROM {table} WHERE {column} IN ({_marks(values)})', values)
        changed = conn.execute("UPDATE command_episodes SET state='ARCHIVED' "
                               "WHERE id=? AND state='RETIRED'",
                               (record['episode']['id'],)).rowcount
        if changed != 1:
            raise InvalidData('command archive episode state conflict')
    return len(records)


def _pressure(ledger, policy):
    snapshot = status(ledger)
    return max(snapshot.mutation_used/policy.entry_mutation_limit,
               (snapshot.intent_used+snapshot.intent_held)/policy.intent_limit,
               (snapshot.order_used+snapshot.order_held)/policy.order_limit)


def reclaim_command_capacity(ledger, policy, now):
    """Bounded, rate-limited reclamation inside the caller's writer transaction."""
    pressure = _pressure(ledger, policy)
    at_boundary = _used(ledger, MUTATION) >= policy.entry_mutation_limit
    if pressure < RECLAIM_PRESSURE and not at_boundary:
        return 0
    stamp = utc(now)
    checked = ledger.connection.execute(
        "SELECT value FROM meta WHERE key='command_reclaim_checked_at'").fetchone()
    if (not at_boundary and pressure < RECLAIM_FORCE and checked is not None
            and timedelta(0) <= stamp-datetime.fromisoformat(checked[0])
                < timedelta(seconds=RECLAIM_CHECK_SECONDS)):
        return 0
    ledger.connection.execute("INSERT OR REPLACE INTO meta VALUES "
                              "('command_reclaim_checked_at',?)", (stamp.isoformat(),))
    forced = at_boundary or pressure >= RECLAIM_FORCE
    archived = _archive_proven_unsent(ledger, 1 if forced else UNSENT_MIN_BATCH)
    archived += _archive_terminal_episodes(ledger, stamp, min_batch=1 if forced else EPISODE_MIN_BATCH)
    return archived


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
    reclaim_command_capacity(ledger, policy, now)
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
