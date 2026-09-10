"""No hardware access. Requires generated protobuf modules on PYTHONPATH."""
from pathlib import Path
import sys
import unittest
import daphneV3_high_level_confs_pb2 as high
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from host_resource_checks import check_host_resources


def snapshot():
    result = high.SystemStatusSnapshot()
    for metric, field, unit, source in (
        (high.HOST_UPTIME_SECONDS, "scalar_value", "s", "/proc/uptime:first field"),
        (high.HOST_LOAD_AVERAGE_1MIN, "scalar_value", "1", "/proc/loadavg:first field"),
        (high.HOST_MEMORY_AVAILABLE_BYTES, "bytes_value", "B", "/proc/meminfo:MemAvailable"),
        (high.HOST_ROOT_FREE_BYTES, "bytes_value", "B", "statvfs(/):f_bfree*f_frsize"),
        (high.HOST_ROOT_AVAILABLE_BYTES, "bytes_value", "B", "statvfs(/):f_bavail*f_frsize"),
        (high.HOST_ROOT_READ_ONLY, "flag_value", "1", "statvfs(/):ST_RDONLY"),
    ):
        item = result.host_resources.add(metric=metric, unit=unit, source=source, detail="fixture",
            quality=high.MEASUREMENT_GOOD, acquisition_started_monotonic_ns=100,
            observed_monotonic_ns=200, observed_host_unix_ns=1000)
        setattr(item, field, False if field == "flag_value" else 0)
    return result


class HostResourcesTests(unittest.TestCase):
    def test_valid_zero_values_and_false_presence(self):
        values = check_host_resources(snapshot(), high, True, now_monotonic_ns=300)
        self.assertEqual([item["value"] for item in values], [0, 0, 0, 0, 0, False])

    def test_old_server_is_optional_but_not_qualified(self):
        self.assertIsNone(check_host_resources(high.SystemStatusSnapshot(), high))
        with self.assertRaises(RuntimeError):
            check_host_resources(high.SystemStatusSnapshot(), high, True)

    def test_duplicate_missing_and_unknown_metrics_rejected(self):
        for metric in (high.HOST_UPTIME_SECONDS, high.HOST_RESOURCE_UNSPECIFIED, 999):
            s = snapshot(); s.host_resources[-1].metric = metric
            with self.assertRaises(RuntimeError): check_host_resources(s, high)
        s = snapshot(); del s.host_resources[-1]
        with self.assertRaises(RuntimeError): check_host_resources(s, high)

    def test_failed_sources_do_not_fabricate_values(self):
        for quality in (high.MEASUREMENT_UNAVAILABLE, high.MEASUREMENT_ERROR):
            s = snapshot(); item = s.host_resources[2]
            item.quality = quality; item.ClearField("value")
            item.observed_monotonic_ns = 0; item.observed_host_unix_ns = 0
            self.assertIsNone(check_host_resources(s, high)[2]["value"])
            with self.assertRaises(RuntimeError): check_host_resources(s, high, True)
            item.bytes_value = 0
            with self.assertRaises(RuntimeError): check_host_resources(s, high)

    def test_value_type_units_source_and_detail(self):
        for field, value in (("bytes_value", 0), ("unit", "%"), ("source", "wrong"), ("detail", ""),
                             ("scalar_value", float("nan")), ("scalar_value", float("inf")), ("scalar_value", -1)):
            s = snapshot(); setattr(s.host_resources[0], field, value)
            with self.assertRaises(RuntimeError): check_host_resources(s, high)

    def test_acquisition_and_freshness(self):
        for start, end in ((0, 100), (100, 0), (300, 200)):
            s = snapshot(); item = s.host_resources[0]
            item.acquisition_started_monotonic_ns = start; item.observed_monotonic_ns = end
            with self.assertRaises(RuntimeError): check_host_resources(s, high)
        for now in (199, 5_000_000_201):
            with self.assertRaises(RuntimeError): check_host_resources(snapshot(), high, now_monotonic_ns=now)
        check_host_resources(snapshot(), high, now_monotonic_ns=5_000_000_200)

    def test_root_filesystem_group_is_coherent(self):
        s = snapshot(); s.host_resources[4].bytes_value = 1
        with self.assertRaises(RuntimeError): check_host_resources(s, high)
        s = snapshot(); s.host_resources[5].observed_monotonic_ns = 201
        with self.assertRaises(RuntimeError): check_host_resources(s, high)
        s = snapshot()
        for item in s.host_resources[3:]:
            item.ClearField("value"); item.quality = high.MEASUREMENT_ERROR
            item.observed_monotonic_ns = 0; item.observed_host_unix_ns = 0
        check_host_resources(s, high)


if __name__ == "__main__":
    unittest.main()
