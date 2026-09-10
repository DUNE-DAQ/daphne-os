"""Hardware-free wire/quality/freshness tests; matching bindings required."""
from pathlib import Path
import sys
import unittest
import daphneV3_high_level_confs_pb2 as h
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from host_software import check_host_software, KEYS


def fixture():
    s = h.SystemStatusSnapshot(kernel_release="6.1", petalinux_version="PetaLinux test")
    values = ("6.1", "PetaLinux test", "petalinux", "2026.1", "base", "daphne", "2")
    for metric, value in enumerate(values, 1):
        s.host_software.add(metric=metric, value=value, quality=h.MEASUREMENT_GOOD,
            source="uname:release" if metric == 1 else f"/etc/os-release:{KEYS[metric-2]}",
            acquisition_started_monotonic_ns=100 if metric == 1 else 200,
            observed_monotonic_ns=150 if metric == 1 else 250, observed_host_unix_ns=1000,
            detail="private-diagnostic-not-exported")
    return s


class HostSoftwareTests(unittest.TestCase):
    def check(self, status, **kwargs):
        return check_host_software(status, h, now_monotonic_ns=300, **kwargs)

    def test_valid_and_serialized(self):
        s = h.SystemStatusSnapshot.FromString(fixture().SerializeToString())
        report = self.check(s)
        self.assertEqual(report["observations"][0]["value"], "6.1")
        self.assertFalse(report["rootfs_integrity_verified"] or report["boot_health_verified"])
        self.assertNotIn("private-diagnostic", str(report))

    def test_missing_optional_labels_and_old_server(self):
        s = fixture()
        for item in s.host_software[4:]:
            item.quality = h.MEASUREMENT_UNAVAILABLE
            for key in ("value", "observed_monotonic_ns", "observed_host_unix_ns"): item.ClearField(key)
        self.assertIsNone(self.check(s)["observations"][4]["value"])
        self.assertIsNone(self.check(h.SystemStatusSnapshot(), required=False))
        with self.assertRaises(RuntimeError): self.check(h.SystemStatusSnapshot())

    def test_inventory(self):
        for metric in (0, 6, 999):
            s = fixture(); s.host_software[-1].metric = metric
            with self.assertRaises(RuntimeError): self.check(s)
        s = fixture(); del s.host_software[-1]
        with self.assertRaises(RuntimeError): self.check(s)

    def test_failed_values_and_aliases(self):
        for quality in (h.MEASUREMENT_ERROR, h.MEASUREMENT_UNAVAILABLE):
            s = fixture(); item = s.host_software[0]; item.quality = quality
            with self.assertRaises(RuntimeError): self.check(s, required=False)
            for key in ("value", "observed_monotonic_ns", "observed_host_unix_ns"): item.ClearField(key)
            with self.assertRaises(RuntimeError): self.check(s, required=False)
            s.kernel_release = ""
            self.assertIsNone(self.check(s, required=False)["observations"][0]["value"])
            with self.assertRaises(RuntimeError): self.check(s)
        s = fixture(); s.petalinux_version = "wrong"
        with self.assertRaises(RuntimeError): self.check(s)

    def test_sources_and_group_times(self):
        s = fixture()
        for item in s.host_software[1:]: item.source = item.source.replace("/etc/", "/usr/lib/")
        self.check(s)
        for field, value in (("source", "/etc/os-release:ID"), ("acquisition_started_monotonic_ns", 201),
                             ("observed_monotonic_ns", 251), ("observed_host_unix_ns", 1001)):
            s = fixture(); setattr(s.host_software[-1], field, value)
            with self.assertRaises(RuntimeError): self.check(s)
        s = fixture(); s.host_software[-1].source = "/usr/lib/os-release:IMAGE_VERSION"
        with self.assertRaises(RuntimeError): self.check(s)

    def test_text_syntax_lengths_and_quality(self):
        for value in ("", "x" * 257, "x\n", "\x1b", "\u0085"):
            s = fixture(); s.host_software[-1].value = value
            with self.assertRaises(RuntimeError): self.check(s)
        for metric, value in ((2, "Invalid"), (3, "two words"), (5, "Invalid")):
            s = fixture(); s.host_software[metric].value = value
            with self.assertRaises(RuntimeError): self.check(s)
        s = fixture(); s.host_software[-1].value = "é€😀"
        self.check(s)
        for field, value in (("detail", ""), ("detail", "x" * 513), ("quality", h.MEASUREMENT_STALE)):
            s = fixture(); setattr(s.host_software[-1], field, value)
            with self.assertRaises(RuntimeError): self.check(s)

    def test_time_failures_and_freshness(self):
        for field, value in (("acquisition_started_monotonic_ns", 0), ("acquisition_started_monotonic_ns", 151),
                             ("observed_monotonic_ns", 0), ("observed_monotonic_ns", 301)):
            s = fixture(); setattr(s.host_software[0], field, value)
            with self.assertRaises(RuntimeError): self.check(s)
        for now in (0, 5_000_000_151):
            with self.assertRaises(RuntimeError): check_host_software(fixture(), h, now_monotonic_ns=now)
        check_host_software(fixture(), h, now_monotonic_ns=5_000_000_150)


if __name__ == "__main__":
    unittest.main()
