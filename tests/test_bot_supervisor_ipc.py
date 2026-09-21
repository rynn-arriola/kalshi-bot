"""D-056 S2A strict protocol and transactional native-control contracts."""
import hashlib
from pathlib import Path
import struct
from tempfile import TemporaryDirectory
import unittest

from kalshi_bot.supervision import (AttentionReason, EventKind, SupervisorEvent,
    SupervisorState, decide, initial_state)
from kalshi_bot.supervisor_protocol import (Envelope, FrameDecoder, MessageKind,
    SequenceTracker, encode_frame)
from kalshi_bot.supervisor_store import SupervisorStore
from kalshi_bot.values import InvalidData


DIGEST = hashlib.sha256(b"test-scope").hexdigest()


def envelope(kind=MessageKind.HELLO, sequence=1, **payload):
    defaults = dict(build_fingerprint="build-a", config_fingerprint="config-a",
                    fixture_mode="normal")
    defaults.update(payload)
    return Envelope(DIGEST, "session-a", "child-a", 1, kind, sequence,
                    1_000_000, defaults)


class ProtocolTests(unittest.TestCase):
    def test_fragmented_round_trip_and_strict_fields(self):
        expected = envelope()
        frame = encode_frame(expected)
        decoder = FrameDecoder()
        found = ()
        for byte in frame:
            found += decoder.feed(bytes((byte,)))
        self.assertEqual(found, (expected,))
        self.assertEqual(decoder.buffer, b"")

    def test_envelope_payload_is_immutable(self):
        source = dict(build_fingerprint="build-a", config_fingerprint="config-a",
                      fixture_mode="normal")
        expected = Envelope(DIGEST, "session-a", "child-a", 1,
            MessageKind.HELLO, 1, 1, source)
        source["fixture_mode"] = "hang_after_admit"
        self.assertEqual(expected.payload["fixture_mode"], "normal")
        with self.assertRaises(TypeError):
            expected.payload["fixture_mode"] = "normal"

    def test_length_duplicate_nonfinite_and_unknown_fields_fail(self):
        with self.assertRaises(InvalidData):
            FrameDecoder().feed(struct.pack(">I", 9000)+b"x")
        duplicate = (b'{"version":1,"version":1,"scope_digest":"'+
                     DIGEST.encode()+b'"}')
        with self.assertRaises(InvalidData):
            FrameDecoder().feed(struct.pack(">I", len(duplicate))+duplicate)
        value = envelope().to_dict() | {"extra": True}
        with self.assertRaises(InvalidData):
            Envelope.from_dict(value)
        with self.assertRaises(InvalidData):
            Envelope(DIGEST, "session-a", "child-a", 1, MessageKind.STATUS,
                1, 1, dict(phase="healthy", progress_sequence=1,
                work_remaining_ms=float("nan"), blockers=[]))

    def test_control_sequence_is_exact_and_status_can_coalesce(self):
        tracker = SequenceTracker()
        tracker.accept(envelope())
        with self.assertRaises(InvalidData):
            tracker.accept(envelope(sequence=1))
        with self.assertRaises(InvalidData):
            SequenceTracker().accept(envelope(sequence=2))
        status = lambda sequence: Envelope(DIGEST, "session-a", "child-a", 1,
            MessageKind.STATUS, sequence, 1_000_000+sequence,
            dict(phase="healthy", progress_sequence=sequence,
                 work_remaining_ms=None, blockers=[]))
        coalesced = SequenceTracker()
        coalesced.accept(status(1))
        coalesced.accept(status(10))
        with self.assertRaises(InvalidData):
            coalesced.accept(status(9))

    def test_s2b_fence_is_deliberately_unimplemented(self):
        with self.assertRaisesRegex(InvalidData, "S2B"):
            Envelope(DIGEST, "session-a", "child-a", 1, MessageKind.FENCE,
                     1, 1, {})


class PolicyAndStoreTests(unittest.TestCase):
    def test_local_safety_fault_fences_and_orphan_release_is_narrow(self):
        state = initial_state("test-scope", 1)
        armed = decide(state, SupervisorEvent(EventKind.ARM, 2,
            expected_generation=0, build_fingerprint="build-a",
            config_fingerprint="config-a")).state
        reserved = decide(armed, SupervisorEvent(EventKind.START_REQUESTED, 2,
            expected_generation=armed.generation, child_id="child-a")).state
        held = decide(reserved, SupervisorEvent(EventKind.LOCAL_SAFETY_FAULT, 3,
            attention_reason=AttentionReason.OWNER_LOST))
        self.assertEqual(held.state.state, SupervisorState.ATTENTION_REQUIRED)
        self.assertEqual(held.state.child_id, "child-a")
        self.assertTrue(held.state.stop_latched)
        released = decide(held.state, SupervisorEvent(EventKind.ORPHAN_RELEASED, 4,
            expected_generation=reserved.child_generation, child_id="child-a"))
        self.assertIsNone(released.state.child_id)
        self.assertEqual(released.state.state, SupervisorState.ATTENTION_REQUIRED)
        self.assertEqual(released.state.attention_reason, AttentionReason.OWNER_LOST)
        self.assertEqual(released.state.incident_attempts, 1)

    def test_explicit_fixture_initialization_and_native_reservation(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary)/"control.db"
            with self.assertRaises(InvalidData):
                SupervisorStore.open_existing(path, scope_id="test-scope")
            with SupervisorStore.initialize_fixture(path, scope_id="test-scope") as store:
                session = "session-a"
                store.begin_parent_session(session, observed_utc=1)
                armed = store.apply(SupervisorEvent(EventKind.ARM, 2,
                    expected_generation=0, build_fingerprint="build-a",
                    config_fingerprint="config-a")).state
                decision = store.reserve_start(SupervisorEvent(
                    EventKind.START_REQUESTED, 2,
                    expected_generation=armed.generation, child_id="child-a"),
                    parent_session=session)
                self.assertFalse(decision.stale)
                self.assertEqual(store.read_native().stage, "reserved")
                store.update_native_stage(parent_session=session,
                    child_id="child-a", child_generation=armed.generation,
                    stage="created", diagnostic_pid=123)
                store.update_native_stage(parent_session=session,
                    child_id="child-a", child_generation=armed.generation,
                    stage="bound", diagnostic_pid=123)
                revision, state, native = SupervisorStore.read_only_snapshot(
                    path, scope_id="test-scope")
                self.assertGreater(revision, 0)
                self.assertEqual((state.child_id, native.stage), ("child-a", "bound"))
            with self.assertRaises(InvalidData):
                SupervisorStore.initialize_fixture(path, scope_id="test-scope")

    def test_new_parent_session_never_resumes_prior_arm(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary)/"control.db"
            with SupervisorStore.initialize_fixture(path, scope_id="test-scope") as store:
                store.begin_parent_session("session-a", observed_utc=1)
                store.apply(SupervisorEvent(EventKind.ARM, 2,
                    expected_generation=0, build_fingerprint="build-a",
                    config_fingerprint="config-a"))
                decision = store.begin_parent_session("session-b", observed_utc=3)
                self.assertEqual(decision.state.state, SupervisorState.ATTENTION_REQUIRED)
                self.assertEqual(decision.state.attention_reason, AttentionReason.OWNER_LOST)
                self.assertFalse(decision.state.desired_armed)


if __name__ == "__main__":
    unittest.main()
