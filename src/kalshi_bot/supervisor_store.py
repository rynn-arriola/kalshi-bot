"""Transactional local control journal for the execution-disabled S1 supervisor."""
from contextlib import contextmanager
import json
import math
from pathlib import Path
import sqlite3
import time

from .supervision import ControlState, SupervisorEvent, SupervisorPolicy, decide, initial_state
from .values import InvalidData, identity


SCHEMA_VERSION = "3"
MAX_EVENTS = 256
CLOCK_SKEW_SECONDS = 2.0
DEFAULT_BOOT_PREFIX = "estimated-"
SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE control (
  singleton INTEGER PRIMARY KEY CHECK(singleton=1),
  revision INTEGER NOT NULL,
  payload TEXT NOT NULL
);
CREATE TABLE clock_state (
  singleton INTEGER PRIMARY KEY CHECK(singleton=1),
  boot_id TEXT NOT NULL,
  wall_utc REAL NOT NULL,
  monotonic REAL NOT NULL,
  control_utc REAL NOT NULL
);
CREATE TABLE events (
  sequence INTEGER PRIMARY KEY AUTOINCREMENT,
  revision INTEGER NOT NULL,
  generation INTEGER NOT NULL,
  kind TEXT NOT NULL,
  observed_utc REAL NOT NULL,
  control_utc REAL NOT NULL,
  clock_trusted INTEGER NOT NULL CHECK(clock_trusted IN (0,1)),
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
                 monotonic_clock=time.monotonic,
                 boot_id=None,
                 event_limit: int = MAX_EVENTS):
        self.path = Path(path) if str(path) != ":memory:" else Path(":memory:")
        self.scope_id = identity(scope_id)
        if type(event_limit) is not int or not 16 <= event_limit <= 4096:
            raise InvalidData("supervisor event limit outside bounds")
        self.event_limit = event_limit
        self.clock = clock
        self.monotonic_clock = monotonic_clock
        if boot_id is not None and not callable(boot_id):
            identity(boot_id)
        self.boot_id = boot_id
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
        expected = {"meta", "control", "clock_state", "events"}
        if tables and tables != expected:
            raise InvalidData("incompatible supervisor control schema")
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        if not tables:
            boot_id, wall_utc, monotonic = self._clock_sample()
            state = initial_state(self.scope_id, wall_utc)
            with self.connection:
                self.connection.executescript(SCHEMA)
                self.connection.execute("INSERT INTO meta VALUES ('schema',?)", (SCHEMA_VERSION,))
                self.connection.execute("INSERT INTO meta VALUES ('scope',?)", (self.scope_id,))
                self.connection.execute("INSERT INTO control VALUES (1,0,?)", (_dump(state.to_dict()),))
                self.connection.execute("INSERT INTO clock_state VALUES (1,?,?,?,?)",
                    (boot_id, wall_utc, monotonic, wall_utc))
        meta = dict(self.connection.execute("SELECT key,value FROM meta"))
        if meta != {"schema": SCHEMA_VERSION, "scope": self.scope_id}:
            raise InvalidData("supervisor schema or scope mismatch")
        self.read()
        self._read_clock()

    def _clock_sample(self):
        wall_utc = float(self.clock())
        monotonic = float(self.monotonic_clock())
        if (not math.isfinite(wall_utc) or wall_utc < 0
                or not math.isfinite(monotonic) or monotonic < 0):
            raise InvalidData("invalid supervisor clock sample")
        if self.boot_id is None:
            boot_id = f"{DEFAULT_BOOT_PREFIX}{wall_utc-monotonic:.9f}"
        else:
            boot_id = self.boot_id() if callable(self.boot_id) else self.boot_id
        return identity(boot_id), wall_utc, monotonic

    def _read_clock(self):
        row = self.connection.execute(
            "SELECT boot_id,wall_utc,monotonic,control_utc FROM clock_state "
            "WHERE singleton=1").fetchone()
        if row is None:
            raise InvalidData("missing supervisor clock state")
        boot_id = identity(row["boot_id"])
        values = tuple(float(row[field]) for field in (
            "wall_utc", "monotonic", "control_utc"))
        if any(not math.isfinite(value) or value < 0 for value in values):
            raise InvalidData("invalid supervisor clock state")
        return (boot_id,)+values

    def _control_sample(self, state):
        prior_boot, prior_wall, prior_monotonic, prior_control = self._read_clock()
        boot_id, wall_utc, monotonic = self._clock_sample()
        monotonic_delta = monotonic-prior_monotonic
        wall_delta = wall_utc-prior_wall
        delta_continuous = (monotonic_delta >= 0
            and abs(wall_delta-monotonic_delta) <= CLOCK_SKEW_SECONDS)
        if self.boot_id is None:
            # The two clocks are sampled sequentially, so their estimated boot
            # epoch is evidence with tolerance, not an exact identifier.  Keep
            # the persisted identity stable while their deltas prove continuity.
            boot_continuous = delta_continuous
            if boot_continuous:
                boot_id = prior_boot
        else:
            boot_continuous = boot_id == prior_boot
        trusted = boot_continuous and delta_continuous
        control_utc = (prior_control+monotonic_delta if trusted
                       else max(prior_control, state.updated_utc))
        return boot_id, wall_utc, monotonic, control_utc, trusted

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
            boot_id, wall_utc, monotonic, control_utc, clock_trusted = (
                self._control_sample(before))
            decision = decide(before, event, policy, control_utc=control_utc,
                              clock_trusted=clock_trusted)
            after = decision.state
            new_revision = revision+1
            cursor = self.connection.execute(
                "UPDATE control SET revision=?,payload=? WHERE singleton=1 AND revision=?",
                (new_revision, _dump(after.to_dict()), revision))
            if cursor.rowcount != 1:
                raise InvalidData("supervisor revision changed concurrently")
            self.connection.execute(
                "UPDATE clock_state SET boot_id=?,wall_utc=?,monotonic=?,control_utc=? "
                "WHERE singleton=1", (boot_id, wall_utc, monotonic, control_utc))
            self.connection.execute(
                "INSERT INTO events(revision,generation,kind,observed_utc,control_utc,"
                "clock_trusted,stale,before_state,after_state,payload) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (new_revision, after.generation, event.kind.value, event.observed_utc,
                 control_utc, int(clock_trusted),
                 int(decision.stale), before.state.value, after.state.value,
                 _dump(event.to_dict())))
            self.connection.execute("DELETE FROM events WHERE sequence <= ("
                "SELECT coalesce(max(sequence),0)-? FROM events)", (self.event_limit,))
        return decision

    def history(self, *, limit=64):
        if type(limit) is not int or not 1 <= limit <= self.event_limit:
            raise InvalidData("invalid supervisor history limit")
        rows = self.connection.execute(
            "SELECT sequence,revision,generation,kind,observed_utc,control_utc,clock_trusted,"
            "stale,before_state,after_state,payload FROM events "
            "ORDER BY sequence DESC LIMIT ?", (limit,)).fetchall()
        return tuple(dict(row) | {"payload": _load(row["payload"], "event payload")}
                     for row in reversed(rows))
