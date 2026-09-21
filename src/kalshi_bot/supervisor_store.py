"""Transactional local control journal for the execution-disabled S1 supervisor."""
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import time

from .supervision import ControlState, SupervisorEvent, SupervisorPolicy, decide, initial_state
from .values import InvalidData, identity


SCHEMA_VERSION = "1"
MAX_EVENTS = 256
SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE control (
  singleton INTEGER PRIMARY KEY CHECK(singleton=1),
  revision INTEGER NOT NULL,
  payload TEXT NOT NULL
);
CREATE TABLE events (
  sequence INTEGER PRIMARY KEY AUTOINCREMENT,
  revision INTEGER NOT NULL,
  generation INTEGER NOT NULL,
  kind TEXT NOT NULL,
  observed_utc REAL NOT NULL,
  stale INTEGER NOT NULL CHECK(stale IN (0,1)),
  before_state TEXT NOT NULL,
  after_state TEXT NOT NULL,
  payload TEXT NOT NULL
);
CREATE INDEX events_generation ON events(generation,sequence);
"""


def _dump(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _load(value, label):
    try:
        return json.loads(value)
    except (TypeError, ValueError) as exc:
        raise InvalidData(f"invalid supervisor {label}") from exc


class SupervisorStore:
    """One small SQLite database; never shares the financial ledger."""
    def __init__(self, path: Path | str, *, scope_id: str, clock=time.time,
                 event_limit: int = MAX_EVENTS):
        self.path = Path(path) if str(path) != ":memory:" else Path(":memory:")
        self.scope_id = identity(scope_id)
        if type(event_limit) is not int or not 16 <= event_limit <= 4096:
            raise InvalidData("supervisor event limit outside bounds")
        self.event_limit = event_limit
        self.clock = clock
        self.connection = sqlite3.connect(str(path), timeout=5)
        self.connection.row_factory = sqlite3.Row
        try:
            self._open()
        except BaseException:
            self.connection.close()
            raise

    def _open(self):
        tables = {row[0] for row in self.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        expected = {"meta", "control", "events"}
        if tables and tables != expected:
            raise InvalidData("incompatible supervisor control schema")
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        if not tables:
            now = float(self.clock())
            state = initial_state(self.scope_id, now)
            with self.connection:
                self.connection.executescript(SCHEMA)
                self.connection.execute("INSERT INTO meta VALUES ('schema',?)", (SCHEMA_VERSION,))
                self.connection.execute("INSERT INTO meta VALUES ('scope',?)", (self.scope_id,))
                self.connection.execute("INSERT INTO control VALUES (1,0,?)", (_dump(state.to_dict()),))
        meta = dict(self.connection.execute("SELECT key,value FROM meta"))
        if meta != {"schema": SCHEMA_VERSION, "scope": self.scope_id}:
            raise InvalidData("supervisor schema or scope mismatch")
        self.read()

    @contextmanager
    def transaction(self):
        if self.connection.in_transaction:
            raise RuntimeError("nested supervisor transaction")
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            yield

    def close(self):
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _read_row(self):
        row = self.connection.execute(
            "SELECT revision,payload FROM control WHERE singleton=1").fetchone()
        if row is None or type(row["revision"]) is not int or row["revision"] < 0:
            raise InvalidData("missing supervisor control state")
        state = ControlState.from_dict(_load(row["payload"], "control state"))
        if state.scope_id != self.scope_id:
            raise InvalidData("supervisor control scope mismatch")
        return row["revision"], state

    def read(self):
        return self._read_row()[1]

    def revision(self):
        return self._read_row()[0]

    def apply(self, event: SupervisorEvent, policy=SupervisorPolicy()):
        if not isinstance(event, SupervisorEvent):
            raise InvalidData("typed supervisor event required")
        with self.transaction():
            revision, before = self._read_row()
            decision = decide(before, event, policy)
            after = decision.state
            new_revision = revision+1
            cursor = self.connection.execute(
                "UPDATE control SET revision=?,payload=? WHERE singleton=1 AND revision=?",
                (new_revision, _dump(after.to_dict()), revision))
            if cursor.rowcount != 1:
                raise InvalidData("supervisor revision changed concurrently")
            self.connection.execute(
                "INSERT INTO events(revision,generation,kind,observed_utc,stale,before_state,"
                "after_state,payload) VALUES (?,?,?,?,?,?,?,?)",
                (new_revision, after.generation, event.kind.value, event.observed_utc,
                 int(decision.stale), before.state.value, after.state.value,
                 _dump(event.to_dict())))
            self.connection.execute("DELETE FROM events WHERE sequence <= ("
                "SELECT coalesce(max(sequence),0)-? FROM events)", (self.event_limit,))
        return decision

    def history(self, *, limit=64):
        if type(limit) is not int or not 1 <= limit <= self.event_limit:
            raise InvalidData("invalid supervisor history limit")
        rows = self.connection.execute(
            "SELECT sequence,revision,generation,kind,observed_utc,stale,before_state,"
            "after_state,payload FROM events ORDER BY sequence DESC LIMIT ?", (limit,)).fetchall()
        return tuple(dict(row) | {"payload": _load(row["payload"], "event payload")}
                     for row in reversed(rows))
