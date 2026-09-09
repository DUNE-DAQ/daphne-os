"""Hardware-free validation tests for the read-only AMS protocol client."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from verify_server_v05 import check_ams_temperatures

HIGH = SimpleNamespace(MEASUREMENT_UNAVAILABLE=0, MEASUREMENT_GOOD=1, MEASUREMENT_ERROR=3,
                       MeasurementQuality=SimpleNamespace(Name=lambda value: {0: "UNAVAILABLE", 1: "GOOD", 3: "ERROR"}[value]))


def readings():
    return [SimpleNamespace(name=name, temperature_c=value, valid=True, quality=1,
                            source=f"Linux IIO xilinx-ams / {name} / iio:device42/in_temp7_input",
                            message="SoC die, not ambient", observed_host_unix_ns=100,
                            observed_monotonic_ns=200)
            for name, value in zip(("Temp_LPD", "Temp_FPD", "Temp_PL"), (39.494, 0, -1.25))]


class TemperatureTests(unittest.TestCase):
    def test_good_including_zero_and_negative(self):
        self.assertEqual([row["temperature_c"] for row in check_ams_temperatures(readings(), HIGH, True)],
                         [39.494, 0, -1.25])

    def test_old_server_allowed_only_without_requirement(self):
        self.assertEqual(check_ams_temperatures([], HIGH), [])
        with self.assertRaises(RuntimeError):
            check_ams_temperatures([], HIGH, True)

    def test_invalid_good_observations(self):
        for field, value in (("temperature_c", float("nan")), ("temperature_c", float("inf")),
                             ("temperature_c", -274), ("valid", False), ("observed_host_unix_ns", 0),
                             ("observed_monotonic_ns", 0), ("source", "unknown"), ("message", "")):
            with self.subTest(field=field, value=value):
                items = readings()
                setattr(items[0], field, value)
                with self.assertRaises(RuntimeError):
                    check_ams_temperatures(items, HIGH)

    def test_missing_duplicate_unknown_identities(self):
        for names in ([], ["Temp_LPD"], ["Temp_LPD", "Temp_LPD", "Temp_PL"],
                      ["Temp_LPD", "Temp_FPD", "Ambient"]):
            items = readings()[:len(names)]
            for item, name in zip(items, names):
                item.name = name
            with self.assertRaises(RuntimeError):
                check_ams_temperatures(items, HIGH, True)

    def test_missing_is_not_a_measured_zero(self):
        for quality in (0, 3):
            items = readings()
            items[0].valid = False
            items[0].quality = quality
            items[0].temperature_c = float("nan")
            items[0].observed_monotonic_ns = items[0].observed_host_unix_ns = 0
            self.assertIsNone(check_ams_temperatures(items, HIGH)[0]["temperature_c"])
            with self.assertRaises(RuntimeError):
                check_ams_temperatures(items, HIGH, True)
            items[0].temperature_c = 0
            with self.assertRaises(RuntimeError):
                check_ams_temperatures(items, HIGH)


if __name__ == "__main__":
    unittest.main()
