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


POLICY = SupervisorPolicy()


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
    values.setdefault("cleanup_complete", True)
    return decide(state, event(EventKind.CHILD_RESULT, now,
        expected_generation=state.generation, child_id=state.child_id,
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
            outcome=ChildOutcome.UNEXPECTED_DEATH, cleanup_complete=True), POLICY)
        self.assertEqual(exited.state.state, SupervisorState.DISARMED)

    def test_repeated_stop_preserves_child_generation_until_exit(self):
        active = started(start(arm(self.state)), 101)
        first = decide(active, event(EventKind.STOP, 102), POLICY).state
        second = decide(first, event(EventKind.STOP, 103), POLICY).state
        self.assertEqual(second.generation, first.generation)
        self.assertEqual(second.child_generation, active.generation)
        exited = decide(second, event(EventKind.CHILD_RESULT, 104,
            expected_generation=active.generation, child_id=active.child_id,
            outcome=ChildOutcome.CLEAN, cleanup_complete=True), POLICY)
        self.assertEqual(exited.state.state, SupervisorState.DISARMED)

    def test_stale_child_result_after_rearm_cannot_change_new_session(self):
        first = start(arm(self.state), child="old")
        stopped = decide(first, event(EventKind.STOP, 101), POLICY).state
        stopped = decide(stopped, event(EventKind.CHILD_RESULT, 102,
            expected_generation=first.generation, child_id="old",
            outcome=ChildOutcome.CLEAN, cleanup_complete=True), POLICY).state
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

    def test_heartbeat_without_progress_cannot_hide_stalled_loop(self):
        active = started(start(arm(self.state)), 101)
        first = decide(active, event(EventKind.CHILD_STATUS, 102,
            expected_generation=active.generation, child_id=active.child_id,
            child_phase=ChildPhase.HEALTHY, progress_sequence=1), POLICY).state
        heartbeat = decide(first, event(EventKind.CHILD_STATUS, 133,
            expected_generation=first.generation, child_id=first.child_id,
            child_phase=ChildPhase.HEALTHY, progress_sequence=1), POLICY).state
        self.assertEqual(heartbeat.last_heartbeat_utc, 133)
        decision = decide(heartbeat, event(EventKind.TICK, 134), POLICY)
        self.assertEqual(decision.state.state, SupervisorState.STOPPING)
        self.assertEqual(decision.state.attention_reason, AttentionReason.PROGRESS_STALLED)

    def test_explicit_work_deadline_allows_slow_healthy_work(self):
        active = started(start(arm(self.state)), 101)
        working = decide(active, event(EventKind.CHILD_STATUS, 102,
            expected_generation=active.generation, child_id=active.child_id,
            child_phase=ChildPhase.RECOVERING, progress_sequence=1,
            work_deadline_utc=200), POLICY).state
        checked = decide(working, event(EventKind.TICK, 150), POLICY)
        self.assertEqual(checked.state.state, SupervisorState.RECOVERING)
        self.assertEqual(checked.actions, ())

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
        stopping = decide(active, event(EventKind.TICK, 132), POLICY).state
        self.assertEqual(stopping.attention_reason, AttentionReason.PROGRESS_STALLED)
        exited = decide(stopping, event(EventKind.CHILD_RESULT, 133,
            expected_generation=active.generation, child_id=active.child_id,
            outcome=ChildOutcome.CLEAN, cleanup_complete=True), POLICY)
        self.assertEqual(exited.state.state, SupervisorState.ATTENTION_REQUIRED)
        self.assertEqual(exited.state.attention_reason, AttentionReason.PROGRESS_STALLED)

    def test_manual_stop_does_not_erase_integrity_result(self):
        active = started(start(arm(self.state)), 101)
        stopping = decide(active, event(EventKind.STOP, 102), POLICY).state
        exited = decide(stopping, event(EventKind.CHILD_RESULT, 103,
            expected_generation=active.generation, child_id=active.child_id,
            outcome=ChildOutcome.INTEGRITY_FAILURE, cleanup_complete=True), POLICY)
        self.assertEqual(exited.state.state, SupervisorState.ATTENTION_REQUIRED)
        self.assertEqual(exited.state.attention_reason, AttentionReason.INTEGRITY_FAILURE)

    def test_startup_timeout_requests_graceful_stop(self):
        active = start(arm(self.state))
        decision = decide(active, event(EventKind.TICK, 161), POLICY)
        self.assertEqual(decision.state.state, SupervisorState.STOPPING)
        self.assertEqual(decision.state.attention_reason, AttentionReason.STARTUP_TIMEOUT)
        self.assertEqual(decision.actions, (SupervisorAction.REQUEST_GRACEFUL_STOP,))

    def test_healthy_progress_resets_incident_only_after_ten_minutes(self):
        active = started(start(arm(self.state)), 101)
        healthy = decide(active, event(EventKind.CHILD_STATUS, 102,
            expected_generation=active.generation, child_id=active.child_id,
            child_phase=ChildPhase.HEALTHY, progress_sequence=1,
            work_deadline_utc=1000), POLICY).state
        early = decide(healthy, event(EventKind.TICK, 701), POLICY).state
        self.assertEqual(early.incident_attempts, 1)
        reset = decide(early, event(EventKind.TICK, 702), POLICY).state
        self.assertEqual((reset.incident_attempts, reset.restart_attempts_utc), (0, ()))

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


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/"supervisor.db"

    def open(self, **values):
        return SupervisorStore(self.path, scope_id="kalshi-primary", clock=lambda: 90, **values)

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


if __name__ == "__main__":
    unittest.main()
