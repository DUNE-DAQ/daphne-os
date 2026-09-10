"""Independent wire/quality/admission tests; matching generated bindings required."""
from pathlib import Path
import sys
import unittest
import daphneV3_high_level_confs_pb2 as h
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from afe_global import check_afe_global, FIELDS, SOURCE


def fixture(word=0, enable=0):
    s = h.SystemStatusSnapshot(success=True)
    s.gateware_identity.CopyFrom(h.GatewareIdentityStatus(magic=0x44415048, abi=0x20000, variant=1,
        build_id=0x1234567, quality=h.MEASUREMENT_GOOD, matches_admitted_profile=True,
        acquisition_started_monotonic_ns=100, observed_monotonic_ns=190))
    s.fpga_programming.CopyFrom(h.FpgaProgrammingStatus(manager_quality=h.MEASUREMENT_GOOD,
        manager_state="operating", manager_observed_monotonic_ns=175, acquisition_started_monotonic_ns=170,
        configuration_observed_monotonic_ns=180, configuration_quality=h.MEASUREMENT_GOOD,
        configuration_status_raw=0x16907ffc))
    s.afe_global.CopyFrom(h.AfeGlobalObservation(quality=h.MEASUREMENT_GOOD,
        global_control_raw=word, bias_enable_raw=enable, power_state_bit=bool(word & 2),
        reset_asserted=bool(word & 1), busy_afe0=bool(word & 4), busy_afe12=bool(word & 8),
        busy_afe34=bool(word & 16), bias_enabled=bool(enable), acquisition_started_monotonic_ns=120,
        observed_monotonic_ns=160, identity_bracket_verified=True, source=SOURCE,
        message="private diagnostic text must not escape", maximum_acquisition_ms=100))
    return s


class AfeGlobalTests(unittest.TestCase):
    def check(self, s, now=200, **kwargs):
        return check_afe_global(h.SystemStatusSnapshot.FromString(s.SerializeToString()), h, now, **kwargs)

    def test_all_bits_and_supported_profiles(self):
        for word in range(32):
            for enable in (0, 1):
                for abi in (0x20000, 0x20001, 0x20002):
                    for variant in (1, 2):
                        s = fixture(word, enable)
                        s.gateware_identity.abi, s.gateware_identity.variant = abi, variant
                        report = self.check(s)
                        self.assertEqual(report["bias_enabled"], bool(enable))
                        self.assertEqual(report["power_state_bit"], bool(word & 2))
                        self.assertNotIn("private", str(report))
                        self.assertNotIn("health", report)

    def test_zero_and_false_need_presence(self):
        for field in FIELDS + ("global_control_raw", "bias_enable_raw"):
            s = fixture(); s.afe_global.ClearField(field)
            with self.subTest(field=field), self.assertRaises(RuntimeError): self.check(s)

    def test_missing_old_server_and_failed_quality(self):
        self.assertIsNone(self.check(h.SystemStatusSnapshot(), required=False))
        with self.assertRaises(RuntimeError): self.check(h.SystemStatusSnapshot())
        for quality in (h.MEASUREMENT_UNAVAILABLE, h.MEASUREMENT_ERROR, h.MEASUREMENT_STALE):
            s = fixture(); s.afe_global.quality = quality
            with self.assertRaises(RuntimeError): self.check(s, required=False)
            for key in FIELDS: s.afe_global.ClearField(key)
            self.assertFalse(self.check(s, required=False)["available"])
            with self.assertRaises(RuntimeError): self.check(s)

    def test_inconsistent_bits_and_reserved_values(self):
        for key in FIELDS:
            s = fixture(); setattr(s.afe_global, key, True)
            with self.subTest(key=key), self.assertRaises(RuntimeError): self.check(s)
        for key, first in (("global_control_raw", 5), ("bias_enable_raw", 1)):
            for bit in range(first, 32):
                s = fixture(); setattr(s.afe_global, key, 1 << bit)
                with self.assertRaises(RuntimeError): self.check(s)

    def test_failed_programming_and_admission(self):
        for field, value in (("magic", 0), ("abi", 0x20003), ("variant", 0), ("variant", 3),
                             ("build_id", 0xf1234567), ("quality", h.MEASUREMENT_ERROR),
                             ("matches_admitted_profile", False)):
            s = fixture(); setattr(s.gateware_identity, field, value)
            with self.assertRaises(RuntimeError): self.check(s)
        for field, value in (("manager_state", "write"), ("manager_quality", h.MEASUREMENT_UNAVAILABLE),
                             ("configuration_quality", h.MEASUREMENT_ERROR), ("manager_error_raw", 0),
                             ("configuration_status_raw", 0), ("configuration_status_raw", 0x16907ffd)):
            s = fixture(); setattr(s.fpga_programming, field, value)
            with self.assertRaises(RuntimeError): self.check(s)
        for field in ("gateware_identity", "fpga_programming"):
            s = fixture(); s.ClearField(field)
            with self.assertRaises(RuntimeError): self.check(s)
        s = fixture(); s.success = False
        with self.assertRaises(RuntimeError): self.check(s)

    def test_freshness_and_bracket(self):
        for field, value in (("acquisition_started_monotonic_ns", 0), ("acquisition_started_monotonic_ns", 99),
                             ("acquisition_started_monotonic_ns", 161), ("observed_monotonic_ns", 119),
                             ("observed_monotonic_ns", 171), ("identity_bracket_verified", False),
                             ("maximum_acquisition_ms", 101), ("source", "cached"), ("message", ""), ("quality", 99)):
            s = fixture(); setattr(s.afe_global, field, value)
            with self.assertRaises(RuntimeError): self.check(s)
        for now in (0, 189, 5_000_000_161):
            with self.assertRaises(RuntimeError): self.check(fixture(), now)
        self.check(fixture(), 5_000_000_160)
        for field in ("acquisition_started_monotonic_ns", "manager_observed_monotonic_ns", "configuration_observed_monotonic_ns"):
            s = fixture(); setattr(s.fpga_programming, field, 159)
            with self.assertRaises(RuntimeError): self.check(s)


if __name__ == "__main__":
    unittest.main()
