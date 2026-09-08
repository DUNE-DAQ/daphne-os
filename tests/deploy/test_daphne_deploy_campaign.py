from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/deploy/daphne_deploy_campaign.py"
RELEASE = "dual-gateware-2026.08.31-rc1"


class DaphneDeployCampaignTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.bundle = self.base / "bundle"
        required = (
            "boot/Image",
            "boot/system.dtb",
            "boot/ramdisk.cpio.gz.u-boot",
            "rootfs/rootfs.ext4",
        )
        for relative in required:
            path = self.bundle / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"fixture:{relative}\n", encoding="utf-8")
        (self.bundle / "SHA256SUMS").write_text(
            "".join(
                f"{self.digest(self.bundle / relative)}  ./{relative}\n"
                for relative in required
            ),
            encoding="utf-8",
        )

        self.call_log = self.base / "deploy-calls.jsonl"
        self.fake_deploy = self.base / "fake-deploy.py"
        self.fake_deploy.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, pathlib, subprocess, sys, time\n"
            "args = sys.argv[1:]\n"
            "board = args[args.index('--board') + 1]\n"
            "record = {'board': board, 'args': args}\n"
            "with pathlib.Path(os.environ['DAPHNE_TEST_CALL_LOG']).open('a') as out:\n"
            "    out.write(json.dumps(record) + '\\n')\n"
            "if board == os.environ.get('DAPHNE_TEST_DELAY_OUTPUT_BOARD'):\n"
            "    time.sleep(0.3)\n"
            "print(f'fake deploy for {board}')\n"
            "if board == os.environ.get('DAPHNE_TEST_SLEEP_BOARD'):\n"
            "    marker = os.environ.get('DAPHNE_TEST_DESCENDANT_MARKER')\n"
            "    if marker:\n"
            "        subprocess.Popen([sys.executable, '-c', "
            "'import pathlib,sys,time; time.sleep(0.5); pathlib.Path(sys.argv[1]).write_text(\"escaped\")', marker])\n"
            "    time.sleep(30)\n"
            "if board == os.environ.get('DAPHNE_TEST_MUTATE_AFTER_BOARD'):\n"
            "    mutate = pathlib.Path(os.environ['DAPHNE_TEST_MUTATE_PATH'])\n"
            "    mutate.chmod(0o644)\n"
            "    mutate.write_text('tampered\\n')\n"
            "fail = set(filter(None, os.environ.get('DAPHNE_TEST_FAIL_BOARDS', '').split(',')))\n"
            "raise SystemExit(9 if board in fail else 0)\n",
            encoding="utf-8",
        )
        self.fake_deploy.chmod(0o755)
        self.env = os.environ.copy()
        self.env["DAPHNE_TEST_CALL_LOG"] = str(self.call_log)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def fingerprint(character: str) -> str:
        return f"SHA256:{character * 43}"

    def board_config(self, board: str) -> Path:
        path = self.base / f"config-{board}"
        path.mkdir()
        files = {
            "manifest.env": (
                f"ASSET_ID={board}\n"
                f"HOSTNAME_FQDN={board.lower()}.example\n"
                "EXPECTED_BOOT_MAC=02:00:00:00:00:01\n"
                f"FIRMWARE_RELEASE={RELEASE}\n"
            ),
            "hostname": f"{board.lower()}.example\n",
            "daphne-board.env": (
                f"BOARD_ID={board}\n"
                f"HOSTNAME_FQDN={board.lower()}.example\n"
            ),
            "20-daphne-mgmt.network": "[Match]\nName=eth0\n",
            "21-daphne-unused.network": "[Match]\nName=eth1\n",
        }
        for name, contents in files.items():
            (path / name).write_text(contents, encoding="utf-8")
        return path

    def row(
        self,
        board: str,
        host: str,
        fingerprint_character: str,
        *,
        user: str = "",
        control_host: str = "",
    ) -> dict[str, str]:
        return {
            "board": board,
            "host": host,
            "board_config": str(self.board_config(board)),
            "host_key_sha256": self.fingerprint(fingerprint_character),
            "user": user,
            "control_host": control_host,
        }

    def campaign_csv(
        self,
        rows: list[dict[str, str]],
        name: str = "campaign.csv",
        *,
        include_optional: bool = True,
    ) -> Path:
        path = self.base / name
        fieldnames = ["board", "host", "board_config", "host_key_sha256"]
        if include_optional:
            fieldnames.extend(("user", "control_host"))
        with path.open("w", newline="", encoding="utf-8") as target:
            writer = csv.DictWriter(
                target,
                fieldnames=fieldnames,
                extrasaction="ignore",
            )
            writer.writeheader()
            writer.writerows(rows)
        return path

    def run_campaign(
        self,
        campaign: Path,
        evidence: Path,
        *extra: str,
        fail_boards: str = "",
    ) -> subprocess.CompletedProcess[str]:
        env = self.env.copy()
        env["DAPHNE_TEST_FAIL_BOARDS"] = fail_boards
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                str(campaign),
                "--bundle",
                str(self.bundle),
                "--evidence-dir",
                str(evidence),
                "--deploy-script",
                str(self.fake_deploy),
                *extra,
            ],
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def calls(self) -> list[dict[str, object]]:
        if not self.call_log.exists():
            return []
        return [
            json.loads(line)
            for line in self.call_log.read_text(encoding="utf-8").splitlines()
        ]

    @staticmethod
    def summary(evidence: Path) -> dict[str, object]:
        return json.loads(
            (evidence / "campaign-summary.json").read_text(encoding="utf-8")
        )

    def test_defaults_to_sequential_dry_run_and_records_evidence(self) -> None:
        campaign = self.campaign_csv(
            [
                self.row(
                    "BOARD-A",
                    "board-a.example",
                    "A",
                    user="operator",
                    control_host="jump@example",
                ),
                self.row("BOARD-B", "board-b.example", "B"),
            ]
        )
        evidence = self.base / "evidence"

        result = self.run_campaign(campaign, evidence, "--reboot")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = self.calls()
        self.assertEqual([call["board"] for call in calls], ["BOARD-A", "BOARD-B"])
        for call in calls:
            self.assertIn("--dry-run", call["args"])
            self.assertIn("--reboot", call["args"])
        self.assertIn("--user", calls[0]["args"])
        self.assertIn("operator", calls[0]["args"])
        self.assertIn("--control-host", calls[0]["args"])
        self.assertNotIn("--user", calls[1]["args"])
        self.assertNotIn("--control-host", calls[1]["args"])

        summary = self.summary(evidence)
        self.assertEqual(summary["mode"], "dry-run")
        self.assertEqual(summary["status"], "dry_run_passed")
        self.assertEqual(summary["attempted_boards"], 2)
        self.assertEqual(summary["bundle_verification"]["verified_entries"], 4)
        self.assertEqual(summary["campaign_csv_sha256"], self.digest(campaign))
        self.assertEqual(summary["firmware_release"], RELEASE)
        self.assertEqual(
            summary["bundle_verification"]["manifest_sha256"],
            self.digest(self.bundle / "SHA256SUMS"),
        )
        self.assertEqual(summary["deploy_script_sha256"], self.digest(self.fake_deploy))
        config_arg_index = calls[0]["args"].index("--board-config") + 1
        bundle_arg_index = calls[0]["args"].index("--bundle") + 1
        self.assertNotEqual(
            Path(calls[0]["args"][config_arg_index]),
            campaign.parent / "config-BOARD-A",
        )
        self.assertNotEqual(Path(calls[0]["args"][bundle_arg_index]), self.bundle)
        self.assertNotEqual(Path(summary["deploy_script"]), self.fake_deploy)
        bundle_snapshot = Path(calls[0]["args"][bundle_arg_index])
        self.assertEqual(
            self.digest(bundle_snapshot / "boot/Image"),
            self.digest(self.bundle / "boot/Image"),
        )
        self.assertEqual(
            summary["input_snapshot"]["bundle"]["artifacts_sha256"]["boot/Image"],
            self.digest(bundle_snapshot / "boot/Image"),
        )
        self.assertEqual(Path(summary["input_snapshot"]["root"]).stat().st_mode & 0o222, 0)
        self.assertEqual(Path(summary["deploy_script"]).stat().st_mode & 0o222, 0)
        self.assertEqual(
            summary["boards"][0]["board_config_sha256"]["manifest.env"],
            self.digest(Path(calls[0]["args"][config_arg_index]) / "manifest.env"),
        )
        self.assertEqual(
            [entry["status"] for entry in summary["boards"]],
            ["dry_run_passed", "dry_run_passed"],
        )
        self.assertEqual(summary["evidence_scope"], "deployment_only_not_qualification")
        self.assertEqual(summary["qualification"]["status"], "not_performed")
        self.assertTrue(summary["qualification"]["required_for_release"])
        self.assertFalse(summary["boards"][0]["release_qualified"])
        self.assertEqual(summary["boards"][0]["firmware_release"], RELEASE)
        self.assertTrue((evidence / "001-BOARD-A.log").is_file())
        self.assertTrue((evidence / "002-BOARD-B.log").is_file())
        self.assertEqual(
            summary["boards"][0]["log_sha256"],
            self.digest(evidence / "001-BOARD-A.log"),
        )

    def test_execute_is_required_to_remove_dry_run(self) -> None:
        campaign = self.campaign_csv(
            [self.row("BOARD-A", "board-a.example", "A")],
            include_optional=False,
        )
        evidence = self.base / "execute-evidence"

        result = self.run_campaign(campaign, evidence, "--execute")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("--dry-run", self.calls()[0]["args"])
        summary = self.summary(evidence)
        self.assertEqual(summary["mode"], "execute")
        self.assertEqual(summary["status"], "staged")
        self.assertEqual(summary["staged_boards"], 1)
        self.assertEqual(summary["boards"][0]["status"], "staged")

    def test_execute_reboot_is_rejected_before_any_action(self) -> None:
        campaign = self.campaign_csv(
            [self.row("BOARD-A", "board-a.example", "A")]
        )
        evidence = self.base / "execute-reboot-evidence"

        result = self.run_campaign(campaign, evidence, "--execute", "--reboot")

        self.assertEqual(result.returncode, 2)
        self.assertIn("post-reboot qualification gate", result.stderr)
        self.assertEqual(self.calls(), [])
        self.assertFalse(evidence.exists())

    def test_late_malformed_row_prevents_every_board_action(self) -> None:
        rows = [
            self.row("BOARD-A", "board-a.example", "A"),
            self.row("BOARD-B", "board-b.example", "B"),
        ]
        rows[1]["host_key_sha256"] = "not-a-fingerprint"
        campaign = self.campaign_csv(rows)
        evidence = self.base / "invalid-evidence"

        result = self.run_campaign(campaign, evidence)

        self.assertEqual(result.returncode, 2)
        self.assertIn("invalid host_key_sha256", result.stderr)
        self.assertEqual(self.calls(), [])
        self.assertFalse(evidence.exists())

    def test_board_config_must_name_a_firmware_release(self) -> None:
        row = self.row("BOARD-A", "board-a.example", "A")
        config = Path(row["board_config"])
        manifest = config / "manifest.env"
        manifest.write_text(
            manifest.read_text(encoding="utf-8").replace(
                f"FIRMWARE_RELEASE={RELEASE}\n", ""
            ),
            encoding="utf-8",
        )
        campaign = self.campaign_csv([row])
        evidence = self.base / "missing-release-evidence"

        result = self.run_campaign(campaign, evidence)

        self.assertEqual(result.returncode, 2)
        self.assertIn("FIRMWARE_RELEASE", result.stderr)
        self.assertEqual(self.calls(), [])
        self.assertFalse(evidence.exists())

    def test_campaign_rejects_mixed_firmware_releases(self) -> None:
        rows = [
            self.row("BOARD-A", "board-a.example", "A"),
            self.row("BOARD-B", "board-b.example", "B"),
        ]
        second_manifest = Path(rows[1]["board_config"]) / "manifest.env"
        second_manifest.write_text(
            second_manifest.read_text(encoding="utf-8").replace(
                RELEASE, "dual-gateware-other-rc"
            ),
            encoding="utf-8",
        )
        campaign = self.campaign_csv(rows)
        evidence = self.base / "mixed-release-evidence"

        result = self.run_campaign(campaign, evidence)

        self.assertEqual(result.returncode, 2)
        self.assertIn("different firmware releases", result.stderr)
        self.assertEqual(self.calls(), [])
        self.assertFalse(evidence.exists())

    def test_malformed_quoted_header_is_a_clean_preflight_failure(self) -> None:
        campaign = self.base / "malformed.csv"
        campaign.write_text('"board,host\n', encoding="utf-8")
        evidence = self.base / "malformed-header-evidence"

        result = self.run_campaign(campaign, evidence)

        self.assertEqual(result.returncode, 2)
        self.assertIn("malformed campaign CSV", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(self.calls(), [])
        self.assertFalse(evidence.exists())

    def test_ssh_option_like_optional_fields_are_rejected(self) -> None:
        for index, field in enumerate(("user", "control_host"), start=1):
            with self.subTest(field=field):
                board = f"BOARD-{index}"
                row = self.row(
                    board,
                    f"board-{index}.example",
                    chr(ord("A") + index - 1),
                )
                row[field] = "-Fattacker-config"
                campaign = self.campaign_csv(
                    [row], name=f"unsafe-{field}.csv"
                )
                evidence = self.base / f"unsafe-{field}-evidence"

                result = self.run_campaign(campaign, evidence)

                self.assertEqual(result.returncode, 2)
                self.assertIn(f"unsafe {field}", result.stderr)
                self.assertEqual(self.calls(), [])
                self.assertFalse(evidence.exists())

    def test_duplicate_board_is_rejected_before_any_action(self) -> None:
        first = self.row("BOARD-A", "board-a.example", "A")
        second = self.row("BOARD-B", "board-b.example", "B")
        second["board"] = "board-a"
        second_config = Path(second["board_config"])
        (second_config / "manifest.env").write_text(
            "ASSET_ID=board-a\n"
            "HOSTNAME_FQDN=board-a.example\n"
            "EXPECTED_BOOT_MAC=02:00:00:00:00:01\n"
            f"FIRMWARE_RELEASE={RELEASE}\n",
            encoding="utf-8",
        )
        (second_config / "hostname").write_text(
            "board-a.example\n", encoding="utf-8"
        )
        (second_config / "daphne-board.env").write_text(
            "BOARD_ID=board-a\nHOSTNAME_FQDN=board-a.example\n",
            encoding="utf-8",
        )
        campaign = self.campaign_csv([first, second])
        evidence = self.base / "duplicate-evidence"

        result = self.run_campaign(campaign, evidence)

        self.assertEqual(result.returncode, 2)
        self.assertIn("duplicate board", result.stderr)
        self.assertEqual(self.calls(), [])

    def test_late_unsafe_board_config_prevents_every_board_action(self) -> None:
        rows = [
            self.row("BOARD-A", "board-a.example", "A"),
            self.row("BOARD-B", "board-b.example", "B"),
        ]
        (Path(rows[1]["board_config"]) / "20-daphne-mgmt.network").write_text(
            "[Link]\nMACAddress=02:00:00:00:00:02\n", encoding="utf-8"
        )
        campaign = self.campaign_csv(rows)
        evidence = self.base / "unsafe-config-evidence"

        result = self.run_campaign(campaign, evidence)

        self.assertEqual(result.returncode, 2)
        self.assertIn("forbidden MAC setter", result.stderr)
        self.assertEqual(self.calls(), [])
        self.assertFalse(evidence.exists())

    def test_inconsistent_board_identity_payload_prevents_every_action(self) -> None:
        cases = (
            ("hostname", "some-other-board.example\n"),
            (
                "daphne-board.env",
                "BOARD_ID=SOME-OTHER-BOARD\nHOSTNAME_FQDN=board-b.example\n",
            ),
        )
        for index, (filename, contents) in enumerate(cases, start=1):
            with self.subTest(filename=filename):
                rows = [
                    self.row(f"BOARD-A{index}", f"board-a{index}.example", "A"),
                    self.row(f"BOARD-B{index}", f"board-b{index}.example", "B"),
                ]
                (Path(rows[1]["board_config"]) / filename).write_text(
                    contents, encoding="utf-8"
                )
                campaign = self.campaign_csv(
                    rows, name=f"inconsistent-{filename}.csv"
                )
                evidence = self.base / f"inconsistent-{filename}-evidence"

                result = self.run_campaign(campaign, evidence)

                self.assertEqual(result.returncode, 2)
                self.assertIn("does not match manifest", result.stderr)
                self.assertEqual(self.calls(), [])
                self.assertFalse(evidence.exists())

    def test_stops_on_first_failure_and_marks_remaining_board(self) -> None:
        campaign = self.campaign_csv(
            [
                self.row("BOARD-A", "board-a.example", "A"),
                self.row("BOARD-B", "board-b.example", "B"),
                self.row("BOARD-C", "board-c.example", "C"),
            ]
        )
        evidence = self.base / "stop-evidence"

        result = self.run_campaign(
            campaign, evidence, fail_boards="BOARD-B"
        )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            [call["board"] for call in self.calls()], ["BOARD-A", "BOARD-B"]
        )
        summary = self.summary(evidence)
        self.assertEqual(summary["status"], "failed")
        self.assertEqual(summary["attempted_boards"], 2)
        self.assertEqual(summary["not_attempted_boards"], 1)
        self.assertEqual(
            [entry["status"] for entry in summary["boards"]],
            ["dry_run_passed", "failed", "not_attempted"],
        )

    def test_continue_on_error_attempts_every_board(self) -> None:
        campaign = self.campaign_csv(
            [
                self.row("BOARD-A", "board-a.example", "A"),
                self.row("BOARD-B", "board-b.example", "B"),
                self.row("BOARD-C", "board-c.example", "C"),
            ]
        )
        evidence = self.base / "continue-evidence"

        result = self.run_campaign(
            campaign,
            evidence,
            "--continue-on-error",
            fail_boards="BOARD-B",
        )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            [call["board"] for call in self.calls()],
            ["BOARD-A", "BOARD-B", "BOARD-C"],
        )
        summary = self.summary(evidence)
        self.assertTrue(summary["continue_on_error"])
        self.assertEqual(summary["attempted_boards"], 3)
        self.assertEqual(summary["failed_boards"], 1)

    def test_source_change_after_snapshot_does_not_change_deployed_bytes(self) -> None:
        rows = [
            self.row("BOARD-A", "board-a.example", "A"),
            self.row("BOARD-B", "board-b.example", "B"),
        ]
        campaign = self.campaign_csv(rows)
        evidence = self.base / "drift-evidence"
        env = self.env.copy()
        env["DAPHNE_TEST_MUTATE_AFTER_BOARD"] = "BOARD-A"
        env["DAPHNE_TEST_MUTATE_PATH"] = str(
            Path(rows[1]["board_config"]) / "hostname"
        )
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                str(campaign),
                "--bundle",
                str(self.bundle),
                "--evidence-dir",
                str(evidence),
                "--deploy-script",
                str(self.fake_deploy),
            ],
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = self.calls()
        self.assertEqual([call["board"] for call in calls], ["BOARD-A", "BOARD-B"])
        second_config_index = calls[1]["args"].index("--board-config") + 1
        second_snapshot = Path(calls[1]["args"][second_config_index])
        self.assertEqual(
            (second_snapshot / "hostname").read_text(encoding="utf-8"),
            "board-b.example\n",
        )
        self.assertEqual(
            (Path(rows[1]["board_config"]) / "hostname").read_text(encoding="utf-8"),
            "tampered\n",
        )
        summary = self.summary(evidence)
        self.assertEqual(summary["status"], "dry_run_passed")
        self.assertEqual(
            [entry["status"] for entry in summary["boards"]],
            ["dry_run_passed", "dry_run_passed"],
        )

    def test_snapshot_tamper_stops_before_later_board_launch(self) -> None:
        rows = [
            self.row("BOARD-A", "board-a.example", "A"),
            self.row("BOARD-B", "board-b.example", "B"),
        ]
        campaign = self.campaign_csv(rows)
        evidence = self.base / "snapshot-tamper-evidence"
        env = self.env.copy()
        env["DAPHNE_TEST_MUTATE_AFTER_BOARD"] = "BOARD-A"
        env["DAPHNE_TEST_MUTATE_PATH"] = str(
            evidence / "inputs/board-configs/002-BOARD-B/hostname"
        )
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                str(campaign),
                "--bundle",
                str(self.bundle),
                "--evidence-dir",
                str(evidence),
                "--deploy-script",
                str(self.fake_deploy),
            ],
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("changed after campaign preflight", result.stderr)
        self.assertEqual([call["board"] for call in self.calls()], ["BOARD-A"])
        summary = self.summary(evidence)
        self.assertEqual(summary["status"], "failed")
        self.assertIn("changed after campaign preflight", summary["error"])
        self.assertEqual(
            [entry["status"] for entry in summary["boards"]],
            ["dry_run_passed", "not_attempted"],
        )

    def test_bundle_checksum_failure_prevents_every_board_action(self) -> None:
        campaign = self.campaign_csv(
            [self.row("BOARD-A", "board-a.example", "A")]
        )
        (self.bundle / "boot/Image").write_text("tampered\n", encoding="utf-8")
        evidence = self.base / "checksum-evidence"

        result = self.run_campaign(campaign, evidence)

        self.assertEqual(result.returncode, 2)
        self.assertIn("bundle checksum mismatch", result.stderr)
        self.assertEqual(self.calls(), [])
        self.assertFalse(evidence.exists())

    def test_interrupt_records_active_board_and_stops_campaign(self) -> None:
        campaign = self.campaign_csv(
            [
                self.row("BOARD-A", "board-a.example", "A"),
                self.row("BOARD-B", "board-b.example", "B"),
            ]
        )
        evidence = self.base / "interrupt-evidence"
        env = self.env.copy()
        env["DAPHNE_TEST_SLEEP_BOARD"] = "BOARD-A"
        descendant_marker = self.base / "escaped-descendant"
        env["DAPHNE_TEST_DESCENDANT_MARKER"] = str(descendant_marker)
        process = subprocess.Popen(
            [
                sys.executable,
                str(SCRIPT),
                str(campaign),
                "--bundle",
                str(self.bundle),
                "--evidence-dir",
                str(evidence),
                "--deploy-script",
                str(self.fake_deploy),
            ],
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        deadline = time.monotonic() + 5
        while not self.call_log.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertTrue(self.call_log.exists(), "fake deploy did not start")
        process.send_signal(signal.SIGINT)
        stdout, stderr = process.communicate(timeout=10)

        self.assertEqual(process.returncode, 130, stdout + stderr)
        summary = self.summary(evidence)
        self.assertEqual(summary["status"], "interrupted")
        self.assertEqual(summary["attempted_boards"], 1)
        self.assertEqual(summary["interrupted_boards"], 1)
        self.assertEqual(
            [entry["status"] for entry in summary["boards"]],
            ["interrupted", "not_attempted"],
        )
        time.sleep(0.7)
        self.assertFalse(descendant_marker.exists())

    def test_closed_stdout_does_not_abandon_active_deploy(self) -> None:
        campaign = self.campaign_csv(
            [self.row("BOARD-A", "board-a.example", "A")]
        )
        evidence = self.base / "closed-stdout-evidence"
        env = self.env.copy()
        env["DAPHNE_TEST_DELAY_OUTPUT_BOARD"] = "BOARD-A"
        process = subprocess.Popen(
            [
                sys.executable,
                str(SCRIPT),
                str(campaign),
                "--bundle",
                str(self.bundle),
                "--evidence-dir",
                str(evidence),
                "--deploy-script",
                str(self.fake_deploy),
            ],
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        deadline = time.monotonic() + 5
        while not self.call_log.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertTrue(self.call_log.exists(), "fake deploy did not start")
        assert process.stdout is not None
        process.stdout.close()
        return_code = process.wait(timeout=10)
        assert process.stderr is not None
        stderr = process.stderr.read()
        process.stderr.close()

        self.assertEqual(return_code, 0, stderr)
        self.assertEqual(self.summary(evidence)["status"], "dry_run_passed")

    def test_sigterm_records_active_board_and_kills_descendants(self) -> None:
        campaign = self.campaign_csv(
            [
                self.row("BOARD-A", "board-a.example", "A"),
                self.row("BOARD-B", "board-b.example", "B"),
            ]
        )
        evidence = self.base / "term-evidence"
        env = self.env.copy()
        env["DAPHNE_TEST_SLEEP_BOARD"] = "BOARD-A"
        descendant_marker = self.base / "term-escaped-descendant"
        env["DAPHNE_TEST_DESCENDANT_MARKER"] = str(descendant_marker)
        process = subprocess.Popen(
            [
                sys.executable,
                str(SCRIPT),
                str(campaign),
                "--bundle",
                str(self.bundle),
                "--evidence-dir",
                str(evidence),
                "--deploy-script",
                str(self.fake_deploy),
            ],
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        deadline = time.monotonic() + 5
        while not self.call_log.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertTrue(self.call_log.exists(), "fake deploy did not start")
        process.send_signal(signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=10)

        self.assertEqual(process.returncode, 143, stdout + stderr)
        summary = self.summary(evidence)
        self.assertEqual(summary["status"], "interrupted")
        self.assertEqual(
            [entry["status"] for entry in summary["boards"]],
            ["interrupted", "not_attempted"],
        )
        time.sleep(0.7)
        self.assertFalse(descendant_marker.exists())


if __name__ == "__main__":
    unittest.main()
