from __future__ import annotations

import importlib.machinery
import importlib.util
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
RECIPE = ROOT / "petalinux/meta-daphne/recipes-core/daphne-services"
SCRIPT = RECIPE / "files/daphne-service-status"
LOADER = importlib.machinery.SourceFileLoader("daphne_service_status", str(SCRIPT))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
STATUS = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(STATUS)


class DaphneServiceStatusTests(unittest.TestCase):
    def env(self, mode="self-trigger", **updates):
        return {
            "GATEWARE_MODE": mode,
            "IDENTITY_ABI_MAJOR": "2",
            "IDENTITY_ABI_MINOR": "0",
            "IDENTITY_BUILD_ID": "0x03f17f1b",
            **updates,
        }

    def test_both_modes_show_configuration_not_health(self):
        for mode in ("self-trigger", "full-stream"):
            with self.subTest(mode=mode):
                text = STATUS.status_text("start", self.env(mode))
                self.assertIn(f"Config: {mode} | ABI 2.0 | build 0x03F17F1B", text)
                self.assertIn("timing: NOT CONFIGURED", text)
                self.assertIn("sensor health: see journal", text)

    def test_configured_timing_is_not_reported_as_locked(self):
        text = STATUS.status_text("start", self.env(TIMING_PROFILE="endpoint-sync-v14"))
        self.assertIn("timing: configured (not lock status)", text)

    def test_missing_values_are_unknown_not_success(self):
        text = STATUS.status_text("start", {})
        self.assertIn("Config: unknown | ABI unknown | build unknown", text)
        self.assertIn("NOT CONFIGURED", text)

    def test_decimal_build_is_formatted_as_hex(self):
        text = STATUS.status_text("start", self.env(IDENTITY_BUILD_ID="00000123"))
        self.assertIn("build 0x0000007B", text)

    def test_invalid_values_cannot_inject_notifications_or_secrets(self):
        env = self.env(
            "secret\nREADY=1", IDENTITY_ABI_MAJOR="secret", IDENTITY_ABI_MINOR="0\nMAINPID=1",
            IDENTITY_BUILD_ID="0x123\nREADY=1", TIMING_PROFILE="secret", PASSWORD="secret",
        )
        text = STATUS.status_text("start", env)
        self.assertNotIn("secret", text)
        self.assertNotIn("\n", text)
        self.assertIn("ABI unknown | build unknown", text)
        self.assertIn("build unknown", STATUS.status_text("start", self.env(IDENTITY_BUILD_ID="9999999999")))

    def test_stop_clears_startup_summary_without_claiming_final_success(self):
        for result in ("success", "exit-code", "signal", "timeout"):
            text = STATUS.status_text("stop", self.env(SERVICE_RESULT=result))
            self.assertIn("Server stopped | check Result and journalctl", text)
            self.assertNotIn(result, text)
            self.assertNotIn("Config:", text)
        self.assertNotIn("\n", STATUS.status_text("stop", {"SERVICE_RESULT": "bad\nREADY=1"}))

    def test_notification_only_sends_status_and_is_bounded(self):
        with patch.dict(os.environ, self.env(), clear=True), patch.object(STATUS.sys, "argv", [str(SCRIPT)]), patch.object(STATUS.subprocess, "run") as run:
            self.assertEqual(STATUS.main(), 0)
        args, kwargs = run.call_args
        self.assertEqual(args[0], ["systemd-notify", "--status=" + STATUS.status_text("start", self.env())])
        self.assertEqual(kwargs, {"check": True, "timeout": 3})

    def test_print_mode_does_not_notify(self):
        with patch.object(STATUS.sys, "argv", [str(SCRIPT), "--print"]), patch.object(STATUS.subprocess, "run") as run, patch("builtins.print") as output:
            self.assertEqual(STATUS.main(), 0)
        run.assert_not_called()
        output.assert_called_once()

    def test_notify_failure_is_reported(self):
        for error in (FileNotFoundError("missing"), subprocess.TimeoutExpired("systemd-notify", 3), subprocess.CalledProcessError(1, "systemd-notify")):
            with self.subTest(error=error), patch.object(STATUS.sys, "argv", [str(SCRIPT)]), patch.object(STATUS.subprocess, "run", side_effect=error), patch("builtins.print"):
                self.assertEqual(STATUS.main(), 1)

    def test_unit_reporting_is_optional_without_changing_lifecycle(self):
        unit = (RECIPE / "files/daphne.service").read_text()
        for line in (
            "Type=simple", "NotifyAccess=exec", "SyslogIdentifier=daphne",
            "ExecStartPost=-/usr/local/bin/daphne-service-status start",
            "ExecStopPost=-/usr/local/bin/daphne-service-status stop",
            "ExecStopPost=/usr/sbin/daphne-gateware quiesce", "RestartPreventExitStatus=78",
        ):
            self.assertIn(line, unit)
        self.assertLess(unit.index("daphne-service-status stop"), unit.index("daphne-gateware quiesce"))

    def test_helper_is_packaged(self):
        recipe = (RECIPE / "daphne-services.bb").read_text()
        self.assertIn("file://daphne-service-status", recipe)
        self.assertIn("/usr/local/bin/daphne-service-status", recipe)
        self.assertIn("daphne-endpoint-init.py daphne-service-status; do", recipe)
        self.assertIn("systemd-extra-utils", recipe)


if __name__ == "__main__":
    unittest.main()
