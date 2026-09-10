import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import daphneV3_high_level_confs_pb2 as h
from verify_fpga_health import check_status
from verify_board_identity import same_gateware_image
from test_native_timestamp import native_fixture
from test_protocol_errors import protocol_fixture


class FpgaHealthTests(unittest.TestCase):
    def fixture(self):
        s = h.SystemStatusSnapshot(success=True)
        s.fpga_programming.CopyFrom(h.FpgaProgrammingStatus(
            manager_quality=h.MEASUREMENT_GOOD, manager_state="operating", manager_observed_monotonic_ns=160,
            configuration_quality=h.MEASUREMENT_GOOD, configuration_status_raw=0x16907ffc,
            configuration_observed_monotonic_ns=180, acquisition_started_monotonic_ns=150, source="source", message="scope"))
        s.gateware_identity.CopyFrom(h.GatewareIdentityStatus(magic=0x44415048, abi=0x20000, variant=1,
            build_id=0x3f17f1b, quality=h.MEASUREMENT_GOOD, matches_admitted_profile=True,
            observed_monotonic_ns=190, acquisition_started_monotonic_ns=100))
        s.endpoint.CopyFrom(h.EndpointStatus(observation_quality=h.MEASUREMENT_GOOD, observed_monotonic_ns=140,
                                            endpoint_clock_status_raw=3, endpoint_status_raw=6))
        s.server_state.CopyFrom(h.ServerState(success=True, observed_monotonic_ns=195,
            applied_configuration_valid=True, applied_configuration_hash="a" * 64))
        s.board_identity.binding_state = h.IDENTITY_BINDING_MATCH
        s.board_identity.observed_monotonic_ns = 90
        s.board_identity.management.CopyFrom(h.ManagementNetworkObservation(quality=h.MEASUREMENT_GOOD,
            present=True, interface_up=True, running_flag=True, observed_monotonic_ns=80,
            mac_address="secret-test-only"))
        s.temperatures.add(name="Temp_PL", temperature_c=40, valid=True, quality=h.MEASUREMENT_GOOD,
                           observed_monotonic_ns=192).alarm.state = h.TEMPERATURE_ALARM_GOOD
        s.fpga_health.CopyFrom(h.FpgaHealthAssessment(state=h.FPGA_HEALTH_NOT_READY, scope="external timing",
            message="scope", evaluated_monotonic_ns=200, maximum_observation_age_ms=5000))
        for name in ("kernel_programming", "configuration_error_flags", "configuration_startup", "fabric_clock_locks",
                     "admitted_gateware", "timing_clock_locks", "timing_resets_released", "front_end_configuration",
                     "pl_die_temperature", "management_interface", "management_identity"):
            s.fpga_health.checks.add(name=name, state=h.HEALTH_CHECK_PASS, message="scope")
        s.fpga_health.checks.add(name="external_timing_ready", state=h.HEALTH_CHECK_FAIL, message="bench")
        for name in ("live_timestamp_progress", "hermes_data_path", "external_reset_epoch"):
            s.fpga_health.checks.add(name=name, state=h.HEALTH_CHECK_UNKNOWN, message="unavailable")
        return s

    def check(self, status):
        return check_status(status, h, 0x3f17f1b, 1, require_bench=True)

    def test_expected_bench_is_not_healthy_and_output_redacted(self):
        report = self.check(self.fixture())
        self.assertEqual(report["state"], "FPGA_HEALTH_NOT_READY")
        self.assertNotIn("secret-test-only", str(report))

    def test_false_healthy_or_missing_checks_rejected(self):
        for mutate in (lambda s: setattr(s.fpga_health, "state", h.FPGA_HEALTH_OBSERVED_OK),
                       lambda s: s.fpga_health.checks.pop(),
                       lambda s: setattr(s.fpga_health.checks[0], "state", h.HEALTH_CHECK_UNKNOWN),
                       lambda s: setattr(s.endpoint, "ready", True),
                       lambda s: setattr(s.fpga_health.checks[0], "name", "private-injected-name")):
            s = self.fixture()
            mutate(s)
            with self.assertRaises(RuntimeError):
                self.check(s)

    def test_raw_configuration_bits_checked_independently(self):
        for bit in (29, 27, 22, 17, 16, 15, 0):
            s = self.fixture()
            s.fpga_programming.configuration_status_raw |= 1 << bit
            with self.assertRaises(RuntimeError):
                self.check(s)
        for bit in (14, 13, 12, 11, 7, 6, 5, 4, 2):
            s = self.fixture()
            s.fpga_programming.configuration_status_raw &= ~(1 << bit)
            with self.assertRaises(RuntimeError):
                self.check(s)

    def test_missing_stale_or_out_of_order_samples_rejected(self):
        for mutate in (lambda s: s.fpga_programming.ClearField("configuration_status_raw"),
                       lambda s: setattr(s.gateware_identity, "observed_monotonic_ns", 120),
                       lambda s: setattr(s.fpga_health, "evaluated_monotonic_ns", 6_000_000_000),
                       lambda s: setattr(s.board_identity.management, "interface_up", False),
                       lambda s: setattr(s.server_state, "applied_configuration_valid", False)):
            s = self.fixture()
            mutate(s)
            with self.assertRaises(RuntimeError):
                self.check(s)

    def test_observation_times_are_not_image_identity(self):
        first = self.fixture().gateware_identity
        second = copy.deepcopy(first)
        second.observed_monotonic_ns += 1000
        self.assertTrue(same_gateware_image(first, second))
        second.build_id += 1
        self.assertFalse(same_gateware_image(first, second))

    def test_abi21_bench_progress_and_exact_admission(self):
        s = self.fixture()
        native = native_fixture()
        s.gateware_identity.abi = 0x20001
        s.endpoint.live_timestamp.CopyFrom(native.endpoint.live_timestamp)
        s.endpoint.live_timestamp_quality = h.MEASUREMENT_GOOD
        for check in s.fpga_health.checks:
            if check.name == "live_timestamp_progress":
                check.state = h.HEALTH_CHECK_PASS
        report = check_status(s, h, 0x3f17f1b, 1, require_bench=True, expected_abi=0x20001)
        self.assertEqual(report["checks"]["live_timestamp_progress"], "HEALTH_CHECK_PASS")
        self.assertEqual(report["state"], "FPGA_HEALTH_NOT_READY")
        self.assertNotIn("secret-test-only", str(report))
        with self.assertRaises(RuntimeError):
            self.check(s)  # Default qualification stays at exact ABI 2.0.
        for check in s.fpga_health.checks:
            if check.name == "live_timestamp_progress":
                check.state = h.HEALTH_CHECK_UNKNOWN
        with self.assertRaises(RuntimeError):
            check_status(s, h, 0x3f17f1b, 1, expected_abi=0x20001)

    def test_abi22_reports_history_without_inventing_current_failure(self):
        for count, detail in ((0, 0), (7, 1), (0xffffffff, 255)):
            s = self.fixture()
            s.gateware_identity.abi = 0x20002
            s.endpoint.live_timestamp.CopyFrom(native_fixture().endpoint.live_timestamp)
            s.endpoint.live_timestamp_quality = h.MEASUREMENT_GOOD
            for check in s.fpga_health.checks:
                if check.name == "live_timestamp_progress":
                    check.state = h.HEALTH_CHECK_PASS
            live = s.endpoint.protocol_errors
            live.CopyFrom(protocol_fixture(count, detail).endpoint.protocol_errors)
            live.acquisition_started_monotonic_ns = live.observed_monotonic_ns = 149
            live.attempts[0].acquisition_started_monotonic_ns = live.attempts[0].observed_monotonic_ns = 149
            report = check_status(s, h, 0x3f17f1b, 1, require_bench=True, expected_abi=0x20002)
            self.assertEqual(report["protocol_errors"]["count"], count)
            self.assertEqual(len(report["checks"]), 15)
            self.assertEqual(report["checks"]["live_timestamp_progress"], "HEALTH_CHECK_PASS")
            self.assertNotIn("secret-test-only", str(report))
            with self.assertRaises(RuntimeError):
                self.check(s)
            live.count += 1 if count == 0 else -1
            with self.assertRaises(RuntimeError):
                check_status(s, h, 0x3f17f1b, 1, expected_abi=0x20002)


if __name__ == "__main__":
    unittest.main()
