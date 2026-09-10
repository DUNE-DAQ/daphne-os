"""Independent health derivation; no hardware or SC policy changes."""
import unittest

import daphneV3_high_level_confs_pb2 as h
from test_afe_global import fixture, FIELDS
from afe_global import reset_health_state


class AfeResetHealthTests(unittest.TestCase):
    def state(self, status, now=200):
        # Check the actual protobuf wire representation, including false presence.
        return reset_health_state(h.SystemStatusSnapshot.FromString(status.SerializeToString()), h, now)

    def test_all_profiles_bits_and_bias_values(self):
        for abi in (0x20000, 0x20001, 0x20002):
            for variant in (1, 2):
                for word in range(32):
                    for bias in (0, 1):
                        s = fixture(word, bias)
                        s.gateware_identity.abi, s.gateware_identity.variant = abi, variant
                        self.assertEqual(self.state(s), h.HEALTH_CHECK_FAIL if word & 1 else h.HEALTH_CHECK_PASS)

    def test_absence_corruption_and_quality_are_unknown(self):
        self.assertEqual(self.state(h.SystemStatusSnapshot()), h.HEALTH_CHECK_UNKNOWN)
        for field in FIELDS + ("global_control_raw", "bias_enable_raw"):
            s = fixture(); s.afe_global.ClearField(field)
            self.assertEqual(self.state(s), h.HEALTH_CHECK_UNKNOWN)
        for field, value in (("quality", h.MEASUREMENT_ERROR), ("quality", h.MEASUREMENT_STALE),
                             ("quality", h.MEASUREMENT_UNAVAILABLE), ("quality", 99),
                             ("reset_asserted", True), ("global_control_raw", 32), ("bias_enable_raw", 2),
                             ("identity_bracket_verified", False), ("source", "private-invalid-source"),
                             ("message", ""), ("maximum_acquisition_ms", 101)):
            s = fixture(); setattr(s.afe_global, field, value)
            self.assertEqual(self.state(s), h.HEALTH_CHECK_UNKNOWN)

    def test_programming_identity_and_order_are_required(self):
        for field, value in (("magic", 0), ("abi", 0x20003), ("variant", 3), ("build_id", 0xf1234567),
                             ("quality", h.MEASUREMENT_ERROR), ("matches_admitted_profile", False),
                             ("acquisition_started_monotonic_ns", 0), ("acquisition_started_monotonic_ns", 121),
                             ("observed_monotonic_ns", 201)):
            s = fixture(); setattr(s.gateware_identity, field, value)
            self.assertEqual(self.state(s), h.HEALTH_CHECK_UNKNOWN)
        for field, value in (("manager_state", "write"), ("manager_error_raw", 0),
                             ("manager_quality", h.MEASUREMENT_ERROR), ("configuration_quality", h.MEASUREMENT_ERROR),
                             ("configuration_status_raw", 0), ("configuration_status_raw", 0x16907ffd),
                             ("acquisition_started_monotonic_ns", 159), ("manager_observed_monotonic_ns", 169),
                             ("configuration_observed_monotonic_ns", 174), ("configuration_observed_monotonic_ns", 191)):
            s = fixture(); setattr(s.fpga_programming, field, value)
            self.assertEqual(self.state(s), h.HEALTH_CHECK_UNKNOWN)
        for field in ("gateware_identity", "fpga_programming"):
            s = fixture(); s.ClearField(field)
            self.assertEqual(self.state(s), h.HEALTH_CHECK_UNKNOWN)
        s = fixture(); s.success = False
        self.assertEqual(self.state(s), h.HEALTH_CHECK_UNKNOWN)

    def test_freshness_and_acquisition_boundaries(self):
        self.assertEqual(self.state(fixture(), 5_000_000_160), h.HEALTH_CHECK_PASS)
        self.assertEqual(self.state(fixture(), 5_000_000_161), h.HEALTH_CHECK_UNKNOWN)
        for field, value in (("acquisition_started_monotonic_ns", 0), ("acquisition_started_monotonic_ns", 99),
                             ("acquisition_started_monotonic_ns", 161), ("observed_monotonic_ns", 119),
                             ("observed_monotonic_ns", 171)):
            s = fixture(); setattr(s.afe_global, field, value)
            self.assertEqual(self.state(s), h.HEALTH_CHECK_UNKNOWN)
        s = fixture()
        s.afe_global.observed_monotonic_ns = 100_000_120
        s.fpga_programming.acquisition_started_monotonic_ns = 100_000_130
        s.fpga_programming.manager_observed_monotonic_ns = 100_000_140
        s.fpga_programming.configuration_observed_monotonic_ns = 100_000_150
        s.gateware_identity.observed_monotonic_ns = 100_000_160
        self.assertEqual(self.state(s, 100_000_200), h.HEALTH_CHECK_PASS)
        s.afe_global.observed_monotonic_ns += 1
        self.assertEqual(self.state(s, 100_000_200), h.HEALTH_CHECK_UNKNOWN)


if __name__ == "__main__":
    unittest.main()
