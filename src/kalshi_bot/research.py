"""Research dataset for calibration (operator request, 2026-09-26; D-151).

Durable, append-only evidence about what the bot decided and how it turned out:
entry lifecycles, fills and their mark-outs, protective withdrawals, public
trades, hourly health and reward estimates. It lives in its own SQLite file,
separate from the financial ledger, and one background thread writes it.

Producers never block and never raise: ``record`` only enqueues; a full queue
or a write error is counted and the record dropped. Nothing here is trading,
accounting or reward authority.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
from queue import Empty, Full, Queue
import sqlite3
from threading import Event, Lock, Thread

TABLES = frozenset((
    'entries', 'entry_ends', 'fills', 'fill_marks', 'withdrawals', 'withdrawal_marks',
    'trades', 'health_hourly', 'reward_estimates', 'reward_credits'))
# Rows whose key is a venue identity are stored once (re-delivery is ignored).
UNIQUE_KEY_TABLES = frozenset(('entry_ends', 'fills', 'trades', 'reward_credits',
                               'reward_estimates', 'health_hourly'))
RETENTION_DAYS = 120
BATCH = 256


def _encode(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (set, frozenset, tuple)):
        return list(value)
    raise TypeError('unsupported research value')


class ResearchStore:
    def __init__(self, path, *, capacity=4096, now=lambda: datetime.now(timezone.utc)):
        self.path = Path(path)
        self.now = now
        self._queue = Queue(capacity)
        self._stop, self._ready = Event(), Event()
        self._lock = Lock()
        self._thread = None
        self.accepted = self.written = self.dropped = self.failures = 0
        self.last_error = None

    # ----- producer side (event loop): never blocks, never raises --------
    def record(self, table, key, **fields):
        try:
            if table not in TABLES or self._stop.is_set():
                raise ValueError('unknown research table or closed store')
            payload = json.dumps(fields, default=_encode, separators=(',', ':'),
                                 sort_keys=True, allow_nan=False)
            self._queue.put_nowait((table, str(key), self.now().isoformat(), payload))
            with self._lock:
                self.accepted += 1
            return True
        except (Full, TypeError, ValueError):
            with self._lock:
                self.dropped += 1
            return False

    # ----- writer thread --------------------------------------------------
    def start(self):
        self._thread = Thread(target=self._run, name='kalshi-research', daemon=True)
        self._thread.start()
        self._ready.wait(5)
        return self

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA synchronous=NORMAL')
        for table in sorted(TABLES):
            conn.execute(f'CREATE TABLE IF NOT EXISTS {table} (id INTEGER PRIMARY KEY, '
                         'at TEXT NOT NULL, key TEXT NOT NULL, payload TEXT NOT NULL)')
            conn.execute(f'CREATE INDEX IF NOT EXISTS {table}_at ON {table}(at)')
            unique = 'UNIQUE ' if table in UNIQUE_KEY_TABLES else ''
            conn.execute(f'CREATE {unique}INDEX IF NOT EXISTS {table}_key ON {table}(key)')
        conn.commit()
        return conn

    def _prune(self, conn):
        cutoff = (self.now()-timedelta(days=RETENTION_DAYS)).isoformat()
        for table in sorted(TABLES):
            conn.execute(f'DELETE FROM {table} WHERE at < ?', (cutoff,))
        conn.commit()

    def _run(self):
        conn = None
        try:
            conn = self._connect()
            self._prune(conn)
            pruned_at = self.now()
            self._ready.set()
            while not self._stop.is_set() or not self._queue.empty():
                try:
                    rows = [self._queue.get(timeout=.5)]
                except Empty:
                    continue
                while len(rows) < BATCH:
                    try:
                        rows.append(self._queue.get_nowait())
                    except Empty:
                        break
                try:
                    with conn:
                        for table, key, at, payload in rows:
                            verb = 'INSERT OR IGNORE' if table in UNIQUE_KEY_TABLES else 'INSERT'
                            conn.execute(f'{verb} INTO {table}(at,key,payload) VALUES (?,?,?)',
                                         (at, key, payload))
                    with self._lock:
                        self.written += len(rows)
                except sqlite3.Error as exc:
                    with self._lock:
                        self.failures += 1
                        self.dropped += len(rows)
                        self.last_error = type(exc).__name__
                if self.now()-pruned_at > timedelta(hours=6):
                    self._prune(conn)
                    pruned_at = self.now()
        except Exception as exc:
            with self._lock:
                self.failures += 1
                self.last_error = type(exc).__name__
        finally:
            self._ready.set()
            if conn is not None:
                conn.close()

    def close(self, timeout=5):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)

    def status(self):
        with self._lock:
            return dict(path=self.path.name, accepted=self.accepted, written=self.written,
                        dropped=self.dropped, failures=self.failures,
                        backlog=self._queue.qsize(), last_error=self.last_error,
                        alive=bool(self._thread and self._thread.is_alive()))
