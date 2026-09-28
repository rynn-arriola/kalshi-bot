"""Strict, bounded S2 supervisor protocol. No process or trading authority."""
from dataclasses import dataclass
from enum import StrEnum
import json
import math
import re
import struct
from types import MappingProxyType
from collections.abc import Mapping

from .values import InvalidData, identity, integer


PROTOCOL_VERSION = 1
MAX_FRAME_BYTES = 8192
MAX_CONTROL_FRAMES = 64
MAX_DEPTH = 6
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class MessageKind(StrEnum):
    HELLO = "hello"
    STATUS = "status"
    RESULT = "result"
    FENCE = "fence"
    ADMIT = "admit"
    PULSE = "pulse"
    STOP_HINT = "stop_hint"
    FENCE_ACK = "fence_ack"


CHILD_KINDS = frozenset((MessageKind.HELLO, MessageKind.STATUS,
                         MessageKind.RESULT, MessageKind.FENCE))
PARENT_KINDS = frozenset((MessageKind.ADMIT, MessageKind.PULSE,
                          MessageKind.STOP_HINT, MessageKind.FENCE_ACK))
COALESCED_KINDS = frozenset((MessageKind.STATUS, MessageKind.PULSE))


def _pairs(values):
    result = {}
    for key, value in values:
        if key in result:
            raise InvalidData("duplicate supervisor protocol field")
        result[key] = value
    return result


def _constant(_):
    raise InvalidData("nonfinite supervisor protocol number")


def _depth(value, level=0):
    if level > MAX_DEPTH:
        raise InvalidData("supervisor protocol nesting too deep")
    if isinstance(value, Mapping):
        if len(value) > 32:
            raise InvalidData("too many supervisor protocol fields")
        for key, item in value.items():
            if not isinstance(key, str):
                raise InvalidData("supervisor protocol keys must be strings")
            _depth(item, level+1)
    elif isinstance(value, (list, tuple)):
        if len(value) > 64:
            raise InvalidData("supervisor protocol list too large")
        for item in value:
            _depth(item, level+1)
    elif isinstance(value, float) and not math.isfinite(value):
        raise InvalidData("nonfinite supervisor protocol number")
    elif value is not None and not isinstance(value, (str, int, float, bool)):
        raise InvalidData("invalid supervisor protocol value")


def _exact(payload, fields):
    if not isinstance(payload, Mapping) or set(payload) != set(fields):
        raise InvalidData("supervisor message payload fields differ")


def _freeze(value):
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value):
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _validate_payload(kind, payload):
    if kind == MessageKind.HELLO:
        _exact(payload, ("build_fingerprint", "config_fingerprint", "fixture_mode"))
        identity(payload["build_fingerprint"])
        identity(payload["config_fingerprint"])
        if payload["fixture_mode"] not in {"normal", "crash_after_admit",
                "hang_after_admit", "exit_after_status", "runtime_normal",
                "runtime_exhausted", "runtime_crash_before_fence_ack",
                "production_live"}:
            raise InvalidData("invalid supervisor fixture mode")
    elif kind == MessageKind.STATUS:
        _exact(payload, ("phase", "progress_sequence", "work_remaining_ms", "blockers"))
        if payload["phase"] not in {"starting", "recovering", "healthy", "degraded"}:
            raise InvalidData("invalid child phase")
        integer(payload["progress_sequence"], 0, 2**63-1)
        if payload["work_remaining_ms"] is not None:
            integer(payload["work_remaining_ms"], 1, 60000)
        if (not isinstance(payload["blockers"], (list, tuple))
                or len(payload["blockers"]) > 32):
            raise InvalidData("invalid child blockers")
        for blocker in payload["blockers"]:
            identity(blocker)
    elif kind == MessageKind.RESULT:
        _exact(payload, ("outcome", "cleanup_complete", "cleanup_failed",
                         "unresolved_work", "retry_holds"))
        if payload["outcome"] not in {"clean", "transient_failure",
                "unexpected_death", "startup_refused", "retry_exhausted",
                "integrity_failure", "unknown_failure"}:
            raise InvalidData("invalid child result outcome")
        for field in ("cleanup_complete", "cleanup_failed", "unresolved_work"):
            if type(payload[field]) is not bool:
                raise InvalidData("invalid child result boolean")
        if payload["cleanup_complete"] and payload["cleanup_failed"]:
            raise InvalidData("child cleanup cannot be complete and failed")
        if (not isinstance(payload["retry_holds"], (list, tuple))
                or len(payload["retry_holds"]) > 32):
            raise InvalidData("invalid child result holds")
        for hold in payload["retry_holds"]:
            identity(hold)
    elif kind in {MessageKind.ADMIT, MessageKind.PULSE}:
        _exact(payload, ("control_revision",))
        integer(payload["control_revision"], 0, 2**63-1)
    elif kind == MessageKind.FENCE_ACK:
        _exact(payload, ("control_revision", "fence_revision"))
        integer(payload["control_revision"], 0, 2**63-1)
        integer(payload["fence_revision"], 1, 2**63-1)
    elif kind == MessageKind.STOP_HINT:
        _exact(payload, ("reason",))
        identity(payload["reason"])
    elif kind == MessageKind.FENCE:
        _exact(payload, ("fence_revision", "component_holds", "cooldowns",
                         "terminal_checkpoint_complete"))
        integer(payload["fence_revision"], 1, 2**63-1)
        holds = payload["component_holds"]
        if not isinstance(holds, (list, tuple)) or len(holds) > 32:
            raise InvalidData("invalid recovery-fence holds")
        for hold in holds:
            identity(hold)
        if len(set(holds)) != len(holds):
            raise InvalidData("duplicate recovery-fence hold")
        cooldowns = payload["cooldowns"]
        if (not isinstance(cooldowns, (list, tuple)) or len(cooldowns) > 8):
            raise InvalidData("invalid recovery-fence cooldowns")
        names = []
        for cooldown in cooldowns:
            _exact(cooldown, ("name", "remaining_ms"))
            names.append(identity(cooldown["name"]))
            integer(cooldown["remaining_ms"], 1, 86400000)
        if len(set(names)) != len(names):
            raise InvalidData("duplicate recovery-fence cooldown")
        if type(payload["terminal_checkpoint_complete"]) is not bool:
            raise InvalidData("invalid terminal checkpoint flag")
    else:
        raise InvalidData("unsupported supervisor message")
    _depth(payload)


@dataclass(frozen=True)
class Envelope:
    scope_digest: str
    parent_session: str
    child_id: str
    child_generation: int
    kind: MessageKind
    sequence: int
    sent_monotonic_ns: int
    payload: dict
    version: int = PROTOCOL_VERSION

    def __post_init__(self):
        integer(self.version, PROTOCOL_VERSION, PROTOCOL_VERSION)
        if not isinstance(self.scope_digest, str) or not _DIGEST.fullmatch(self.scope_digest):
            raise InvalidData("invalid supervisor scope digest")
        identity(self.parent_session)
        identity(self.child_id)
        integer(self.child_generation, 0, 2**63-1)
        try:
            kind = self.kind if isinstance(self.kind, MessageKind) else MessageKind(self.kind)
        except (TypeError, ValueError) as exc:
            raise InvalidData("invalid supervisor message kind") from exc
        object.__setattr__(self, "kind", kind)
        integer(self.sequence, 1, 2**63-1)
        integer(self.sent_monotonic_ns, 1, 2**63-1)
        _validate_payload(kind, self.payload)
        object.__setattr__(self, "payload", _freeze(self.payload))

    def to_dict(self):
        return dict(version=self.version, scope_digest=self.scope_digest,
            parent_session=self.parent_session, child_id=self.child_id,
            child_generation=self.child_generation, kind=self.kind.value,
            sequence=self.sequence, sent_monotonic_ns=self.sent_monotonic_ns,
            payload=_thaw(self.payload))

    @classmethod
    def from_dict(cls, value):
        fields = {"version", "scope_digest", "parent_session", "child_id",
                  "child_generation", "kind", "sequence", "sent_monotonic_ns",
                  "payload"}
        if not isinstance(value, dict) or set(value) != fields:
            raise InvalidData("supervisor envelope fields differ")
        return cls(**value)


def encode_frame(envelope):
    if not isinstance(envelope, Envelope):
        raise InvalidData("typed supervisor envelope required")
    body = json.dumps(envelope.to_dict(), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")
    if not 1 <= len(body) <= MAX_FRAME_BYTES:
        raise InvalidData("supervisor frame outside bounds")
    return struct.pack(">I", len(body))+body


def decode_body(body):
    if not isinstance(body, bytes) or not 1 <= len(body) <= MAX_FRAME_BYTES:
        raise InvalidData("supervisor frame outside bounds")
    try:
        value = json.loads(body.decode("utf-8"), object_pairs_hook=_pairs,
                           parse_constant=_constant)
    except InvalidData:
        raise
    except (UnicodeError, ValueError, TypeError) as exc:
        raise InvalidData("invalid supervisor frame JSON") from exc
    _depth(value)
    return Envelope.from_dict(value)


class FrameDecoder:
    def __init__(self):
        self.buffer = bytearray()

    def feed(self, chunk):
        if not isinstance(chunk, bytes) or not chunk:
            raise InvalidData("nonempty supervisor bytes required")
        if len(self.buffer)+len(chunk) > (MAX_FRAME_BYTES+4)*MAX_CONTROL_FRAMES:
            raise InvalidData("supervisor receive buffer overflow")
        self.buffer.extend(chunk)
        result = []
        while len(self.buffer) >= 4:
            size = struct.unpack(">I", self.buffer[:4])[0]
            if not 1 <= size <= MAX_FRAME_BYTES:
                raise InvalidData("supervisor frame length outside bounds")
            if len(self.buffer) < size+4:
                break
            body = bytes(self.buffer[4:size+4])
            del self.buffer[:size+4]
            result.append(decode_body(body))
        return tuple(result)


class SequenceTracker:
    """Strict retained ordering; coalesced status/pulse may skip forward."""
    def __init__(self):
        self.control = 0
        self.coalesced = 0

    def accept(self, envelope):
        lane = "coalesced" if envelope.kind in COALESCED_KINDS else "control"
        previous = getattr(self, lane)
        if envelope.sequence <= previous:
            raise InvalidData("replayed supervisor message")
        if lane == "control" and envelope.sequence != previous+1:
            raise InvalidData("missing supervisor control message")
        setattr(self, lane, envelope.sequence)


def validate_peer(envelope, *, scope_digest, parent_session, child_id,
                  child_generation, allowed, tracker, now_ns, late_ok=frozenset()):
    """Shared same-boot identity/age gate; invalid frames cannot advance lanes.

    Kinds in ``late_ok`` that arrive too old return None instead of raising:
    the caller grants them nothing and they do not advance the lane."""
    if ((envelope.scope_digest, envelope.parent_session, envelope.child_id,
         envelope.child_generation) !=
            (scope_digest, parent_session, child_id, child_generation)
            or envelope.kind not in allowed):
        raise InvalidData("supervisor peer envelope identity or direction mismatch")
    age = now_ns-envelope.sent_monotonic_ns
    if age > 4_000_000_000 and envelope.kind in late_ok:
        return None
    if not 0 <= age <= 4_000_000_000:
        raise InvalidData("stale supervisor peer envelope")
    tracker.accept(envelope)
    return age/1_000_000_000


class ParentProtocol:
    """Child-side phase gate; S2B acknowledgements confer no authority."""
    def __init__(self, scope_digest, parent_session, child_id, child_generation):
        self.identity = dict(scope_digest=scope_digest, parent_session=parent_session,
                             child_id=child_id, child_generation=child_generation)
        self.tracker = SequenceTracker()
        self.admitted = self.stopped = False
        self.revision = -1
        self.fence_revision = 0

    def accept(self, message, *, now_ns, current_revision=None):
        age = validate_peer(message, **self.identity, allowed={MessageKind.ADMIT,
            MessageKind.PULSE, MessageKind.STOP_HINT, MessageKind.FENCE_ACK},
            tracker=self.tracker, now_ns=now_ns, late_ok={MessageKind.PULSE})
        if age is None:
            # 2026-09-28: a recovery-only child that could not read for > 4 s
            # crashed on its backlog of pulses and looped. A late pulse grants
            # no freshness (the 6 s pulse watchdog still stops the child) and
            # is not a fault; late control messages remain fatal.
            if self.stopped:
                raise InvalidData("supervisor control after stop")
            return False
        if self.stopped and message.kind != MessageKind.FENCE_ACK:
            raise InvalidData("supervisor control after stop")
        if message.kind == MessageKind.STOP_HINT:
            self.stopped = True
        else:
            revision = message.payload["control_revision"]
            if current_revision is None or revision > current_revision:
                raise InvalidData("supervisor control revision differs")
            if message.kind == MessageKind.PULSE and revision < self.revision:
                return False  # A coalesced pre-fence pulse grants no freshness.
            if revision < self.revision:
                raise InvalidData("supervisor control revision regressed")
            if message.kind == MessageKind.ADMIT:
                if self.admitted or revision != current_revision:
                    raise InvalidData("duplicate or revoked supervisor admission")
                self.admitted = True
            elif not self.admitted:
                raise InvalidData("supervisor control before admission")
            elif message.kind == MessageKind.FENCE_ACK:
                fence_revision = message.payload["fence_revision"]
                if fence_revision <= self.fence_revision:
                    raise InvalidData("stale recovery-fence acknowledgement")
                self.fence_revision = fence_revision
            self.revision = revision
        return True
