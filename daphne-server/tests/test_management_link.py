from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import daphneV3_high_level_confs_pb2 as h
from management_link import SPECS, check_link


def fixture():
    link = h.ManagementLinkStatus(quality=h.MEASUREMENT_GOOD, detail="scope", interface_index=3,
        acquisition_started_monotonic_ns=100, observed_monotonic_ns=200, observed_host_unix_ns=1234,
        link_state_bracket_verified=True)
    values = ("up", True, 1000, "full", 1500, (1 << 64) - 1, 1 << 32, 0, 0, 1234, 4, 0, 0, (1 << 32) - 1)
    for n, ((path, unit, kind, width), value) in enumerate(zip(SPECS, values), 1):
        item = link.observations.add(metric=n, quality=h.MEASUREMENT_GOOD, source=path, unit=unit,
            counter_width_bits=width, detail="scope", acquisition_started_monotonic_ns=100 + n,
            observed_monotonic_ns=101 + n, observed_host_unix_ns=1234)
        setattr(item, kind, value)
    return link


class ManagementLinkTests(unittest.TestCase):
    def test_all_fourteen_typed_fields_and_full_width_counts(self):
        link = h.ManagementLinkStatus.FromString(fixture().SerializeToString())
        report = check_link(link, h, require_all_good=True)
        self.assertEqual(len(report["metrics"]), 14)
        self.assertEqual(report["metrics"]["MANAGEMENT_LINK_RX_BYTES"]["value"], (1 << 64) - 1)
        self.assertEqual(report["metrics"]["MANAGEMENT_LINK_RX_ERRORS"]["value"], 0)
        self.assertEqual(report["counter_epoch"], "unobserved")

    def test_unknown_and_missing_are_not_zero(self):
        link = fixture()
        item = link.observations[2]
        item.quality = h.MEASUREMENT_UNAVAILABLE
        for name in ("value", "observed_monotonic_ns", "observed_host_unix_ns"):
            item.ClearField(name)
        self.assertIsNone(check_link(link, h)["metrics"]["MANAGEMENT_LINK_SPEED_MBPS"]["value"])
        with self.assertRaises(RuntimeError):
            check_link(link, h, require_all_good=True)

    def test_bad_shapes_types_values_and_times_rejected(self):
        for mutate in (lambda l: l.observations.pop(),
                       lambda l: setattr(l.observations[0], "metric", 2),
                       lambda l: setattr(l.observations[0], "text_value", "private-invalid-state"),
                       lambda l: setattr(l.observations[0], "source", "private-unexpected-source"),
                       lambda l: setattr(l.observations[1], "unsigned_value", 1),
                       lambda l: setattr(l.observations[2], "unsigned_value", 0xffffffff),
                       lambda l: setattr(l.observations[3], "text_value", "unknown"),
                       lambda l: setattr(l.observations[4], "unsigned_value", 0),
                       lambda l: setattr(l.observations[13], "unsigned_value", 1 << 32),
                       lambda l: setattr(l.observations[13], "counter_width_bits", 64),
                       lambda l: setattr(l.observations[0], "observed_monotonic_ns", 201),
                       lambda l: setattr(l.observations[0], "quality", h.MEASUREMENT_UNAVAILABLE),
                       lambda l: setattr(l, "interface_index", 0),
                       lambda l: setattr(l, "link_state_bracket_verified", False)):
            link = fixture()
            mutate(link)
            with self.assertRaisesRegex(RuntimeError, "private details suppressed"):
                check_link(link, h)

    def test_down_link_suppresses_old_negotiation(self):
        link = fixture()
        link.observations[0].text_value = "down"
        link.observations[1].flag_value = False
        with self.assertRaises(RuntimeError):
            check_link(link, h)
        for item in link.observations[2:4]:
            item.quality = h.MEASUREMENT_UNAVAILABLE
            for name in ("value", "observed_monotonic_ns", "observed_host_unix_ns"):
                item.ClearField(name)
        self.assertFalse(check_link(link, h)["metrics"]["MANAGEMENT_LINK_CARRIER"]["value"])

    def test_invalid_interface_bracket_cannot_retain_values(self):
        link = fixture()
        link.quality = h.MEASUREMENT_ERROR
        with self.assertRaises(RuntimeError):
            check_link(link, h)
        for name in ("interface_index", "observed_monotonic_ns", "observed_host_unix_ns", "link_state_bracket_verified"):
            link.ClearField(name)
        for item in link.observations:
            item.quality = h.MEASUREMENT_ERROR
            for name in ("value", "observed_monotonic_ns", "observed_host_unix_ns"):
                item.ClearField(name)
        self.assertEqual(check_link(link, h)["quality"], "MEASUREMENT_ERROR")


if __name__ == "__main__":
    unittest.main()
