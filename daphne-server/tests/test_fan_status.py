"""Synthetic independent wire contract; not physical fan/PWM qualification."""
from pathlib import Path
import sys
import unittest
import daphneV3_high_level_confs_pb2 as h
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from fan_status import check_fans, DECODED, UNQUALIFIED, SOURCE
from test_afe_global import fixture as afe_fixture


def fixture(pwm=0, pulses=0):
    s = afe_fixture()
    for index in range(2):
        s.fans.add(name="fan" + str(index), source=SOURCE, message="private text must not escape",
                   quality=h.MEASUREMENT_GOOD, pwm_control_raw=pwm, pwm_control_after_raw=pwm,
                   tachometer_raw=pulses << 7, pwm_command=pwm, tach_pulses_capped=pulses,
                   tach_at_counter_limit=pulses == 31, acquisition_started_monotonic_ns=120,
                   observed_monotonic_ns=160, identity_bracket_verified=True, maximum_acquisition_ms=100)
    return s


class FanStatusTests(unittest.TestCase):
    def check(self, s, now=200, **kwargs):
        return check_fans(h.SystemStatusSnapshot.FromString(s.SerializeToString()), h, now, **kwargs)

    def test_all_encodings_and_both_profiles(self):
        for pwm in range(256):
            for pulses in range(32):
                s = fixture(pwm, pulses)
                result = self.check(s)
                self.assertEqual(result[0]["pwm_command"], pwm)
                self.assertEqual(result[1]["tach_pulses_capped"], pulses)
                self.assertIs(result[0]["tach_at_counter_limit"], pulses == 31)
                self.assertNotIn("private", str(result))
        for abi in (0x20000, 0x20001, 0x20002):
            for variant in (1, 2):
                s = fixture(); s.gateware_identity.abi = abi; s.gateware_identity.variant = variant
                self.check(s)

    def test_missing_and_failed_observations(self):
        self.assertIsNone(self.check(h.SystemStatusSnapshot(), required=False))
        with self.assertRaises(RuntimeError): self.check(h.SystemStatusSnapshot())
        for quality in (h.MEASUREMENT_UNAVAILABLE, h.MEASUREMENT_ERROR, h.MEASUREMENT_STALE):
            s = fixture()
            for r in s.fans: r.quality = quality
            with self.assertRaises(RuntimeError): self.check(s, required=False)
            for r in s.fans:
                for key in DECODED: r.ClearField(key)
            with self.assertRaises(RuntimeError): self.check(s)
            self.assertFalse(self.check(s, required=False)[1]["available"])

    def test_zero_false_presence_and_physical_claims(self):
        for key in DECODED + ("pwm_control_raw", "pwm_control_after_raw", "tachometer_raw"):
            s = fixture(); s.fans[0].ClearField(key)
            with self.subTest(key=key), self.assertRaises(RuntimeError): self.check(s)
        for key in UNQUALIFIED:
            for quality in (h.MEASUREMENT_GOOD, h.MEASUREMENT_ERROR):
                s = fixture(); s.fans[0].quality = quality
                setattr(s.fans[0], key, "" if key == "control_mode" else 0)
                with self.subTest(key=key), self.assertRaises(RuntimeError): self.check(s, required=False)

    def test_bad_encoding_shared_command_and_provenance(self):
        changes = (("pwm_control_raw", 256), ("pwm_control_after_raw", 1), ("pwm_command", 1),
                   ("tachometer_raw", 1), ("tachometer_raw", 4096), ("tach_pulses_capped", 32),
                   ("tach_at_counter_limit", True), ("tach_valid", True), ("source_sample_time_known", True),
                   ("source", "cache"), ("name", "fan1"), ("quality", 99), ("message", ""),
                   ("maximum_acquisition_ms", 101), ("identity_bracket_verified", False),
                   ("acquisition_started_monotonic_ns", 0), ("acquisition_started_monotonic_ns", 99),
                   ("acquisition_started_monotonic_ns", 161), ("observed_monotonic_ns", 119),
                   ("observed_monotonic_ns", 171))
        for key, value in changes:
            s = fixture(); setattr(s.fans[0], key, value)
            with self.subTest(key=key, value=value), self.assertRaises(RuntimeError): self.check(s)
        for key in ("pwm_command", "acquisition_started_monotonic_ns", "observed_monotonic_ns"):
            s = fixture()
            if key == "pwm_command":
                for field in ("pwm_command", "pwm_control_raw", "pwm_control_after_raw"): setattr(s.fans[0], field, 1)
            else: setattr(s.fans[0], key, getattr(s.fans[0], key) + 1)
            with self.assertRaisesRegex(RuntimeError, "shared acquisition"): self.check(s)
        s = fixture(); del s.fans[1]
        with self.assertRaises(RuntimeError): self.check(s)
        s = fixture(); s.fans.add().CopyFrom(s.fans[0])
        with self.assertRaises(RuntimeError): self.check(s)

    def test_admission_and_freshness(self):
        for key, value in (("magic", 0), ("abi", 0x20003), ("variant", 0), ("variant", 3),
                           ("build_id", 0xf1234567), ("quality", h.MEASUREMENT_ERROR), ("matches_admitted_profile", False)):
            s = fixture(); setattr(s.gateware_identity, key, value)
            with self.assertRaises(RuntimeError): self.check(s)
        for key, value in (("manager_state", "write"), ("manager_error_raw", 0),
                           ("configuration_status_raw", 0x16907ffd), ("configuration_status_raw", 0),
                           ("manager_quality", h.MEASUREMENT_ERROR), ("configuration_quality", h.MEASUREMENT_ERROR),
                           ("acquisition_started_monotonic_ns", 159), ("configuration_observed_monotonic_ns", 159)):
            s = fixture(); setattr(s.fpga_programming, key, value)
            with self.assertRaises(RuntimeError): self.check(s)
        for key in ("gateware_identity", "fpga_programming"):
            s = fixture(); s.ClearField(key)
            with self.assertRaises(RuntimeError): self.check(s)
        s = fixture(); s.success = False
        with self.assertRaises(RuntimeError): self.check(s)
        for now in (0, 189, 5_000_000_161):
            with self.assertRaises(RuntimeError): self.check(fixture(), now)
        self.check(fixture(), 5_000_000_160)

    def test_mixed_quality_and_acquisition_limit(self):
        s = fixture(); s.fans[1].quality = h.MEASUREMENT_ERROR
        for key in DECODED: s.fans[1].ClearField(key)
        with self.assertRaisesRegex(RuntimeError, "shared acquisition"): self.check(s, required=False)
        for excess in (0, 1):
            s = fixture()
            for r in s.fans: r.observed_monotonic_ns = r.acquisition_started_monotonic_ns + 100_000_000 + excess
            s.fpga_programming.acquisition_started_monotonic_ns += 100_000_000
            s.fpga_programming.manager_observed_monotonic_ns += 100_000_000
            s.fpga_programming.configuration_observed_monotonic_ns += 100_000_000
            s.gateware_identity.observed_monotonic_ns += 100_000_000
            if excess:
                with self.assertRaisesRegex(RuntimeError, "stale"): self.check(s, 100_000_200)
            else: self.check(s, 100_000_200)


if __name__ == "__main__":
    unittest.main()
