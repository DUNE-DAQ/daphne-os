import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import daphneV3_high_level_confs_pb2 as h
from verify_sfp_monitor import check_port, decoded_value, NAMES, QUANTITIES, FIELDS, UNITS


def good_port(channel=0):
    a0 = bytearray(96)
    a0[0:2] = b"\x03\x04"
    a0[92], a0[93], a0[94] = 0x68, 0xf0, 0x0c
    a0[63], a0[95] = sum(a0[:63]) % 256, sum(a0[64:95]) % 256
    p = h.SFPMonitor(name=NAMES[channel], mux_channel=channel, mux_address=0x72, a0_address=0x50,
                     a2_address=0x51, source="PL I2C 9c000000 synthetic", mux_restored=True, previous_mux_route=0,
                     acquisition_started_monotonic_ns=1, diagnostics_observed_monotonic_ns=2,
                     observed_monotonic_ns=4, observed_host_unix_ns=5, present=True,
                     identity_quality=h.MEASUREMENT_GOOD, diagnostic_quality=h.MEASUREMENT_GOOD,
                     a0_raw=bytes(a0), a2_static_raw=bytes(96), a2_monitor_raw=bytes(16),
                     base_checksum_valid=True, extended_checksum_valid=True, diagnostic_checksum_valid=True,
                     diagnostic_type=0x68, enhanced_options=0xf0, standard_revision=0x0c,
                     calibration=h.SFP_CALIBRATION_INTERNAL, data_ready=True, tx_disabled=False,
                     loss_of_signal=False, tx_fault=False, status_a2_0x6e=0, status_a2_0x6f=0,
                     alarm_flags=0, warning_flags=0, flags_observed_monotonic_ns=3)
    p.temperature_alarm.state = h.TEMPERATURE_ALARM_GOOD
    p.temperature_alarm.warning_c = 85; p.temperature_alarm.high_c = 95; p.temperature_alarm.critical_c = 105
    p.temperature_alarm.maximum_age_ms = 5000; p.temperature_alarm.evaluated_monotonic_ns = 4
    p.temperature_alarm.observation_age_ns = 2; p.temperature_alarm.policy_source = "synthetic"
    p.temperature_alarm.message = "synthetic"
    for name, units, field in zip(QUANTITIES, UNITS, FIELDS):
        p.quantities.add(name=name, units=units, raw_code=0, value=0, quality=h.MEASUREMENT_GOOD,
                         threshold_quality=h.MEASUREMENT_GOOD, high_alarm=0, low_alarm=0,
                         high_warning=0, low_warning=0, high_alarm_flag=False, low_alarm_flag=False,
                         high_warning_flag=False, low_warning_flag=False)
        setattr(p, field, 0)
    return p


class SfpTests(unittest.TestCase):
    def test_all_routes_and_explicit_zero_presence(self):
        for channel in range(6):
            p = good_port(channel)
            check_port(h.SFPMonitor.FromString(p.SerializeToString()), h)
            self.assertTrue(p.HasField("temperature_c") and p.HasField("loss_of_signal"))

    def test_missing_measurements_are_not_zero(self):
        for field in FIELDS:
            p = good_port(); p.ClearField(field)
            with self.assertRaises(RuntimeError):
                check_port(p, h)

    def test_bad_checksum_route_restoration_and_time(self):
        for change in (
                lambda p: setattr(p, "a0_raw", bytes(96)),
                lambda p: setattr(p, "a2_static_raw", b"\x01" + bytes(95)),
                lambda p: setattr(p, "mux_channel", 4),
                lambda p: setattr(p, "mux_restored", False),
                lambda p: setattr(p, "diagnostics_observed_monotonic_ns", 100),
                lambda p: setattr(p, "diagnostic_quality", h.MEASUREMENT_ERROR)):
            p = good_port(); change(p)
            with self.assertRaises(RuntimeError):
                check_port(p, h)

    def test_failed_read_has_unknown_presence(self):
        p = good_port(); p.identity_quality = h.MEASUREMENT_ERROR; p.message = "I2C error"
        p.ClearField("present")
        p.ClearField("quantities")
        for field in FIELDS:
            p.ClearField(field)
        check_port(p, h)
        p.present = False
        with self.assertRaises(RuntimeError):
            check_port(p, h)

    def test_disabled_tx_is_not_zero_power(self):
        p = good_port(); p.tx_disabled = True
        p.a2_monitor_raw = bytes(14) + b"\x40\x00"; p.status_a2_0x6e = 0x40
        p.diagnostic_quality = h.MEASUREMENT_UNAVAILABLE
        p.quantities[3].quality = h.MEASUREMENT_UNAVAILABLE
        p.quantities[3].ClearField("value"); p.ClearField("tx_power_mw")
        check_port(p, h)
        p.tx_power_mw = 0
        with self.assertRaises(RuntimeError):
            check_port(p, h)

    def test_asserted_flags_need_confirmation(self):
        p = good_port(); p.warning_flags = 128
        with self.assertRaises(RuntimeError):
            check_port(p, h)
        p.warning_flags_second = 128; p.alarm_flags_second = 0
        p.flags_observed_monotonic_ns = 10; p.flags_second_monotonic_ns = 100_000_010
        p.observed_monotonic_ns = 100_000_020
        p.quantities[4].high_warning_flag = True
        check_port(p, h)

    def test_signed_scaling_and_external_calibration(self):
        self.assertEqual(decoded_value(bytes(96), 0, 0xff00, False), -1)
        raw = bytearray(96); raw[84:88] = b"\x02\x00\xff\x00"
        self.assertEqual(decoded_value(raw, 0, 0xff00, True), -3)
        raw[68:76] = b"\x40\x00\x00\x00\x41\x20\x00\x00"
        self.assertAlmostEqual(decoded_value(raw, 4, 5000, True), 1.001)


if __name__ == "__main__":
    unittest.main()
