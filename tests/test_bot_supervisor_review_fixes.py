"""D-057 regression barriers. Native subprocesses are inert test scopes only."""
import asyncio
from dataclasses import replace
import importlib.util
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread, current_thread
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from kalshi_bot.process_supervisor import OwnedChild, SupervisorHost, fixture_fingerprints
from kalshi_bot.supervision import EventKind, SupervisorEvent, SupervisorState
from kalshi_bot.supervisor_control import ControlOwner, ScopeSpec, SupervisorController
from kalshi_bot.supervisor_protocol import Envelope, MessageKind, ParentProtocol
from kalshi_bot.supervisor_store import SupervisorStore
from kalshi_bot.values import InvalidData
from kalshi_bot.windows import (ProtectedControlFiles, WindowsRoleLease, WindowsStopLatch,
    WindowsControlMutex, current_user_sid, _close_handle)
from kalshi_bot.windows_ipc import PipeServer, connect_pipe, supervisor_pipe_name


def message(kind=MessageKind.ADMIT, seq=1, revision=3):
    return Envelope("a"*64, "session", "child", 2, kind, seq, time.monotonic_ns(),
                    dict(reason="stop") if kind == MessageKind.STOP_HINT else
                    dict(control_revision=revision, fence_revision=1)
                    if kind == MessageKind.FENCE_ACK else
                    dict(control_revision=revision))


class ProtocolAndJournalTests(unittest.TestCase):
    def protocol(self):
        return ParentProtocol("a"*64, "session", "child", 2)

    def test_every_identity_and_age_field_is_checked_before_admission(self):
        for fields in (dict(scope_digest="b"*64), dict(parent_session="wrong"),
                dict(child_id="wrong"), dict(child_generation=3),
                dict(sent_monotonic_ns=1), dict(sent_monotonic_ns=time.monotonic_ns()+10**10)):
            with self.subTest(fields=tuple(fields)):
                protocol = self.protocol()
                with self.assertRaises(InvalidData):
                    protocol.accept(replace(message(), **fields), now_ns=time.monotonic_ns(),
                                    current_revision=3)
                self.assertFalse(protocol.admitted)
                self.assertEqual(protocol.tracker.control, 0)

    def test_duplicate_admit_s2b_early_pulse_and_revision_regression_are_rejected(self):
        for candidate in (message(MessageKind.PULSE), message(MessageKind.FENCE_ACK)):
            with self.assertRaises(InvalidData):
                self.protocol().accept(candidate, now_ns=time.monotonic_ns(), current_revision=3)
        for candidate in (message(seq=2), message(MessageKind.PULSE, revision=5)):
            protocol = self.protocol()
            protocol.accept(message(), now_ns=time.monotonic_ns(), current_revision=3)
            with self.assertRaises(InvalidData):
                protocol.accept(candidate, now_ns=time.monotonic_ns(), current_revision=4)
        protocol = self.protocol()
        protocol.accept(message(), now_ns=time.monotonic_ns(), current_revision=3)
        self.assertFalse(protocol.accept(message(MessageKind.PULSE, revision=2),
            now_ns=time.monotonic_ns(), current_revision=4))

    def test_coalesced_pulse_older_than_fence_ack_is_ignored(self):
        protocol = self.protocol()
        protocol.accept(message(), now_ns=time.monotonic_ns(), current_revision=3)
        protocol.accept(message(MessageKind.FENCE_ACK, seq=2, revision=4),
                        now_ns=time.monotonic_ns(), current_revision=4)
        self.assertFalse(protocol.accept(message(MessageKind.PULSE, seq=1, revision=3),
            now_ns=time.monotonic_ns(), current_revision=4))
        self.assertEqual(protocol.revision, 4)

    def test_parent_sessions_are_bounded_at_every_commit(self):
        with SupervisorStore(":memory:", scope_id="test-journal", event_limit=16) as store:
            for n in range(40):
                store.begin_parent_session("session-"+str(n))
                count = store.connection.execute("SELECT count(*) FROM events").fetchone()[0]
                self.assertLessEqual(count, 16)

    def test_open_existing_never_creates_missing_file(self):
        with TemporaryDirectory() as root:
            path = Path(root)/"missing.db"
            with self.assertRaises(InvalidData):
                SupervisorStore.open_existing(path, scope_id="test-missing")
            self.assertFalse(path.exists())

    def test_native_stage_events_share_the_journal_bound(self):
        with SupervisorStore(":memory:", scope_id="test-stages", event_limit=16) as store:
            for n in range(15):
                store.begin_parent_session("session"+str(n))
            state = store.apply(SupervisorEvent(EventKind.ARM, time.time(),
                expected_generation=0, build_fingerprint="build", config_fingerprint="config")).state
            store.reserve_start(SupervisorEvent(EventKind.START_REQUESTED, time.time(),
                expected_generation=state.generation, child_id="child"), parent_session="session14")
            for stage in ("created", "bound"):
                store.update_native_stage(parent_session="session14", child_id="child",
                    child_generation=state.generation, stage=stage, diagnostic_pid=123)
                self.assertEqual(store.connection.execute("SELECT count(*) FROM events").fetchone()[0], 16)


@unittest.skipUnless(os.name == "nt", "native Windows fixture")
class NativeFixTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        self.scope = ScopeSpec("fixture", "test-"+uuid4().hex,
                               current_user_sid(), Path(self.temp.name))
        ControlOwner.initialize_fixture(self.scope)
        self.owner = ControlOwner(self.scope)
        self.controller = SupervisorController(self.scope, self.owner)
        self.host = self.task = None

    async def asyncTearDown(self):
        if self.host is not None:
            self.host.shutdown_requested = True
            child = self.host.child
            if child and child.process and child.poll_exit() is None:
                child.process.terminate()  # Exact registered test fixture only.
            if self.task:
                try:
                    await asyncio.wait_for(asyncio.shield(self.task), 12)
                except (InvalidData, asyncio.CancelledError):
                    pass
        await self.owner.close()
        self.temp.cleanup()

    async def until(self, predicate, timeout=8):
        async with asyncio.timeout(timeout):
            while not predicate():
                await asyncio.sleep(.01)

    async def launch(self, mode="hang_after_admit"):
        self.host = SupervisorHost(self.scope, fixture_mode=mode)
        self.task = asyncio.create_task(self.host.run())
        await asyncio.wait_for(self.host.started.wait(), 5)
        state = (await self.controller.inspect()).state
        build, config = fixture_fingerprints(mode)
        await self.controller.arm(expected_generation=state.generation,
                                  build_fingerprint=build, config_fingerprint=config)

    async def healthy(self):
        await self.launch()
        await self.until(lambda: self.host.controller_state.state == SupervisorState.HEALTHY)

    def assert_parent_owned(self):
        with self.assertRaises(InvalidData):
            WindowsRoleLease(self.scope.scope_id, "parent").__enter__()
        self.assertFalse(self.task.done())
        self.assertFalse(self.host.owner.closed)

    async def test_repeated_cancellation_retains_live_child_and_parent(self):
        await self.healthy()
        self.task.cancel()
        await self.until(lambda: self.host.controller_state.stop_latched)
        self.task.cancel()
        await asyncio.sleep(.1)
        self.assert_parent_owned()
        self.assertIsNone(self.host.child.poll_exit())

    async def test_wrong_identity_installs_hold_and_retains_live_child(self):
        await self.healthy()
        child = self.host.child
        bad = Envelope(self.scope.digest, self.host.parent_session, "wrong", child.child_generation,
            MessageKind.STATUS, 2, time.monotonic_ns(), dict(phase="healthy",
                progress_sequence=2, work_remaining_ms=None, blockers=[]))
        child.endpoint.incoming.put_nowait(bad)
        child.endpoint.activity.set()
        await self.until(lambda: self.host.controller_state.stop_latched)
        self.assert_parent_owned()
        self.assertEqual(self.host.controller_state.state, SupervisorState.ATTENTION_REQUIRED)
        self.assertIsNotNone(self.host.last_error)

    async def test_cancel_during_spawn_owns_late_process_and_commit(self):
        entered, release = Event(), Event()
        original = OwnedChild.spawn
        def gated(child):
            entered.set()
            release.wait(5)
            return original(child)
        with patch.object(OwnedChild, "spawn", gated):
            await self.launch("normal")
            await self.until(entered.is_set)
            self.task.cancel()
            self.task.cancel()
            self.assert_parent_owned()
            release.set()
            # Stop was signaled while setup was gated: no Popen is allowed.
            try:
                await asyncio.wait_for(asyncio.shield(self.task), 8)
            except (InvalidData, asyncio.CancelledError):
                pass
        self.assertIsNone((await self.controller.inspect()).state.child_id)

    async def test_cancel_during_bind_retains_pending_endpoint(self):
        entered, release = Event(), Event()
        original = PipeServer.accept
        def gated(server, **kwargs):
            endpoint = original(server, **kwargs)
            entered.set()
            release.wait(5)
            return endpoint
        with patch.object(PipeServer, "accept", gated):
            await self.launch("normal")
            await self.until(entered.is_set)
            self.task.cancel()
            await asyncio.sleep(.02)
            self.task.cancel()
            self.assert_parent_owned()
            release.set()
            try:
                await asyncio.wait_for(asyncio.shield(self.task), 8)
            except (InvalidData, asyncio.CancelledError):
                pass
        self.assertIsNone(self.host.child)

    async def test_cancel_during_ipc_join_retains_parent_and_child_lease(self):
        entered, release = Event(), Event()
        await self.launch("normal")
        await self.until(lambda: self.host.controller_state.state == SupervisorState.HEALTHY)
        endpoint = self.host.child.endpoint
        original = endpoint.close_and_join
        def gated(timeout=10):
            entered.set()
            release.wait(5)
            return original(timeout)
        with patch.object(endpoint, "close_and_join", gated):
            await self.controller.stop()
            await self.until(entered.is_set)
            self.task.cancel()
            await asyncio.sleep(.02)
            self.task.cancel()
            self.assert_parent_owned()
            with self.assertRaises(InvalidData):
                WindowsRoleLease(self.scope.scope_id, "child").__enter__()
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await self.task
        self.assertTrue(endpoint.closed)

    async def test_cancel_during_control_close_retains_parent(self):
        await self.launch("normal")
        await self.until(lambda: self.host.controller_state.state == SupervisorState.HEALTHY)
        entered, release = Event(), Event()
        original = SupervisorStore.close
        def gated(store):
            if current_thread() is self.host.owner.thread:
                entered.set()
                release.wait(5)
            return original(store)
        with patch.object(SupervisorStore, "close", gated):
            await self.controller.stop()
            await self.until(entered.is_set)
            self.task.cancel()
            await asyncio.sleep(.02)
            self.task.cancel()
            with self.assertRaises(InvalidData):
                WindowsRoleLease(self.scope.scope_id, "parent").__enter__()
            self.assertFalse(self.task.done())
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await self.task

    async def test_store_failure_cannot_prevent_independent_stop(self):
        await self.healthy()
        original = self.host.owner.submit
        async def failing(operation, *args):
            if operation == "apply" and args[0].kind == EventKind.STOP:
                raise InvalidData("injected durable stop failure")
            return await original(operation, *args)
        with patch.object(self.host.owner, "submit", failing):
            with self.assertRaises(InvalidData):
                await self.host.request_shutdown()
            self.assertTrue(self.host._stop_latch.requested)
            await self.until(lambda: self.host.last_error is not None)
            self.assert_parent_owned()

    async def test_lost_created_stage_ack_retains_child_until_exit(self):
        original = SupervisorStore.update_native_stage
        def lose_ack(store, **values):
            result = original(store, **values)
            if values["stage"] == "created":
                raise InvalidData("injected lost acknowledgement")
            return result
        with patch.object(SupervisorStore, "update_native_stage", lose_ack):
            await self.launch("normal")
            await self.until(lambda: self.task.done())
            with self.assertRaises(InvalidData):
                await self.task
        self.assertIsNone(self.host.child)
        self.assertIsNone((await self.controller.inspect()).state.child_id)

    async def test_cold_parent_waits_for_old_child_lease_before_orphan_commit(self):
        await self.owner.submit("session", "old-parent", time.time())
        state = (await self.controller.inspect()).state
        build, config = fixture_fingerprints()
        await self.controller.arm(expected_generation=state.generation,
                                  build_fingerprint=build, config_fingerprint=config)
        state = (await self.controller.inspect()).state
        await self.owner.submit("reserve", SupervisorEvent(EventKind.START_REQUESTED,
            time.time(), expected_generation=state.generation, child_id="old-child"), "old-parent")
        with WindowsRoleLease(self.scope.scope_id, "child"):
            self.host = SupervisorHost(self.scope)
            self.task = asyncio.create_task(self.host.run())
            await self.host.started.wait()
            await asyncio.sleep(.1)
            self.assert_parent_owned()
            self.assertEqual((await self.controller.inspect()).state.child_id, "old-child")
        await asyncio.wait_for(self.task, 5)
        self.assertEqual((await self.controller.inspect()).native.stage, "orphan_released")

    async def test_clock_denial_has_no_spawn_permission(self):
        sample = [100., 10.]
        with SupervisorStore(":memory:", scope_id=self.scope.scope_id,
                clock=lambda: sample[0], monotonic_clock=lambda: sample[1], boot_id="boot") as store:
            store.begin_parent_session("parent")
            state = store.apply(SupervisorEvent(EventKind.ARM, 100., expected_generation=0,
                build_fingerprint="build", config_fingerprint="config")).state
            sample[:] = [200., 11.]
            calls = []
            factory = SimpleNamespace(created=False, acquire_presence=lambda: None,
                release_presence=lambda: None, validate_launch=lambda state: None,
                spawn=lambda: calls.append(True))
            receipt = self.owner._execute(store, "spawn", (SupervisorEvent(
                EventKind.START_REQUESTED, 200., expected_generation=state.generation,
                child_id="child"), "parent", factory))
            self.assertFalse(receipt.spawned)
            self.assertEqual(calls, [])
            self.assertIsNone(store.read().child_id)
            self.assertEqual(store.read().state, SupervisorState.ATTENTION_REQUIRED)

    async def test_uncertain_process_constructor_never_releases_reservation(self):
        with SupervisorStore(":memory:", scope_id=self.scope.scope_id) as store:
            store.begin_parent_session("parent")
            state = store.apply(SupervisorEvent(EventKind.ARM, time.time(), expected_generation=0,
                build_fingerprint="build", config_fingerprint="config")).state
            releases = []
            def uncertain():
                raise InvalidData("constructor outcome unknown")
            factory = SimpleNamespace(created=False, creation_attempted=True,
                acquire_presence=lambda: None, release_presence=lambda: releases.append(True),
                validate_launch=lambda state: None, spawn=uncertain)
            with self.assertRaises(InvalidData):
                self.owner._execute(store, "spawn", (SupervisorEvent(EventKind.START_REQUESTED,
                    time.time(), expected_generation=state.generation, child_id="child"),
                    "parent", factory))
            self.assertEqual(releases, [])
            self.assertEqual(store.read_native().stage, "reserved")
            self.assertEqual(store.read().child_id, "child")

    async def test_partial_handle_acquisition_does_not_leak_presence(self):
        with WindowsStopLatch(self.scope.scope_id) as latch:
            child = OwnedChild(self.scope, latch, parent_session="parent", child_id="child",
                               child_generation=1, mode="normal")
            child.acquire_presence()
            try:
                with patch.object(latch, "duplicate_inheritable", side_effect=InvalidData("fault")):
                    with self.assertRaises(InvalidData):
                        child.spawn()
            finally:
                child.release_presence()
            with WindowsRoleLease(self.scope.scope_id, "child"):
                pass

    async def test_abandoned_control_denies_spawn_with_explicit_receipt(self):
        await self.owner.submit("session", "parent", time.time())
        state = (await self.controller.inspect()).state
        build, config = fixture_fingerprints()
        await self.controller.arm(expected_generation=state.generation,
                                  build_fingerprint=build, config_fingerprint=config)
        state = (await self.controller.inspect()).state
        held = []
        def abandon():
            mutex = WindowsControlMutex(self.scope.scope_id)
            mutex.__enter__()
            held.append(mutex)
        thread = Thread(target=abandon)
        thread.start()
        thread.join(5)
        calls = []
        factory = SimpleNamespace(acquire_presence=lambda: calls.append(True))
        try:
            receipt = await self.owner.submit("spawn", SupervisorEvent(EventKind.START_REQUESTED,
                time.time(), expected_generation=state.generation, child_id="child"), "parent", factory)
            self.assertFalse(receipt.spawned)
            self.assertIsNone(receipt.value)
            self.assertEqual(calls, [])
            self.assertEqual(receipt.state.state, SupervisorState.ATTENTION_REQUIRED)
        finally:
            _close_handle(held[0].handle)  # Exact test-owned abandoned handle only.

    async def test_stopped_or_drifted_launch_never_calls_popen(self):
        build, config = fixture_fingerprints()
        state = SimpleNamespace(desired_armed=True, stop_latched=False,
                                build_fingerprint=build, config_fingerprint=config)
        with WindowsStopLatch(self.scope.scope_id) as latch:
            child = OwnedChild(self.scope, latch, parent_session="parent", child_id="child",
                               child_generation=1, mode="normal")
            with patch("kalshi_bot.process_supervisor.subprocess.Popen") as popen:
                state.build_fingerprint = "drifted"
                with self.assertRaises(InvalidData):
                    child.validate_launch(state)
                state.build_fingerprint = build
                latch.request_owned()
                with self.assertRaises(InvalidData):
                    child.validate_launch(state)
                popen.assert_not_called()

    async def test_power_during_bind_prevents_admission(self):
        original = OwnedChild.bind
        async def invalidate(child):
            endpoint = await original(child)
            self.host._power.changed.set()
            return endpoint
        with patch.object(OwnedChild, "bind", invalidate):
            await self.launch("normal")
            await self.until(lambda: self.task.done())
            with self.assertRaises(InvalidData):
                await self.task
        final = await self.controller.inspect()
        self.assertTrue(final.state.stop_latched)
        self.assertNotEqual(final.state.state, SupervisorState.HEALTHY)

    async def test_diagnostic_failure_revokes_authority_and_retains_child(self):
        await self.healthy()
        self.host.diagnostics._fail("injected_sink_failure")
        await self.until(lambda: self.host.controller_state.stop_latched)
        self.assert_parent_owned()
        self.assertEqual(self.host.diagnostics.status()["failure"], "injected_sink_failure")

    async def test_control_root_and_database_have_protected_dacls(self):
        guard = ProtectedControlFiles(self.scope.store_path, self.scope.approved_user_sid,
                                      readonly=True)
        try:
            # Pinned root/database must not be replaceable during an active owner.
            with self.assertRaises(OSError):
                self.scope.store_path.rename(self.scope.store_path.with_suffix(".moved"))
        finally:
            guard.close()

    async def test_sqlite_sidecars_are_pinned_and_revalidated_without_reopening(self):
        guard = ProtectedControlFiles(self.scope.store_path, self.scope.approved_user_sid,
                                      readonly=True)
        try:
            guard.validate_sidecars(create_missing=True)
            retained = dict(guard.sidecar_handles)
            self.assertEqual(set(retained), {"-wal", "-shm"})
            guard.validate_sidecars()
            self.assertEqual(guard.sidecar_handles, retained)
            wal = Path(str(self.scope.store_path)+"-wal")
            with self.assertRaises(OSError):
                wal.rename(Path(str(wal)+".moved"))
        finally:
            guard.close()

    async def test_exact_inherited_sqlite_sidecars_are_accepted_after_clean_close(self):
        await self.owner.close()
        # SQLite may recreate these during final close. Files created under the
        # protected root inherit only its exact user/System full-control ACEs.
        for suffix in ('-wal', '-shm'):
            path = Path(str(self.scope.store_path)+suffix)
            if path.exists():
                path.unlink()
            path.write_bytes(b'')
        guard = ProtectedControlFiles(self.scope.store_path,
                                      self.scope.approved_user_sid,
                                      readonly=True)
        try:
            self.assertEqual(set(guard.sidecar_handles), {'-wal', '-shm'})
        finally:
            guard.close()

    async def test_permissive_replaced_database_is_refused_without_repair(self):
        await self.owner.close()
        data = self.scope.store_path.read_bytes()
        # Replace only the disposable fixture, outside any active pinned owner.
        self.scope.store_path.unlink()
        self.scope.store_path.write_bytes(data)  # Inherited, not protected DACL.
        with self.assertRaisesRegex(InvalidData, "DACL differs"):
            ProtectedControlFiles(self.scope.store_path, self.scope.approved_user_sid)
        self.assertEqual(self.scope.store_path.read_bytes(), data)

    async def test_old_schema_is_refused_without_creating_sidecars(self):
        import sqlite3
        await self.owner.close()
        connection = sqlite3.connect(self.scope.store_path)
        connection.execute("UPDATE meta SET value='old' WHERE key='schema'")
        connection.commit()
        connection.close()
        names = set(self.scope.control_root.iterdir())
        data = self.scope.store_path.read_bytes()
        with self.assertRaisesRegex(InvalidData, "schema"):
            SupervisorStore.open_existing(self.scope.store_path, scope_id=self.scope.scope_id,
                                          security_sid=self.scope.approved_user_sid)
        self.assertEqual(set(self.scope.control_root.iterdir()), names)
        self.assertEqual(self.scope.store_path.read_bytes(), data)

    async def test_reparse_database_is_refused_without_following_target(self):
        await self.owner.close()
        target = self.scope.control_root/"real.db"
        self.scope.store_path.rename(target)
        try:
            self.scope.store_path.symlink_to(target)
        except OSError as exc:
            self.skipTest("native symlink privilege unavailable: "+str(exc.winerror))
        with self.assertRaisesRegex(InvalidData, "reparse"):
            ProtectedControlFiles(self.scope.store_path, self.scope.approved_user_sid)
        self.assertTrue(target.is_file())

    async def test_diagnostics_are_safe_and_correlated(self):
        await self.healthy()
        self.host._record_fault(InvalidData("PRIVATE-SENTINEL-do-not-log"))
        self.host.shutdown_requested = True
        self.host.child.process.terminate()
        with self.assertRaises(InvalidData):
            await self.task
        text = (self.scope.control_root/"parent-logs"/"events.jsonl").read_text()
        self.assertNotIn("PRIVATE-SENTINEL", text)
        rows = [json.loads(line) for line in text.splitlines()]
        fault = next(row for row in rows if row["event"] == "supervisor_failed")
        self.assertIn("operation_ref", fault["context"])
        self.assertEqual(fault["errors"][0]["type"], "InvalidData")

    async def test_child_power_flag_blocks_hello_and_status(self):
        from unittest.mock import Mock
        spec = importlib.util.spec_from_file_location("inert_child",
            Path(__file__).parent/"fixtures"/"supervisor_child.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        endpoint, diagnostics = Mock(), Mock()
        power = SimpleNamespace(changed=Event())
        power.changed.set()
        with self.assertRaisesRegex(InvalidData, "power"):
            module.run_child(SimpleNamespace(), self.scope, endpoint, power, diagnostics)
        endpoint.send_control.assert_not_called()
        endpoint.publish_latest.assert_not_called()

    async def test_parent_subtracts_message_transit_age(self):
        host = SupervisorHost(self.scope)
        host.child = SimpleNamespace(child_id="child", child_generation=1, result=None)
        event = Envelope(self.scope.digest, host.parent_session, "child", 1,
            MessageKind.STATUS, 1, 1_000_000_000, dict(phase="recovering",
                progress_sequence=1, work_remaining_ms=5000, blockers=[]))
        events = []
        async def apply(event):
            events.append(event)
        with patch.object(host, "_apply", apply), patch("kalshi_bot.process_supervisor.time.monotonic_ns",
                return_value=3_000_000_000), patch("kalshi_bot.process_supervisor.time.time", return_value=100):
            await host._message(event)
        self.assertEqual(events[0].work_deadline_utc, 103)


@unittest.skipUnless(os.name == "nt", "native Windows fixture")
class PipeCompletionTests(unittest.TestCase):
    def pair(self):
        name = supervisor_pipe_name("a"*64, uuid4().hex)
        server = PipeServer(name)
        found = {}
        worker = Thread(target=lambda: found.update(client=connect_pipe(name)))
        worker.start()
        parent = server.accept(expected_pid=os.getpid())
        worker.join(5)
        return parent, found["client"]

    def test_terminal_receipt_waits_for_native_write_before_close(self):
        parent, child = self.pair()
        entered, release = Event(), Event()
        original = child._write
        def gated(data):
            entered.set()
            release.wait(5)
            return original(data)
        try:
            with patch.object(child, "_write", gated):
                receipt = child.send_control(Envelope("a"*64, "session", "child", 1,
                    MessageKind.RESULT, 1, time.monotonic_ns(), dict(outcome="clean",
                        cleanup_complete=True, cleanup_failed=False, unresolved_work=False,
                        retry_holds=[])))
                self.assertTrue(entered.wait(2))
                self.assertFalse(receipt.done())
                release.set()
                receipt.result(timeout=2)
                child.close_and_join()
                self.assertEqual(parent.receive(timeout=2).kind, MessageKind.RESULT)
                self.assertEqual(len(child._writes), 0)
        finally:
            release.set()
            child.close_and_join()
            parent.close_and_join()

    def test_join_timeout_is_retryable_not_marked_closed(self):
        parent, child = self.pair()
        entered, release = Event(), Event()
        original = child._write
        def gated(data):
            entered.set()
            release.wait(5)
            return original(data)
        try:
            with patch.object(child, "_write", gated):
                receipt = child.send_control(message())
                self.assertTrue(entered.wait(2))
                with self.assertRaises(InvalidData):
                    child.close_and_join(timeout=.01)
                self.assertFalse(child.closed)
                self.assertIsNotNone(child.handle)
                release.set()
                child.close_and_join(timeout=2)
                self.assertTrue(child.closed)
                self.assertFalse(child.thread.is_alive())
                with self.assertRaises(InvalidData):
                    receipt.result(timeout=2)
        finally:
            release.set()
            child.close_and_join()
            parent.close_and_join()
