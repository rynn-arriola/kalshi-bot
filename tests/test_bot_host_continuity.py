import asyncio
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from kalshi_bot import detached_host, supervised_live
from kalshi_bot.supervision import SupervisorState
from kalshi_bot.supervisor_control import ControlOwner, ScopeSpec, SupervisorController
from kalshi_bot.supervisor_store import SupervisorStore
from kalshi_bot.values import InvalidData
from kalshi_bot.windows import WindowsRoleLease, current_user_sid, role_present


class HostControlTests(unittest.TestCase):
    def test_saved_json_is_bounded_and_typed(self):
        with TemporaryDirectory() as folder:
            path = Path(folder)/"status.json"
            for payload in ("[1]", '{"value":"'+"x"*100+'"}'):
                path.write_text(payload, encoding="utf-8")
                with self.assertRaises(InvalidData):
                    supervised_live._read_object(path, 50)

    def test_bad_launch_identity_reports_blocked(self):
        with patch("sys.stdout", io.StringIO()) as output:
            code = supervised_live.main(["start", "--live", "--launch-id", "../bad"])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output.getvalue())["state"], "BLOCKED")

    def test_start_and_launch_require_live_before_spawning(self):
        for command in ("start", "launch"):
            with patch.object(supervised_live, "_launch") as launch, patch.object(
                    supervised_live, "_start") as start, patch("sys.stdout", io.StringIO()):
                self.assertEqual(supervised_live.main([command]), 2)
                launch.assert_not_called()
                start.assert_not_called()

    def test_independent_creation_flags_and_no_shell_or_secret_environment(self):
        with patch.object(detached_host.subprocess, "Popen") as popen:
            detached_host.spawn_host(["-m", "fixed.module"], cwd=Path.cwd())
        args, kwargs = popen.call_args
        self.assertEqual(args[0][-2:], ["-m", "fixed.module"])
        self.assertFalse(kwargs["shell"])
        self.assertTrue(kwargs["close_fds"])
        flags = kwargs["creationflags"]
        self.assertTrue(flags & subprocess.CREATE_BREAKAWAY_FROM_JOB)
        self.assertTrue(flags & subprocess.DETACHED_PROCESS)
        self.assertTrue(flags & subprocess.CREATE_NEW_PROCESS_GROUP)
        self.assertNotIn("PATH", kwargs["env"])

    def test_creation_failure_is_not_retried_without_breakaway(self):
        with patch.object(detached_host.subprocess, "Popen", side_effect=OSError) as popen:
            with self.assertRaises(OSError):
                detached_host.spawn_host([], cwd=Path.cwd())
            self.assertEqual(popen.call_count, 1)

    def test_launch_timeout_does_not_kill_or_claim_health(self):
        process = Mock(pid=123)
        process.poll.return_value = None
        with TemporaryDirectory() as folder, patch.object(supervised_live,
                "CONTROL_ROOT", Path(folder)), patch.object(supervised_live,
                "spawn_host", return_value=process), patch.object(supervised_live.time,
                "monotonic", side_effect=[0, 11]):
            result, code = supervised_live._launch(SimpleNamespace(initialize=False))
        self.assertEqual(code, 2)
        self.assertEqual(result["state"], "UNKNOWN")
        self.assertFalse(result["trading_ready"])
        process.terminate.assert_not_called()
        process.kill.assert_not_called()

    def test_correlated_ack_is_not_trading_ready(self):
        process = Mock(pid=123)
        process.poll.return_value = None
        with TemporaryDirectory() as folder, patch.object(supervised_live,
                "CONTROL_ROOT", Path(folder)):
            def spawn(command, **_):
                supervised_live.save_result(supervised_live._launch_path(command[-1]),
                    dict(state="HOST_STARTED", pid=123, trading_ready=False))
                return process
            with patch.object(supervised_live, "spawn_host", side_effect=spawn):
                result, code = supervised_live._launch(SimpleNamespace(initialize=False))
        self.assertEqual(code, 0)
        self.assertEqual(result["state"], "HOST_STARTED")
        self.assertFalse(result["trading_ready"])

    def test_unreadable_ack_preserves_unknown_process_identity(self):
        process = Mock(pid=123)
        process.poll.return_value = None
        with TemporaryDirectory() as folder, patch.object(supervised_live,
                "CONTROL_ROOT", Path(folder)):
            def spawn(command, **_):
                supervised_live._launch_path(command[-1]).write_text("[]", encoding="utf-8")
                return process
            with patch.object(supervised_live, "spawn_host", side_effect=spawn):
                result, code = supervised_live._launch(SimpleNamespace(initialize=False))
        self.assertEqual((code, result["state"], result["pid"]), (2, "UNKNOWN", 123))
        process.kill.assert_not_called()

    def test_early_host_exit_is_blocked_even_with_zero_exit_code(self):
        process = Mock(pid=123)
        process.poll.return_value = 0
        with TemporaryDirectory() as folder, patch.object(supervised_live,
                "CONTROL_ROOT", Path(folder)), patch.object(supervised_live,
                "spawn_host", return_value=process):
            result, code = supervised_live._launch(SimpleNamespace(initialize=False))
        self.assertEqual((code, result["state"]), (2, "BLOCKED"))

    def test_wrong_pid_receipt_never_reports_started(self):
        process = Mock(pid=123)
        process.poll.return_value = None
        with TemporaryDirectory() as folder, patch.object(supervised_live,
                "CONTROL_ROOT", Path(folder)):
            def spawn(command, **_):
                supervised_live.save_result(supervised_live._launch_path(command[-1]),
                    dict(state="HOST_STARTED", pid=456, trading_ready=False))
                return process
            with patch.object(supervised_live, "spawn_host", side_effect=spawn):
                result, code = supervised_live._launch(SimpleNamespace(initialize=False))
        self.assertEqual((code, result["state"]), (2, "BLOCKED"))

    def test_saved_healthy_never_overrides_current_presence(self):
        control = SimpleNamespace(to_dict=lambda: {"state": "HEALTHY"})
        native = SimpleNamespace(parent_session="old", child_id="old",
            child_generation=1, stage="healthy", diagnostic_pid=os.getpid())
        for presence, expected in (([False, False], "STOPPED"),
                ([True, True], "RUNNING_UNVERIFIED"),
                ([False, True], "TRANSITION_OR_ORPHAN"),
                ([InvalidData("unavailable"), False], "UNKNOWN")):
            with TemporaryDirectory() as folder, patch.object(supervised_live,
                    "DATA", Path(folder)), patch.object(supervised_live,
                    "production_scope", return_value=SimpleNamespace(store_path="unused",
                        scope_id="test", approved_user_sid="test")), patch.object(
                    SupervisorStore, "read_only_snapshot", return_value=(1, control, native)), patch.object(
                    supervised_live, "role_present", side_effect=presence):
                result, _ = supervised_live._status()
            self.assertEqual(result["state"], expected)
            self.assertFalse(result["account_flat_verified"])
            self.assertFalse(result["saved_snapshot_only"])
            self.assertTrue(result["control_and_runtime_are_historical"])


@unittest.skipUnless(os.name == "nt", "native Windows host")
class NativeHostTests(unittest.IsolatedAsyncioTestCase):
    async def test_ack_write_failure_joins_owned_host(self):
        class FakeHost:
            parent_session = "fixture"
            def __init__(self):
                self.started = asyncio.Event()
                self.joined = False
            async def run(self):
                self.started.set()
                try:
                    await asyncio.Future()
                finally:
                    await asyncio.sleep(.01)
                    self.joined = True
        host = FakeHost()
        with TemporaryDirectory() as folder:
            path = Path(folder)/"store"
            path.touch()
            with patch.object(supervised_live, "production_scope", return_value=
                    SimpleNamespace(store_path=path)), patch.object(supervised_live,
                    "SupervisorHost", return_value=host), patch.object(supervised_live,
                    "save_result", side_effect=OSError("fixture")):
                with self.assertRaises(OSError):
                    await supervised_live._start(SimpleNamespace(initialize=False,
                        launch_id=str(uuid4())))
        self.assertTrue(host.joined)

    async def test_presence_has_no_pid_reuse_assumption(self):
        scope, sid = "test-presence-"+uuid4().hex, current_user_sid()
        self.assertFalse(role_present(scope, "parent", user_sid=sid))
        with WindowsRoleLease(scope, "parent", user_sid=sid):
            self.assertTrue(role_present(scope, "parent", user_sid=sid))
        self.assertFalse(role_present(scope, "parent", user_sid=sid))

    async def test_detached_host_survives_launcher_exit_then_stops_normally(self):
        with TemporaryDirectory() as folder:
            scope = ScopeSpec("fixture", "test-detached-"+uuid4().hex,
                current_user_sid(), Path(folder).resolve())
            ControlOwner.initialize_fixture(scope)
            helper = Path(__file__).parent/"fixtures"/"detached_supervisor.py"
            launch = await asyncio.to_thread(subprocess.run,
                [sys.executable, "-B", str(helper), "--root", str(scope.control_root),
                 "--account", scope.account_scope, "--sid", scope.approved_user_sid],
                capture_output=True, text=True, timeout=10)
            self.assertEqual(launch.returncode, 0, launch.stderr)
            self.assertGreater(json.loads(launch.stdout)["pid"], 0)
            owner = ControlOwner(scope)
            controller = SupervisorController(scope, owner)
            try:
                deadline = time.monotonic()+10
                while time.monotonic() < deadline:
                    state = (await controller.inspect()).state
                    if state.state == SupervisorState.HEALTHY:
                        break
                    await asyncio.sleep(.05)
                self.assertEqual(state.state, SupervisorState.HEALTHY)
                # Launching process is already gone; both protected roles remain.
                for role in ("parent", "child"):
                    self.assertTrue(role_present(scope.scope_id, role,
                                                 user_sid=scope.approved_user_sid))
            finally:
                await controller.stop()
                deadline = time.monotonic()+10
                while time.monotonic() < deadline and role_present(scope.scope_id,
                        "parent", user_sid=scope.approved_user_sid):
                    await asyncio.sleep(.05)
                await owner.close()
            self.assertFalse(role_present(scope.scope_id, "parent", user_sid=scope.approved_user_sid))
            _, final, _ = SupervisorStore.read_only_snapshot(scope.store_path,
                scope_id=scope.scope_id, security_sid=scope.approved_user_sid)
            self.assertEqual(final.state, SupervisorState.DISARMED)
