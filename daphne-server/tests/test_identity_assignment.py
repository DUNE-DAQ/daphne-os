import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import stat
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import daphneV3_high_level_confs_pb2 as h
import extract_oks_identity as extraction
import prepare_identity_assignment as prepare
import test_oks_identity as fixtures
from verify_board_identity import check_status


class IdentityAssignmentTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.OksIdentityTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.review = self.fixture.extract()
        extraction.verify_target(self.review, "expected.example", lambda host: "192.0.2.20")
        self.review_file = self.root / "review.json"
        self.review_file.write_text(json.dumps(self.review))
        self.link = self.root / "10-approved.link"
        self.link.write_text("[Match]\nPath=platform-ff0b0000.ethernet\n[Link]\nMACAddress=02:aa:bb:00:00:15\nMACAddressPolicy=none\n")
        self.network = self.root / "20-approved.network"
        self.network.write_text("[Match]\nName=eth0\n[Network]\nDHCP=no\nAddress=192.0.2.20/24\nDNS=192.0.2.1\nDNS=192.0.2.2\n")

    def build(self):
        review = prepare.read_review(self.review_file, self.root)
        return prepare.prepare(review, self.link, self.network, "eth0", h)

    def test_assignments_not_baseline_or_guessed_identity(self):
        value = self.build()
        self.assertEqual(value.assignments.management_address.value, "board.example")
        self.assertFalse(value.assignments.management_mac_address.HasField("value"))
        self.assertFalse(value.assignments.timing_endpoint_address.HasField("value"))
        self.assertEqual(value.binding.expected_mac_address, "02:aa:bb:00:00:15")
        self.assertEqual(list(value.binding.expected_ipv4_cidrs), ["192.0.2.20/24"])
        self.assertEqual(value.binding.controller_node, "ethernet@ff0b0000")
        self.assertEqual(value.assignments.crate_id.source.object_id, "board")
        self.assertFalse(value.assignments.hermes_interfaces[0].physical_connector.HasField("value"))
        self.assertEqual(len(value.assignments.hermes_interfaces), 1)
        self.assertEqual(list(value.assignments.hermes_interfaces[0].ip_addresses.values), ["192.0.2.15"])

    def test_review_mutation_or_stale_source_rejected(self):
        for mutate in (
            lambda value: value["placement"]["crate_id"].update(value=7),
            lambda value: value.update(unknown="not silently ignored"),
            lambda value: value["target_check"].update(status="not_checked"),
            lambda value: value["target_check"].update(observed_host_unix_ns=0),
        ):
            changed = copy.deepcopy(self.review)
            mutate(changed)
            self.review_file.write_text(json.dumps(changed))
            with self.assertRaises(extraction.IdentityError):
                self.build()
        self.review_file.write_text(json.dumps(self.review))
        with (self.root / self.fixture.files[0]).open("a") as output:
            output.write("\n")
        with self.assertRaises(extraction.IdentityError):
            self.build()

    def test_duplicate_review_keys_rejected(self):
        self.review_file.write_text('{"secret":1,"secret":2}')
        with self.assertRaises(extraction.IdentityError):
            self.build()

    def test_inconsistent_network_binding_rejected(self):
        original = self.network.read_text()
        for changed in (
            original.replace("eth0", "eth1"),
            original.replace("DHCP=no", "DHCP=yes"),
            original.replace("192.0.2.20/24", "192.0.2.21/24"),
            original.replace("192.0.2.20/24", "192.0.2.20/33"),
            original + "Address=192.0.2.20/24\n",
        ):
            self.network.write_text(changed)
            with self.assertRaises(extraction.IdentityError):
                self.build()

    def test_inconsistent_link_binding_rejected(self):
        original = self.link.read_text()
        for changed in (
            original.replace("platform-ff0b0000.ethernet", "*"),
            original.replace("MACAddressPolicy=none", "MACAddressPolicy=random"),
            original.replace("02:aa:bb:00:00:15", "01:aa:bb:00:00:15"),
            original + "MACAddress=02:aa:bb:00:00:15\n",
        ):
            self.link.write_text(changed)
            with self.assertRaises(extraction.IdentityError):
                self.build()

    def test_private_output_no_overwrite(self):
        file = self.root / "identity.pb"
        digest = prepare.write_artifact(file, self.build())
        self.assertEqual(len(digest), 64)
        self.assertEqual(stat.S_IMODE(file.stat().st_mode), 0o600)
        before = file.read_bytes()
        self.assertEqual(h.BoardIdentityAssignmentFile.FromString(before), self.build())
        with self.assertRaises(FileExistsError):
            prepare.write_artifact(file, self.build())
        self.assertEqual(file.read_bytes(), before)

    def status(self, details=True):
        artifact = self.build()
        status = h.BoardIdentityStatus(assignment_configured=True, assignment_artifact_sha256="a" * 64,
                                       source_revision_sha256=artifact.assignments.source_revision_sha256,
                                       binding_state=h.IDENTITY_BINDING_MATCH, message="Scope", details_included=details,
                                       observed_monotonic_ns=200)
        if details:
            status.assignments.CopyFrom(artifact.assignments)
            status.binding.CopyFrom(artifact.binding)
            status.management.CopyFrom(h.ManagementNetworkObservation(
                quality=h.MEASUREMENT_GOOD, present=True, interface_name="eth0", controller_node="ethernet@ff0b0000",
                mac_address=artifact.binding.expected_mac_address, ipv4_cidrs=artifact.binding.expected_ipv4_cidrs,
                interface_index=2, flags_raw=65, interface_up=True, running_flag=True,
                acquisition_started_monotonic_ns=1, observed_monotonic_ns=100, observed_host_unix_ns=1))
        return status, artifact

    def test_client_checks_exact_assignment_and_presence(self):
        status, artifact = self.status()
        check_status(status, artifact, "a" * 64, h, True)
        for mutate in (
            lambda s: setattr(s.assignments.crate_id, "value", 7),
            lambda s: setattr(s.assignments.timing_endpoint_address, "value", 0),
            lambda s: s.management.ClearField("mac_address"),
            lambda s: s.management.ClearField("interface_up"),
            lambda s: setattr(s.management, "flags_raw", 0),
            lambda s: setattr(s.management, "observed_monotonic_ns", 201),
            lambda s: setattr(s, "binding_state", h.IDENTITY_BINDING_MISMATCH),
            lambda s: setattr(s, "assignment_artifact_sha256", "b" * 64),
        ):
            wrong = h.BoardIdentityStatus()
            wrong.CopyFrom(status)
            mutate(wrong)
            with self.assertRaises(RuntimeError):
                check_status(wrong, artifact, "a" * 64, h, True)

    def test_client_checks_default_redaction(self):
        status, artifact = self.status(False)
        check_status(status, artifact, "a" * 64, h, False)
        status.message = artifact.binding.expected_mac_address
        with self.assertRaises(RuntimeError):
            check_status(status, artifact, "a" * 64, h, False)
        status.message = "Scope"
        status.assignments.CopyFrom(artifact.assignments)
        with self.assertRaises(RuntimeError):
            check_status(status, artifact, "a" * 64, h, False)


if __name__ == "__main__":
    unittest.main()
