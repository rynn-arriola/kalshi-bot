"""Transactional local control journal for the execution-disabled S1 supervisor."""
from contextlib import contextmanager
from dataclasses import dataclass
import json
import math
from pathlib import Path
import sqlite3
import time

from .supervision import (AttentionReason, ControlState, EventKind, SupervisorEvent,
                          SupervisorPolicy, decide, initial_state)
from .values import InvalidData, identity, integer


SCHEMA_VERSION = "4"
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
CREATE TABLE native_state (
  singleton INTEGER PRIMARY KEY CHECK(singleton=1),
  parent_session TEXT,
  child_id TEXT,
  child_generation INTEGER,
  stage TEXT NOT NULL,
  diagnostic_pid INTEGER,
  build_fingerprint TEXT NOT NULL,
  config_fingerprint TEXT NOT NULL
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

NATIVE_STAGES = frozenset(("idle", "reserved", "created", "bound", "exited", "orphan_released"))


@dataclass(frozen=True)
class NativeState:
    parent_session: str | None
    child_id: str | None
    child_generation: int | None
    stage: str
    diagnostic_pid: int | None
    build_fingerprint: str
    config_fingerprint: str

    def __post_init__(self):
        for value in (self.parent_session, self.child_id):
            if value is not None:
                identity(value)
        if (self.child_id is None) != (self.child_generation is None):
            raise InvalidData("native child identity and generation must be paired")
        if self.child_generation is not None:
            integer(self.child_generation, 0, 2**63-1)
        if self.stage not in NATIVE_STAGES:
            raise InvalidData("invalid native reservation stage")
        if self.child_id is None and self.stage not in {"idle", "exited", "orphan_released"}:
            raise InvalidData("native reservation stage requires a child")
        if self.diagnostic_pid is not None:
            integer(self.diagnostic_pid, 1, 2**32-1)
            if self.child_id is None:
                raise InvalidData("native PID requires a child reservation")
        for value in (self.build_fingerprint, self.config_fingerprint):
            if value:
                identity(value)


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
                 event_limit: int = MAX_EVENTS,
                 mode: str = "create_if_missing", security_sid=None):
        self.path = Path(path) if str(path) != ":memory:" else Path(":memory:")
        self.scope_id = identity(scope_id)
        if mode not in {"create_if_missing", "create_only", "open_existing"}:
            raise InvalidData("invalid supervisor store open mode")
        self.mode = mode
        if mode == "open_existing" and str(path) != ":memory:" and not Path(path).is_file():
            raise InvalidData("supervisor control store does not exist")
        if type(event_limit) is not int or not 16 <= event_limit <= 4096:
            raise InvalidData("supervisor event limit outside bounds")
        self.event_limit = event_limit
        self.clock = clock
        self.monotonic_clock = monotonic_clock
        if boot_id is not None and not callable(boot_id):
            identity(boot_id)
        self.boot_id = boot_id
        self.file_guard = None
        target = (Path(path).resolve().as_uri()+"?mode=rw"
                  if mode == "open_existing" and str(path) != ":memory:" else str(path))
        try:
            if security_sid is not None:
                from .windows import ProtectedControlFiles
                self.file_guard = ProtectedControlFiles(path, security_sid,
                    create=mode == "create_only", readonly=True)
                if mode == "open_existing":
                    # Schema is immutable in S2A and checkpointed by fixture
                    # initialization. Inspect it without creating sidecars first.
                    check = sqlite3.connect(Path(path).resolve().as_uri()+
                                            "?mode=ro&immutable=1", uri=True)
                    try:
                        meta = dict(check.execute("SELECT key,value FROM meta"))
                        if meta != {"schema": SCHEMA_VERSION, "scope": self.scope_id}:
                            raise InvalidData("supervisor schema or scope mismatch")
                    finally:
                        check.close()
                self.file_guard.validate_sidecars(create_missing=True)
            self.connection = sqlite3.connect(target, timeout=5,
                                             uri=mode == "open_existing")
            self.connection.row_factory = sqlite3.Row
            self._open()
        except BaseException:
            if hasattr(self, "connection"):
                self.connection.close()
            if self.file_guard:
                self.file_guard.close()
            raise

    def _open(self):
        tables = {row[0] for row in self.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        expected = {"meta", "control", "clock_state", "native_state", "events"}
        if tables and tables != expected:
            raise InvalidData("incompatible supervisor control schema")
        if self.mode == "create_only" and tables:
            raise InvalidData("supervisor control store already exists")
        if self.mode == "open_existing" and not tables:
            raise InvalidData("supervisor control store is empty")
        if tables and dict(self.connection.execute("SELECT key,value FROM meta")) != {
                "schema": SCHEMA_VERSION, "scope": self.scope_id}:
            raise InvalidData("supervisor schema or scope mismatch")
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
                self.connection.execute(
                    "INSERT INTO native_state VALUES (1,NULL,NULL,NULL,'idle',NULL,'','')")
        meta = dict(self.connection.execute("SELECT key,value FROM meta"))
        if meta != {"schema": SCHEMA_VERSION, "scope": self.scope_id}:
            raise InvalidData("supervisor schema or scope mismatch")
        self.read()
        self._read_clock()
        self.read_native()

    @classmethod
    def initialize_fixture(cls, path, *, scope_id, **values):
        checked_scope = identity(scope_id)
        if not (checked_scope.startswith("test-") or "-test-" in checked_scope):
            raise InvalidData("S2 fixture scope must start with test-")
        return cls(path, scope_id=checked_scope, mode="create_only", **values)

    @classmethod
    def open_existing(cls, path, *, scope_id, **values):
        return cls(path, scope_id=scope_id, mode="open_existing", **values)

    @staticmethod
    def read_only_snapshot(path, *, scope_id, security_sid=None):
        """Read the existing S2 control view without creating WAL/files."""
        path = Path(path)
        if not path.is_file():
            raise InvalidData("supervisor control store does not exist")
        guard = connection = None
        try:
            if security_sid is not None:
                from .windows import ProtectedControlFiles
                guard = ProtectedControlFiles(path, security_sid, readonly=True)
            connection = sqlite3.connect(path.resolve().as_uri()+"?mode=ro", uri=True,
                                         timeout=5)
            connection.row_factory = sqlite3.Row
            connection.execute("BEGIN")
            meta = dict(connection.execute("SELECT key,value FROM meta"))
            if meta != {"schema": SCHEMA_VERSION, "scope": identity(scope_id)}:
                raise InvalidData("supervisor schema or scope mismatch")
            row = connection.execute(
                "SELECT revision,payload FROM control WHERE singleton=1").fetchone()
            native = connection.execute(
                "SELECT parent_session,child_id,child_generation,stage,diagnostic_pid,"
                "build_fingerprint,config_fingerprint FROM native_state WHERE singleton=1"
            ).fetchone()
            if row is None or native is None:
                raise InvalidData("missing supervisor control state")
            return (int(row["revision"]),
                    ControlState.from_dict(_load(row["payload"], "control state")),
                    NativeState(**dict(native)))
        finally:
            if connection is not None:
                connection.close()
            if guard is not None:
                guard.close()

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
        try:
            self.connection.close()
        finally:
            if self.file_guard:
                self.file_guard.close()

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

    def read_native(self):
        row = self.connection.execute(
            "SELECT parent_session,child_id,child_generation,stage,diagnostic_pid,"
            "build_fingerprint,config_fingerprint FROM native_state WHERE singleton=1"
        ).fetchone()
        if row is None:
            raise InvalidData("missing supervisor native state")
        return NativeState(**dict(row))

    def _write_native(self, value):
        if not isinstance(value, NativeState):
            raise InvalidData("typed native state required")
        cursor = self.connection.execute(
            "UPDATE native_state SET parent_session=?,child_id=?,child_generation=?,"
            "stage=?,diagnostic_pid=?,build_fingerprint=?,config_fingerprint=? "
            "WHERE singleton=1", (value.parent_session, value.child_id,
            value.child_generation, value.stage, value.diagnostic_pid,
            value.build_fingerprint, value.config_fingerprint))
        if cursor.rowcount != 1:
            raise InvalidData("missing supervisor native state")

    def _apply_locked(self, event, policy, *, coalesce_noop_tick=False):
        revision, before = self._read_row()
        boot_id, wall_utc, monotonic, control_utc, clock_trusted = (
            self._control_sample(before))
        decision = decide(before, event, policy, control_utc=control_utc,
                          clock_trusted=clock_trusted)
        after = decision.state
        materially_idle = False
        if (coalesce_noop_tick and event.kind == EventKind.TICK
                and not decision.actions and not decision.stale):
            before_material = before.to_dict()
            after_material = after.to_dict()
            before_material.pop("updated_utc")
            after_material.pop("updated_utc")
            materially_idle = after_material == before_material
        if materially_idle:
            # An idle tick still samples and validates both clocks, but it need
            # not fsync a journal row whose only change is the observation time.
            # The prior durable clock sample remains the continuity anchor; any
            # later drift, reboot, deadline or policy transition is persisted.
            return decision
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
             control_utc, int(clock_trusted), int(decision.stale),
             before.state.value, after.state.value, _dump(event.to_dict())))
        self._prune_events()
        if before.child_id is not None and after.child_id is None:
            native = self.read_native()
            self._write_native(NativeState(native.parent_session, None, None,
                "orphan_released" if event.kind == EventKind.ORPHAN_RELEASED else "exited",
                None, native.build_fingerprint, native.config_fingerprint))
        return decision

    def _prune_events(self):
        self.connection.execute("DELETE FROM events WHERE sequence <= ("
            "SELECT coalesce(max(sequence),0)-? FROM events)", (self.event_limit,))

    def apply(self, event: SupervisorEvent, policy=SupervisorPolicy()):
        if not isinstance(event, SupervisorEvent):
            raise InvalidData("typed supervisor event required")
        with self.transaction():
            return self._apply_locked(event, policy)

    def tick(self, event: SupervisorEvent, policy=SupervisorPolicy()):
        """Evaluate a host timer tick and coalesce a materially idle result."""
        if not isinstance(event, SupervisorEvent) or event.kind != EventKind.TICK:
            raise InvalidData("typed supervisor tick required")
        with self.transaction():
            return self._apply_locked(event, policy, coalesce_noop_tick=True)

    def begin_parent_session(self, session_id, *, observed_utc=None,
                             policy=SupervisorPolicy()):
        session_id = identity(session_id)
        observed = float(self.clock() if observed_utc is None else observed_utc)
        with self.transaction():
            native = self.read_native()
            revision, state = self._read_row()
            if state.desired_armed or state.child_id is not None:
                decision = self._apply_locked(SupervisorEvent(
                    EventKind.LOCAL_SAFETY_FAULT, observed,
                    attention_reason=AttentionReason.OWNER_LOST), policy)
            else:
                decision = None
                cursor = self.connection.execute(
                    "UPDATE control SET revision=? WHERE singleton=1 AND revision=?",
                    (revision+1, revision))
                if cursor.rowcount != 1:
                    raise InvalidData("supervisor revision changed concurrently")
                self.connection.execute(
                    "INSERT INTO events(revision,generation,kind,observed_utc,control_utc,"
                    "clock_trusted,stale,before_state,after_state,payload) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (revision+1, state.generation, "parent_session", observed,
                     state.updated_utc, 1, 0, state.state.value, state.state.value,
                     _dump({"parent_session": session_id})))
                self._prune_events()
            self._write_native(NativeState(session_id, native.child_id,
                native.child_generation, native.stage, native.diagnostic_pid,
                native.build_fingerprint, native.config_fingerprint))
        return decision

    def reserve_start(self, event, *, parent_session, policy=SupervisorPolicy()):
        if event.kind != EventKind.START_REQUESTED:
            raise InvalidData("start reservation event required")
        parent_session = identity(parent_session)
        with self.transaction():
            native = self.read_native()
            if native.parent_session != parent_session or native.child_id is not None:
                raise InvalidData("native parent session or reservation mismatch")
            decision = self._apply_locked(event, policy)
            if decision.stale or decision.state.child_id != event.child_id:
                return decision
            self._write_native(NativeState(parent_session, event.child_id,
                decision.state.child_generation, "reserved", None,
                decision.state.build_fingerprint, decision.state.config_fingerprint))
            return decision

    def update_native_stage(self, *, parent_session, child_id, child_generation,
                            stage, diagnostic_pid=None):
        parent_session = identity(parent_session)
        child_id = identity(child_id)
        integer(child_generation, 0, 2**63-1)
        if stage not in {"created", "bound"}:
            raise InvalidData("invalid native stage update")
        with self.transaction():
            revision, state = self._read_row()
            native = self.read_native()
            if ((native.parent_session, native.child_id, native.child_generation)
                    != (parent_session, child_id, child_generation)
                    or (native.stage, stage) not in {("reserved", "created"),
                                                     ("created", "bound")}):
                raise InvalidData("stale native stage update")
            updated = NativeState(parent_session, child_id, child_generation,
                stage, diagnostic_pid, native.build_fingerprint,
                native.config_fingerprint)
            self._write_native(updated)
            cursor = self.connection.execute(
                "UPDATE control SET revision=? WHERE singleton=1 AND revision=?",
                (revision+1, revision))
            if cursor.rowcount != 1:
                raise InvalidData("supervisor revision changed concurrently")
            self.connection.execute(
                "INSERT INTO events(revision,generation,kind,observed_utc,control_utc,"
                "clock_trusted,stale,before_state,after_state,payload) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (revision+1, state.generation, "native_"+stage, state.updated_utc,
                 state.updated_utc, 1, 0, state.state.value, state.state.value,
                 _dump({"child_id": child_id, "child_generation": child_generation,
                        "stage": stage, "diagnostic_pid": diagnostic_pid})))
            self._prune_events()
        return updated

    def history(self, *, limit=64):
        if type(limit) is not int or not 1 <= limit <= self.event_limit:
            raise InvalidData("invalid supervisor history limit")
        rows = self.connection.execute(
            "SELECT sequence,revision,generation,kind,observed_utc,control_utc,clock_trusted,"
            "stale,before_state,after_state,payload FROM events "
            "ORDER BY sequence DESC LIMIT ?", (limit,)).fetchall()
        return tuple(dict(row) | {"payload": _load(row["payload"], "event payload")}
                     for row in reversed(rows))
