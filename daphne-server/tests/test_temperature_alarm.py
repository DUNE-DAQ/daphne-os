"""Run with generated protobufs on PYTHONPATH; no hardware access."""
from pathlib import Path
import sys
import unittest
import daphneV3_high_level_confs_pb2 as high
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from verify_server_v05 import check_temperature_alarm


def reading(value=31):
    item = high.TemperatureStatus(name="fixture", temperature_c=value, valid=True,
                                  quality=high.MEASUREMENT_GOOD, observed_monotonic_ns=100)
    item.alarm.CopyFrom(high.TemperatureAlarm(state=high.TEMPERATURE_ALARM_GOOD,
        warning_c=85, high_c=95, critical_c=105, maximum_age_ms=5000,
        evaluated_monotonic_ns=200, observation_age_ns=100, policy_source="fixture", message="fixture"))
    return item


class TemperatureAlarmTests(unittest.TestCase):
    def test_boundaries(self):
        for value, state in ((0, high.TEMPERATURE_ALARM_GOOD), (85, high.TEMPERATURE_ALARM_WARNING),
                             (95, high.TEMPERATURE_ALARM_HIGH), (105, high.TEMPERATURE_ALARM_CRITICAL)):
            item = reading(value)
            item.alarm.state = state
            self.assertIsNotNone(check_temperature_alarm(item, high, True))

    def test_old_server(self):
        item = reading()
        item.ClearField("alarm")
        self.assertIsNone(check_temperature_alarm(item, high))
        with self.assertRaises(RuntimeError):
            check_temperature_alarm(item, high, True)

    def test_stale(self):
        item = reading(120)
        item.alarm.evaluated_monotonic_ns = 5_000_000_101
        item.alarm.observation_age_ns = 5_000_000_001
        item.alarm.state = high.TEMPERATURE_ALARM_STALE
        check_temperature_alarm(item, high, True)

    def test_missing_and_invalid(self):
        item = reading(float("nan"))
        item.valid = False
        item.quality = high.MEASUREMENT_UNAVAILABLE
        item.observed_monotonic_ns = 0
        item.alarm.ClearField("observation_age_ns")
        item.alarm.state = high.TEMPERATURE_ALARM_MISSING
        check_temperature_alarm(item, high, True)
        item.temperature_c = 0
        with self.assertRaises(RuntimeError):
            check_temperature_alarm(item, high, True)
        item.alarm.state = high.TEMPERATURE_ALARM_INVALID
        check_temperature_alarm(item, high, True)

    def test_rejects_inconsistent_evidence(self):
        for key, value in (("state", high.TEMPERATURE_ALARM_UNSPECIFIED), ("warning_c", float("nan")),
                           ("high_c", 80), ("maximum_age_ms", 0), ("policy_source", ""),
                           ("evaluated_monotonic_ns", 0), ("observation_age_ns", 101)):
            item = reading()
            setattr(item.alarm, key, value)
            with self.assertRaises(RuntimeError):
                check_temperature_alarm(item, high, True)


if __name__ == "__main__":
    unittest.main()
