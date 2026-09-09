"""Run with matching generated protobufs on PYTHONPATH; no hardware access."""
from pathlib import Path
import sys
import unittest
import daphneV3_low_level_confs_pb2 as low
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from verify_current_monitor import check_current_sample


def sample(channel=0, code=0):
    return low.cmd_readCurrentMonitor_response(success=True, message="fixture", quality=low.CURRENT_MONITOR_GOOD,
        currentMonitorChannel=channel, currentValue=code & 0xffffffff, raw_code=code,
        differential_volts=code * 2.5 / 8388608, adc_id=0x81, adc_status=4,
        adc_input_mux=0x21 + 0x22 * (channel // 8), pga_gain=1, pga_bypassed=True,
        nominal_reference_volts=2.5, observed_monotonic_ns=100, observed_host_unix_ns=200,
        source="ADS1261 9c020000", current_quality=low.CURRENT_MONITOR_UNAVAILABLE,
        current_detail="No calibration", carrier_mux_restored=True,
        carrier_mux_enable=1 if channel % 8 < 4 else 2, carrier_mux_address=channel % 4)


class CurrentMonitorTests(unittest.TestCase):
    def test_all_channels_and_signed_zero(self):
        for ch in range(40):
            for code in (-1, 0, 1):
                check_current_sample(sample(ch, code), ch, low)

    def test_missing_presence(self):
        for field in ("raw_code", "differential_volts", "carrier_mux_restored", "adc_id", "adc_status", "adc_input_mux"):
            r = sample()
            r.ClearField(field)
            with self.assertRaises(RuntimeError):
                check_current_sample(r, 0, low)

    def test_bad_evidence(self):
        for key, value in (("adc_status", 0), ("pga_gain", 32), ("carrier_mux_restored", False),
                           ("carrier_mux_enable", 3), ("differential_volts", float("nan")),
                           ("observed_monotonic_ns", 0), ("source", "unknown"), ("success", False),
                           ("raw_code", 8388607), ("quality", low.CURRENT_MONITOR_ERROR)):
            r = sample()
            setattr(r, key, value)
            with self.assertRaises(RuntimeError):
                check_current_sample(r, 0, low)

    def test_uncalibrated_amperes_not_zero(self):
        r = sample()
        r.current_amperes = 0
        with self.assertRaises(RuntimeError):
            check_current_sample(r, 0, low)

    def test_explicit_channel_zero_survives_wire(self):
        r = low.cmd_readCurrentMonitor(physical_channel=0)
        self.assertTrue(low.cmd_readCurrentMonitor.FromString(r.SerializeToString()).HasField("physical_channel"))
        self.assertFalse(low.cmd_readCurrentMonitor().HasField("physical_channel"))


if __name__ == "__main__":
    unittest.main()
