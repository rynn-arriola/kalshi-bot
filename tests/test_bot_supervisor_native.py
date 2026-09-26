"""Native Windows S2A/S2B acceptance with fixed offline subprocesses only."""
import asyncio
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Thread
import time
import unittest
from uuid import uuid4

from kalshi_bot.process_supervisor import SupervisorHost, fixture_fingerprints
from kalshi_bot.supervision import SupervisorPolicy, SupervisorState
from kalshi_bot.supervisor_control import (ControlOwner, ScopeSpec,
                                           SupervisorController)
from kalshi_bot.supervisor_protocol import Envelope, MessageKind
from kalshi_bot.supervisor_store import SupervisorStore
from kalshi_bot.values import InvalidData
from kalshi_bot.windows import (WindowsControlMutex, WindowsRoleLease,
                                WindowsStopLatch, current_user_sid,
                                role_object_name)
from kalshi_bot.windows_ipc import PipeServer, connect_pipe, supervisor_pipe_name


@unittest.skipUnless(os.name == "nt", "native Windows S2A")
class NativePrimitiveTests(unittest.TestCase):
    def test_protected_role_lease_excludes_another_process(self):
        scope = "test-native-"+uuid4().hex
        with WindowsRoleLease(scope, "parent"):
            code = ("from kalshi_bot.windows import WindowsRoleLease;"
                    "import sys; WindowsRoleLease(sys.argv[1],'parent').__enter__()")
            result = subprocess.run([sys.executable, "-B", "-c", code, scope],
                                    capture_output=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
        with WindowsRoleLease(scope, "parent"):
            pass

    def test_permissive_role_object_is_rejected_not_trusted(self):
        scope = "test-squat-"+uuid4().hex
        api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL,
                                     wintypes.LPCWSTR]
        api.CreateMutexW.restype = wintypes.HANDLE
        api.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = api.CreateMutexW(None, False, role_object_name(scope, "parent"))
        self.assertTrue(handle)
        try:
            with self.assertRaisesRegex(InvalidData, "DACL differs"):
                WindowsRoleLease(scope, "parent").__enter__()
        finally:
            api.CloseHandle(handle)

    def test_control_mutex_reports_abandoned_owner(self):
        scope = "test-abandon-"+uuid4().hex
        code = ("from kalshi_bot.windows import WindowsControlMutex;"
                "import os,sys,time; m=WindowsControlMutex(sys.argv[1]);"
                "m.__enter__(); print('held',flush=True); os._exit(7)")
        keeper = WindowsControlMutex(scope, retain_handle=True)
        keeper.open()
        try:
            process = subprocess.Popen([sys.executable, "-B", "-c", code, scope],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                self.assertEqual(process.stdout.readline().strip(), "held")
                process.wait(timeout=10)
                with keeper as mutex:
                    self.assertTrue(mutex.abandoned)
            finally:
                process.stdout.close()
                process.stderr.close()
        finally:
            keeper.close()

    def test_stop_latch_and_named_pipe_are_cross_thread_bounded(self):
        scope = "test-pipe-"+uuid4().hex
        digest = hashlib.sha256(scope.encode()).hexdigest()
        name = supervisor_pipe_name(digest, uuid4().hex)
        server = PipeServer(name)
        found = {}
        def connect():
            found["client"] = connect_pipe(name, expected_server_pid=os.getpid())
        thread = Thread(target=connect)
        thread.start()
        parent = server.accept(timeout=5, expected_pid=os.getpid())
        thread.join(5)
        client = found["client"]
        try:
            message = Envelope(digest, "session-a", "child-a", 1,
                MessageKind.ADMIT, 1, time.monotonic_ns(),
                dict(control_revision=1))
            parent.send_control(message)
            received = client.receive(timeout=2)
            self.assertEqual(received, message)
            with WindowsStopLatch(scope) as latch:
                self.assertFalse(latch.requested)
                self.assertTrue(WindowsStopLatch.request(scope))
                self.assertTrue(latch.requested)
        finally:
            parent.close_and_join()
            client.close_and_join()


@unittest.skipUnless(os.name == "nt", "native Windows S2A")
class NativeHostTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        self.scope = ScopeSpec("fixture", "test-"+uuid4().hex,
            current_user_sid(), Path(self.temp.name))
        ControlOwner.initialize_fixture(self.scope)
        self.owners = []
        self.hosts = []

    async def asyncTearDown(self):
        for host, task in reversed(self.hosts):
            if host.child is not None and host.child.poll_exit() is None:
                host.child.process.terminate()  # Exact registered inert test handle only.
            if not task.done():
                try:
                    await asyncio.wait_for(task, 10)
                except (BaseException, asyncio.TimeoutError):
                    task.cancel()
        for owner in reversed(self.owners):
            await owner.close()
        self.temp.cleanup()

    async def eventually(self, predicate, timeout=12):
        async with asyncio.timeout(timeout):
            while not predicate():
                await asyncio.sleep(.02)

    async def controller(self):
        owner = ControlOwner(self.scope)
        self.owners.append(owner)
        return owner, SupervisorController(self.scope, owner)

    async def launch(self, mode="normal", policy=None):
        host = SupervisorHost(self.scope, fixture_mode=mode,
                              policy=policy or SupervisorPolicy())
        task = asyncio.create_task(host.run())
        self.hosts.append((host, task))
        await asyncio.wait_for(host.started.wait(), 5)
        return host, task

    async def arm(self, controller, host):
        state = (await controller.inspect()).state
        build, config = fixture_fingerprints(host.fixture_mode)
        receipt = await controller.arm(expected_generation=state.generation,
            build_fingerprint=build, config_fingerprint=config)
        self.assertFalse(receipt.decision.stale)

    async def test_normal_child_health_stop_and_exact_exit(self):
        host, task = await self.launch()
        _, controller = await self.controller()
        await self.arm(controller, host)
        await self.eventually(lambda: host.controller_state is not None
                              and host.controller_state.state == SupervisorState.HEALTHY)
        pid = host.child.process.pid
        generation = host.controller_state.generation
        receipt, signaled = await controller.stop()
        self.assertTrue(signaled)
        self.assertEqual(receipt.state.state, SupervisorState.STOPPING)
        await asyncio.wait_for(task, 10)
        final = await controller.inspect()
        self.assertEqual(final.state.state, SupervisorState.DISARMED)
        self.assertEqual(final.state.generation, generation+1)
        self.assertEqual(final.native.stage, "exited")
        self.assertIsNone(final.state.child_id)
        self.assertIsInstance(pid, int)
        with WindowsRoleLease(self.scope.scope_id, "child",
                              user_sid=self.scope.approved_user_sid):
            pass

    async def test_offline_runtime_transfers_terminal_fence_before_clean_exit(self):
        host, task = await self.launch("runtime_normal")
        _, controller = await self.controller()
        await self.arm(controller, host)
        try:
            await self.eventually(lambda: host.controller_state is not None
                and host.controller_state.state in {
                    SupervisorState.HEALTHY, SupervisorState.RECOVERING})
        except TimeoutError:
            logs = {str(path.relative_to(self.scope.control_root)): path.read_text(
                encoding="utf-8", errors="replace") for path in
                self.scope.control_root.rglob("*.jsonl")}
            self.fail(f"runtime fixture did not become healthy: "
                      f"state={host.controller_state!r} error={host.last_error!r} "
                      f"logs={logs!r}")
        await controller.stop()
        try:
            await asyncio.wait_for(task, 15)
        except InvalidData:
            logs = {str(path.relative_to(self.scope.control_root)): path.read_text(
                encoding="utf-8", errors="replace") for path in
                self.scope.control_root.rglob("*.jsonl")}
            self.fail(f"runtime fixture stop fault: error={host.last_error!r} logs={logs!r}")
        final = await controller.inspect()
        fence = SupervisorStore.read_only_recovery_fence(self.scope.store_path,
            scope_id=self.scope.scope_id, security_sid=self.scope.approved_user_sid)
        self.assertEqual(final.state.state, SupervisorState.DISARMED)
        self.assertTrue(fence.terminal_checkpoint_complete)
        self.assertGreaterEqual(fence.fence_revision, 2)
        self.assertEqual(host.validated_results, 1)

    async def test_offline_runtime_crash_before_ack_installs_unknown_fence_hold(self):
        host, task = await self.launch("runtime_crash_before_fence_ack")
        _, controller = await self.controller()
        await self.arm(controller, host)
        await self.eventually(lambda: host.controller_state is not None
            and host.controller_state.state == SupervisorState.ATTENTION_REQUIRED,
            timeout=15)
        state = (await controller.inspect()).state
        self.assertIn("recovery_fence_unknown", state.retry_holds)
        self.assertEqual(state.incident_attempts, 1)
        await host.request_shutdown()
        await asyncio.wait_for(task, 10)

    async def test_offline_runtime_retains_exhaustion_and_shared_cooldown(self):
        host, task = await self.launch("runtime_exhausted")
        _, controller = await self.controller()
        await self.arm(controller, host)
        await self.eventually(lambda: host.controller_state is not None
            and "fixture_write_quota_exhausted" in
                host.controller_state.retry_holds, timeout=15)
        await controller.stop()
        await asyncio.wait_for(task, 15)
        fence = SupervisorStore.read_only_recovery_fence(self.scope.store_path,
            scope_id=self.scope.scope_id, security_sid=self.scope.approved_user_sid)
        self.assertIn("fixture_write_quota_exhausted", fence.component_holds)
        self.assertIn("fixture_write_429", tuple(item.name for item in fence.cooldowns))
        self.assertTrue(fence.terminal_checkpoint_complete)

    async def test_duplicate_parent_is_rejected(self):
        host, task = await self.launch()
        duplicate = SupervisorHost(self.scope)
        with self.assertRaisesRegex(InvalidData, "already owned"):
            await duplicate.run()
        await host.request_shutdown()
        await asyncio.wait_for(task, 5)

    async def test_crashes_consume_persisted_budget_and_hold(self):
        policy = SupervisorPolicy(restart_delays=(.05, .05, .05),
            max_incident_restarts=3, rolling_restart_limit=3)
        host, task = await self.launch("crash_after_admit", policy)
        _, controller = await self.controller()
        await self.arm(controller, host)
        # D-144: the exhausted budget becomes a long cooldown, not a latch.
        await self.eventually(lambda: host.controller_state is not None
            and host.controller_state.state == SupervisorState.BACKOFF
            and host.controller_state.next_restart_utc is not None
            and host.controller_state.next_restart_utc-host.controller_state.updated_utc
                > policy.cooldown_restart_seconds/2, timeout=15)
        state = (await controller.inspect()).state
        self.assertEqual((state.incident_attempts, state.restart_attempts_utc), (0, ()))
        self.assertTrue(state.desired_armed)
        self.assertFalse(state.stop_latched)
        self.assertIsNone(state.attention_reason)
        self.assertGreaterEqual(state.next_restart_utc-state.updated_utc,
                                policy.cooldown_restart_seconds-1)
        await asyncio.sleep(.3)  # No fourth spawn during the cooldown.
        await host.request_shutdown()
        await asyncio.wait_for(task, 5)
        events = [json.loads(line) for line in
            (self.scope.control_root/'parent-logs'/'events.jsonl').read_text().splitlines()]
        exits = [row['context'] for row in events
                 if row['event'] == 'supervisor_child_exited']
        self.assertEqual(len(exits), 3)
        self.assertTrue(all(row['exit_code'] == 7 for row in exits))

    async def test_hung_child_is_not_replaced_after_shutdown_timeout(self):
        policy = SupervisorPolicy(shutdown_timeout_seconds=.2)
        host, task = await self.launch("hang_after_admit", policy)
        _, controller = await self.controller()
        await self.arm(controller, host)
        await self.eventually(lambda: host.controller_state is not None
            and host.controller_state.state == SupervisorState.HEALTHY)
        pid = host.child.process.pid
        await controller.stop()
        await self.eventually(lambda: host.controller_state.state
            == SupervisorState.ATTENTION_REQUIRED, timeout=5)
        self.assertEqual(host.child.process.pid, pid)
        self.assertIsNone(host.child.poll_exit())
        host.child.process.terminate()  # Exact inert fixture cleanup; not host policy.
        await asyncio.wait_for(task, 10)

    async def test_parent_death_child_exits_and_cold_parent_releases_orphan(self):
        helper = (Path(__file__).parent/"fixtures"/"supervisor_parent.py").resolve()
        environment = {key: os.environ[key] for key in
                       ("SystemRoot", "WINDIR", "TEMP", "TMP", "COMSPEC")
                       if key in os.environ}
        environment.update(PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1",
            __PYVENV_LAUNCHER__=str(Path(sys.executable).resolve()))
        process = subprocess.Popen([sys._base_executable, "-B", str(helper),
            "--environment", self.scope.environment,
            "--account-scope", self.scope.account_scope,
            "--approved-user-sid", self.scope.approved_user_sid,
            "--control-root", str(self.scope.control_root)],
            cwd=Path(__file__).resolve().parents[1], env=environment,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, close_fds=True,
            creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            child_pid = int(await asyncio.wait_for(
                asyncio.to_thread(process.stdout.readline), 12))
            self.assertGreater(child_pid, 0)
            await asyncio.to_thread(process.wait, 10)
            self.assertEqual(process.returncode, 77)
        finally:
            process.stdout.close()
            process.stderr.close()

        # The inherited parent-process handle causes the child to leave without
        # a PID lookup or forced kill.  A cold parent then uses lease exclusion
        # to clear only the orphan reservation and remains fail-closed.
        await self.eventually(lambda: self._child_lease_is_free(), timeout=10)
        cold, task = await self.launch()
        await asyncio.wait_for(task, 10)
        _, controller = await self.controller()
        final = await controller.inspect()
        self.assertIsNone(final.state.child_id)
        self.assertEqual(final.state.state, SupervisorState.ATTENTION_REQUIRED)
        self.assertEqual(final.native.stage, "orphan_released")

    def _child_lease_is_free(self):
        lease = WindowsRoleLease(self.scope.scope_id, "child",
                                 user_sid=self.scope.approved_user_sid)
        try:
            lease.__enter__()
        except InvalidData:
            return False
        lease.__exit__()
        return True


if __name__ == "__main__":
    unittest.main()
