import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from kalshi_bot import live
from kalshi_bot.live_session import LiveSession
from kalshi_bot.process_supervisor import SupervisorHost
from kalshi_bot.recovery_fence import RecoveryFence
from kalshi_bot.supervisor_control import ScopeSpec
from kalshi_bot.supervisor_launch import (PRODUCTION_MODE,
    ProductionLaunchProfile, production_build_fingerprint,
    production_child_mode)
from kalshi_bot.supervisor_protocol import Envelope, MessageKind
from kalshi_bot.values import InvalidData
from kalshi_bot.windows import current_user_sid


class ProductionSupervisorTests(unittest.TestCase):
    def test_profile_is_fixed_and_routes_recovery_only(self):
        normal = ProductionLaunchProfile(False)
        opening = ProductionLaunchProfile(True)
        self.assertEqual(normal.mode, PRODUCTION_MODE)
        self.assertEqual(normal.build_fingerprint, production_build_fingerprint())
        self.assertNotEqual(normal.config_fingerprint, opening.config_fingerprint)
        command = opening.command(Path("C:/Python/python.exe"), ["--scope-id", "x"],
                                  recovery_only=True, explicit_retry=True)
        self.assertEqual(command[:4], ["C:\\Python\\python.exe", "-B", "-m",
                                      "kalshi_bot.supervised_live_child"])
        self.assertIn("--initialize-approved", command)
        self.assertIn("--recovery-only", command)
        self.assertIn("--explicit-retry", command)
        self.assertTrue(opening.supports_fence)
        self.assertEqual(opening.classify_exit(27), 'unexpected_death')
        self.assertEqual(opening.classify_exit(-1), 'unexpected_death')
        self.assertEqual(opening.classify_exit(20), 'startup_refused')

    def test_production_scope_is_exact(self):
        with TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            scope = ScopeSpec("production", "kalshi-primary-account",
                current_user_sid(), root, "production")
            self.assertEqual(scope.scope_id,
                             "production-kalshi-primary-account")
            with self.assertRaises(InvalidData):
                ScopeSpec("production", "another-account",
                          current_user_sid(), root, "production")
            with self.assertRaisesRegex(InvalidData, "production launch profile"):
                SupervisorHost(scope, launch_profile=object())

    def test_protocol_accepts_only_fixed_production_mode(self):
        profile = ProductionLaunchProfile()
        message = Envelope("a"*64, "parent", "child", 1,
            MessageKind.HELLO, 1, 1,
            dict(build_fingerprint=profile.build_fingerprint,
                 config_fingerprint=profile.config_fingerprint,
                 fixture_mode=PRODUCTION_MODE))
        self.assertEqual(message.payload["fixture_mode"], PRODUCTION_MODE)

    def test_one_time_initialize_and_recovery_modes(self):
        opening = production_child_mode(initialize_approved=True,
            ledger_exists=False, recovery_only=False)
        self.assertTrue(opening.initialize)
        restart = production_child_mode(initialize_approved=True,
            ledger_exists=True, recovery_only=False)
        self.assertFalse(restart.initialize)
        recovery = production_child_mode(initialize_approved=True,
            ledger_exists=True, recovery_only=True)
        self.assertFalse(recovery.initialize)
        self.assertTrue(recovery.recovery_only)
        with self.assertRaisesRegex(InvalidData, "recovery ledger"):
            production_child_mode(initialize_approved=True,
                ledger_exists=False, recovery_only=True)
        with self.assertRaisesRegex(InvalidData, "explicit initialize"):
            production_child_mode(initialize_approved=False,
                ledger_exists=False, recovery_only=False)

    def test_restart_reason_forces_recovery_only(self):
        profile = ProductionLaunchProfile()
        self.assertFalse(profile.recovery_only(
            SimpleNamespace(recovery_reasons=())))
        self.assertTrue(profile.recovery_only(
            SimpleNamespace(recovery_reasons=("unexpected_death",))))
        prior = RecoveryFence('parent', 'child', 1, 1)
        self.assertFalse(profile.explicit_retry(
            SimpleNamespace(generation=1), prior))
        self.assertTrue(profile.explicit_retry(
            SimpleNamespace(generation=2), prior))

    def test_recovery_only_never_combines_with_initialize(self):
        args = SimpleNamespace(initialize=True)
        with self.assertRaisesRegex(InvalidData, "recovery-only"):
            asyncio.run(live.run(args, None, None, None, None,
                                 recovery_only=True))

    def test_recovery_only_pauses_entries_before_signer_access(self):
        with TemporaryDirectory() as folder:
            data = Path(folder)
            (data / "account.db").touch()
            args = SimpleNamespace(initialize=False,
                key_id_file=data / "id", private_key_file=data / "key")
            session = LiveSession(run_id="test-recovery",
                                  tickers=("TEST-TICKER",))
            with patch.object(live, "DATA", data), patch.object(
                    live, "load_signer", side_effect=InvalidData("blocked")):
                with self.assertRaises(InvalidData):
                    asyncio.run(live.run(args, None, session, None, None,
                                         recovery_only=True))
            self.assertTrue(session.entries_paused)


if __name__ == "__main__":
    unittest.main()
