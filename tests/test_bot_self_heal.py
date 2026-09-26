"""D-144 24/7 self-healing: supervisor cooldowns, boot restart and order lease."""
import unittest

from kalshi_bot.supervised_live import boot_decision
from kalshi_bot.supervision import (AttentionReason, ChildOutcome, EventKind,
                                    SupervisorAction, SupervisorState, decide)
import test_bot_supervision as sup


class BootDecisionTests(unittest.TestCase):
    def status(self, state='STOPPED', **control):
        return dict(state=state, control=dict(dict(desired_armed=True, stop_latched=False), **control))

    def test_restarts_only_a_bot_that_was_running(self):
        self.assertEqual(boot_decision(self.status()), (True, 'was_running_before_restart'))

    def test_manual_stop_or_attention_is_never_undone(self):
        for control in (dict(stop_latched=True, desired_armed=False),
                        dict(desired_armed=False),
                        dict(stop_latched=True)):
            with self.subTest(**control):
                self.assertEqual(boot_decision(self.status(**control))[0], False)

    def test_never_duplicates_running_or_unknown_processes(self):
        for state in ('RUNNING_UNVERIFIED', 'TRANSITION_OR_ORPHAN', 'UNKNOWN'):
            self.assertEqual(boot_decision(self.status(state)),
                             (False, 'processes_present_or_unknown'))


class SupervisorSelfHealTests(unittest.TestCase):
    def setUp(self):
        test = sup.PolicyTests('test_duplicate_arm_cannot_reset_restart_budget')
        test.setUp()
        self.initial = test.state

    def test_cooldown_then_a_fresh_restart(self):
        state = sup.arm(self.initial)
        for number in range(3):
            state = sup.start(state, child=f'child-{number}')
            state = sup.result(state, ChildOutcome.TRANSIENT_FAILURE).state
        self.assertEqual(state.state, SupervisorState.BACKOFF)
        early = decide(state, sup.event(EventKind.TICK, state.next_restart_utc-1), sup.POLICY)
        self.assertEqual(early.actions, ())
        due = decide(state, sup.event(EventKind.TICK, state.next_restart_utc), sup.POLICY)
        self.assertEqual(due.actions, (SupervisorAction.START_DUE,))
        fresh = sup.start(due.state, child='after-cooldown')
        self.assertEqual(fresh.state, SupervisorState.STARTING)
        self.assertEqual(fresh.incident_attempts, 1)

    def test_startup_timeout_with_clean_exit_restarts(self):
        active = sup.start(sup.arm(self.initial))
        stopping = decide(active, sup.event(EventKind.TICK, 281), sup.POLICY).state
        self.assertEqual(stopping.attention_reason, AttentionReason.STARTUP_TIMEOUT)
        exited = sup.result(stopping, ChildOutcome.CLEAN).state
        self.assertEqual(exited.state, SupervisorState.BACKOFF)
        self.assertTrue(exited.desired_armed)

    def test_startup_timeout_with_unresolved_work_still_waits(self):
        active = sup.start(sup.arm(self.initial))
        stopping = decide(active, sup.event(EventKind.TICK, 281), sup.POLICY).state
        exited = sup.result(stopping, ChildOutcome.CLEAN, unresolved_work=True).state
        self.assertEqual(exited.state, SupervisorState.ATTENTION_REQUIRED)

    def test_manual_stop_is_never_self_healed(self):
        active = sup.started(sup.start(sup.arm(self.initial)), 101)
        stopping = decide(active, sup.event(EventKind.STOP, 102), sup.POLICY).state
        exited = sup.result(stopping, ChildOutcome.CLEAN).state
        self.assertEqual(exited.state, SupervisorState.DISARMED)
        self.assertFalse(exited.desired_armed)


if __name__ == '__main__':
    unittest.main()
