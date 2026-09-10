from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import daphneV3_high_level_confs_pb2 as h
from host_clock import check_host_time, utc, CLOCK_FIELDS, KERNEL_FIELDS, CLOCK_SOURCE, KERNEL_SOURCE


def fixture():
    stamp = 1_700_000_000_000_000_200
    boot = stamp - 50 - 123_000_000_200
    result = h.SystemStatusSnapshot(ps_local_time=utc(stamp), ps_local_unix_ns=stamp)
    result.host_time.clock.CopyFrom(h.HostClockObservation(unix_time_ns=stamp, current_utc=utc(stamp),
        boottime_ns=123_000_000_200, boot_time_estimate_unix_ns=boot, boot_time_estimate_utc=utc(boot),
        realtime_sample_span_ns=100, quality=h.MEASUREMENT_GOOD,
        acquisition_started_monotonic_ns=100, observed_monotonic_ns=200, source=CLOCK_SOURCE, detail="Unverified wall clock"))
    result.host_time.kernel.CopyFrom(h.KernelClockObservation(time_state_raw=5, status_raw=0x2040,
        reports_synchronized=False, adjustment_offset_ns=-1234, maximum_error_ns=5000, estimated_error_ns=6000,
        quality=h.MEASUREMENT_GOOD, acquisition_started_monotonic_ns=300, observed_monotonic_ns=400,
        source=KERNEL_SOURCE, detail="Kernel state, not independent verification"))
    return result


class HostClockTests(unittest.TestCase):
    def check(self, status, **kwargs):
        return check_host_time(status, h, now_monotonic_ns=500, **kwargs)

    def test_unsynchronized_is_valid_observation_with_false_presence(self):
        result = self.check(h.SystemStatusSnapshot.FromString(fixture().SerializeToString()))
        self.assertIs(result["kernel"]["reports_synchronized"], False)
        self.assertEqual(result["clock"]["current_utc"], "2023-11-14T22:13:20.000000200Z")
        self.assertEqual(result["clock"]["boot_time_estimate_utc"], "2023-11-14T22:11:16.999999950Z")
        self.assertEqual(h.SystemStatusSnapshot.DESCRIPTOR.fields_by_name["host_time"].number, 30)

    def test_missing_each_value_and_old_reply_rejected(self):
        for group, fields in (("clock", CLOCK_FIELDS), ("kernel", KERNEL_FIELDS)):
            for field in fields:
                with self.subTest(group=group, field=field):
                    status = fixture(); getattr(status.host_time, group).ClearField(field)
                    with self.assertRaises(RuntimeError): self.check(status)
        with self.assertRaises(RuntimeError): self.check(h.SystemStatusSnapshot())

    def test_failed_group_does_not_keep_partial_values_or_aliases(self):
        for group, fields in (("clock", CLOCK_FIELDS), ("kernel", KERNEL_FIELDS)):
            status = fixture(); item = getattr(status.host_time, group)
            item.quality = h.MEASUREMENT_UNAVAILABLE
            with self.assertRaises(RuntimeError): self.check(status, require_good=False)
            for field in fields: item.ClearField(field)
            item.observed_monotonic_ns = 0
            if group == "clock":
                status.ClearField("ps_local_time"); status.ClearField("ps_local_unix_ns")
            self.assertIsNone(self.check(status, require_good=False)[group][fields[0]])
            with self.assertRaises(RuntimeError): self.check(status)

    def test_stale_future_reversed_and_overlong_brackets(self):
        status = fixture()
        with self.assertRaises(RuntimeError): check_host_time(status, h, now_monotonic_ns=5_000_000_401)
        with self.assertRaises(RuntimeError): check_host_time(status, h, now_monotonic_ns=399)
        for group in ("clock", "kernel"):
            for field, value in (("acquisition_started_monotonic_ns", 0), ("acquisition_started_monotonic_ns", 450),
                                 ("observed_monotonic_ns", 501)):
                status = fixture(); setattr(getattr(status.host_time, group), field, value)
                with self.assertRaises(RuntimeError): self.check(status)
            status = fixture(); getattr(status.host_time, group).observed_monotonic_ns = 250_000_401
            with self.assertRaises(RuntimeError): check_host_time(status, h, now_monotonic_ns=250_000_500)
        status = fixture(); status.host_time.kernel.acquisition_started_monotonic_ns = 199
        with self.assertRaises(RuntimeError): self.check(status)

    def test_wall_alias_math_format_span_and_range_rejected(self):
        for field, value in (("current_utc", "private-secret"), ("unix_time_ns", -1),
                ("boot_time_estimate_unix_ns", -1), ("boot_time_estimate_utc", "bad"),
                ("boottime_ns", (1 << 63)), ("realtime_sample_span_ns", 1_000_101)):
            status = fixture(); setattr(status.host_time.clock, field, value)
            with self.assertRaisesRegex(RuntimeError, "details suppressed") as caught: self.check(status)
            self.assertNotIn("private-secret", str(caught.exception))
        for field in ("ps_local_time", "ps_local_unix_ns"):
            status = fixture(); status.ClearField(field)
            with self.assertRaises(RuntimeError): self.check(status)

    def test_kernel_state_units_and_false_zero_values(self):
        for state in range(6):
            status = fixture(); kernel = status.host_time.kernel
            kernel.time_state_raw = state; kernel.reports_synchronized = state != 5
            self.check(status)
        for field, value in (("time_state_raw", 6), ("status_raw", 1 << 31), ("reports_synchronized", True),
                             ("maximum_error_ns", 1), ("estimated_error_ns", 999)):
            status = fixture(); setattr(status.host_time.kernel, field, value)
            with self.assertRaises(RuntimeError): self.check(status)
        status = fixture(); status.host_time.kernel.status_raw = 0x40
        with self.assertRaises(RuntimeError): self.check(status)
        status.host_time.kernel.adjustment_offset_ns = -2000
        self.check(status)
        status.host_time.kernel.adjustment_offset_ns = 0
        self.assertEqual(self.check(status)["kernel"]["adjustment_offset_ns"], 0)

    def test_epoch_signed_maximum_and_odd_sample_span(self):
        self.assertEqual(utc(0), "1970-01-01T00:00:00.000000000Z")
        self.assertEqual(utc((1 << 63) - 1), "2262-04-11T23:47:16.854775807Z")
        status = fixture(); wall = status.host_time.clock
        wall.realtime_sample_span_ns = 99
        self.check(status)  # ceil(99/2) and ceil(100/2) agree.
        wall.realtime_sample_span_ns = 101
        with self.assertRaises(RuntimeError): self.check(status)

    def test_free_text_and_unrelated_private_fields_never_returned(self):
        status = fixture(); status.hostname = "private-secret"
        status.host_time.clock.detail = "private-secret"
        report = str(self.check(status))
        self.assertNotIn("private-secret", report)
        for group in ("clock", "kernel"):
            test = fixture(); getattr(test.host_time, group).source = "private-secret"
            with self.assertRaisesRegex(RuntimeError, "details suppressed"): self.check(test)


if __name__ == "__main__":
    unittest.main()
