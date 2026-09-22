"""D-050 S1 uses pure policy, disposable stores and fake process evidence."""
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from threading import Barrier, Thread
import unittest

from kalshi_bot.supervision import (
    AttentionReason, ChildOutcome, ChildPhase, ControlState, EventKind,
    SupervisorAction, SupervisorEvent, SupervisorPolicy, SupervisorState,
    decide, initial_state)
from kalshi_bot.supervisor_store import SupervisorStore
from kalshi_bot.values import InvalidData
from scripts.benchmark_supervision import measure_idle


POLICY = SupervisorPolicy()


class ControlledClock:
    def __init__(self, wall=100.0, monotonic=0.0, boot="boot-a"):
        self.wall = wall
        self.monotonic_value = monotonic
        self.boot = boot

    def utc(self):
        return self.wall

    def monotonic(self):
        return self.monotonic_value

    def boot_id(self):
        return self.boot

    def advance(self, seconds):
        self.wall += seconds
        self.monotonic_value += seconds


def event(kind, now, **values):
    return SupervisorEvent(kind, now, **values)


def arm(state, now=100):
    return decide(state, event(EventKind.ARM, now,
        expected_generation=state.generation, build_fingerprint="build-a",
        config_fingerprint="config-a"), POLICY).state


def start(state, now=None, child="child-a"):
    now = state.next_restart_utc if now is None else now
    result = decide(state, event(EventKind.START_REQUESTED, now,
        expected_generation=state.generation, child_id=child), POLICY)
    if result.actions != (SupervisorAction.SPAWN_RECOVERY,):
        raise AssertionError(result)
    return result.state


def started(state, now=None):
    now = state.updated_utc+1 if now is None else now
    return decide(state, event(EventKind.CHILD_STARTED, now,
        expected_generation=state.generation, child_id=state.child_id), POLICY).state


def result(state, outcome, now=None, **values):
    now = state.updated_utc+1 if now is None else now
    values.setdefault("process_exited", True)
    values.setdefault("cleanup_complete", True)
    return decide(state, event(EventKind.CHILD_RESULT, now,
        expected_generation=state.child_generation, child_id=state.child_id,
        outcome=outcome, **values), POLICY)


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.state = initial_state("kalshi-primary", 90)

    def test_contracts_are_immutable_and_never_authorize_trading(self):
        with self.assertRaises(FrozenInstanceError):
            self.state.state = SupervisorState.HEALTHY
        self.assertFalse(self.state.entry_allowed)
        self.assertFalse(self.state.live_ready)
        decision = decide(self.state, event(EventKind.TICK, 91), POLICY)
        self.assertFalse(decision.entry_allowed)
        self.assertFalse(decision.live_ready)

    def test_arm_start_and_child_status_stay_recovery_only(self):
        armed = arm(self.state)
        self.assertEqual((armed.state, armed.generation, armed.next_restart_utc),
                         (SupervisorState.BACKOFF, 1, 100))
        due = decide(armed, event(EventKind.TICK, 100), POLICY)
        self.assertEqual(due.actions, (SupervisorAction.START_DUE,))
        running = started(start(armed), 101)
        status = decide(running, event(EventKind.CHILD_STATUS, 102,
            expected_generation=running.generation, child_id=running.child_id,
            child_phase=ChildPhase.HEALTHY, progress_sequence=1), POLICY)
        self.assertEqual(status.state.state, SupervisorState.HEALTHY)
        self.assertFalse(status.entry_allowed)

    def test_manual_stop_wins_during_backoff_and_active_child(self):
        armed = arm(self.state)
        stopped = decide(armed, event(EventKind.STOP, 101), POLICY)
        self.assertEqual(stopped.state.state, SupervisorState.DISARMED)
        self.assertTrue(stopped.state.stop_latched)
        active = started(start(arm(stopped.state, 102), 102), 103)
        stopping = decide(active, event(EventKind.STOP, 104), POLICY)
        self.assertEqual(stopping.state.state, SupervisorState.STOPPING)
        self.assertEqual(stopping.actions, (SupervisorAction.REQUEST_GRACEFUL_STOP,))
        exited = decide(stopping.state, event(EventKind.CHILD_RESULT, 105,
            expected_generation=active.child_generation,
            child_id=stopping.state.child_id,
            outcome=ChildOutcome.UNEXPECTED_DEATH, process_exited=True,
            cleanup_complete=True), POLICY)
        self.assertEqual(exited.state.state, SupervisorState.DISARMED)

    def test_repeated_stop_preserves_child_generation_until_exit(self):
        active = started(start(arm(self.state)), 101)
        first = decide(active, event(EventKind.STOP, 102), POLICY).state
        second = decide(first, event(EventKind.STOP, 103), POLICY).state
        self.assertEqual(second.generation, first.generation+1)
        self.assertEqual(second.child_generation, active.generation)
        exited = decide(second, event(EventKind.CHILD_RESULT, 104,
            expected_generation=active.generation, child_id=active.child_id,
            outcome=ChildOutcome.CLEAN, process_exited=True,
            cleanup_complete=True), POLICY)
        self.assertEqual(exited.state.state, SupervisorState.DISARMED)

    def test_repeated_stop_fences_arm_prepared_after_first_stop(self):
        active = started(start(arm(self.state)), 101)
        first = decide(active, event(EventKind.STOP, 102), POLICY).state
        prepared = event(EventKind.ARM, 102.5,
            expected_generation=first.generation, build_fingerprint="build-b",
            config_fingerprint="config-b")
        second = decide(first, event(EventKind.STOP, 103), POLICY).state
        exited = result(second, ChildOutcome.CLEAN, 104).state
        refused = decide(exited, prepared, POLICY, control_utc=105)
        self.assertTrue(refused.stale)
        self.assertEqual(refused.state.state, SupervisorState.DISARMED)

    def test_stale_child_result_after_rearm_cannot_change_new_session(self):
        first = start(arm(self.state), child="old")
        stopped = decide(first, event(EventKind.STOP, 101), POLICY).state
        stopped = decide(stopped, event(EventKind.CHILD_RESULT, 102,
            expected_generation=first.generation, child_id="old",
            outcome=ChildOutcome.CLEAN, process_exited=True,
            cleanup_complete=True), POLICY).state
        second = arm(stopped, 103)
        stale = decide(second, event(EventKind.CHILD_RESULT, 104,
            expected_generation=1, child_id="old",
            outcome=ChildOutcome.CLEAN), POLICY)
        self.assertTrue(stale.stale)
        self.assertEqual(stale.state, second)

    def test_three_failed_children_exhaust_incident_budget(self):
        state = arm(self.state)
        for number in range(3):
            state = start(state, child=f"child-{number}")
            decision = result(state, ChildOutcome.TRANSIENT_FAILURE)
            state = decision.state
            if number < 2:
                self.assertEqual(state.state, SupervisorState.BACKOFF)
        self.assertEqual(state.state, SupervisorState.ATTENTION_REQUIRED)
        self.assertEqual(state.attention_reason, AttentionReason.RESTART_BUDGET_EXHAUSTED)

    def test_duplicate_arm_cannot_reset_restart_budget(self):
        armed = arm(self.state)
        duplicate = decide(armed, event(EventKind.ARM, 101,
            expected_generation=armed.generation, build_fingerprint="build-a",
            config_fingerprint="config-a"), POLICY)
        self.assertTrue(duplicate.stale)
        self.assertEqual(duplicate.state, armed)

    def test_failure_classification_refuses_unsafe_restart(self):
        mapping = {
            ChildOutcome.STARTUP_REFUSED: AttentionReason.STARTUP_REFUSED,
            ChildOutcome.RETRY_EXHAUSTED: AttentionReason.RETRY_EXHAUSTED,
            ChildOutcome.INTEGRITY_FAILURE: AttentionReason.INTEGRITY_FAILURE,
            ChildOutcome.UNKNOWN_FAILURE: AttentionReason.UNKNOWN_FAILURE,
        }
        for outcome, reason in mapping.items():
            with self.subTest(outcome=outcome):
                decision = result(start(arm(self.state)), outcome)
                self.assertEqual(decision.state.state, SupervisorState.ATTENTION_REQUIRED)
                self.assertEqual(decision.state.attention_reason, reason)
                self.assertEqual(decision.actions, ())

    def test_clean_result_disarms_and_unexpected_death_backs_off(self):
        clean = result(start(arm(self.state)), ChildOutcome.CLEAN)
        self.assertEqual(clean.state.state, SupervisorState.DISARMED)
        dead = result(start(arm(self.state)), ChildOutcome.UNEXPECTED_DEATH)
        self.assertEqual(dead.state.state, SupervisorState.BACKOFF)
        self.assertGreater(dead.state.next_restart_utc, dead.state.updated_utc)

    def test_failed_spawn_backs_off_without_forgetting_reserved_attempt(self):
        reserved = start(arm(self.state))
        decision = decide(reserved, event(EventKind.SPAWN_FAILED, 101,
            expected_generation=reserved.generation, child_id=reserved.child_id), POLICY)
        self.assertEqual(decision.state.state, SupervisorState.BACKOFF)
        self.assertEqual(decision.state.incident_attempts, 1)
        self.assertIsNone(decision.state.child_id)
        self.assertGreater(decision.state.next_restart_utc, 101)

    def test_failed_spawn_releases_stopped_or_clock_faulted_reservation(self):
        reserved = start(arm(self.state))
        stopped = decide(reserved, event(EventKind.STOP, 101), POLICY).state
        stopped_result = decide(stopped, event(EventKind.SPAWN_FAILED, 102,
            expected_generation=reserved.child_generation,
            child_id=reserved.child_id), POLICY)
        self.assertEqual(stopped_result.state.state, SupervisorState.DISARMED)
        self.assertIsNone(stopped_result.state.child_id)

        reserved = start(arm(self.state))
        faulted = decide(reserved, event(EventKind.TICK, 99), POLICY).state
        failed = decide(faulted, event(EventKind.SPAWN_FAILED, 101,
            expected_generation=reserved.child_generation,
            child_id=reserved.child_id), POLICY, control_utc=101)
        self.assertEqual(failed.state.state, SupervisorState.ATTENTION_REQUIRED)
        self.assertEqual(failed.state.attention_reason, AttentionReason.CLOCK_REGRESSED)
        self.assertIsNone(failed.state.child_id)

    def test_clean_exit_without_cleanup_proof_requires_attention(self):
        decision = result(start(arm(self.state)), ChildOutcome.CLEAN,
                          cleanup_complete=False, unresolved_work=True)
        self.assertEqual(decision.state.state, SupervisorState.ATTENTION_REQUIRED)
        self.assertEqual(decision.state.attention_reason, AttentionReason.UNKNOWN_FAILURE)
        self.assertEqual(decision.state.retry_holds,
                         ("cleanup_incomplete", "unresolved_work"))

    def test_transient_exit_cannot_restart_without_cleanup_proof(self):
        decision = result(start(arm(self.state)), ChildOutcome.TRANSIENT_FAILURE,
                          cleanup_complete=False)
        self.assertEqual(decision.state.state, SupervisorState.ATTENTION_REQUIRED)
        self.assertEqual(decision.state.attention_reason, AttentionReason.UNKNOWN_FAILURE)
        self.assertIsNone(decision.state.next_restart_utc)

    def test_clock_reversal_enters_attention_and_requests_stop(self):
        active = started(start(arm(self.state)), 110)
        decision = decide(active, event(EventKind.TICK, 109), POLICY)
        self.assertEqual(decision.state.attention_reason, AttentionReason.CLOCK_REGRESSED)
        self.assertEqual(decision.actions, (SupervisorAction.REQUEST_GRACEFUL_STOP,))

    def test_stale_child_timestamp_cannot_create_current_clock_fault(self):
        active = started(start(arm(self.state)), 101)
        current = decide(active, event(EventKind.CHILD_STATUS, 200,
            expected_generation=active.child_generation, child_id=active.child_id,
            child_phase=ChildPhase.HEALTHY, progress_sequence=1), POLICY).state
        stale = decide(current, event(EventKind.CHILD_RESULT, 150,
            expected_generation=0, child_id="old-child", outcome=ChildOutcome.CLEAN,
            process_exited=True, cleanup_complete=True), POLICY, control_utc=201)
        self.assertTrue(stale.stale)
        self.assertEqual(stale.state, current)

    def test_local_clock_fault_precedes_stale_child_filter(self):
        active = started(start(arm(self.state)), 101)
        held = decide(active, event(EventKind.CHILD_RESULT, 50,
            expected_generation=0, child_id="old-child", outcome=ChildOutcome.CLEAN,
            process_exited=True, cleanup_complete=True), POLICY, control_utc=102,
            clock_trusted=False)
        self.assertTrue(held.stale)
        self.assertEqual(held.state.state, SupervisorState.ATTENTION_REQUIRED)
        self.assertEqual(held.state.attention_reason, AttentionReason.CLOCK_UNTRUSTED)
        self.assertEqual(held.state.child_id, active.child_id)
        self.assertEqual(held.actions, (SupervisorAction.REQUEST_GRACEFUL_STOP,))

    def test_heartbeat_without_progress_cannot_hide_stalled_loop(self):
        active = started(start(arm(self.state)), 101)
        first = decide(active, event(EventKind.CHILD_STATUS, 102,
            expected_generation=active.generation, child_id=active.child_id,
            child_phase=ChildPhase.HEALTHY, progress_sequence=1), POLICY).state
        decision = decide(first, event(EventKind.CHILD_STATUS, 133,
            expected_generation=first.generation, child_id=first.child_id,
            child_phase=ChildPhase.HEALTHY, progress_sequence=1), POLICY)
        self.assertEqual(decision.state.state, SupervisorState.STOPPING)
        self.assertEqual(decision.state.attention_reason, AttentionReason.PROGRESS_STALLED)
        self.assertEqual(decision.state.last_heartbeat_utc, 102)
        self.assertEqual(decision.actions, (SupervisorAction.REQUEST_GRACEFUL_STOP,))

    def test_explicit_work_deadline_allows_slow_healthy_work(self):
        active = started(start(arm(self.state)), 101)
        working = decide(active, event(EventKind.CHILD_STATUS, 102,
            expected_generation=active.generation, child_id=active.child_id,
            child_phase=ChildPhase.RECOVERING, progress_sequence=1,
            work_deadline_utc=150), POLICY).state
        working = decide(working, event(EventKind.CHILD_STATUS, 130,
            expected_generation=working.child_generation, child_id=working.child_id,
            child_phase=ChildPhase.RECOVERING, progress_sequence=1,
            work_deadline_utc=150), POLICY).state
        checked = decide(working, event(EventKind.TICK, 150), POLICY)
        self.assertEqual(checked.state.state, SupervisorState.RECOVERING)
        self.assertEqual(checked.actions, ())

    def test_work_deadline_cannot_hide_missing_heartbeat(self):
        active = started(start(arm(self.state)), 101)
        working = decide(active, event(EventKind.CHILD_STATUS, 102,
            expected_generation=active.child_generation, child_id=active.child_id,
            child_phase=ChildPhase.RECOVERING, progress_sequence=1,
            work_deadline_utc=162), POLICY).state
        decision = decide(working, event(EventKind.TICK, 132), POLICY)
        self.assertEqual(decision.state.state, SupervisorState.STOPPING)
        self.assertEqual(decision.state.attention_reason, AttentionReason.PROGRESS_STALLED)

    def test_unchanged_progress_cannot_extend_work_deadline(self):
        active = started(start(arm(self.state)), 101)
        working = decide(active, event(EventKind.CHILD_STATUS, 102,
            expected_generation=active.child_generation, child_id=active.child_id,
            child_phase=ChildPhase.RECOVERING, progress_sequence=1,
            work_deadline_utc=150), POLICY).state
        extended = decide(working, event(EventKind.CHILD_STATUS, 120,
            expected_generation=working.child_generation, child_id=working.child_id,
            child_phase=ChildPhase.RECOVERING, progress_sequence=1,
            work_deadline_utc=180), POLICY)
        self.assertEqual(extended.state.state, SupervisorState.ATTENTION_REQUIRED)
        self.assertEqual(extended.state.attention_reason, AttentionReason.INTEGRITY_FAILURE)

    def test_shutdown_timeout_never_kills_or_restarts_child(self):
        active = started(start(arm(self.state)), 101)
        stopping = decide(active, event(EventKind.STOP, 110), POLICY).state
        decision = decide(stopping, event(EventKind.TICK, 171), POLICY)
        self.assertEqual(decision.state.state, SupervisorState.ATTENTION_REQUIRED)
        self.assertEqual(decision.state.attention_reason, AttentionReason.SHUTDOWN_TIMEOUT)
        self.assertEqual(decision.state.child_id, active.child_id)
        self.assertEqual(decision.actions, ())

    def test_timeout_attention_survives_clean_child_exit(self):
        active = started(start(arm(self.state)), 101)
        active = decide(active, event(EventKind.CHILD_STATUS, 102,
            expected_generation=active.child_generation, child_id=active.child_id,
            child_phase=ChildPhase.RECOVERING, progress_sequence=1), POLICY).state
        stopping = decide(active, event(EventKind.TICK, 132), POLICY).state
        self.assertEqual(stopping.attention_reason, AttentionReason.PROGRESS_STALLED)
        exited = decide(stopping, event(EventKind.CHILD_RESULT, 133,
            expected_generation=active.generation, child_id=active.child_id,
            outcome=ChildOutcome.CLEAN, process_exited=True,
            cleanup_complete=True), POLICY)
        self.assertEqual(exited.state.state, SupervisorState.ATTENTION_REQUIRED)
        self.assertEqual(exited.state.attention_reason, AttentionReason.PROGRESS_STALLED)

    def test_manual_stop_does_not_erase_integrity_result(self):
        active = started(start(arm(self.state)), 101)
        stopping = decide(active, event(EventKind.STOP, 102), POLICY).state
        exited = decide(stopping, event(EventKind.CHILD_RESULT, 103,
            expected_generation=active.generation, child_id=active.child_id,
            outcome=ChildOutcome.INTEGRITY_FAILURE, process_exited=True,
            cleanup_complete=True), POLICY)
        self.assertEqual(exited.state.state, SupervisorState.ATTENTION_REQUIRED)
        self.assertEqual(exited.state.attention_reason, AttentionReason.INTEGRITY_FAILURE)

    def test_startup_timeout_requests_graceful_stop(self):
        active = start(arm(self.state))
        decision = decide(active, event(EventKind.TICK, 161), POLICY)
        self.assertEqual(decision.state.state, SupervisorState.STOPPING)
        self.assertEqual(decision.state.attention_reason, AttentionReason.STARTUP_TIMEOUT)
        self.assertEqual(decision.actions, (SupervisorAction.REQUEST_GRACEFUL_STOP,))

    def test_safety_stop_fences_arm_prepared_before_fault(self):
        active = started(start(arm(self.state)), 101)
        active = decide(active, event(EventKind.CHILD_STATUS, 102,
            expected_generation=active.child_generation, child_id=active.child_id,
            child_phase=ChildPhase.RECOVERING, progress_sequence=1), POLICY).state
        prepared = event(EventKind.ARM, 134,
            expected_generation=active.generation, build_fingerprint="build-b",
            config_fingerprint="config-b")
        stopping = decide(active, event(EventKind.TICK, 132), POLICY).state
        self.assertEqual(stopping.state, SupervisorState.STOPPING)
        self.assertEqual(stopping.generation, active.generation+1)
        exited = decide(stopping, event(EventKind.CHILD_RESULT, 133,
            expected_generation=active.child_generation, child_id=active.child_id,
            outcome=ChildOutcome.CLEAN, process_exited=True,
            cleanup_complete=True), POLICY).state
        stale = decide(exited, prepared, POLICY)
        self.assertTrue(stale.stale)
        self.assertEqual(stale.state.state, SupervisorState.ATTENTION_REQUIRED)
        self.assertTrue(stale.state.stop_latched)

    def test_startup_uses_absolute_sixty_second_deadline(self):
        active = start(arm(self.state))
        early = None
        for stamp in range(101, 131):
            early = decide(active, event(EventKind.TICK, stamp), POLICY)
            active = early.state
            self.assertEqual(active.state, SupervisorState.STARTING)
        started_state = started(early.state, 131)
        for sequence, stamp in enumerate(range(132, 160, 2), start=1):
            started_state = decide(started_state, event(EventKind.CHILD_STATUS, stamp,
                expected_generation=started_state.child_generation,
                child_id=started_state.child_id, child_phase=ChildPhase.STARTING,
                progress_sequence=sequence), POLICY).state
        expired = decide(started_state, event(EventKind.TICK, 160), POLICY)
        self.assertEqual(expired.state.state, SupervisorState.STOPPING)
        self.assertEqual(expired.state.attention_reason, AttentionReason.STARTUP_TIMEOUT)

    def test_late_startup_status_cannot_erase_expired_deadline(self):
        active = started(start(arm(self.state)), 101)
        expired = decide(active, event(EventKind.CHILD_STATUS, 160,
            expected_generation=active.child_generation, child_id=active.child_id,
            child_phase=ChildPhase.HEALTHY, progress_sequence=1), POLICY)
        self.assertEqual(expired.state.state, SupervisorState.STOPPING)
        self.assertEqual(expired.state.attention_reason, AttentionReason.STARTUP_TIMEOUT)
        self.assertEqual(expired.actions, (SupervisorAction.REQUEST_GRACEFUL_STOP,))

    def test_completed_startup_leaves_absolute_startup_deadline(self):
        active = started(start(arm(self.state)), 101)
        recovering = decide(active, event(EventKind.CHILD_STATUS, 150,
            expected_generation=active.child_generation, child_id=active.child_id,
            child_phase=ChildPhase.RECOVERING, progress_sequence=1), POLICY).state
        checked = decide(recovering, event(EventKind.TICK, 160), POLICY)
        self.assertEqual(checked.state.state, SupervisorState.RECOVERING)

    def test_healthy_progress_resets_incident_only_after_ten_minutes(self):
        active = started(start(arm(self.state)), 101)
        healthy = decide(active, event(EventKind.CHILD_STATUS, 102,
            expected_generation=active.generation, child_id=active.child_id,
            child_phase=ChildPhase.HEALTHY, progress_sequence=1), POLICY).state
        for sequence, stamp in enumerate(range(122, 683, 20), start=2):
            healthy = decide(healthy, event(EventKind.CHILD_STATUS, stamp,
                expected_generation=healthy.child_generation,
                child_id=healthy.child_id, child_phase=ChildPhase.HEALTHY,
                progress_sequence=sequence), POLICY).state
        early = decide(healthy, event(EventKind.TICK, 701), POLICY).state
        self.assertEqual(early.incident_attempts, 1)
        early = decide(early, event(EventKind.CHILD_STATUS, 702,
            expected_generation=early.child_generation, child_id=early.child_id,
            child_phase=ChildPhase.HEALTHY, progress_sequence=31), POLICY).state
        reset = decide(early, event(EventKind.TICK, 702), POLICY).state
        self.assertEqual((reset.incident_attempts, reset.restart_attempts_utc), (0, ()))

    def test_late_progress_status_cannot_erase_expired_deadline(self):
        active = started(start(arm(self.state)), 101)
        healthy = decide(active, event(EventKind.CHILD_STATUS, 102.2,
            expected_generation=active.child_generation, child_id=active.child_id,
            child_phase=ChildPhase.HEALTHY, progress_sequence=1), POLICY).state
        for stamp in range(103, 133):
            healthy = decide(healthy, event(EventKind.TICK, stamp), POLICY).state
        expired = decide(healthy, event(EventKind.CHILD_STATUS, 132.5,
            expected_generation=healthy.child_generation, child_id=healthy.child_id,
            child_phase=ChildPhase.HEALTHY, progress_sequence=2), POLICY)
        self.assertEqual(expired.state.state, SupervisorState.STOPPING)
        self.assertEqual(expired.state.attention_reason, AttentionReason.PROGRESS_STALLED)

    def test_status_after_health_observation_gap_cannot_refund_attempts(self):
        active = started(start(arm(self.state)), 101)
        healthy = decide(active, event(EventKind.CHILD_STATUS, 102,
            expected_generation=active.child_generation, child_id=active.child_id,
            child_phase=ChildPhase.HEALTHY, progress_sequence=1), POLICY).state
        expired = decide(healthy, event(EventKind.CHILD_STATUS, 702,
            expected_generation=healthy.child_generation, child_id=healthy.child_id,
            child_phase=ChildPhase.HEALTHY, progress_sequence=2), POLICY)
        self.assertEqual(expired.state.state, SupervisorState.STOPPING)
        self.assertEqual(expired.state.incident_attempts, 1)
        self.assertEqual(expired.state.restart_attempts_utc, (100.0,))

    def test_retry_holds_survive_status_and_prevent_healthy_label(self):
        active = started(start(arm(self.state)), 101)
        status = decide(active, event(EventKind.CHILD_STATUS, 102,
            expected_generation=active.generation, child_id=active.child_id,
            child_phase=ChildPhase.HEALTHY, progress_sequence=1,
            retry_holds=("quota_retry_exhausted",)), POLICY).state
        self.assertEqual(status.state, SupervisorState.DEGRADED)
        self.assertEqual(status.retry_holds, ("quota_retry_exhausted",))
        omitted = decide(status, event(EventKind.CHILD_STATUS, 103,
            expected_generation=status.generation, child_id=status.child_id,
            child_phase=ChildPhase.HEALTHY, progress_sequence=2), POLICY).state
        self.assertEqual(omitted.state, SupervisorState.DEGRADED)
        self.assertEqual(omitted.retry_holds, ("quota_retry_exhausted",))
        failed = result(omitted, ChildOutcome.TRANSIENT_FAILURE).state
        self.assertEqual(failed.retry_holds, ("quota_retry_exhausted",))
        self.assertEqual(failed.state, SupervisorState.ATTENTION_REQUIRED)

    def test_retry_holds_require_explicit_resolution_before_arm(self):
        active = started(start(arm(self.state)), 101)
        held = decide(active, event(EventKind.CHILD_STATUS, 102,
            expected_generation=active.child_generation, child_id=active.child_id,
            child_phase=ChildPhase.DEGRADED, progress_sequence=1,
            retry_holds=("quota_retry_exhausted", "cooldown_pending")), POLICY).state
        stopped = result(held, ChildOutcome.RETRY_EXHAUSTED, 103).state
        refused = decide(stopped, event(EventKind.ARM, 104,
            expected_generation=stopped.generation, build_fingerprint="build-b",
            config_fingerprint="config-b"), POLICY)
        self.assertTrue(refused.stale)
        self.assertEqual(refused.state.retry_holds,
                         ("quota_retry_exhausted", "cooldown_pending"))
        resolved = decide(stopped, event(EventKind.HOLDS_RESOLVED, 104,
            expected_generation=stopped.generation,
            retry_holds=("quota_retry_exhausted", "cooldown_pending")), POLICY).state
        rearmed = decide(resolved, event(EventKind.ARM, 105,
            expected_generation=resolved.generation, build_fingerprint="build-b",
            config_fingerprint="config-b"), POLICY)
        self.assertEqual(rearmed.state.state, SupervisorState.BACKOFF)

    def test_late_spawn_events_do_not_release_running_child(self):
        active = started(start(arm(self.state)), 101)
        late_failure = decide(active, event(EventKind.SPAWN_FAILED, 102,
            expected_generation=active.child_generation, child_id=active.child_id), POLICY)
        self.assertTrue(late_failure.stale)
        self.assertEqual(late_failure.state, active)
        replay = decide(active, event(EventKind.CHILD_STARTED, 129,
            expected_generation=active.child_generation, child_id=active.child_id), POLICY)
        self.assertTrue(replay.stale)
        self.assertEqual(replay.state.last_progress_utc, 101)

    def test_late_spawn_events_do_not_release_stopping_or_attention_child(self):
        active = started(start(arm(self.state)), 101)
        stopping = decide(active, event(EventKind.STOP, 102), POLICY).state
        attention = decide(active, event(EventKind.TICK, 100), POLICY).state
        self.assertEqual(attention.state, SupervisorState.ATTENTION_REQUIRED)
        for current in (stopping, attention):
            with self.subTest(state=current.state):
                failed = decide(current, event(EventKind.SPAWN_FAILED, 103,
                    expected_generation=current.child_generation,
                    child_id=current.child_id), POLICY, control_utc=103)
                replay = decide(current, event(EventKind.CHILD_STARTED, 103,
                    expected_generation=current.child_generation,
                    child_id=current.child_id), POLICY, control_utc=103)
                self.assertTrue(failed.stale)
                self.assertTrue(replay.stale)
                self.assertEqual(failed.state.child_id, active.child_id)
                self.assertEqual(replay.state.child_id, active.child_id)

    def test_confirmed_unexpected_death_enters_recovery_without_cleanup_claim(self):
        active = started(start(arm(self.state)), 101)
        crashed = decide(active, event(EventKind.CHILD_RESULT, 102,
            expected_generation=active.child_generation, child_id=active.child_id,
            outcome=ChildOutcome.UNEXPECTED_DEATH, process_exited=True,
            unresolved_work=True), POLICY)
        self.assertEqual(crashed.state.state, SupervisorState.BACKOFF)
        self.assertIsNone(crashed.state.child_id)
        self.assertEqual(crashed.state.recovery_reasons,
                         ("unexpected_death", "cleanup_unconfirmed", "unresolved_work"))
        self.assertEqual(crashed.actions, ())

    def test_uncertain_exit_retains_child_and_cleanup_failure_blocks(self):
        active = started(start(arm(self.state)), 101)
        uncertain = decide(active, event(EventKind.CHILD_RESULT, 102,
            expected_generation=active.child_generation, child_id=active.child_id,
            outcome=ChildOutcome.UNEXPECTED_DEATH), POLICY)
        self.assertEqual(uncertain.state.state, SupervisorState.ATTENTION_REQUIRED)
        self.assertEqual(uncertain.state.child_id, active.child_id)
        self.assertIn("process_exit_unconfirmed", uncertain.state.retry_holds)
        failed = decide(active, event(EventKind.CHILD_RESULT, 102,
            expected_generation=active.child_generation, child_id=active.child_id,
            outcome=ChildOutcome.UNEXPECTED_DEATH, process_exited=True,
            cleanup_failed=True), POLICY)
        self.assertEqual(failed.state.state, SupervisorState.ATTENTION_REQUIRED)
        self.assertIsNone(failed.state.child_id)
        self.assertIn("cleanup_failed", failed.state.retry_holds)

    def test_regressing_progress_is_integrity_failure(self):
        active = started(start(arm(self.state)), 101)
        current = decide(active, event(EventKind.CHILD_STATUS, 102,
            expected_generation=active.generation, child_id=active.child_id,
            child_phase=ChildPhase.RECOVERING, progress_sequence=3), POLICY).state
        decision = decide(current, event(EventKind.CHILD_STATUS, 103,
            expected_generation=current.generation, child_id=current.child_id,
            child_phase=ChildPhase.RECOVERING, progress_sequence=2), POLICY)
        self.assertEqual(decision.state.attention_reason, AttentionReason.INTEGRITY_FAILURE)
        self.assertEqual(decision.actions, (SupervisorAction.REQUEST_GRACEFUL_STOP,))

    def test_invalid_contracts_fail_closed(self):
        with self.assertRaises(InvalidData):
            SupervisorPolicy(restart_delays=(10, 5))
        with self.assertRaises(InvalidData):
            replace(self.state, state=SupervisorState.HEALTHY, child_id=None)
        with self.assertRaises(InvalidData):
            event(EventKind.CHILD_STATUS, float("nan"))

    def test_child_events_without_complete_identity_are_stale(self):
        childless = (self.state, arm(self.state),
                     replace(self.state, state=SupervisorState.ATTENTION_REQUIRED,
                         attention_reason=AttentionReason.UNKNOWN_FAILURE))
        for state in childless:
            for values in ({}, {"child_id": "child-a"}, {"expected_generation": 0}):
                with self.subTest(state=state.state, values=values):
                    decision = decide(state, event(EventKind.CHILD_RESULT, 91,
                        outcome=ChildOutcome.UNKNOWN_FAILURE, process_exited=True,
                        **values), POLICY, control_utc=max(91, state.updated_utc))
                    self.assertTrue(decision.stale)
                    self.assertEqual(decision.state, state)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/"supervisor.db"

    def open(self, **values):
        return SupervisorStore(self.path, scope_id="kalshi-primary", **values)

    def arm_event(self, generation=0, now=100):
        return event(EventKind.ARM, now, expected_generation=generation,
            build_fingerprint="build-a", config_fingerprint="config-a")

    def test_missing_store_initializes_disarmed_and_persists(self):
        with self.open() as store:
            self.assertEqual(store.read().state, SupervisorState.DISARMED)
            store.apply(self.arm_event())
        with self.open() as reopened:
            self.assertEqual(reopened.read().state, SupervisorState.BACKOFF)
            self.assertFalse(reopened.read().live_ready)

    def test_host_tick_coalesces_only_materially_idle_journal_work(self):
        clock = ControlledClock()
        with self.open(clock=clock.utc, monotonic_clock=clock.monotonic,
                boot_id=clock.boot_id) as store:
            before_revision = store.revision()
            before_events = len(store.history(limit=store.event_limit))
            clock.advance(1)
            idle = store.tick(event(EventKind.TICK, 101))
            self.assertEqual(idle.state.updated_utc, 101)
            self.assertEqual(store.read().updated_utc, 100)
            self.assertEqual(store.revision(), before_revision)
            self.assertEqual(len(store.history(limit=store.event_limit)), before_events)

            armed = store.apply(self.arm_event(store.read().generation, 101)).state
            before_revision = store.revision()
            due = store.tick(event(EventKind.TICK, 101))
            self.assertEqual(due.actions, (SupervisorAction.START_DUE,))
            self.assertEqual(store.revision(), before_revision+1)
            self.assertEqual(store.read().updated_utc, 101)
            self.assertEqual(due.state.generation, armed.generation)

    def test_host_tick_persists_clock_fault_instead_of_coalescing(self):
        clock = ControlledClock()
        with self.open(clock=clock.utc, monotonic_clock=clock.monotonic,
                boot_id=clock.boot_id) as store:
            before_revision = store.revision()
            clock.wall = 10_000
            clock.monotonic_value = 1
            held = store.tick(event(EventKind.TICK, 10_000)).state
            self.assertEqual(store.revision(), before_revision+1)
            self.assertEqual(held.state, SupervisorState.ATTENTION_REQUIRED)
            self.assertEqual(held.attention_reason, AttentionReason.CLOCK_UNTRUSTED)
            self.assertEqual(store.read(), held)

    def test_start_attempt_is_durable_before_spawn_action(self):
        with self.open() as store:
            armed = store.apply(self.arm_event()).state
            decision = store.apply(event(EventKind.START_REQUESTED, 100,
                expected_generation=armed.generation, child_id="child-a"))
            self.assertEqual(decision.actions, (SupervisorAction.SPAWN_RECOVERY,))
        with self.open() as reopened:
            state = reopened.read()
            self.assertEqual((state.state, state.incident_attempts, state.child_id),
                             (SupervisorState.STARTING, 1, "child-a"))

    def test_failed_transaction_does_not_reserve_attempt(self):
        with self.open() as store:
            armed = store.apply(self.arm_event()).state
            store.connection.execute("CREATE TRIGGER reject_control BEFORE UPDATE ON control "
                                     "BEGIN SELECT RAISE(ABORT,'injected'); END")
            with self.assertRaises(sqlite3.IntegrityError):
                store.apply(event(EventKind.START_REQUESTED, 100,
                    expected_generation=armed.generation, child_id="child-a"))
            store.connection.execute("DROP TRIGGER reject_control")
            state = store.read()
            self.assertEqual((state.incident_attempts, state.child_id), (0, None))

    def test_corrupt_or_missing_state_refuses_open_and_read(self):
        store = self.open()
        store.connection.execute("UPDATE control SET payload='{}'")
        store.connection.commit()
        with self.assertRaises(InvalidData):
            store.read()
        store.close()
        with self.assertRaises(InvalidData):
            self.open()

    def test_missing_clock_checkpoint_refuses_apply_and_reopen(self):
        store = self.open()
        store.connection.execute("DELETE FROM clock_state")
        store.connection.commit()
        with self.assertRaises(InvalidData):
            store.apply(event(EventKind.TICK, 100))
        store.close()
        with self.assertRaises(InvalidData):
            self.open()

    def test_missing_control_row_is_never_recreated_as_armed(self):
        with self.open() as store:
            store.connection.execute("DELETE FROM control")
            store.connection.commit()
            with self.assertRaises(InvalidData):
                store.read()
        with self.assertRaises(InvalidData):
            self.open()

    def test_scope_mismatch_refuses_existing_store(self):
        self.open().close()
        with self.assertRaises(InvalidData):
            SupervisorStore(self.path, scope_id="another-account")

    def test_history_is_bounded_and_contains_no_trading_authority(self):
        with self.open(event_limit=16) as store:
            for stamp in range(91, 111):
                store.apply(event(EventKind.TICK, stamp))
            history = store.history(limit=16)
            self.assertEqual(len(history), 16)
            self.assertTrue(all("live_ready" not in row["payload"] for row in history))

    def test_concurrent_prepared_arm_and_stop_always_finishes_disarmed(self):
        with self.open() as store:
            generation = store.read().generation
        gate = Barrier(3)
        failures = []
        def apply_one(which):
            try:
                with self.open() as local:
                    gate.wait()
                    local.apply(self.arm_event(generation) if which == "arm"
                        else event(EventKind.STOP, 100))
            except BaseException as exc:
                failures.append(exc)
        threads = [Thread(target=apply_one, args=(name,)) for name in ("arm", "stop")]
        for thread in threads:
            thread.start()
        gate.wait()
        for thread in threads:
            thread.join()
        self.assertEqual(failures, [])
        with self.open() as store:
            state = store.read()
            self.assertEqual(state.state, SupervisorState.DISARMED)
            self.assertTrue(state.stop_latched)

    def test_stale_prepared_arm_is_journaled_but_cannot_clear_stop(self):
        with self.open() as store:
            generation = store.read().generation
            store.apply(event(EventKind.STOP, 100))
            decision = store.apply(self.arm_event(generation, 101))
            self.assertTrue(decision.stale)
            self.assertEqual(store.read().state, SupervisorState.DISARMED)
            self.assertTrue(store.history(limit=2)[-1]["stale"])

    def test_delayed_stop_fences_prepared_arm_with_separate_control_clock(self):
        class Clock:
            wall = 90.0
            monotonic_value = 0.0

            def utc(self):
                return self.wall

            def monotonic(self):
                return self.monotonic_value

            def advance(self, seconds):
                self.wall += seconds
                self.monotonic_value += seconds

        clock = Clock()
        with self.open(clock=clock.utc, monotonic_clock=clock.monotonic) as store:
            armed = store.apply(self.arm_event()).state
            prepared = self.arm_event(armed.generation, 103)
            clock.advance(12)
            store.apply(event(EventKind.TICK, 102))
            stopped = store.apply(event(EventKind.STOP, 101)).state
            self.assertEqual(stopped.state, SupervisorState.DISARMED)
            self.assertEqual(stopped.generation, armed.generation+1)
            clock.advance(1)
            stale = store.apply(prepared)
            self.assertTrue(stale.stale)
            self.assertEqual(stale.state.state, SupervisorState.DISARMED)

    def test_repeated_stop_fences_intervening_arm_in_store(self):
        clock = ControlledClock()
        with self.open(clock=clock.utc, monotonic_clock=clock.monotonic,
                boot_id=clock.boot_id) as store:
            armed = store.apply(self.arm_event(now=100)).state
            reserved = store.apply(event(EventKind.START_REQUESTED, 100,
                expected_generation=armed.generation, child_id="child-a")).state
            clock.advance(1)
            active = store.apply(event(EventKind.CHILD_STARTED, 101,
                expected_generation=reserved.child_generation,
                child_id=reserved.child_id)).state
            clock.advance(1)
            first = store.apply(event(EventKind.STOP, 102)).state
            prepared = self.arm_event(first.generation, 102.5)
            clock.advance(1)
            second = store.apply(event(EventKind.STOP, 103)).state
            self.assertEqual(second.generation, first.generation+1)
            clock.advance(1)
            exited = store.apply(event(EventKind.CHILD_RESULT, 104,
                expected_generation=active.child_generation, child_id=active.child_id,
                outcome=ChildOutcome.CLEAN, process_exited=True,
                cleanup_complete=True)).state
            clock.advance(1)
            stale = store.apply(prepared)
            self.assertTrue(stale.stale)
            self.assertEqual(exited.state, SupervisorState.DISARMED)
            self.assertEqual(stale.state.state, SupervisorState.DISARMED)

    def test_failed_spawn_after_timeout_commits_across_reopen(self):
        clock = ControlledClock()
        with self.open(clock=clock.utc, monotonic_clock=clock.monotonic,
                boot_id=clock.boot_id) as store:
            armed = store.apply(self.arm_event(now=100)).state
            reserved = store.apply(event(EventKind.START_REQUESTED, 100,
                expected_generation=armed.generation, child_id="child-a")).state
            clock.advance(60)
            timed_out = store.apply(event(EventKind.TICK, 160)).state
            self.assertEqual(timed_out.attention_reason, AttentionReason.STARTUP_TIMEOUT)
        clock.advance(1)
        with self.open(clock=clock.utc, monotonic_clock=clock.monotonic,
                boot_id=clock.boot_id) as store:
            failed = store.apply(event(EventKind.SPAWN_FAILED, 161,
                expected_generation=reserved.child_generation,
                child_id=reserved.child_id)).state
            self.assertEqual(failed.state, SupervisorState.ATTENTION_REQUIRED)
            self.assertEqual(failed.attention_reason, AttentionReason.STARTUP_TIMEOUT)
            self.assertIsNone(failed.child_id)

    def test_validated_clock_continuity_survives_reopen_without_aging_early(self):
        clock = ControlledClock()
        with self.open(clock=clock.utc, monotonic_clock=clock.monotonic,
                boot_id=clock.boot_id) as store:
            armed = store.apply(self.arm_event(now=100)).state
            reserved = store.apply(event(EventKind.START_REQUESTED, 100,
                expected_generation=armed.generation, child_id="child-a")).state
            clock.advance(1)
            waiting = store.apply(event(EventKind.SPAWN_FAILED, 101,
                expected_generation=reserved.child_generation,
                child_id=reserved.child_id)).state
            self.assertEqual(waiting.next_restart_utc, 111)
        clock.advance(1)
        with self.open(clock=clock.utc, monotonic_clock=clock.monotonic,
                boot_id=clock.boot_id) as store:
            early = store.apply(event(EventKind.TICK, 102))
            self.assertEqual(early.actions, ())
            self.assertEqual(early.state.state, SupervisorState.BACKOFF)
        clock.advance(9)
        with self.open(clock=clock.utc, monotonic_clock=clock.monotonic,
                boot_id=clock.boot_id) as store:
            due = store.apply(event(EventKind.TICK, 111))
            self.assertEqual(due.actions, (SupervisorAction.START_DUE,))

    def test_wall_adjustments_and_boot_change_hold_for_attention(self):
        cases = ((10000.0, 2.0, "boot-a"),
                 (50.0, 2.0, "boot-a"),
                 (102.0, 2.0, "boot-b"))
        for number, (wall, monotonic, boot) in enumerate(cases):
            with self.subTest(wall=wall, monotonic=monotonic, boot=boot):
                path = Path(self.temp.name)/f"clock-{number}.db"
                clock = ControlledClock()
                with SupervisorStore(path, scope_id="kalshi-primary",
                        clock=clock.utc, monotonic_clock=clock.monotonic,
                        boot_id=clock.boot_id) as store:
                    store.apply(self.arm_event(now=100))
                clock.wall = wall
                clock.monotonic_value = monotonic
                clock.boot = boot
                with SupervisorStore(path, scope_id="kalshi-primary",
                        clock=clock.utc, monotonic_clock=clock.monotonic,
                        boot_id=clock.boot_id) as store:
                    held = store.apply(event(EventKind.TICK, wall)).state
                    self.assertEqual(held.state, SupervisorState.ATTENTION_REQUIRED)
                    self.assertEqual(held.attention_reason,
                                     AttentionReason.CLOCK_UNTRUSTED)
                    self.assertTrue(held.stop_latched)

    def test_concurrent_store_instances_share_clock_checkpoint(self):
        clock = ControlledClock()
        first = self.open(clock=clock.utc, monotonic_clock=clock.monotonic,
            boot_id=clock.boot_id)
        second = self.open(clock=clock.utc, monotonic_clock=clock.monotonic,
            boot_id=clock.boot_id)
        self.addCleanup(first.close)
        self.addCleanup(second.close)
        first.apply(self.arm_event(now=100))
        clock.advance(1)
        one = first.apply(event(EventKind.TICK, 101)).state
        clock.advance(1)
        two = second.apply(event(EventKind.TICK, 102)).state
        self.assertEqual(one.state, SupervisorState.BACKOFF)
        self.assertEqual(two.state, SupervisorState.BACKOFF)
        self.assertEqual(two.updated_utc, 102)

    def test_untrusted_clock_cannot_be_consumed_by_stale_or_missing_child(self):
        payloads = (
            dict(expected_generation=0, child_id="old-child"),
            dict(expected_generation=None, child_id=None),
        )
        for number, values in enumerate(payloads):
            with self.subTest(values=values):
                path = Path(self.temp.name)/f"stale-clock-{number}.db"
                clock = ControlledClock()
                first = SupervisorStore(path, scope_id="kalshi-primary",
                    clock=clock.utc, monotonic_clock=clock.monotonic,
                    boot_id=clock.boot_id)
                second = SupervisorStore(path, scope_id="kalshi-primary",
                    clock=clock.utc, monotonic_clock=clock.monotonic,
                    boot_id=clock.boot_id)
                try:
                    armed = first.apply(self.arm_event(now=100)).state
                    clock.wall = 10000
                    clock.monotonic_value = 1
                    held = second.apply(event(EventKind.CHILD_RESULT, 10000,
                        outcome=ChildOutcome.CLEAN, process_exited=True,
                        cleanup_complete=True, **values))
                    self.assertTrue(held.stale)
                    self.assertEqual(held.state.state,
                                     SupervisorState.ATTENTION_REQUIRED)
                    self.assertEqual(held.state.attention_reason,
                                     AttentionReason.CLOCK_UNTRUSTED)
                    self.assertTrue(held.state.stop_latched)
                    self.assertEqual(second.history(limit=1)[0]["clock_trusted"], 0)
                    clock.advance(1)
                    persisted = first.apply(event(EventKind.TICK, 10001))
                    self.assertEqual(persisted.state.state,
                                     SupervisorState.ATTENTION_REQUIRED)
                    self.assertEqual(persisted.actions, ())
                    refused = first.apply(event(EventKind.START_REQUESTED, 10001,
                        expected_generation=armed.generation, child_id="next-child"))
                    self.assertTrue(refused.stale)
                finally:
                    first.close()
                    second.close()
                clock.advance(1)
                with SupervisorStore(path, scope_id="kalshi-primary",
                        clock=clock.utc, monotonic_clock=clock.monotonic,
                        boot_id=clock.boot_id) as reopened:
                    self.assertEqual(reopened.read().state,
                                     SupervisorState.ATTENTION_REQUIRED)
                    self.assertTrue(reopened.read().stop_latched)

    def test_clock_fault_precedes_duplicate_lifecycle_and_preserves_child(self):
        clock = ControlledClock()
        with self.open(clock=clock.utc, monotonic_clock=clock.monotonic,
                boot_id=clock.boot_id) as store:
            armed = store.apply(self.arm_event(now=100)).state
            reserved = store.apply(event(EventKind.START_REQUESTED, 100,
                expected_generation=armed.generation, child_id="child-a")).state
            clock.advance(1)
            active = store.apply(event(EventKind.CHILD_STARTED, 101,
                expected_generation=reserved.child_generation,
                child_id=reserved.child_id)).state
            clock.wall = 10000
            clock.monotonic_value = 2
            held = store.apply(event(EventKind.CHILD_STARTED, 10000,
                expected_generation=active.child_generation,
                child_id=active.child_id))
            self.assertTrue(held.stale)
            self.assertEqual(held.state.state, SupervisorState.ATTENTION_REQUIRED)
            self.assertEqual(held.state.attention_reason,
                             AttentionReason.CLOCK_UNTRUSTED)
            self.assertEqual(held.state.child_id, active.child_id)
            self.assertEqual(held.actions, (SupervisorAction.REQUEST_GRACEFUL_STOP,))
            clock.advance(1)
            status = store.apply(event(EventKind.CHILD_STATUS, 10001,
                expected_generation=active.child_generation,
                child_id=active.child_id, child_phase=ChildPhase.HEALTHY,
                progress_sequence=1))
            self.assertTrue(status.stale)
            self.assertEqual(status.state.state, SupervisorState.ATTENTION_REQUIRED)
            clock.advance(1)
            exited = store.apply(event(EventKind.CHILD_RESULT, 10002,
                expected_generation=active.child_generation,
                child_id=active.child_id, outcome=ChildOutcome.CLEAN,
                process_exited=True, cleanup_complete=True)).state
            self.assertEqual(exited.state, SupervisorState.ATTENTION_REQUIRED)
            self.assertEqual(exited.attention_reason, AttentionReason.CLOCK_UNTRUSTED)
            self.assertIsNone(exited.child_id)

    def test_default_clock_tolerates_sampling_skew_across_reopen_and_instances(self):
        clock = ControlledClock(wall=110.001, monotonic=10)
        with self.open(clock=clock.utc, monotonic_clock=clock.monotonic) as store:
            store.apply(self.arm_event(now=110.001))
            original_boot = store._read_clock()[0]
        clock.wall = 111.001
        clock.monotonic_value = 11.002
        first = self.open(clock=clock.utc, monotonic_clock=clock.monotonic)
        second = self.open(clock=clock.utc, monotonic_clock=clock.monotonic)
        self.addCleanup(first.close)
        self.addCleanup(second.close)
        one = first.apply(event(EventKind.TICK, 111.001)).state
        self.assertEqual(one.state, SupervisorState.BACKOFF)
        self.assertEqual(first.history(limit=1)[0]["clock_trusted"], 1)
        self.assertEqual(first._read_clock()[0], original_boot)
        clock.wall = 112.003
        clock.monotonic_value = 12.003
        two = second.apply(event(EventKind.TICK, 112.003)).state
        self.assertEqual(two.state, SupervisorState.BACKOFF)
        self.assertNotEqual(two.attention_reason, AttentionReason.CLOCK_UNTRUSTED)
        self.assertEqual(second._read_clock()[0], original_boot)

    def test_default_clock_discontinuities_hold_for_attention(self):
        cases = ((10000.0, 2.0), (50.0, 2.0), (101.0, 0.5))
        for number, (wall, monotonic) in enumerate(cases):
            with self.subTest(wall=wall, monotonic=monotonic):
                path = Path(self.temp.name)/f"default-clock-{number}.db"
                clock = ControlledClock(wall=100, monotonic=1)
                with SupervisorStore(path, scope_id="kalshi-primary",
                        clock=clock.utc, monotonic_clock=clock.monotonic) as store:
                    store.apply(self.arm_event(now=100))
                clock.wall = wall
                clock.monotonic_value = monotonic
                with SupervisorStore(path, scope_id="kalshi-primary",
                        clock=clock.utc, monotonic_clock=clock.monotonic) as store:
                    held = store.apply(event(EventKind.TICK, wall)).state
                    self.assertEqual(held.state, SupervisorState.ATTENTION_REQUIRED)
                    self.assertEqual(held.attention_reason,
                                     AttentionReason.CLOCK_UNTRUSTED)
                    self.assertTrue(held.stop_latched)

    def test_stop_fences_arm_when_clock_continuity_is_lost(self):
        clock = ControlledClock()
        with self.open(clock=clock.utc, monotonic_clock=clock.monotonic,
                boot_id=clock.boot_id) as store:
            armed = store.apply(self.arm_event(now=100)).state
            prepared = self.arm_event(armed.generation, 101)
            clock.wall = 10000
            clock.monotonic_value = 1
            stopped = store.apply(event(EventKind.STOP, 10000)).state
            self.assertEqual(stopped.state, SupervisorState.ATTENTION_REQUIRED)
            self.assertEqual(stopped.attention_reason, AttentionReason.CLOCK_UNTRUSTED)
            self.assertTrue(stopped.stop_latched)
            clock.advance(1)
            stale = store.apply(prepared)
            self.assertTrue(stale.stale)
            self.assertEqual(stale.state.state, SupervisorState.ATTENTION_REQUIRED)

    def test_retry_holds_persist_and_block_arm_until_explicit_resolution(self):
        with self.open() as store:
            armed = store.apply(self.arm_event()).state
            running = store.apply(event(EventKind.START_REQUESTED, 101,
                expected_generation=armed.generation, child_id="child-a")).state
            running = store.apply(event(EventKind.CHILD_STARTED, 102,
                expected_generation=running.child_generation,
                child_id=running.child_id)).state
            held = store.apply(event(EventKind.CHILD_STATUS, 103,
                expected_generation=running.child_generation,
                child_id=running.child_id, child_phase=ChildPhase.DEGRADED,
                progress_sequence=1,
                retry_holds=("quota_retry_exhausted",))).state
            stopped = store.apply(event(EventKind.CHILD_RESULT, 104,
                expected_generation=held.child_generation, child_id=held.child_id,
                outcome=ChildOutcome.RETRY_EXHAUSTED, process_exited=True,
                cleanup_complete=True)).state
        with self.open() as store:
            persisted = store.read()
            self.assertEqual(persisted.retry_holds, ("quota_retry_exhausted",))
            refused = store.apply(self.arm_event(persisted.generation, 105))
            self.assertTrue(refused.stale)
            resolved = store.apply(event(EventKind.HOLDS_RESOLVED, 106,
                expected_generation=persisted.generation,
                retry_holds=("quota_retry_exhausted",))).state
            self.assertEqual(resolved.retry_holds, ())


class ResourceFixtureTests(unittest.TestCase):
    def test_idle_fixture_executes_policy_and_journal(self):
        report = measure_idle(0.01)
        self.assertGreaterEqual(report["policy_events"], 6)
        self.assertEqual(report["journal_events"], report["policy_events"])
        self.assertFalse(report["live_ready"])


if __name__ == "__main__":
    unittest.main()
