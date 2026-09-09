"""Run with generated protobuf modules on PYTHONPATH; no hardware access."""
from pathlib import Path
import sys
import unittest

import daphneV3_high_level_confs_pb2 as high

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from verify_server_v05 import check_carrier_temperature, check_service_status


def carrier():
    return high.TemperatureStatus(name="Carrier_U9_MCP9808", temperature_c=31.8125, valid=True,
                                  quality=high.MEASUREMENT_GOOD, observed_host_unix_ns=100,
                                  observed_monotonic_ns=200,
                                  source="Carrier U9 MCP9808 PS I2C1 ff030000 / 0x18")


def status():
    result = high.SystemStatusSnapshot(server_instance_id="a" * 32, server_uptime_ms=10,
                                       hostname="fixture", kernel_release="fixture", petalinux_version="fixture")
    for name in ("daphne-runtime.target", "daphne-gateware-prepare.service", "firmware.service",
                 "daphne-gateware-verify.service", "clockchip.service", "endpoint.service", "hermes.service", "daphne.service"):
        item = result.services.add(name=name, quality=high.MEASUREMENT_GOOD, load_state="loaded",
                                   active_state="active", sub_state="running", message="systemd observation",
                                   observed_monotonic_ns=200, observed_host_unix_ns=100)
        if name == "daphne.service":
            item.main_pid = 123
            item.automatic_restarts = 0
            item.invocation_id = "a" * 32
    return result


class BoardTelemetryTests(unittest.TestCase):
    def test_carrier_valid_zero_and_negative(self):
        for value in (31.8125, 0, -1):
            item = carrier()
            item.temperature_c = value
            self.assertEqual(check_carrier_temperature([item], high, True)["temperature_c"], value)

    def test_carrier_failures(self):
        for key, value in (("name", "Ambient"), ("temperature_c", float("nan")),
                           ("observed_monotonic_ns", 0), ("source", "xilinx-ams"), ("valid", False)):
            item = carrier()
            setattr(item, key, value)
            with self.assertRaises(RuntimeError):
                check_carrier_temperature([item], high, True)
        for items in ([], [carrier(), carrier()]):
            with self.assertRaises(RuntimeError):
                check_carrier_temperature(items, high, True)

    def test_complete_services(self):
        self.assertEqual(len(check_service_status(status(), high, True)), 8)

    def test_service_missing_and_duplicate(self):
        result = status()
        del result.services[-1]
        with self.assertRaises(RuntimeError):
            check_service_status(result, high, True)
        result = status()
        result.services[-1].name = result.services[0].name
        with self.assertRaises(RuntimeError):
            check_service_status(result, high, True)

    def test_service_process_provenance(self):
        for key, value in (("main_pid", 0), ("active_state", "inactive"), ("invocation_id", "b" * 32),
                           ("observed_monotonic_ns", 0)):
            result = status()
            setattr(result.services[-1], key, value)
            with self.assertRaises(RuntimeError):
                check_service_status(result, high, True)
        result = status()
        result.services[-1].ClearField("automatic_restarts")
        with self.assertRaises(RuntimeError):
            check_service_status(result, high, True)

    def test_unknown_service_measurement_is_not_zero(self):
        result = status()
        item = result.services[0]
        item.quality = high.MEASUREMENT_ERROR
        item.observed_monotonic_ns = item.observed_host_unix_ns = 0
        self.assertEqual(len(check_service_status(result, high)), 8)
        with self.assertRaises(RuntimeError):
            check_service_status(result, high, True)
        item.main_pid = 0
        with self.assertRaises(RuntimeError):
            check_service_status(result, high)


if __name__ == "__main__":
    unittest.main()
