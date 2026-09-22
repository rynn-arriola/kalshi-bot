"""S2B offline runtime ownership and durable restriction transfer."""
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest

from kalshi_bot.supervision import (ChildOutcome, ChildPhase, EventKind,
                                    SupervisorEvent)
from kalshi_bot.supervised_runtime import (FenceCooldown, RecoveryFence,
    RuntimeContext, RuntimeRestrictions, create_offline_runtime_adapter)
from kalshi_bot.supervisor_store import SupervisorStore
from kalshi_bot.values import InvalidData
from kalshi_bot.writer import LedgerWriter


class RecoveryFenceTests(unittest.TestCase):
    def bound_store(self):
        store = SupervisorStore(":memory:", scope_id="fixture-test-fence")
        store.begin_parent_session("parent-a", observed_utc=1)
        armed = store.apply(SupervisorEvent(EventKind.ARM, 2,
            expected_generation=0, build_fingerprint="build",
            config_fingerprint="config")).state
        store.reserve_start(SupervisorEvent(EventKind.START_REQUESTED, 2,
            expected_generation=armed.generation, child_id="child-a"),
            parent_session="parent-a")
        store.update_native_stage(parent_session="parent-a", child_id="child-a",
            child_generation=armed.generation, stage="created", diagnostic_pid=123)
        store.update_native_stage(parent_session="parent-a", child_id="child-a",
            child_generation=armed.generation, stage="bound", diagnostic_pid=123)
        return store, armed.generation

    def test_commit_is_identity_bound_monotonic_and_never_shortens_restrictions(self):
        store, generation = self.bound_store()
        self.addCleanup(store.close)
        first = RecoveryFence("parent-a", "child-a", generation, 1,
            ("quota_exhausted",), (FenceCooldown("shared_429", 100),), False)
        stored = store.commit_recovery_fence(first)
        self.assertEqual(stored, store.read_recovery_fence())
        second = RecoveryFence("parent-a", "child-a", generation, 2, (),
                               (FenceCooldown("shared_429", 90),), True)
        stored = store.commit_recovery_fence(second)
        self.assertEqual(stored.component_holds, ("quota_exhausted",))
        self.assertEqual(stored.cooldowns[0].deadline_utc, 100)
        self.assertTrue(stored.terminal_checkpoint_complete)
        with self.assertRaisesRegex(InvalidData, "revision"):
            store.commit_recovery_fence(second)
        with self.assertRaisesRegex(InvalidData, "identity"):
            store.commit_recovery_fence(RecoveryFence(
                "parent-a", "other-child", generation, 3, (), (), False))

    def test_bounds_and_duplicate_names_fail_closed(self):
        with self.assertRaises(InvalidData):
            RecoveryFence("parent", "child", 1, 1,
                          tuple("h"+str(n) for n in range(33)))
        with self.assertRaises(InvalidData):
            RecoveryFence("parent", "child", 1, 1, (),
                (FenceCooldown("same", 1), FenceCooldown("same", 2)))
        with self.assertRaises(InvalidData):
            RecoveryFence("parent", "child", 1, 1, ([],))
        with self.assertRaises(InvalidData):
            RecoveryFence.from_dict(dict(parent_session="parent", child_id="child",
                child_generation=1, fence_revision=1, component_holds="bad",
                cooldowns=[], terminal_checkpoint_complete=False))

    def test_cross_session_cooldown_never_expires_from_untrusted_wall_time(self):
        restrictions = RuntimeRestrictions(clock=lambda: 1000)
        restrictions.apply(RecoveryFence("old-parent", "child", 1, 1, (),
            (FenceCooldown("shared_429", 1),), True),
            current_parent_session="new-parent")
        self.assertEqual(tuple(item.name for item in restrictions.cooldowns),
                         ("shared_429",))
        self.assertIn("recovery_fence_clock_untrusted", restrictions.holds)

    def test_explicit_current_revision_resolution_is_atomic_and_childless(self):
        store, generation = self.bound_store()
        self.addCleanup(store.close)
        fence = store.commit_recovery_fence(RecoveryFence(
            "parent-a", "child-a", generation, 1, ("quota_exhausted",),
            (FenceCooldown("shared_429", 100),), True))
        store.apply(SupervisorEvent(EventKind.CHILD_STARTED, 3,
            expected_generation=generation, child_id="child-a"))
        held = store.apply(SupervisorEvent(EventKind.CHILD_STATUS, 4,
            expected_generation=generation, child_id="child-a",
            child_phase=ChildPhase.DEGRADED, progress_sequence=1,
            retry_holds=("quota_exhausted", "cooldown_shared_429"))).state
        held = store.apply(SupervisorEvent(EventKind.CHILD_RESULT, 5,
            expected_generation=generation, child_id="child-a",
            outcome=ChildOutcome.CLEAN, process_exited=True,
            cleanup_complete=True, retry_holds=())).state
        self.assertIsNone(held.child_id)
        decision, updated = store.resolve_recovery_fence(SupervisorEvent(
            EventKind.HOLDS_RESOLVED, 6, expected_generation=held.generation,
            retry_holds=("quota_exhausted", "cooldown_shared_429")),
            expected_fence_revision=fence.fence_revision,
            component_holds=("quota_exhausted",),
            cooldown_names=("shared_429",), parent_session="parent-a")
        self.assertEqual(decision.state.retry_holds, ())
        self.assertEqual(updated.component_holds, ())
        self.assertEqual(updated.cooldowns, ())
        with self.assertRaisesRegex(InvalidData, "stale"):
            store.resolve_recovery_fence(SupervisorEvent(
                EventKind.HOLDS_RESOLVED, 7,
                expected_generation=decision.state.generation,
                retry_holds=("quota_exhausted",)),
                expected_fence_revision=fence.fence_revision,
                component_holds=("quota_exhausted",),
                parent_session="parent-a")


class RuntimeAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_fence_precedes_every_read_and_cleanup_is_joined(self):
        with TemporaryDirectory() as folder:
            path = Path(folder)/"runtime.db"
            restrictions = RuntimeRestrictions()
            restrictions.apply(None)
            adapter = await create_offline_runtime_adapter(
                path, restrictions)
            await adapter.start(RuntimeContext("fixture-test-runtime", "child", 1))
            try:
                async with asyncio.timeout(4):
                    while adapter.runtime.reads.calls == 0:
                        await asyncio.sleep(.001)
                snapshot = adapter.health_snapshot()
                self.assertIn(snapshot.phase, {"recovering", "healthy"})
                self.assertGreater(adapter.runtime.reads.calls, 0)
                self.assertEqual(restrictions.restored_tokens, 0)
            finally:
                adapter.request_stop("test_stop")
            evidence = await adapter.join()
            self.assertTrue(evidence.cleanup_complete)
            self.assertFalse(evidence.cleanup_failed)
            self.assertFalse(adapter.runtime.running)
            self.assertFalse(adapter.writer._thread.is_alive())
            reopened = await LedgerWriter(path, market_capacity=4).start()
            try:
                self.assertEqual(await reopened.private_epoch_gap_count(
                    subaccount=0), 0)
            finally:
                await reopened.close()

    async def test_start_refuses_authority_or_missing_fence(self):
        with TemporaryDirectory() as folder:
            restrictions = RuntimeRestrictions()
            with self.assertRaisesRegex(InvalidData, "restrictions"):
                await create_offline_runtime_adapter(Path(folder)/"missing.db",
                                                     restrictions)
            restrictions.apply(None)
            adapter = await create_offline_runtime_adapter(
                Path(folder)/"runtime.db", restrictions)
            try:
                with self.assertRaisesRegex(InvalidData, "authority"):
                    RuntimeContext("fixture-test-runtime", "child", 1,
                                   credentials_present=True)
            finally:
                await adapter.writer.close()


if __name__ == "__main__":
    unittest.main()
