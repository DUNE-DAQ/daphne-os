#!/usr/bin/env python3
"""Contract tests for per-board DAPHNE hardware qualification evidence."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

try:
    import jsonschema
except ImportError:  # The production CLI intentionally has no third-party dependency.
    jsonschema = None


REPOSITORY = Path(__file__).resolve().parents[2]
SCRIPT = REPOSITORY / "scripts" / "deploy" / "daphne_qualification.py"
SCHEMA = (
    REPOSITORY
    / "scripts"
    / "deploy"
    / "schemas"
    / "daphne-hardware-qualification-v1.schema.json"
)
EXAMPLE = (
    REPOSITORY
    / "scripts"
    / "deploy"
    / "examples"
    / "daphne-hardware-qualification-v1.example.json"
)
SPEC = importlib.util.spec_from_file_location("daphne_qualification", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
QUALIFICATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(QUALIFICATION)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class QualificationContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.campaign_dir = self.base / "campaign"
        self.campaign_dir.mkdir()
        self.campaign = self.campaign_dir / "campaign-summary.json"
        self.compatibility = self.base / "COMPATIBILITY.json"
        self.record = self.base / "qualification.json"
        self.board_id = "DAPHNE-01"
        self._write_campaign()
        self._write_compatibility()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _write_campaign(self, path: Path | None = None, marker: str | None = None) -> Path:
        destination = path or self.campaign
        destination.parent.mkdir(parents=True, exist_ok=True)
        log = destination.parent / "001-DAPHNE-01.log"
        log.write_text("staged exact inactive slot\n", encoding="utf-8")
        summary: dict[str, Any] = {
            "contract": "daphne.deploy-campaign",
            "version": 1,
            "campaign_csv": "/frozen/campaign.csv",
            "campaign_csv_sha256": "1" * 64,
            "bundle": "/frozen/bundle",
            "bundle_source": "/source/bundle",
            "bundle_verification": {
                "manifest_sha256": "2" * 64,
                "verified_entries": 4,
                "artifacts_sha256": {
                    "boot/Image": "3" * 64,
                    "boot/boot.scr": "4" * 64,
                    "rootfs/rootfs.ext4": "5" * 64,
                    "rootfs/rootfs.wic.gz": "6" * 64,
                },
            },
            "deploy_script": "/frozen/daphne_deploy.sh",
            "deploy_script_source": "/source/daphne_deploy.sh",
            "deploy_script_sha256": "7" * 64,
            "mode": "execute",
            "reboot": False,
            "firmware_release": "dual-gateware-test-rc1",
            "continue_on_error": False,
            "started_utc": "2026-08-31T20:00:00Z",
            "completed_utc": "2026-08-31T20:01:00Z",
            "status": "staged",
            "total_boards": 1,
            "attempted_boards": 1,
            "staged_boards": 1,
            "failed_boards": 0,
            "evidence_scope": "deployment_only_not_qualification",
            "qualification": {
                "status": "not_performed",
                "required_for_release": True,
            },
            "boards": [
                {
                    "index": 1,
                    "source_line": 2,
                    "board": self.board_id,
                    "host": "daphne-01.example",
                    "user": "root",
                    "control_host": None,
                    "board_config_source": "/source/config-DAPHNE-01",
                    "board_config": "/frozen/config-DAPHNE-01",
                    "board_config_sha256": {
                        "manifest.env": "8" * 64,
                        "ssh_host_ed25519_key.pub": "9" * 64,
                    },
                    "host_key_sha256": "SHA256:" + "A" * 43,
                    "firmware_release": "dual-gateware-test-rc1",
                    "qualification_status": "not_performed",
                    "release_qualified": False,
                    "command": ["daphne_deploy.sh", "--board", self.board_id],
                    "log": log.name,
                    "log_sha256": digest(log),
                    "started_utc": "2026-08-31T20:00:00Z",
                    "completed_utc": "2026-08-31T20:01:00Z",
                    "duration_seconds": 60.0,
                    "return_code": 0,
                    "status": "staged",
                }
            ],
        }
        if marker is not None:
            summary["test_marker"] = marker
        destination.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        return destination

    def _write_compatibility(
        self, path: Path | None = None, release_id: str = "dual-gateware-test-rc1"
    ) -> Path:
        destination = path or self.compatibility
        destination.parent.mkdir(parents=True, exist_ok=True)
        compatibility = {
            "contract": "daphne.dual-gateware-release",
            "contract_version": 1,
            "release_id": release_id,
            "lifecycle": "engineering_rc",
            "profiles": {
                "self-trigger": {"build_id": "0x03F17F1B"},
                "full-stream": {"build_id": "0x0B24E416"},
            },
            "artifacts": {
                "petalinux_image": {
                    "sha256": "b" * 64,
                    "rootfs_ext4_sha256": "5" * 64,
                    "bundle_manifest_sha256": "2" * 64,
                },
                "self_trigger_build": {"sha256": "c" * 64},
                "full_stream_build": {"sha256": "d" * 64},
                "server_runtime": {"sha256": "e" * 64},
                "client_install": {"sha256": "f" * 64},
            },
        }
        destination.write_text(
            json.dumps(compatibility, indent=2) + "\n", encoding="utf-8"
        )
        return destination

    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *arguments],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def init(
        self,
        campaign: Path | None = None,
        compatibility: Path | None = None,
        output: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return self.run_cli(
            "init",
            "--campaign-summary",
            str(campaign or self.campaign),
            "--board",
            self.board_id,
            "--compatibility",
            str(compatibility or self.compatibility),
            "--output",
            str(output or self.record),
        )

    def check(
        self,
        campaign: Path | None = None,
        compatibility: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return self.run_cli(
            "check",
            str(self.record),
            "--campaign-summary",
            str(campaign or self.campaign),
            "--compatibility",
            str(compatibility or self.compatibility),
        )

    def load_record(self) -> dict[str, Any]:
        return json.loads(self.record.read_text(encoding="utf-8"))

    def save_record(self, record: dict[str, Any]) -> None:
        self.record.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")

    def evidence(self, name: str, content: str | None = None) -> dict[str, str]:
        directory = self.base / "evidence"
        directory.mkdir(exist_ok=True)
        path = directory / f"{name}.log"
        path.write_text(content or f"evidence for {name}\n", encoding="utf-8")
        return {"path": str(path.relative_to(self.base)), "sha256": digest(path)}

    def fill_valid_record(self) -> dict[str, Any]:
        record = self.load_record()
        config = self.base / "evidence" / "daq-config.json"
        config.parent.mkdir(exist_ok=True)
        config.write_text('{"channels":[0,1,2,3]}\n', encoding="utf-8")
        config_reference = {
            "path": str(config.relative_to(self.base)),
            "sha256": digest(config),
        }
        command = ["daq-run", "--config", "evidence/daq-config.json"]
        record["acceptance"] = {
            "daq": {"command_argv": command, "config": config_reference},
            "ethernet": {
                "minimum_duration_seconds": 3600,
                "minimum_counter_deltas": {"rx_frames": 1000},
                "maximum_error_deltas": {"rx_errors": 0, "tx_errors": 0},
            },
        }
        self_id = record["binding"]["release"]["self_trigger_build_id"]
        full_id = record["binding"]["release"]["full_stream_build_id"]
        gate_by_id = {gate["id"]: gate for gate in record["gates"]}

        for gate_id, gate in gate_by_id.items():
            gate["status"] = "PASS"
            gate["evidence"] = [self.evidence(gate_id)]
            gate["notes"] = "hardware observation complete"

        gate_by_id["postboot_identity"]["observed"] = {
            "profiles": [
                {
                    "profile": "self-trigger",
                    "build_id": self_id,
                    "server_mode": "self-trigger",
                    "service_active": True,
                },
                {
                    "profile": "full-stream",
                    "build_id": full_id,
                    "server_mode": "full-stream",
                    "service_active": True,
                },
            ]
        }
        sequence = [
            {
                "profile": "self-trigger",
                "build_id": self_id,
                "server_mode": "self-trigger",
                "service_active": True,
                "switch_exit_code": 0,
            },
            {
                "profile": "full-stream",
                "build_id": full_id,
                "server_mode": "full-stream",
                "service_active": True,
                "switch_exit_code": 0,
            },
            {
                "profile": "self-trigger",
                "build_id": self_id,
                "server_mode": "self-trigger",
                "service_active": True,
                "switch_exit_code": 0,
            },
        ]
        gate_by_id["switch_cycle_1_self_full_self"]["observed"] = {
            "sequence": sequence
        }
        gate_by_id["switch_cycle_2_self_full_self"]["observed"] = {
            "sequence": json.loads(json.dumps(sequence))
        }
        gate_by_id["failed_load_rollback"]["observed"] = {
            "attempted_profile": "full-stream",
            "failure_observed": True,
            "switch_exit_code": 1,
            "restored_profile": "self-trigger",
            "restored_build_id": self_id,
            "server_mode": "self-trigger",
            "service_active": True,
        }
        gate_by_id["self_trigger_data"]["observed"] = {
            "daq_command_argv": command,
            "daq_config": config_reference,
            "data_units": 100,
            "errors": 0,
        }
        gate_by_id["full_stream_data_channel_mapping"]["observed"] = {
            "daq_command_argv": command,
            "daq_config": config_reference,
            "data_units": 100,
            "errors": 0,
            "configured_channels": [0, 1, 2, 3],
            "observed_channels": [0, 1, 2, 3],
            "mapping_errors": 0,
        }
        gate_by_id["four_link_ethernet"]["observed"] = {
            "links": [
                {
                    "link_id": str(link),
                    "link_up": True,
                    "duration_seconds": 3600,
                    "counter_deltas": {"rx_frames": 1200},
                    "error_deltas": {"rx_errors": 0, "tx_errors": 0},
                }
                for link in range(4)
            ]
        }
        record["review"] = {
            "status": "PASS",
            "reviewer": "Authorized Reviewer",
            "approved_utc": record["created_utc"],
            "evidence": [self.evidence("review")],
            "notes": "approved for this board and exact release",
        }
        record["qualification_status"] = "PASS"
        record["release_qualified"] = True
        self.save_record(record)
        return record

    def test_init_binds_inputs_and_creates_not_run_record(self) -> None:
        result = self.init()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        record = self.load_record()
        self.assertEqual(record["qualification_status"], "NOT_RUN")
        self.assertFalse(record["release_qualified"])
        self.assertEqual(record["binding"]["campaign"]["sha256"], digest(self.campaign))
        self.assertEqual(record["binding"]["release"]["sha256"], digest(self.compatibility))
        self.assertEqual(record["binding"]["deployment"]["board"], self.board_id)
        self.assertEqual(
            record["binding"]["release"]["self_trigger_build_id"], "0x03F17F1B"
        )
        self.assertEqual(
            record["binding"]["release"]["full_stream_build_id"], "0x0B24E416"
        )
        self.assertEqual(
            record["binding"]["campaign"]["firmware_release"],
            "dual-gateware-test-rc1",
        )
        self.assertEqual(
            record["binding"]["deployment"]["firmware_release"],
            record["binding"]["release"]["release_id"],
        )
        self.assertEqual(
            record["binding"]["campaign"]["bundle_artifact_sha256"][
                "rootfs/rootfs.ext4"
            ],
            record["binding"]["release"]["petalinux_rootfs_ext4_sha256"],
        )
        self.assertEqual(
            record["binding"]["campaign"]["bundle_manifest_sha256"],
            record["binding"]["release"]["petalinux_bundle_manifest_sha256"],
        )
        self.assertEqual(len(record["gates"]), 7)

    def test_initialized_record_is_valid_but_not_qualified(self) -> None:
        self.assertEqual(self.init().returncode, 0)

        result = self.check()

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("VALID:", result.stdout)
        self.assertIn("NOT QUALIFIED", result.stdout)
        self.assertIn("minimum_duration_seconds is unresolved", result.stdout)

    def test_complete_filled_record_qualifies(self) -> None:
        self.assertEqual(self.init().returncode, 0)
        self.fill_valid_record()

        result = self.check()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("QUALIFIED:", result.stdout)

    def test_tampered_evidence_is_invalid(self) -> None:
        self.assertEqual(self.init().returncode, 0)
        record = self.fill_valid_record()
        evidence_path = self.base / record["gates"][0]["evidence"][0]["path"]
        evidence_path.write_text("tampered after review\n", encoding="utf-8")

        result = self.check()

        self.assertEqual(result.returncode, 2)
        self.assertIn("SHA-256 mismatch", result.stderr)

    def test_duplicate_gate_ids_are_invalid(self) -> None:
        self.assertEqual(self.init().returncode, 0)
        record = self.load_record()
        record["gates"][-1]["id"] = record["gates"][0]["id"]
        self.save_record(record)

        result = self.check()

        self.assertEqual(result.returncode, 2)
        self.assertIn("duplicate hardware gate id", result.stderr)
        self.assertIn("missing hardware gates", result.stderr)

    def test_bad_recorded_hash_is_invalid(self) -> None:
        self.assertEqual(self.init().returncode, 0)
        record = self.fill_valid_record()
        record["gates"][0]["evidence"][0]["sha256"] = "0" * 64
        self.save_record(record)

        result = self.check()

        self.assertEqual(result.returncode, 2)
        self.assertIn("SHA-256 mismatch", result.stderr)

    def test_wrong_campaign_and_release_bindings_are_invalid(self) -> None:
        self.assertEqual(self.init().returncode, 0)
        alternate_campaign = self.base / "other-campaign" / "campaign-summary.json"
        self._write_campaign(alternate_campaign, marker="different campaign")
        alternate_release = self.base / "OTHER-COMPATIBILITY.json"
        self._write_compatibility(alternate_release, release_id="different-release")

        campaign_result = self.check(campaign=alternate_campaign)
        release_result = self.check(compatibility=alternate_release)

        self.assertEqual(campaign_result.returncode, 2)
        self.assertIn("campaign-summary SHA-256", campaign_result.stderr)
        self.assertEqual(release_result.returncode, 2)
        self.assertIn("release.release_id", release_result.stderr)

    def test_openssh_host_fingerprint_format_is_required(self) -> None:
        summary = json.loads(self.campaign.read_text(encoding="utf-8"))
        self.assertEqual(len(summary["boards"][0]["host_key_sha256"].split(":")[1]), 43)
        summary["boards"][0]["host_key_sha256"] = "a" * 64
        self.campaign.write_text(json.dumps(summary) + "\n", encoding="utf-8")

        result = self.init()

        self.assertEqual(result.returncode, 2)
        self.assertIn("SHA256:<43-base64-characters>", result.stderr)

    def test_schema_reference_and_versions_are_strict(self) -> None:
        campaign_bool = self.base / "campaign-bool" / "campaign-summary.json"
        self._write_campaign(campaign_bool)
        campaign_data = json.loads(campaign_bool.read_text(encoding="utf-8"))
        campaign_data["version"] = True
        campaign_bool.write_text(json.dumps(campaign_data) + "\n", encoding="utf-8")
        campaign_result = self.init(
            campaign=campaign_bool, output=self.base / "campaign-bool-record.json"
        )

        compatibility_bool = self.base / "COMPATIBILITY-bool.json"
        self._write_compatibility(compatibility_bool)
        compatibility_data = json.loads(
            compatibility_bool.read_text(encoding="utf-8")
        )
        compatibility_data["contract_version"] = True
        compatibility_bool.write_text(
            json.dumps(compatibility_data) + "\n", encoding="utf-8"
        )
        compatibility_result = self.init(
            compatibility=compatibility_bool,
            output=self.base / "compatibility-bool-record.json",
        )

        self.assertEqual(self.init().returncode, 0)
        original = self.load_record()
        wrong_schema = json.loads(json.dumps(original))
        wrong_schema["$schema"] = "some-other-schema.json"
        self.save_record(wrong_schema)
        schema_result = self.check()
        bool_version = json.loads(json.dumps(original))
        bool_version["version"] = True
        self.save_record(bool_version)
        version_result = self.check()

        self.assertEqual(campaign_result.returncode, 2)
        self.assertIn("campaign version must be integer 1", campaign_result.stderr)
        self.assertEqual(compatibility_result.returncode, 2)
        self.assertIn(
            "release compatibility contract_version must be integer 1",
            compatibility_result.stderr,
        )
        self.assertEqual(schema_result.returncode, 2)
        self.assertIn("$schema must be", schema_result.stderr)
        self.assertEqual(version_result.returncode, 2)
        self.assertIn("version must be integer 1", version_result.stderr)

    def test_non_finite_acceptance_and_observations_are_rejected(self) -> None:
        self.assertEqual(self.init().returncode, 0)
        baseline = self.fill_valid_record()
        cases = (
            ("acceptance duration", lambda record: record["acceptance"]["ethernet"].__setitem__("minimum_duration_seconds", float("inf"))),
            ("observed duration", lambda record: record["gates"][-1]["observed"]["links"][0].__setitem__("duration_seconds", float("nan"))),
            ("counter threshold", lambda record: record["acceptance"]["ethernet"]["minimum_counter_deltas"].__setitem__("rx_frames", float("inf"))),
        )
        for label, mutate in cases:
            with self.subTest(label=label):
                record = json.loads(json.dumps(baseline))
                mutate(record)
                self.save_record(record)
                result = self.check()
                self.assertEqual(result.returncode, 2)
                self.assertIn("non-finite JSON number is forbidden", result.stderr)

    def test_full_stream_channel_order_must_match(self) -> None:
        self.assertEqual(self.init().returncode, 0)
        record = self.fill_valid_record()
        full_gate = next(
            gate
            for gate in record["gates"]
            if gate["id"] == "full_stream_data_channel_mapping"
        )
        full_gate["observed"]["observed_channels"] = [1, 0, 2, 3]
        self.save_record(record)

        result = self.check()

        self.assertEqual(result.returncode, 2)
        self.assertIn("do not match configured channels in order", result.stderr)

    def test_campaign_and_release_identity_must_align(self) -> None:
        top_level_mismatch = self.base / "top-release" / "campaign-summary.json"
        self._write_campaign(top_level_mismatch)
        top_data = json.loads(top_level_mismatch.read_text(encoding="utf-8"))
        top_data["firmware_release"] = "wrong-release"
        top_level_mismatch.write_text(json.dumps(top_data) + "\n", encoding="utf-8")

        board_mismatch = self.base / "board-release" / "campaign-summary.json"
        self._write_campaign(board_mismatch)
        board_data = json.loads(board_mismatch.read_text(encoding="utf-8"))
        board_data["boards"][0]["firmware_release"] = "wrong-release"
        board_mismatch.write_text(json.dumps(board_data) + "\n", encoding="utf-8")

        rootfs_mismatch = self.base / "rootfs" / "campaign-summary.json"
        self._write_campaign(rootfs_mismatch)
        rootfs_data = json.loads(rootfs_mismatch.read_text(encoding="utf-8"))
        rootfs_data["bundle_verification"]["artifacts_sha256"][
            "rootfs/rootfs.ext4"
        ] = "0" * 64
        rootfs_mismatch.write_text(json.dumps(rootfs_data) + "\n", encoding="utf-8")

        manifest_mismatch = self.base / "manifest" / "campaign-summary.json"
        self._write_campaign(manifest_mismatch)
        manifest_data = json.loads(manifest_mismatch.read_text(encoding="utf-8"))
        manifest_data["bundle_verification"]["manifest_sha256"] = "0" * 64
        manifest_mismatch.write_text(
            json.dumps(manifest_data) + "\n", encoding="utf-8"
        )

        top_result = self.init(
            campaign=top_level_mismatch, output=self.base / "top-record.json"
        )
        board_result = self.init(
            campaign=board_mismatch, output=self.base / "board-record.json"
        )
        rootfs_result = self.init(
            campaign=rootfs_mismatch, output=self.base / "rootfs-record.json"
        )
        manifest_result = self.init(
            campaign=manifest_mismatch, output=self.base / "manifest-record.json"
        )

        self.assertEqual(top_result.returncode, 2)
        self.assertIn("deployment.firmware_release", top_result.stderr)
        self.assertEqual(board_result.returncode, 2)
        self.assertIn("deployment.firmware_release", board_result.stderr)
        self.assertEqual(rootfs_result.returncode, 2)
        self.assertIn("staged rootfs/rootfs.ext4 SHA-256", rootfs_result.stderr)
        self.assertEqual(manifest_result.returncode, 2)
        self.assertIn("staged bundle manifest SHA-256", manifest_result.stderr)

    def test_bound_cross_release_fields_cannot_be_tampered(self) -> None:
        self.assertEqual(self.init().returncode, 0)
        original = self.load_record()
        mutations = (
            (
                "deployment release",
                lambda record: record["binding"]["deployment"].__setitem__(
                    "firmware_release", "wrong-release"
                ),
                "deployment.firmware_release",
            ),
            (
                "staged rootfs",
                lambda record: record["binding"]["campaign"][
                    "bundle_artifact_sha256"
                ].__setitem__("rootfs/rootfs.ext4", "0" * 64),
                "staged rootfs/rootfs.ext4 SHA-256",
            ),
            (
                "bundle manifest",
                lambda record: record["binding"]["campaign"].__setitem__(
                    "bundle_manifest_sha256", "0" * 64
                ),
                "staged bundle manifest SHA-256",
            ),
        )
        for label, mutate, expected in mutations:
            with self.subTest(label=label):
                record = json.loads(json.dumps(original))
                mutate(record)
                self.save_record(record)
                result = self.check()
                self.assertEqual(result.returncode, 2)
                self.assertIn(expected, result.stderr)

    def test_evidence_symlink_cannot_escape_record_directory(self) -> None:
        self.assertEqual(self.init().returncode, 0)
        record = self.fill_valid_record()
        with tempfile.TemporaryDirectory() as outside_name:
            outside = Path(outside_name) / "outside.log"
            outside.write_text("outside evidence\n", encoding="utf-8")
            escape = self.base / "evidence" / "escape.log"
            escape.symlink_to(outside)
            record["gates"][0]["evidence"] = [
                {
                    "path": str(escape.relative_to(self.base)),
                    "sha256": digest(outside),
                }
            ]
            self.save_record(record)

            result = self.check()

        self.assertEqual(result.returncode, 2)
        self.assertIn("escapes the qualification record directory", result.stderr)

    def test_deployment_log_symlink_cannot_escape_campaign_directory(self) -> None:
        with tempfile.TemporaryDirectory() as outside_name:
            outside = Path(outside_name)
            outside_log = outside / "outside.log"
            outside_log.write_text("forged external campaign log\n", encoding="utf-8")
            logs_link = self.campaign_dir / "logs"
            logs_link.symlink_to(outside, target_is_directory=True)
            summary = json.loads(self.campaign.read_text(encoding="utf-8"))
            summary["boards"][0]["log"] = "logs/outside.log"
            summary["boards"][0]["log_sha256"] = digest(outside_log)
            self.campaign.write_text(json.dumps(summary) + "\n", encoding="utf-8")

            result = self.init()

        self.assertEqual(result.returncode, 2)
        self.assertIn("deployment log escapes", result.stderr)
        self.assertFalse(self.record.exists())

    def test_invalid_thresholds_never_raise_traceback(self) -> None:
        self.assertEqual(self.init().returncode, 0)
        baseline = self.fill_valid_record()
        mutations = (
            (
                "invalid minimum",
                lambda record: record["acceptance"]["ethernet"][
                    "minimum_counter_deltas"
                ].__setitem__("rx_frames", "invalid"),
            ),
            (
                "invalid maximum",
                lambda record: record["acceptance"]["ethernet"][
                    "maximum_error_deltas"
                ].__setitem__("rx_errors", "invalid"),
            ),
            (
                "arbitrarily large integer",
                lambda record: record["acceptance"]["ethernet"][
                    "minimum_counter_deltas"
                ].__setitem__("rx_frames", 10**400),
            ),
        )
        for label, mutate in mutations:
            with self.subTest(label=label):
                record = json.loads(json.dumps(baseline))
                mutate(record)
                self.save_record(record)
                result = self.check()
                self.assertEqual(result.returncode, 2)
                self.assertNotIn("Traceback", result.stdout + result.stderr)

    def test_unhashable_status_values_are_clean_validation_errors(self) -> None:
        self.assertEqual(self.init().returncode, 0)
        baseline = self.load_record()
        cases = (
            (
                "qualification list",
                lambda record: record.__setitem__("qualification_status", []),
            ),
            (
                "qualification object",
                lambda record: record.__setitem__("qualification_status", {}),
            ),
            ("gate list", lambda record: record["gates"][0].__setitem__("status", [])),
            ("gate object", lambda record: record["gates"][0].__setitem__("status", {})),
            ("review list", lambda record: record["review"].__setitem__("status", [])),
            ("review object", lambda record: record["review"].__setitem__("status", {})),
        )
        for label, mutate in cases:
            with self.subTest(label=label):
                record = json.loads(json.dumps(baseline))
                mutate(record)
                self.save_record(record)
                result = self.check()
                self.assertEqual(result.returncode, 2)
                self.assertNotIn("Traceback", result.stdout + result.stderr)

    def test_timestamp_form_and_review_chronology_are_strict(self) -> None:
        self.assertEqual(self.init().returncode, 0)
        initial = self.load_record()
        original = json.loads(json.dumps(initial))
        initial["created_utc"] = "20260831T235900Z"
        self.save_record(initial)
        basic_result = self.check()

        self.save_record(original)
        record = self.fill_valid_record()
        record["review"]["approved_utc"] = "2000-01-01T00:00:00Z"
        self.save_record(record)
        chronology_result = self.check()

        self.assertEqual(basic_result.returncode, 2)
        self.assertIn("YYYY-MM-DDTHH:MM:SS", basic_result.stderr)
        self.assertEqual(chronology_result.returncode, 2)
        self.assertIn("must not be earlier than created_utc", chronology_result.stderr)

    def test_symlink_loop_is_clean_operational_error(self) -> None:
        loop = self.base / "loop"
        loop.symlink_to("loop")

        result = self.run_cli(
            "check",
            str(loop),
            "--campaign-summary",
            str(loop),
            "--compatibility",
            str(loop),
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("INVALID:", result.stderr)
        self.assertNotIn("Traceback", result.stdout + result.stderr)

    @unittest.skipIf(jsonschema is None, "jsonschema is not installed")
    def test_draft_2020_schema_rejects_false_qualification_claims(self) -> None:
        assert jsonschema is not None
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        validator_class = jsonschema.Draft202012Validator
        validator_class.check_schema(schema)
        validator = validator_class(
            schema, format_checker=jsonschema.FormatChecker()
        )
        example = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        self.assertEqual(list(validator.iter_errors(example)), [])

        false_claim = json.loads(json.dumps(example))
        false_claim["qualification_status"] = "PASS"
        false_claim["release_qualified"] = True
        self.assertTrue(list(validator.iter_errors(false_claim)))

        boolean_mismatch = json.loads(json.dumps(example))
        boolean_mismatch["release_qualified"] = True
        self.assertTrue(list(validator.iter_errors(boolean_mismatch)))

        self.assertEqual(self.init().returncode, 0)
        valid_record = self.fill_valid_record()
        self.assertEqual(list(validator.iter_errors(valid_record)), [])

        suppressed_claim = json.loads(json.dumps(valid_record))
        suppressed_claim["qualification_status"] = "IN_PROGRESS"
        suppressed_claim["release_qualified"] = False
        self.assertTrue(list(validator.iter_errors(suppressed_claim)))

        missing_gate_evidence = json.loads(json.dumps(valid_record))
        missing_gate_evidence["gates"][0]["evidence"] = []
        self.assertTrue(list(validator.iter_errors(missing_gate_evidence)))

        empty_observations = json.loads(json.dumps(valid_record))
        for gate in empty_observations["gates"]:
            gate["observed"] = {}
        self.assertTrue(list(validator.iter_errors(empty_observations)))

    def test_init_refuses_to_overwrite(self) -> None:
        first = self.init()
        original = self.record.read_bytes()
        second = self.init()

        self.assertEqual(first.returncode, 0)
        self.assertEqual(second.returncode, 2)
        self.assertIn("refusing to overwrite", second.stderr)
        self.assertEqual(self.record.read_bytes(), original)

    def test_init_refuses_dangling_output_symlink_without_creating_target(self) -> None:
        with tempfile.TemporaryDirectory() as outside_name:
            outside_target = Path(outside_name) / "created.json"
            self.record.symlink_to(outside_target)

            result = self.init()

            self.assertEqual(result.returncode, 2)
            self.assertIn("refusing to overwrite", result.stderr)
            self.assertTrue(self.record.is_symlink())
            self.assertFalse(outside_target.exists())

    def test_schema_and_example_match_initialized_contract(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        example = json.loads(EXAMPLE.read_text(encoding="utf-8"))

        self.assertEqual(schema["properties"]["contract"]["const"], example["contract"])
        self.assertEqual(schema["properties"]["version"]["const"], example["version"])
        self.assertEqual(example["qualification_status"], "NOT_RUN")
        self.assertFalse(example["release_qualified"])
        self.assertEqual(
            {gate["id"] for gate in example["gates"]}, set(QUALIFICATION.GATE_IDS)
        )
        errors, reasons, status, qualified = QUALIFICATION.validate_record_shape(
            example, EXAMPLE
        )
        self.assertEqual(errors, [])
        self.assertTrue(reasons)
        self.assertEqual(status, "NOT_RUN")
        self.assertFalse(qualified)

    def test_help_documents_exit_codes(self) -> None:
        result = self.run_cli("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("1 = valid but not qualified", result.stdout)
        self.assertIn("2 = invalid/error", result.stdout)


if __name__ == "__main__":
    unittest.main()
