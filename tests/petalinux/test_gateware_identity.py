"""OS consumer of sealed build identity; synthetic artifacts, not routed evidence."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("os_gateware_identity", ROOT / "scripts/petalinux/gateware_identity.py")
identity = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(identity)


class GatewareIdentityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="daphne-os-identity-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source with spaces.vhd"
        self.record = self.root / "input.json"
        self.sealed = self.root / "sealed.json"
        self.report = self.root / identity.REPORT_NAME
        self.make_source()
        self.make_report()

    def make_source(self, abi=0x20002, variant=1):
        self.variant = variant
        self.source.write_text("\n".join(f'constant {name}: std_logic_vector(31 downto 0) := X"{value:08X}";'
            for name, value in (("FW_ID_MAGIC_C", 0x44415048), ("FW_ABI_VERSION_C", abi), ("FW_VARIANT_ID_C", variant))))
        prefix = "daphne_selftrigger" if variant == 1 else "daphne_fullstream"
        self.binary, self.xsa = [self.root / f"{prefix}_abcdef1.{suffix}" for suffix in ("bin", "xsa")]
        self.binary.write_bytes(b"synthetic binary, not FPGA firmware")
        self.xsa.write_bytes(b"synthetic XSA, not a hardware platform")

    def make_report(self, abi=0x20002):
        mailboxes = [("local_snapshot", 65), ("external_snapshot", 65)]
        category = "timestamp"
        if abi == 0x20002:
            mailboxes.append(("protocol_snapshot", 40))
            category = "diagnostic"
        self.report.write_text(f"Native {category} payload timing: per-bit routed checks\n" + "".join(
            f"ep/ep_axi_inst/{mailbox}/destination_data_reg[{bit}] requirement_ns=10.0 slack_ns=1.0\n"
            for mailbox, width in mailboxes for bit in range(width)))

    def capture(self):
        identity.capture(self.source, "abcdef1", "2026.1", self.record, "32'h0abcdef1")

    def seal(self):
        identity.seal(self.record, self.source, self.binary, self.xsa, self.report, self.sealed)

    def verify(self):
        return identity.verify(self.sealed, self.binary, self.report, "abcdef1", self.variant, self.xsa)

    def test_each_known_abi_and_variant_roundtrips(self):
        for abi in (0x20000, 0x20001, 0x20002):
            for variant in (1, 2):
                with self.subTest(abi=abi, variant=variant):
                    self.record.unlink(missing_ok=True)
                    self.sealed.unlink(missing_ok=True)
                    self.make_source(abi, variant)
                    self.make_report(abi)
                    self.capture()
                    self.seal()
                    self.assertEqual(self.verify(), abi & 0xffff)
                    self.assertNotIn(str(self.root), self.sealed.read_text())

    def test_abi21_and_abi22_reports_cannot_qualify_each_other(self):
        for abi, other in ((0x20001, 0x20002), (0x20002, 0x20001)):
            self.make_report(abi)
            identity.check_report(self.report, abi)
            with self.assertRaises(ValueError):
                identity.check_report(self.report, other)
        with self.assertRaises(ValueError):
            identity.check_report(self.report, 0x20003)

    def test_every_payload_bit_is_required(self):
        original = self.report.read_text().splitlines()
        for index in range(1, 171):
            with self.subTest(missing_row=index), self.assertRaises(ValueError):
                self.report.write_text("\n".join(original[:index] + original[index + 1:]))
                identity.check_report(self.report, 0x20002)

    def test_bad_population_header_and_timing_rejected(self):
        original = self.report.read_text()
        corruptions = [
            original.replace("diagnostic payload", "timestamp payload"),
            original.replace("protocol_snapshot/destination_data_reg[39]", "protocol_snapshot/destination_data_reg[40]"),
            original.replace("protocol_snapshot/destination_data_reg[39]", "protocol_snapshot/destination_data_reg[38]"),
            original.replace("protocol_snapshot", "external_snapshot"),
            original.replace("ep/ep_axi_inst/", "other/parent/", 1),
        ]
        for value in ("nan", "inf", "-0.1"):
            corruptions.append(original.replace("slack_ns=1.0", "slack_ns=" + value, 1))
        for value in ("nan", "inf", "0", "-1"):
            corruptions.append(original.replace("requirement_ns=10.0", "requirement_ns=" + value, 1))
        for bad in corruptions:
            self.report.write_text(bad)
            with self.assertRaises(ValueError):
                identity.check_report(self.report, 0x20002)

    def test_unknown_abi_variant_generic_and_tool_refused_without_output(self):
        for abi, variant, word, version in ((0x20003, 1, "0x0abcdef1", "2026.1"),
                (0x20002, 3, "0x0abcdef1", "2026.1"), (0x20002, 1, "0x0abcdef2", "2026.1"),
                (0x20002, 1, "0x1abcdef1", "2026.1"), (0x20002, 1, "0x0abcdef1", "2024.1")):
            self.make_source(abi, variant)
            with self.assertRaises(ValueError):
                identity.capture(self.source, "abcdef1", version, self.record, word)
            self.assertFalse(self.record.exists())

    def test_artifact_and_selection_hashes_are_not_labels(self):
        self.capture()
        self.seal()
        for path in (self.binary, self.xsa, self.report):
            original = path.read_bytes()
            path.write_bytes(original + b"changed")
            with self.assertRaises(ValueError):
                self.verify()
            path.write_bytes(original)
        with self.assertRaises(ValueError):
            identity.verify(self.sealed, self.binary, self.report, "abcdef2", 1)
        with self.assertRaises(ValueError):
            identity.verify(self.sealed, self.binary, self.report, "abcdef1", 2)

    def test_source_change_and_missing_report_refuse_sealing(self):
        self.capture()
        original = self.source.read_text()
        self.source.write_text(original + "\n-- changed\n")
        with self.assertRaises(ValueError):
            self.seal()
        self.assertFalse(self.sealed.exists())
        self.source.write_text(original)
        self.report.unlink()
        with self.assertRaises(OSError):
            self.seal()
        self.assertFalse(self.sealed.exists())

    def test_metadata_types_duplicates_and_extra_keys_refused(self):
        self.capture()
        original = self.record.read_text()
        for changed in (original.replace('"abi": 131074,', '"abi": 131074, "abi": 131074,'),
                        original.replace('"abi": 131074,', '"abi": true,'),
                        original.replace('"schema_version": 1,', '"schema_version": true,')):
            self.record.write_text(changed)
            with self.assertRaises(ValueError):
                identity.read_record(self.record)
        record = json.loads(original)
        record['override_abi'] = 131072
        self.record.write_text(json.dumps(record))
        with self.assertRaises(ValueError):
            identity.read_record(self.record)

    def test_output_is_exclusive_create(self):
        self.capture()
        with self.assertRaises(FileExistsError):
            self.capture()
        self.seal()
        with self.assertRaises(FileExistsError):
            self.seal()


if __name__ == "__main__":
    unittest.main()
