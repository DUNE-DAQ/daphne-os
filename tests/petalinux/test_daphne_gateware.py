from __future__ import annotations

import fcntl
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SERVICE_FILES = (
    ROOT
    / "petalinux"
    / "meta-daphne"
    / "recipes-core"
    / "daphne-services"
    / "files"
)
SWITCHER = SERVICE_FILES / "daphne-gateware"
FW_STOP = SERVICE_FILES / "daphne-fw-stop.sh"


class DaphneGatewareTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.etc = self.root / "etc" / "daphne-gateware"
        self.run = self.root / "run" / "daphne-gateware"
        self.firmware = self.root / "firmware" / "xilinx"
        self.fake_bin = self.root / "fake-bin"
        self.log = self.root / "systemctl.log"
        self.devmem_log = self.root / "devmem.log"
        self.mux_control = self.root / "mux-control.state"
        self.state = self.root / "runtime.state"
        self.active_check_count = self.root / "active-check.count"
        self.etc.joinpath("profiles").mkdir(parents=True)
        self.run.mkdir(parents=True)
        self.firmware.mkdir(parents=True)
        self.fake_bin.mkdir()

        self._write_profile("self-trigger", "self_app", 1)
        self._write_profile("full-stream", "full_app", 2)
        (self.etc / "default-profile").write_text(
            "self-trigger\n", encoding="utf-8"
        )
        self._write_metadata("self_app", "1f9cde5109a120903b2875fa250dbf421c17f9c6")
        self._write_metadata("full_app", "7afa1585b0dadde8001d31e1d60cdc8e74c738a2")
        self._write_fake_commands()

        self.env = {
            **os.environ,
            "PATH": f"{self.fake_bin}:{os.environ['PATH']}",
            "DAPHNE_GATEWARE_ALLOW_NONROOT": "1",
            "DAPHNE_GATEWARE_ETC_DIR": str(self.etc),
            "DAPHNE_GATEWARE_RUN_DIR": str(self.run),
            "DAPHNE_GATEWARE_FIRMWARE_DIR": str(self.firmware),
            "DAPHNE_TEST_SYSTEMCTL_LOG": str(self.log),
            "DAPHNE_TEST_DEVMEM_LOG": str(self.devmem_log),
            "DAPHNE_TEST_MUX_CONTROL": str(self.mux_control),
            "DAPHNE_TEST_RUNTIME_STATE": str(self.state),
            "DAPHNE_TEST_ACTIVE_CHECK_COUNT": str(self.active_check_count),
            "DAPHNE_GATEWARE_STABILITY_CHECKS": "2",
            "DAPHNE_GATEWARE_STABILITY_INTERVAL_SECONDS": "0",
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _write_profile(self, name: str, app: str, variant: int) -> None:
        (self.etc / "profiles" / f"{name}.conf").write_text(
            textwrap.dedent(
                f"""\
                PROFILE={name}
                APP={app}
                GATEWARE_MODE={name}
                IDENTITY_MAGIC=0x44415048
                IDENTITY_ABI_MAJOR=2
                IDENTITY_ABI_MINOR=0
                IDENTITY_VARIANT={variant}
                IDENTITY_BUILD_ID=metadata
                """
            ),
            encoding="utf-8",
        )

    def _write_metadata(self, app: str, git_sha: str) -> None:
        app_dir = self.firmware / app
        app_dir.mkdir()
        for name in (f"{app}.bin", f"{app}.dtbo", "shell.json"):
            (app_dir / name).write_text(f"{name}\n", encoding="utf-8")
        (app_dir / "BUILD-METADATA.txt").write_text(
            f"git_sha={git_sha}\n", encoding="utf-8"
        )

    def _write_executable(self, name: str, content: str) -> None:
        path = self.fake_bin / name
        path.write_text(textwrap.dedent(content), encoding="utf-8")
        path.chmod(0o755)

    def _write_fake_commands(self) -> None:
        self._write_executable(
            "systemctl",
            r"""#!/bin/sh
            set -eu
            command=$1
            shift
            case "$command" in
              is-active)
                profile=$(sed -n 's/^PROFILE=//p' "$DAPHNE_GATEWARE_RUN_DIR/active.env" 2>/dev/null || true)
                for unit in "$@"; do
                  if [ "${DAPHNE_TEST_INACTIVE_UNIT:-}" = "$unit" ]; then
                    exit 1
                  fi
                done
                count=$(cat "$DAPHNE_TEST_ACTIVE_CHECK_COUNT" 2>/dev/null || echo 0)
                count=$((count + 1))
                printf '%s\n' "$count" >"$DAPHNE_TEST_ACTIVE_CHECK_COUNT"
                if [ "${DAPHNE_TEST_UNSTABLE_PROFILE:-}" = "$profile" ] \
                  && [ "$count" -gt "${DAPHNE_TEST_UNSTABLE_AFTER:-999999}" ]; then
                  exit 1
                fi
                [ "$(cat "$DAPHNE_TEST_RUNTIME_STATE" 2>/dev/null || true)" = active ]
                ;;
              stop)
                profile=$(sed -n 's/^PROFILE=//p' "$DAPHNE_GATEWARE_RUN_DIR/active.env")
                printf 'stop|%s|%s\n' "$profile" "$*" >>"$DAPHNE_TEST_SYSTEMCTL_LOG"
                if [ "${DAPHNE_TEST_STOP_FAIL:-0}" = 1 ]; then
                  echo "mock unload failure" >&2
                  exit 19
                fi
                echo inactive >"$DAPHNE_TEST_RUNTIME_STATE"
                ;;
              start)
                profile=$(sed -n 's/^PROFILE=//p' "$DAPHNE_GATEWARE_RUN_DIR/active.env")
                printf 'start|%s|%s\n' "$profile" "$*" >>"$DAPHNE_TEST_SYSTEMCTL_LOG"
                if [ "${DAPHNE_TEST_FAIL_PROFILE:-}" = "$profile" ]; then
                  echo "mock start failure for $profile" >&2
                  exit 23
                fi
                echo active >"$DAPHNE_TEST_RUNTIME_STATE"
                echo 0 >"$DAPHNE_TEST_ACTIVE_CHECK_COUNT"
                ;;
              list-unit-files)
                exit 0
                ;;
              *)
                echo "unexpected systemctl command: $command $*" >&2
                exit 2
                ;;
            esac
            """,
        )
        self._write_executable(
            "devmem",
            r"""#!/bin/sh
            set -eu
            . "$DAPHNE_GATEWARE_RUN_DIR/active.env"
            printf '%s\n' "$1" >>"$DAPHNE_TEST_DEVMEM_LOG"
            if [ "$#" -eq 3 ]; then
              [ "$1" = 0xA0020080 ] || exit 2
              printf '%s\n' "$3" >"$DAPHNE_TEST_MUX_CONTROL"
              exit 0
            fi
            case "$1" in
              0x940000F0) value=$IDENTITY_MAGIC ;;
              0x940000F4) value=$((IDENTITY_ABI_MAJOR << 16 | IDENTITY_ABI_MINOR)) ;;
              0x940000F8)
                if [ "${DAPHNE_TEST_BAD_VARIANT:-0}" = 1 ]; then
                  value=99
                else
                  value=$IDENTITY_VARIANT
                fi
                ;;
              0x940000FC) value=$IDENTITY_BUILD_ID ;;
              0xA0020080)
                if [ "${DAPHNE_TEST_STUCK_MUX:-0}" = 1 ]; then
                  value=3
                else
                  value=$(cat "$DAPHNE_TEST_MUX_CONTROL" 2>/dev/null || echo 3)
                fi
                ;;
              *) exit 2 ;;
            esac
            printf '0x%08X\n' "$value"
            """,
        )

    def _run(
        self,
        *arguments: str,
        check: bool = True,
        timeout: float = 5.0,
        **env: str,
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [sys.executable, str(SWITCHER), *arguments],
            text=True,
            capture_output=True,
            env={**self.env, **env},
            check=False,
            timeout=timeout,
        )
        if check and result.returncode != 0:
            self.fail(f"command failed: {result.stdout}\n{result.stderr}")
        return result

    def _prepare_active_self_trigger(self) -> None:
        self._run("prepare-default")
        self.state.write_text("active\n", encoding="utf-8")

    def _prepare_active_full_stream(self) -> None:
        (self.etc / "default-profile").write_text(
            "full-stream\n", encoding="utf-8"
        )
        self._run("prepare-default")
        self.state.write_text("active\n", encoding="utf-8")

    def test_full_sha_metadata_uses_zero_extended_first_seven_hex_digits(self) -> None:
        result = self._run("list")
        self.assertIn("self-trigger", result.stdout)
        self.assertIn("build=0x01F9CDE5", result.stdout)
        self.assertIn("build=0x07AFA158", result.stdout)

    def test_quiesce_full_stream_verifies_identity_and_waits_for_ack(self) -> None:
        self._prepare_active_full_stream()

        result = self._run("quiesce")

        self.assertIn("full-stream output quiesced", result.stdout)
        self.assertEqual(
            self.mux_control.read_text(encoding="utf-8").strip(),
            "0x00000000",
        )
        self.assertEqual(
            self.devmem_log.read_text(encoding="utf-8").splitlines(),
            [
                "0x940000F0",
                "0x940000F4",
                "0x940000F8",
                "0x940000FC",
                "0xA0020080",
                "0xA0020080",
            ],
        )

    def test_quiesce_failure_is_fatal(self) -> None:
        self._prepare_active_full_stream()

        result = self._run(
            "quiesce", check=False, DAPHNE_TEST_STUCK_MUX="1"
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("did not acknowledge quiesce", result.stderr)

    def test_switch_stops_all_clients_then_starts_and_verifies_new_profile(self) -> None:
        self._prepare_active_self_trigger()

        result = self._run("switch", "full-stream")

        self.assertIn("identity ok: profile=full-stream", result.stdout)
        self.assertIn("switched gateware to full-stream", result.stdout)
        active = (self.run / "active.env").read_text(encoding="utf-8")
        self.assertIn("PROFILE=full-stream", active)
        self.assertIn("IDENTITY_BUILD_ID=0x07AFA158", active)
        calls = self.log.read_text(encoding="utf-8").splitlines()
        self.assertTrue(calls[0].startswith("stop|self-trigger|"), calls)
        for unit in (
            "daphne.service",
            "hermes.service",
            "endpoint.service",
            "clockchip.service",
            "daphne-gateware-verify.service",
            "firmware.service",
        ):
            self.assertIn(unit, calls[0])
        self.assertEqual(calls[1], "start|full-stream|daphne-runtime.target")
        self.assertEqual(
            self.devmem_log.read_text(encoding="utf-8").splitlines(),
            ["0x940000F0", "0x940000F4", "0x940000F8", "0x940000FC"],
        )

    def test_prepare_does_not_reacquire_parent_switch_lock(self) -> None:
        self._prepare_active_self_trigger()

        lock_path = self.run / "switch.lock"
        with lock_path.open("a+", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            result = self._run("prepare-default", timeout=1.0)

        self.assertEqual(result.returncode, 0)
        self.assertIn(
            "PROFILE=self-trigger",
            (self.run / "active.env").read_text(encoding="utf-8"),
        )

    def test_failed_start_rolls_back_previous_profile(self) -> None:
        self._prepare_active_self_trigger()

        result = self._run(
            "switch",
            "full-stream",
            check=False,
            DAPHNE_TEST_FAIL_PROFILE="full-stream",
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("rolled back successfully to self-trigger", result.stderr)
        active = (self.run / "active.env").read_text(encoding="utf-8")
        self.assertIn("PROFILE=self-trigger", active)
        calls = self.log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(
            [line.split("|", 2)[:2] for line in calls],
            [
                ["stop", "self-trigger"],
                ["start", "full-stream"],
                ["stop", "full-stream"],
                ["start", "self-trigger"],
            ],
        )
        self.assertEqual(self.state.read_text(encoding="utf-8").strip(), "active")

    def test_daemon_dying_in_stability_window_rolls_back(self) -> None:
        self._prepare_active_self_trigger()

        result = self._run(
            "switch",
            "full-stream",
            check=False,
            DAPHNE_TEST_UNSTABLE_PROFILE="full-stream",
            DAPHNE_TEST_UNSTABLE_AFTER="7",
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("stability window", result.stderr)
        self.assertIn("rolled back successfully to self-trigger", result.stderr)
        self.assertIn(
            "PROFILE=self-trigger",
            (self.run / "active.env").read_text(encoding="utf-8"),
        )

    def test_unload_failure_does_not_change_profile(self) -> None:
        self._prepare_active_self_trigger()

        result = self._run(
            "switch",
            "full-stream",
            check=False,
            DAPHNE_TEST_STOP_FAIL="1",
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("profile was not changed", result.stderr)
        active = (self.run / "active.env").read_text(encoding="utf-8")
        self.assertIn("PROFILE=self-trigger", active)

    def test_identity_mismatch_is_fatal(self) -> None:
        self._prepare_active_self_trigger()
        result = self._run(
            "verify", check=False, DAPHNE_TEST_BAD_VARIANT="1"
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("identity mismatch", result.stderr)
        self.assertIn("variant=0x00000063", result.stderr)

    def test_firmware_stop_propagates_xmutil_failure(self) -> None:
        self._write_executable(
            "xmutil",
            """\
            #!/bin/sh
            exit 17
            """,
        )
        result = subprocess.run(
            ["/bin/sh", str(FW_STOP)],
            text=True,
            capture_output=True,
            env={**self.env, "PATH": f"{self.fake_bin}:/usr/bin:/bin"},
            check=False,
        )
        self.assertEqual(result.returncode, 17, result)
        self.assertIn("Unloading FPGA app via xmutil", result.stdout)

    def test_server_receives_mode_and_pinned_build_id(self) -> None:
        unit = (SERVICE_FILES / "daphne.service").read_text(encoding="utf-8")
        self.assertIn('--gateware-mode "${GATEWARE_MODE}"', unit)
        self.assertIn(
            '--expected-gateware-build-id "${IDENTITY_BUILD_ID}"', unit
        )
        self.assertIn("RestartPreventExitStatus=78", unit)
        self.assertIn("ExecStopPost=/usr/sbin/daphne-gateware quiesce", unit)

    def test_status_and_set_default_keep_runtime_selection_separate(self) -> None:
        self._prepare_active_self_trigger()
        status = self._run("status")
        self.assertIn("default profile: self-trigger", status.stdout)
        self.assertIn("active profile: self-trigger", status.stdout)
        self.assertIn("identity ok: profile=self-trigger", status.stdout)

        changed = self._run("set-default", "full-stream")
        self.assertIn("active profile was not changed", changed.stdout)
        self.assertEqual(
            (self.etc / "default-profile").read_text(encoding="utf-8"),
            "full-stream\n",
        )
        self.assertIn(
            "PROFILE=self-trigger",
            (self.run / "active.env").read_text(encoding="utf-8"),
        )

    def test_status_reports_an_unhealthy_runtime_daemon(self) -> None:
        self._prepare_active_self_trigger()

        status = self._run(
            "status", check=False, DAPHNE_TEST_INACTIVE_UNIT="daphne.service"
        )

        self.assertEqual(status.returncode, 1)
        self.assertIn("unhealthy units: daphne.service", status.stdout)
        self.assertIn("identity ok: profile=self-trigger", status.stdout)

    def test_systemd_verifier_gates_every_pl_client(self) -> None:
        verifier = (SERVICE_FILES / "daphne-gateware-verify.service").read_text(
            encoding="utf-8"
        )
        clock = (SERVICE_FILES / "clockchip.service").read_text(encoding="utf-8")
        self.assertIn(
            "Before=clockchip.service endpoint.service hermes.service daphne.service",
            verifier,
        )
        self.assertIn("Requires=daphne-gateware-verify.service", clock)


if __name__ == "__main__":
    unittest.main()
