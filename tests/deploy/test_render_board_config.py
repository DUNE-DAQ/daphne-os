from __future__ import annotations

import copy
import csv
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/deploy/render_board_config.py"
SCHEMA = ROOT / "scripts/deploy/schemas/daphne-board-config-v1.schema.json"
EXAMPLE = ROOT / "scripts/deploy/examples/daphne-board-config-v1.example.json"
RELEASE = "dual-gateware-2026.08.31-rc1"


def valid_record(*, authorized: bool = False) -> dict[str, Any]:
    return {
        "contract": "daphne.board-config",
        "version": 1,
        "asset": {
            "asset_id": "DAPHNE-EXAMPLE-001",
            "carrier_revision": "DAPHNE-V2",
        },
        "som": {
            "uuid": "00000000-0000-4000-8000-000000000001",
            "serial": "SOM-EXAMPLE-001",
            "product": "SM-K26-XCL2GC-ED",
            "factory_mac_id_0": "02:00:00:00:00:01",
        },
        "network": {
            "mac_source": "som_eeprom",
            "production_mac": "02:00:00:00:00:01",
            "ipv4_address": "192.0.2.10",
            "hostname": "daphne-example-001.example",
            "vlan": 100,
            "authorized": authorized,
        },
        "runtime": {
            "timing_endpoint": "0x001",
            "firmware_release": RELEASE,
        },
        "source": {"assignment_revision": 1, "asset_record_revision": 3},
    }


class RenderBoardConfigTests(unittest.TestCase):
    def write_record(self, directory: Path, record: object) -> tuple[Path, str]:
        path = directory / "board-config-v1.json"
        path.write_text(
            json.dumps(record, sort_keys=True, separators=(",", ":")), encoding="utf-8"
        )
        return path, hashlib.sha256(path.read_bytes()).hexdigest()

    def record_command(
        self,
        record_path: Path,
        digest: str,
        output: Path,
        *,
        allow_unapproved: bool = True,
    ) -> list[str]:
        command = [
            "python3",
            str(SCRIPT),
            "--record",
            str(record_path),
            "--record-sha256",
            digest,
            "--output",
            str(output),
            "--prefix",
            "24",
            "--gateway",
            "192.0.2.1",
            "--dns",
            "192.0.2.53",
            "--expected-firmware-release",
            RELEASE,
        ]
        if allow_unapproved:
            command.append("--allow-unapproved")
        return command

    def run_record(
        self,
        directory: Path,
        record: object,
        *,
        allow_unapproved: bool = True,
    ) -> tuple[subprocess.CompletedProcess[str], Path]:
        record_path, digest = self.write_record(directory, record)
        output = directory / "rendered"
        result = subprocess.run(
            self.record_command(
                record_path, digest, output, allow_unapproved=allow_unapproved
            ),
            check=False,
            capture_output=True,
            text=True,
        )
        return result, output

    def assert_rejected(self, record: object, message: str) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result, output = self.run_record(Path(tmp), record)
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn(message, result.stderr)
            self.assertFalse(output.exists(), "invalid input created partial output")

    def test_render_versioned_board_config_with_checksum(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            record_path, digest = self.write_record(tmp_path, valid_record())
            output = tmp_path / "rendered"
            subprocess.run(
                self.record_command(record_path, digest, output),
                check=True,
                capture_output=True,
                text=True,
            )
            combined = "\n".join(path.read_text() for path in output.iterdir())
            self.assertIn(f"BOARD_CONFIG_SHA256={digest}", combined)
            self.assertIn(f"FIRMWARE_RELEASE={RELEASE}", combined)
            self.assertIn("Address=192.0.2.10/24", combined)
            self.assertNotIn("MACAddress=", combined)
            self.assertNotIn("ethaddr=", combined)
            self.assertEqual(
                sorted(path.name for path in output.iterdir()),
                [
                    "20-daphne-mgmt.network",
                    "21-daphne-unused.network",
                    "daphne-board.env",
                    "hostname",
                    "manifest.env",
                ],
            )

    def test_checked_in_schema_and_example_match_renderer(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        example = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(set(schema["required"]), set(example))
        for section in ("asset", "som", "network", "runtime", "source"):
            section_schema = schema["properties"][section]
            self.assertEqual(section_schema["type"], "object")
            self.assertFalse(section_schema["additionalProperties"])
            self.assertEqual(set(section_schema["required"]), set(example[section]))
            self.assertEqual(set(section_schema["properties"]), set(example[section]))
        self.assertEqual(
            schema["properties"]["network"]["properties"]["authorized"],
            {"type": "boolean"},
        )
        self.assertEqual(
            schema["properties"]["network"]["properties"]["ipv4_address"]["format"],
            "ipv4",
        )
        self.assertEqual(
            schema["properties"]["som"]["properties"]["uuid"]["format"], "uuid"
        )
        for field in ("assignment_revision", "asset_record_revision"):
            revision_schema = schema["properties"]["source"]["properties"][field]
            self.assertEqual(revision_schema["type"], "integer")
            self.assertEqual(revision_schema["minimum"], 1)
        self.assertFalse(example["network"]["authorized"])
        self.assertEqual(example["network"]["ipv4_address"], "192.0.2.10")
        self.assertEqual(example["runtime"]["firmware_release"], RELEASE)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            record_path = tmp_path / "example.json"
            record_path.write_bytes(EXAMPLE.read_bytes())
            digest = hashlib.sha256(record_path.read_bytes()).hexdigest()
            output = tmp_path / "rendered"
            subprocess.run(
                self.record_command(record_path, digest, output),
                check=True,
                capture_output=True,
                text=True,
            )

    def test_string_false_is_not_network_authorization(self) -> None:
        record = valid_record()
        record["network"]["authorized"] = "false"
        self.assert_rejected(record, "network.authorized must be a boolean")

    def test_contract_and_version_types_are_strict(self) -> None:
        cases = [
            ("wrong contract type", "contract", 1, "contract must be a nonempty string"),
            ("boolean version", "version", True, "unsupported board configuration version"),
            ("floating version", "version", 1.0, "unsupported board configuration version"),
        ]
        for name, field, value, message in cases:
            with self.subTest(name=name):
                record = valid_record()
                record[field] = value
                self.assert_rejected(record, message)

    def test_unapproved_record_requires_explicit_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result, output = self.run_record(
                Path(tmp), valid_record(), allow_unapproved=False
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("network admission is not approved", result.stderr)
            self.assertFalse(output.exists())

    def test_record_checksum_is_required_and_must_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            path, digest = self.write_record(tmp_path, valid_record())
            output = tmp_path / "rendered"
            command = self.record_command(path, digest, output)
            sha_index = command.index("--record-sha256")
            del command[sha_index : sha_index + 2]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--record-sha256 is required", result.stderr)
            self.assertFalse(output.exists())

            command = self.record_command(path, "0" * 64, output)
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("checksum mismatch", result.stderr)
            self.assertFalse(output.exists())

    def test_prefix_and_expected_release_are_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            path, digest = self.write_record(tmp_path, valid_record())
            for option in ("--prefix", "--expected-firmware-release"):
                with self.subTest(option=option):
                    output = tmp_path / option.removeprefix("--")
                    command = self.record_command(path, digest, output)
                    index = command.index(option)
                    del command[index : index + 2]
                    result = subprocess.run(command, capture_output=True, text=True)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("required", result.stderr)
                    self.assertFalse(output.exists())

    def test_record_firmware_release_must_match_expected_release(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            path, digest = self.write_record(tmp_path, valid_record())
            output = tmp_path / "rendered"
            command = self.record_command(path, digest, output)
            index = command.index("--expected-firmware-release") + 1
            command[index] = "another-release"
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("record firmware_release mismatch", result.stderr)
            self.assertFalse(output.exists())

    def test_required_nested_objects_fields_and_no_unknown_fields(self) -> None:
        cases: list[tuple[str, dict[str, Any], str]] = []
        missing_object = valid_record()
        del missing_object["source"]
        cases.append(("missing object", missing_object, "missing required field(s): source"))
        wrong_object = valid_record()
        wrong_object["network"] = []
        cases.append(("wrong object type", wrong_object, "network must be an object"))
        missing_field = valid_record()
        del missing_field["som"]["serial"]
        cases.append(("missing nested field", missing_field, "som is missing required field(s): serial"))
        extra_root = valid_record()
        extra_root["approval"] = True
        cases.append(("extra root", extra_root, "unsupported field(s): approval"))
        extra_nested = valid_record()
        extra_nested["network"]["prefix"] = 24
        cases.append(("extra nested", extra_nested, "network contains unsupported field(s): prefix"))
        for name, record, message in cases:
            with self.subTest(name=name):
                self.assert_rejected(record, message)

    def test_every_free_string_field_must_be_nonempty(self) -> None:
        paths = [
            ("asset", "asset_id"),
            ("asset", "carrier_revision"),
            ("som", "serial"),
            ("som", "product"),
            ("network", "hostname"),
            ("runtime", "timing_endpoint"),
            ("runtime", "firmware_release"),
        ]
        for section, field in paths:
            with self.subTest(path=f"{section}.{field}"):
                record = valid_record()
                record[section][field] = " \t"
                self.assert_rejected(record, f"{section}.{field} must be a nonempty string")

    def test_uuid_ipv4_and_mac_fields_are_validated(self) -> None:
        cases = [
            ("noncanonical uuid", ("som", "uuid"), "00000000-0000-4000-8000-00000000000A", "canonical lowercase UUID"),
            ("invalid uuid", ("som", "uuid"), "not-a-uuid", "must be a valid UUID"),
            ("ipv6", ("network", "ipv4_address"), "2001:db8::1", "must be a valid IPv4"),
            ("invalid IPv4", ("network", "ipv4_address"), "192.0.2.999", "must be a valid IPv4"),
            ("factory MAC", ("som", "factory_mac_id_0"), "02-00-00-00-00-01", "48-bit MAC"),
            ("production MAC", ("network", "production_mac"), "02:00:00:00:00", "48-bit MAC"),
        ]
        for name, path, value, message in cases:
            with self.subTest(name=name):
                record = valid_record()
                record[path[0]][path[1]] = value
                self.assert_rejected(record, message)

    def test_source_revisions_are_positive_non_boolean_integers(self) -> None:
        for field in ("assignment_revision", "asset_record_revision"):
            for value in (True, False, 0, -1, 1.0, "1"):
                with self.subTest(field=field, value=value):
                    record = valid_record()
                    record["source"][field] = value
                    self.assert_rejected(record, f"source.{field} must be a positive integer")

    def test_vlan_is_null_or_an_integer_from_one_through_4094(self) -> None:
        for value in (True, False, 0, 4095, -1, 100.0, "100"):
            with self.subTest(value=value):
                record = valid_record()
                record["network"]["vlan"] = value
                self.assert_rejected(record, "network.vlan must be null or an integer")
        with tempfile.TemporaryDirectory() as tmp:
            record = valid_record()
            record["network"]["vlan"] = None
            result, output = self.run_record(Path(tmp), record)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(output.is_dir())

    def test_invalid_input_does_not_modify_existing_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            record = valid_record()
            record["network"]["hostname"] = "unsafe hostname"
            record_path, digest = self.write_record(tmp_path, record)
            output = tmp_path / "rendered"
            output.mkdir()
            sentinel = output / "keep.txt"
            sentinel.write_text("unchanged\n", encoding="utf-8")
            result = subprocess.run(
                self.record_command(record_path, digest, output),
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "unchanged\n")
            self.assertEqual(list(output.iterdir()), [sentinel])

    def test_legacy_inventory_requires_matching_firmware_release(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            inventory = tmp_path / "inventory.csv"
            row = {
                "asset_id": "DAPHNE-EXAMPLE-001",
                "som_uuid": "00000000-0000-4000-8000-000000000001",
                "factory_mac_id_0": "02:00:00:00:00:01",
                "mac_source": "som_eeprom",
                "production_mac": "02:00:00:00:00:01",
                "ipv4_address": "192.0.2.10",
                "hostname": "daphne-example-001.example",
                "timing_endpoint": "0x001",
                "firmware_release": RELEASE,
                "network_admission_approved": "1",
            }
            with inventory.open("w", newline="", encoding="utf-8") as target:
                writer = csv.DictWriter(target, fieldnames=list(row))
                writer.writeheader()
                writer.writerow(row)
            output = tmp_path / "rendered"
            command = [
                "python3", str(SCRIPT), "--inventory", str(inventory),
                "--asset", row["asset_id"], "--output", str(output),
                "--prefix", "24", "--gateway", "192.0.2.1",
                "--dns", "192.0.2.53", "--expected-firmware-release", RELEASE,
            ]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(f"FIRMWARE_RELEASE={RELEASE}", (output / "manifest.env").read_text())

            mismatch_output = tmp_path / "mismatch"
            mismatch_command = copy.copy(command)
            mismatch_command[mismatch_command.index(str(output))] = str(mismatch_output)
            mismatch_command[-1] = "another-release"
            result = subprocess.run(mismatch_command, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("inventory firmware_release mismatch", result.stderr)
            self.assertFalse(mismatch_output.exists())


if __name__ == "__main__":
    unittest.main()
