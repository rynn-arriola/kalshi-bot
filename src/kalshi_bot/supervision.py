"""Pure, execution-disabled supervisor policy for D-050 S1.

The module classifies local process lifecycle evidence.  It cannot authorize
entries, access an account, launch a process or modify the financial ledger.
"""
from dataclasses import dataclass, replace
from enum import StrEnum
import math

from .values import InvalidData, identity, integer


class SupervisorState(StrEnum):
    DISARMED = "disarmed"
    STARTING = "starting"
    RECOVERING = "recovering"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    STOPPING = "stopping"
    BACKOFF = "backoff"
    ATTENTION_REQUIRED = "attention_required"


class EventKind(StrEnum):
    ARM = "arm"
    STOP = "stop"
    START_REQUESTED = "start_requested"
    SPAWN_FAILED = "spawn_failed"
    CHILD_STARTED = "child_started"
    CHILD_STATUS = "child_status"
    CHILD_RESULT = "child_result"
    HOLDS_RESOLVED = "holds_resolved"
    LOCAL_SAFETY_FAULT = "local_safety_fault"
    ORPHAN_RELEASED = "orphan_released"
    TICK = "tick"


class ChildPhase(StrEnum):
    STARTING = "starting"
    RECOVERING = "recovering"
    HEALTHY = "healthy"
    DEGRADED = "degraded"


class ChildOutcome(StrEnum):
    CLEAN = "clean"
    TRANSIENT_FAILURE = "transient_failure"
    UNEXPECTED_DEATH = "unexpected_death"
    STARTUP_REFUSED = "startup_refused"
    RETRY_EXHAUSTED = "retry_exhausted"
    INTEGRITY_FAILURE = "integrity_failure"
    UNKNOWN_FAILURE = "unknown_failure"


class SupervisorAction(StrEnum):
    START_DUE = "start_due"
    SPAWN_RECOVERY = "spawn_recovery"
    REQUEST_GRACEFUL_STOP = "request_graceful_stop"


class AttentionReason(StrEnum):
    CLOCK_REGRESSED = "clock_regressed"
    CLOCK_UNTRUSTED = "clock_untrusted"
    RESTART_BUDGET_EXHAUSTED = "restart_budget_exhausted"
    STARTUP_REFUSED = "startup_refused"
    RETRY_EXHAUSTED = "retry_exhausted"
    INTEGRITY_FAILURE = "integrity_failure"
    UNKNOWN_FAILURE = "unknown_failure"
    PROGRESS_STALLED = "progress_stalled"
    STARTUP_TIMEOUT = "startup_timeout"
    SHUTDOWN_TIMEOUT = "shutdown_timeout"
    OWNER_LOST = "owner_lost"
    CONTROL_ABANDONED = "control_abandoned"
    IPC_FAILURE = "ipc_failure"
    POWER_STATE_CHANGED = "power_state_changed"
    RECOVERY_FENCE_UNKNOWN = "recovery_fence_unknown"


LOCAL_SAFETY_REASONS = frozenset({
    AttentionReason.OWNER_LOST,
    AttentionReason.CONTROL_ABANDONED,
    AttentionReason.IPC_FAILURE,
    AttentionReason.POWER_STATE_CHANGED,
    AttentionReason.RECOVERY_FENCE_UNKNOWN,
})


def _time(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidData(f"{field} must be a finite timestamp")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise InvalidData(f"{field} must be a finite timestamp")
    return result


def _optional_time(value, field):
    return None if value is None else _time(value, field)


def _enum(value, kind, field):
    try:
        return value if isinstance(value, kind) else kind(value)
    except (TypeError, ValueError) as exc:
        raise InvalidData(f"invalid {field}") from exc


def _identities(values, field):
    if not isinstance(values, (tuple, list)) or len(values) > 32:
        raise InvalidData(f"invalid {field}")
    result = tuple(identity(value) for value in values)
    if len(set(result)) != len(result):
        raise InvalidData(f"duplicate {field}")
    return result


@dataclass(frozen=True)
class SupervisorPolicy:
    restart_delays: tuple[float, ...] = (10.0, 20.0, 40.0, 60.0)
    max_incident_restarts: int = 3
    rolling_restart_limit: int = 3
    rolling_restart_seconds: float = 600.0
    healthy_reset_seconds: float = 600.0
    heartbeat_seconds: float = 2.0
    progress_timeout_seconds: float = 30.0
    # D-136: measured live starts take 56-58 s to runtime_started (candidate
    # discovery with public 429 retries plus quota refresh); 60 s stopped a
    # healthy start. Still bounded, so a hung start requests a graceful stop.
    startup_timeout_seconds: float = 180.0
    shutdown_timeout_seconds: float = 60.0
    # The longest work deadline a child may declare beyond its last progress
    # (formerly the startup allowance; unchanged at 60 s).
    work_deadline_limit_seconds: float = 60.0

    def __post_init__(self):
        if not isinstance(self.restart_delays, (tuple, list)) or not self.restart_delays:
            raise InvalidData("restart delays required")
        delays = tuple(_time(value, "restart delay") for value in self.restart_delays)
        if any(value <= 0 for value in delays) or tuple(sorted(delays)) != delays:
            raise InvalidData("restart delays must be positive and nondecreasing")
        object.__setattr__(self, "restart_delays", delays)
        integer(self.max_incident_restarts, 1, 32)
        integer(self.rolling_restart_limit, 1, 32)
        for field in ("rolling_restart_seconds", "healthy_reset_seconds", "heartbeat_seconds",
                      "progress_timeout_seconds", "startup_timeout_seconds",
                      "shutdown_timeout_seconds", "work_deadline_limit_seconds"):
            value = _time(getattr(self, field), field)
            if value <= 0:
                raise InvalidData(f"{field} must be positive")
            object.__setattr__(self, field, value)


@dataclass(frozen=True)
class ControlState:
    scope_id: str
    generation: int
    state: SupervisorState
    desired_armed: bool
    stop_latched: bool
    build_fingerprint: str
    config_fingerprint: str
    incident_attempts: int
    restart_attempts_utc: tuple[float, ...]
    next_restart_utc: float | None
    child_id: str | None
    child_generation: int | None
    start_requested_utc: float | None
    child_started_utc: float | None
    last_heartbeat_utc: float | None
    last_progress_utc: float | None
    progress_sequence: int
    work_deadline_utc: float | None
    healthy_since_utc: float | None
    stop_requested_utc: float | None
    attention_reason: AttentionReason | None
    retry_holds: tuple[str, ...]
    recovery_reasons: tuple[str, ...]
    updated_utc: float
    schema_version: int = 3

    def __post_init__(self):
        identity(self.scope_id)
        integer(self.schema_version, 3, 3)
        integer(self.generation, 0, 2**63-1)
        object.__setattr__(self, "state", _enum(self.state, SupervisorState, "supervisor state"))
        if type(self.desired_armed) is not bool or type(self.stop_latched) is not bool:
            raise InvalidData("supervisor booleans required")
        for field in ("build_fingerprint", "config_fingerprint"):
            value = getattr(self, field)
            if value:
                identity(value)
        object.__setattr__(self, "updated_utc", _time(self.updated_utc, "updated time"))
        integer(self.incident_attempts, 0, 32)
        if not isinstance(self.restart_attempts_utc, (tuple, list)) or len(self.restart_attempts_utc) > 64:
            raise InvalidData("invalid restart attempt history")
        attempts = tuple(_time(value, "restart attempt") for value in self.restart_attempts_utc)
        if tuple(sorted(attempts)) != attempts or any(value > self.updated_utc for value in attempts):
            raise InvalidData("restart attempts are not ordered")
        object.__setattr__(self, "restart_attempts_utc", attempts)
        object.__setattr__(self, "next_restart_utc", _optional_time(self.next_restart_utc, "next restart"))
        if self.child_id is not None:
            identity(self.child_id)
        if self.child_generation is not None:
            integer(self.child_generation, 0, 2**63-1)
        for field in ("start_requested_utc", "child_started_utc", "last_heartbeat_utc",
                      "last_progress_utc", "work_deadline_utc", "healthy_since_utc",
                      "stop_requested_utc"):
            object.__setattr__(self, field, _optional_time(getattr(self, field), field))
        integer(self.progress_sequence, 0, 2**63-1)
        if self.attention_reason is not None:
            object.__setattr__(self, "attention_reason",
                               _enum(self.attention_reason, AttentionReason, "attention reason"))
        object.__setattr__(self, "retry_holds", _identities(self.retry_holds, "retry holds"))
        object.__setattr__(self, "recovery_reasons",
                           _identities(self.recovery_reasons, "recovery reasons"))
        child_states = {SupervisorState.STARTING, SupervisorState.RECOVERING,
                        SupervisorState.HEALTHY, SupervisorState.DEGRADED,
                        SupervisorState.STOPPING}
        if self.state in child_states and self.child_id is None:
            raise InvalidData("active supervisor state requires child identity")
        if (self.child_id is None) != (self.child_generation is None):
            raise InvalidData("child identity and generation must be paired")
        if self.child_generation is not None and self.child_generation > self.generation:
            raise InvalidData("child generation cannot exceed control generation")
        if self.child_id is not None and self.state not in child_states | {
                SupervisorState.ATTENTION_REQUIRED}:
            raise InvalidData("inactive supervisor state cannot retain a child")
        if self.child_id is not None and self.start_requested_utc is None:
            raise InvalidData("active child requires its start reservation time")
        if self.child_id is None and (self.start_requested_utc is not None
                                      or self.child_started_utc is not None):
            raise InvalidData("inactive state cannot retain child timing")
        historical = (self.start_requested_utc, self.child_started_utc,
                      self.last_heartbeat_utc, self.last_progress_utc,
                      self.healthy_since_utc, self.stop_requested_utc)
        if any(value is not None and value > self.updated_utc for value in historical):
            raise InvalidData("supervisor history cannot be in the future")
        if (self.child_started_utc is not None
                and self.child_started_utc < self.start_requested_utc):
            raise InvalidData("child cannot start before its reservation")
        if (self.state in {SupervisorState.RECOVERING, SupervisorState.HEALTHY,
                           SupervisorState.DEGRADED}
                and self.child_started_utc is None):
            raise InvalidData("running child state requires confirmed process start")
        armed_states = {SupervisorState.BACKOFF, SupervisorState.STARTING,
                        SupervisorState.RECOVERING, SupervisorState.HEALTHY,
                        SupervisorState.DEGRADED}
        if self.state in armed_states and (not self.desired_armed or self.stop_latched):
            raise InvalidData("active recovery state must remain armed")
        if self.state in {SupervisorState.DISARMED, SupervisorState.STOPPING,
                          SupervisorState.ATTENTION_REQUIRED} and (
                self.desired_armed or not self.stop_latched):
            raise InvalidData("stopped supervisor state must retain stop latch")
        if self.state == SupervisorState.DISARMED and (self.desired_armed or not self.stop_latched):
            raise InvalidData("disarmed state must retain the stop latch")
        if self.desired_armed and self.stop_latched:
            raise InvalidData("armed state cannot retain stop latch")
        if self.state == SupervisorState.ATTENTION_REQUIRED and self.attention_reason is None:
            raise InvalidData("attention state requires a reason")

    @property
    def entry_allowed(self):
        return False

    @property
    def live_ready(self):
        return False

    def to_dict(self):
        return dict(schema_version=self.schema_version, scope_id=self.scope_id,
            generation=self.generation, state=self.state.value,
            desired_armed=self.desired_armed, stop_latched=self.stop_latched,
            build_fingerprint=self.build_fingerprint,
            config_fingerprint=self.config_fingerprint,
            incident_attempts=self.incident_attempts,
            restart_attempts_utc=list(self.restart_attempts_utc),
            next_restart_utc=self.next_restart_utc, child_id=self.child_id,
            child_generation=self.child_generation,
            start_requested_utc=self.start_requested_utc,
            child_started_utc=self.child_started_utc,
            last_heartbeat_utc=self.last_heartbeat_utc,
            last_progress_utc=self.last_progress_utc,
            progress_sequence=self.progress_sequence,
            work_deadline_utc=self.work_deadline_utc,
            healthy_since_utc=self.healthy_since_utc,
            stop_requested_utc=self.stop_requested_utc,
            attention_reason=(self.attention_reason.value if self.attention_reason else None),
            retry_holds=list(self.retry_holds),
            recovery_reasons=list(self.recovery_reasons), updated_utc=self.updated_utc)

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict):
            raise InvalidData("supervisor state object required")
        expected = {field.name for field in cls.__dataclass_fields__.values()}
        if set(value) != expected:
            raise InvalidData("supervisor state fields differ from schema")
        return cls(**value)


@dataclass(frozen=True)
class SupervisorEvent:
    kind: EventKind
    observed_utc: float
    expected_generation: int | None = None
    child_id: str | None = None
    build_fingerprint: str | None = None
    config_fingerprint: str | None = None
    child_phase: ChildPhase | None = None
    outcome: ChildOutcome | None = None
    progress_sequence: int | None = None
    work_deadline_utc: float | None = None
    retry_holds: tuple[str, ...] = ()
    process_exited: bool = False
    cleanup_complete: bool = False
    cleanup_failed: bool = False
    unresolved_work: bool = False
    attention_reason: AttentionReason | None = None

    def __post_init__(self):
        object.__setattr__(self, "kind", _enum(self.kind, EventKind, "event kind"))
        object.__setattr__(self, "observed_utc", _time(self.observed_utc, "event time"))
        if self.expected_generation is not None:
            integer(self.expected_generation, 0, 2**63-1)
        if self.child_id is not None:
            identity(self.child_id)
        for field in ("build_fingerprint", "config_fingerprint"):
            value = getattr(self, field)
            if value is not None:
                identity(value)
        if self.child_phase is not None:
            object.__setattr__(self, "child_phase", _enum(self.child_phase, ChildPhase, "child phase"))
        if self.outcome is not None:
            object.__setattr__(self, "outcome", _enum(self.outcome, ChildOutcome, "child outcome"))
        if self.progress_sequence is not None:
            integer(self.progress_sequence, 0, 2**63-1)
        object.__setattr__(self, "work_deadline_utc",
                           _optional_time(self.work_deadline_utc, "work deadline"))
        object.__setattr__(self, "retry_holds", _identities(self.retry_holds, "retry holds"))
        if (type(self.process_exited) is not bool or type(self.cleanup_complete) is not bool
                or type(self.cleanup_failed) is not bool
                or type(self.unresolved_work) is not bool):
            raise InvalidData("event booleans required")
        if self.cleanup_complete and self.cleanup_failed:
            raise InvalidData("cleanup cannot be complete and failed")
        if self.attention_reason is not None:
            object.__setattr__(self, "attention_reason",
                _enum(self.attention_reason, AttentionReason, "attention reason"))
        if (self.kind == EventKind.LOCAL_SAFETY_FAULT
                and self.attention_reason not in LOCAL_SAFETY_REASONS):
            raise InvalidData("local safety fault requires a local reason")
        if self.kind != EventKind.LOCAL_SAFETY_FAULT and self.attention_reason is not None:
            raise InvalidData("attention reason is only valid for a local safety fault")

    def to_dict(self):
        return dict(kind=self.kind.value, observed_utc=self.observed_utc,
            expected_generation=self.expected_generation, child_id=self.child_id,
            build_fingerprint=self.build_fingerprint,
            config_fingerprint=self.config_fingerprint,
            child_phase=(self.child_phase.value if self.child_phase else None),
            outcome=(self.outcome.value if self.outcome else None),
            progress_sequence=self.progress_sequence,
            work_deadline_utc=self.work_deadline_utc,
            retry_holds=list(self.retry_holds), process_exited=self.process_exited,
            cleanup_complete=self.cleanup_complete, cleanup_failed=self.cleanup_failed,
            unresolved_work=self.unresolved_work,
            attention_reason=(self.attention_reason.value if self.attention_reason else None))


@dataclass(frozen=True)
class SupervisorDecision:
    state: ControlState
    actions: tuple[SupervisorAction, ...] = ()
    stale: bool = False

    def __post_init__(self):
        if not isinstance(self.state, ControlState):
            raise InvalidData("control state required")
        object.__setattr__(self, "actions", tuple(
            _enum(action, SupervisorAction, "supervisor action") for action in self.actions))
        if type(self.stale) is not bool:
            raise InvalidData("stale flag must be boolean")

    @property
    def entry_allowed(self):
        return False

    @property
    def live_ready(self):
        return False


def initial_state(scope_id, observed_utc=0.0):
    return ControlState(scope_id=identity(scope_id), generation=0,
        state=SupervisorState.DISARMED, desired_armed=False, stop_latched=True,
        build_fingerprint="", config_fingerprint="", incident_attempts=0,
        restart_attempts_utc=(), next_restart_utc=None, child_id=None,
        child_generation=None, start_requested_utc=None, child_started_utc=None,
        last_heartbeat_utc=None,
        last_progress_utc=None, progress_sequence=0, work_deadline_utc=None,
        healthy_since_utc=None, stop_requested_utc=None, attention_reason=None,
        retry_holds=(), recovery_reasons=(),
        updated_utc=_time(observed_utc, "initial time"))


def _updated(current, event, **changes):
    return replace(current, updated_utc=event.observed_utc, **changes)


def _attention(state, event, reason, *, request_stop=False):
    actions = ((SupervisorAction.REQUEST_GRACEFUL_STOP,) if request_stop and state.child_id else ())
    return SupervisorDecision(_updated(state, event,
        generation=state.generation+1 if state.desired_armed else state.generation,
        state=SupervisorState.ATTENTION_REQUIRED, desired_armed=False,
        stop_latched=True, next_restart_utc=None, attention_reason=reason,
        stop_requested_utc=(event.observed_utc if state.child_id else state.stop_requested_utc)), actions)


def _rolling_attempts(state, policy, now):
    cutoff = max(0.0, now-policy.rolling_restart_seconds)
    return tuple(value for value in state.restart_attempts_utc if value >= cutoff)


def _budget_exhausted(state, policy, now):
    return (state.incident_attempts >= policy.max_incident_restarts
            or len(_rolling_attempts(state, policy, now)) >= policy.rolling_restart_limit)


def _restart_delay(policy, attempts):
    return policy.restart_delays[min(max(attempts-1, 0), len(policy.restart_delays)-1)]


def _expired_child_deadline(state, event, policy):
    """Apply prior-state deadlines before a new status can refresh them."""
    if state.child_id is None:
        return None
    if (state.state == SupervisorState.STARTING
            and state.start_requested_utc is not None
            and event.observed_utc-state.start_requested_utc
            >= policy.startup_timeout_seconds):
        reason = AttentionReason.STARTUP_TIMEOUT
    else:
        reference = (state.last_progress_utc if state.last_progress_utc is not None
                     else state.child_started_utc)
        heartbeat_fresh = (state.last_heartbeat_utc is not None
            and event.observed_utc-state.last_heartbeat_utc
            < policy.progress_timeout_seconds)
        deadline_active = (state.work_deadline_utc is not None
            and event.observed_utc <= state.work_deadline_utc and heartbeat_fresh)
        if not (state.state in {SupervisorState.RECOVERING, SupervisorState.HEALTHY,
                                SupervisorState.DEGRADED}
                and reference is not None
                and event.observed_utc-reference >= policy.progress_timeout_seconds
                and not deadline_active):
            return None
        reason = AttentionReason.PROGRESS_STALLED
    stopped = _updated(state, event, state=SupervisorState.STOPPING,
        generation=state.generation+1, desired_armed=False, stop_latched=True,
        stop_requested_utc=event.observed_utc, attention_reason=reason)
    return SupervisorDecision(stopped, (SupervisorAction.REQUEST_GRACEFUL_STOP,))


def _child_event_stale(state, event):
    if event.kind not in {EventKind.SPAWN_FAILED, EventKind.CHILD_STARTED,
                          EventKind.CHILD_STATUS, EventKind.CHILD_RESULT,
                          EventKind.ORPHAN_RELEASED}:
        return False
    if (state.child_id is None or state.child_generation is None
            or event.child_id is None or event.expected_generation is None
            or event.expected_generation != state.child_generation
            or event.child_id != state.child_id):
        return True
    if event.kind == EventKind.SPAWN_FAILED:
        return not (state.state in {SupervisorState.STARTING,
                                    SupervisorState.STOPPING,
                                    SupervisorState.ATTENTION_REQUIRED}
                    and state.child_started_utc is None)
    if event.kind == EventKind.CHILD_STARTED:
        return not (state.state == SupervisorState.STARTING
                    and state.child_started_utc is None and not state.stop_latched)
    if event.kind == EventKind.CHILD_STATUS and (
            event.child_phase is not None and event.progress_sequence is not None):
        return (state.child_started_utc is None
            or state.state not in {SupervisorState.STARTING,
                                   SupervisorState.RECOVERING,
                                   SupervisorState.HEALTHY,
                                   SupervisorState.DEGRADED}
            or (event.child_phase == ChildPhase.STARTING
                and state.state != SupervisorState.STARTING))
    if event.kind == EventKind.ORPHAN_RELEASED:
        return state.state != SupervisorState.ATTENTION_REQUIRED
    return False


def decide(state, event, policy=SupervisorPolicy(), *, control_utc=None,
           clock_trusted=True):
    """Return a deterministic transition. The caller persists before actions.

    ``observed_utc`` is diagnostic event time. ``control_utc`` is the trusted,
    monotonic-normalized local sample used for ordering and deadlines.
    """
    if not isinstance(state, ControlState) or not isinstance(event, SupervisorEvent):
        raise InvalidData("typed supervisor state/event required")
    if not isinstance(policy, SupervisorPolicy):
        raise InvalidData("supervisor policy required")
    if type(clock_trusted) is not bool:
        raise InvalidData("clock trust flag must be boolean")
    child_stale = _child_event_stale(state, event)

    now = _time(event.observed_utc if control_utc is None else control_utc,
                "control time")
    clock_regressed = now < state.updated_utc
    clock_fault = not clock_trusted or clock_regressed
    clock_reason = (AttentionReason.CLOCK_UNTRUSTED if not clock_trusted
                    else AttentionReason.CLOCK_REGRESSED)
    transition = replace(event, observed_utc=max(now, state.updated_utc))

    if event.kind == EventKind.STOP:
        active = state.child_id is not None
        reason = (clock_reason if clock_fault
                  else state.attention_reason if active else None)
        target = (SupervisorState.STOPPING if active else
                  SupervisorState.ATTENTION_REQUIRED if reason else SupervisorState.DISARMED)
        stopped = _updated(state, transition,
            generation=state.generation+1,
            state=target, desired_armed=False, stop_latched=True,
            next_restart_utc=None,
            stop_requested_utc=(state.stop_requested_utc or transition.observed_utc)
                if active else None,
            attention_reason=reason)
        return SupervisorDecision(stopped,
            ((SupervisorAction.REQUEST_GRACEFUL_STOP,) if active else ()))

    # Local clock trust is control evidence, independent of the payload.  Handle
    # it before stale child filtering so an old message cannot consume the fault.
    # A trusted direct-policy call still filters stale payloads before considering
    # their diagnostic timestamp, preserving non-authoritative child event time.
    if not clock_trusted:
        held = _attention(state, transition, clock_reason, request_stop=True)
        return SupervisorDecision(held.state, held.actions, stale=child_stale)

    if child_stale:
        return SupervisorDecision(state, stale=True)
    if event.kind == EventKind.CHILD_STATUS:
        if event.child_phase is None or event.progress_sequence is None:
            raise InvalidData("child status requires phase and progress sequence")

    if clock_fault:
        return _attention(state, transition, clock_reason,
                          request_stop=True)
    event = transition

    if event.kind == EventKind.LOCAL_SAFETY_FAULT:
        return _attention(state, event, event.attention_reason,
                          request_stop=True)

    if event.kind == EventKind.ORPHAN_RELEASED:
        # Absence of the account-scoped native child lease proves only that a
        # conforming process no longer owns this reservation.  It cannot claim
        # clean shutdown, clear holds/attempts or restore launch authority.
        return SupervisorDecision(_updated(state, event,
            child_id=None, child_generation=None, start_requested_utc=None,
            child_started_utc=None, last_heartbeat_utc=None,
            last_progress_utc=None, progress_sequence=0,
            work_deadline_utc=None, healthy_since_utc=None,
            stop_requested_utc=None))

    if event.kind == EventKind.ARM:
        if (event.expected_generation != state.generation or state.child_id is not None
                or state.desired_armed or state.retry_holds
                or state.state not in {SupervisorState.DISARMED,
                                       SupervisorState.ATTENTION_REQUIRED}
                or event.build_fingerprint is None or event.config_fingerprint is None):
            return SupervisorDecision(state, stale=True)
        return SupervisorDecision(_updated(state, event, generation=state.generation+1,
            state=SupervisorState.BACKOFF, desired_armed=True, stop_latched=False,
            build_fingerprint=event.build_fingerprint,
            config_fingerprint=event.config_fingerprint, incident_attempts=0,
            restart_attempts_utc=(), next_restart_utc=event.observed_utc,
            child_id=None, child_generation=None, start_requested_utc=None,
            child_started_utc=None, last_heartbeat_utc=None,
            last_progress_utc=None, progress_sequence=0, work_deadline_utc=None,
            healthy_since_utc=None, stop_requested_utc=None, attention_reason=None))

    if event.kind == EventKind.HOLDS_RESOLVED:
        requested = set(event.retry_holds)
        if (event.expected_generation != state.generation or not requested
                or not requested.issubset(state.retry_holds)):
            return SupervisorDecision(state, stale=True)
        remaining = tuple(hold for hold in state.retry_holds if hold not in requested)
        return SupervisorDecision(_updated(state, event, retry_holds=remaining))

    if event.kind == EventKind.TICK:
        if state.state == SupervisorState.BACKOFF and state.desired_armed:
            if state.retry_holds:
                return _attention(state, event, AttentionReason.RETRY_EXHAUSTED)
            if _budget_exhausted(state, policy, event.observed_utc):
                return _attention(state, event, AttentionReason.RESTART_BUDGET_EXHAUSTED)
            if state.next_restart_utc is None or event.observed_utc >= state.next_restart_utc:
                return SupervisorDecision(_updated(state, event), (SupervisorAction.START_DUE,))
        if state.child_id is not None:
            if (state.state == SupervisorState.STOPPING and state.stop_requested_utc is not None
                    and event.observed_utc-state.stop_requested_utc
                    >= policy.shutdown_timeout_seconds):
                return _attention(state, event, AttentionReason.SHUTDOWN_TIMEOUT)
            expired = _expired_child_deadline(state, event, policy)
            if expired is not None:
                return expired
        if (state.state == SupervisorState.HEALTHY and not state.retry_holds
                and state.healthy_since_utc is not None and state.last_progress_utc is not None
                and event.observed_utc-state.healthy_since_utc
                    >= policy.healthy_reset_seconds
                and event.observed_utc-state.last_progress_utc
                    < policy.progress_timeout_seconds
                and state.incident_attempts):
            return SupervisorDecision(_updated(state, event, incident_attempts=0,
                restart_attempts_utc=(), healthy_since_utc=event.observed_utc))
        return SupervisorDecision(_updated(state, event))

    if event.kind == EventKind.START_REQUESTED:
        if (event.expected_generation != state.generation or event.child_id is None
                or state.child_id is not None or state.state != SupervisorState.BACKOFF
                or not state.desired_armed or state.stop_latched or state.retry_holds
                or (state.next_restart_utc is not None
                    and event.observed_utc < state.next_restart_utc)):
            return SupervisorDecision(state, stale=True)
        attempts = _rolling_attempts(state, policy, event.observed_utc)
        if _budget_exhausted(replace(state, restart_attempts_utc=attempts), policy,
                             event.observed_utc):
            return _attention(state, event, AttentionReason.RESTART_BUDGET_EXHAUSTED)
        return SupervisorDecision(_updated(state, event, state=SupervisorState.STARTING,
            child_id=event.child_id, child_generation=state.generation,
            start_requested_utc=event.observed_utc, child_started_utc=None,
            last_heartbeat_utc=None, last_progress_utc=None,
            progress_sequence=0, work_deadline_utc=None, healthy_since_utc=None,
            stop_requested_utc=None, attention_reason=None,
            incident_attempts=state.incident_attempts+1,
            restart_attempts_utc=attempts+(event.observed_utc,), next_restart_utc=None),
            (SupervisorAction.SPAWN_RECOVERY,))

    if event.kind == EventKind.SPAWN_FAILED:
        bare = _updated(state, event, state=SupervisorState.BACKOFF,
            desired_armed=True, stop_latched=False, attention_reason=None,
            child_id=None, child_generation=None, start_requested_utc=None,
            child_started_utc=None, last_heartbeat_utc=None, last_progress_utc=None,
            progress_sequence=0, work_deadline_utc=None, healthy_since_utc=None)
        if state.stop_latched or state.state in {
                SupervisorState.STOPPING, SupervisorState.ATTENTION_REQUIRED}:
            target = (SupervisorState.ATTENTION_REQUIRED if state.attention_reason
                      else SupervisorState.DISARMED)
            return SupervisorDecision(replace(bare, state=target,
                desired_armed=False, stop_latched=True, next_restart_utc=None,
                stop_requested_utc=None,
                attention_reason=state.attention_reason if target
                    == SupervisorState.ATTENTION_REQUIRED else None))
        if _budget_exhausted(bare, policy, event.observed_utc):
            return _attention(bare, event, AttentionReason.RESTART_BUDGET_EXHAUSTED)
        return SupervisorDecision(replace(bare, state=SupervisorState.BACKOFF,
            next_restart_utc=event.observed_utc
                + _restart_delay(policy, bare.incident_attempts)))

    if event.kind == EventKind.CHILD_STARTED:
        return SupervisorDecision(_updated(state, event, state=SupervisorState.STARTING,
            child_started_utc=event.observed_utc,
            last_heartbeat_utc=event.observed_utc,
            last_progress_utc=event.observed_utc))

    if event.kind == EventKind.CHILD_STATUS:
        expired = _expired_child_deadline(state, event, policy)
        if expired is not None:
            return expired
        if event.progress_sequence < state.progress_sequence:
            return _attention(state, event, AttentionReason.INTEGRITY_FAILURE,
                              request_stop=True)
        progressed = event.progress_sequence > state.progress_sequence
        progress_time = event.observed_utc if progressed else state.last_progress_utc
        deadline = event.work_deadline_utc
        if deadline is not None and deadline <= event.observed_utc:
            deadline = None
        if (deadline is not None and (progress_time is None
                or deadline-progress_time > policy.work_deadline_limit_seconds)):
            return _attention(state, event, AttentionReason.INTEGRITY_FAILURE,
                              request_stop=True)
        holds = tuple(dict.fromkeys(state.retry_holds+event.retry_holds))
        mapped = SupervisorState(event.child_phase.value)
        if (holds or state.recovery_reasons) and mapped == SupervisorState.HEALTHY:
            mapped = SupervisorState.DEGRADED
        return SupervisorDecision(_updated(state, event, state=mapped,
            last_heartbeat_utc=event.observed_utc,
            last_progress_utc=progress_time,
            progress_sequence=event.progress_sequence,
            work_deadline_utc=deadline,
            healthy_since_utc=(state.healthy_since_utc
                if mapped == SupervisorState.HEALTHY
                    and state.state == SupervisorState.HEALTHY
                else event.observed_utc if mapped == SupervisorState.HEALTHY else None),
            retry_holds=holds))

    if event.kind == EventKind.CHILD_RESULT:
        if event.outcome is None:
            raise InvalidData("child result requires outcome")
        if not event.process_exited:
            uncertain = replace(state, retry_holds=tuple(dict.fromkeys(
                state.retry_holds+event.retry_holds+("process_exit_unconfirmed",))))
            return _attention(uncertain, event, AttentionReason.UNKNOWN_FAILURE,
                              request_stop=True)
        holds = tuple(dict.fromkeys(state.retry_holds+event.retry_holds
            + (("cleanup_failed",) if event.cleanup_failed else ())))
        reasons = tuple(dict.fromkeys(state.recovery_reasons
            + (("unexpected_death",) if event.outcome == ChildOutcome.UNEXPECTED_DEATH else ())
            + (("cleanup_unconfirmed",) if event.outcome == ChildOutcome.UNEXPECTED_DEATH
                and not event.cleanup_complete else ())
            + (("unresolved_work",) if event.outcome == ChildOutcome.UNEXPECTED_DEATH
                and event.unresolved_work else ())))
        bare = _updated(state, event, state=SupervisorState.BACKOFF,
            desired_armed=True, stop_latched=False, attention_reason=None,
            child_id=None, child_generation=None, start_requested_utc=None,
            child_started_utc=None, last_heartbeat_utc=None, last_progress_utc=None,
            progress_sequence=0, work_deadline_utc=None, healthy_since_utc=None,
            stop_requested_utc=None, retry_holds=holds, recovery_reasons=reasons)
        attention = {
            ChildOutcome.STARTUP_REFUSED: AttentionReason.STARTUP_REFUSED,
            ChildOutcome.RETRY_EXHAUSTED: AttentionReason.RETRY_EXHAUSTED,
            ChildOutcome.INTEGRITY_FAILURE: AttentionReason.INTEGRITY_FAILURE,
            ChildOutcome.UNKNOWN_FAILURE: AttentionReason.UNKNOWN_FAILURE,
        }
        if event.outcome in attention:
            return _attention(bare, event, attention[event.outcome])
        if event.cleanup_failed:
            return _attention(bare, event, AttentionReason.UNKNOWN_FAILURE)
        if state.attention_reason is not None:
            return _attention(bare, event, state.attention_reason)
        if state.stop_latched or state.state == SupervisorState.STOPPING:
            if not event.cleanup_complete or event.unresolved_work:
                return _attention(bare, event, AttentionReason.UNKNOWN_FAILURE)
            return SupervisorDecision(replace(bare, state=SupervisorState.DISARMED,
                desired_armed=False, stop_latched=True, next_restart_utc=None,
                attention_reason=None, recovery_reasons=()))
        if event.outcome == ChildOutcome.UNEXPECTED_DEATH:
            if holds:
                return _attention(bare, event, AttentionReason.RETRY_EXHAUSTED)
            if _budget_exhausted(bare, policy, event.observed_utc):
                return _attention(bare, event, AttentionReason.RESTART_BUDGET_EXHAUSTED)
            return SupervisorDecision(replace(bare, state=SupervisorState.BACKOFF,
                next_restart_utc=event.observed_utc
                    + _restart_delay(policy, bare.incident_attempts)))
        if not event.cleanup_complete or event.unresolved_work:
            incomplete = replace(bare, retry_holds=tuple(dict.fromkeys(
                bare.retry_holds
                + (("cleanup_incomplete",) if not event.cleanup_complete else ())
                + (("unresolved_work",) if event.unresolved_work else ()))))
            return _attention(incomplete, event, AttentionReason.UNKNOWN_FAILURE)
        if holds:
            return _attention(bare, event, AttentionReason.RETRY_EXHAUSTED)
        if event.outcome == ChildOutcome.CLEAN:
            if state.recovery_reasons:
                # The still-armed parent requested this recovery after an
                # unexpected death. Exact verified-flat cleanup may now launch
                # one fresh normal child, which re-ranks current markets and
                # passes every ordinary entry gate. Manual STOP was handled
                # above and can never enter this branch.
                return SupervisorDecision(replace(bare,
                    state=SupervisorState.BACKOFF, desired_armed=True,
                    stop_latched=False, next_restart_utc=event.observed_utc,
                    attention_reason=None, recovery_reasons=(),
                    # A verified cleanup and its normal-child handoff share
                    # one reserved restart slot. Failed starts/deaths remain
                    # charged; this is not a reset of the incident budget.
                    incident_attempts=max(0, bare.incident_attempts-1),
                    restart_attempts_utc=(bare.restart_attempts_utc[:-1]
                        if bare.restart_attempts_utc and bare.restart_attempts_utc[-1]
                            == state.start_requested_utc else bare.restart_attempts_utc)))
            return SupervisorDecision(replace(bare, state=SupervisorState.DISARMED,
                desired_armed=False, stop_latched=True, next_restart_utc=None,
                attention_reason=None, recovery_reasons=()))
        if event.outcome == ChildOutcome.TRANSIENT_FAILURE:
            if _budget_exhausted(bare, policy, event.observed_utc):
                return _attention(bare, event, AttentionReason.RESTART_BUDGET_EXHAUSTED)
            return SupervisorDecision(replace(bare, state=SupervisorState.BACKOFF,
                next_restart_utc=event.observed_utc
                    + _restart_delay(policy, bare.incident_attempts)))
    raise InvalidData("event is not valid for supervisor policy")
