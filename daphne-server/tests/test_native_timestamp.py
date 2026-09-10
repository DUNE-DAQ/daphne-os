"""Hardware-free, independent protocol checks; no network or MMIO."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import daphneV3_high_level_confs_pb2 as h
from native_timestamp import check_progress


def native_fixture(first=100, second=200, external=False):
    s = h.SystemStatusSnapshot()
    s.gateware_identity.CopyFrom(h.GatewareIdentityStatus(abi=0x20001, quality=h.MEASUREMENT_GOOD,
        matches_admitted_profile=True, acquisition_started_monotonic_ns=100, observed_monotonic_ns=190))
    s.fpga_programming.acquisition_started_monotonic_ns = 150
    s.fpga_programming.configuration_observed_monotonic_ns = 180
    ep = s.endpoint
    ep.observation_quality, ep.observed_monotonic_ns = h.MEASUREMENT_GOOD, 140
    ep.endpoint_clock_selected, ep.endpoint_clock_control_raw = external, 4 if external else 0
    ep.live_timestamp_quality = h.MEASUREMENT_GOOD
    live = ep.live_timestamp
    live.quality = h.MEASUREMENT_GOOD
    live.feature_abi = live.feature_abi_after = 0x54530100
    live.timeout_cycles = live.timeout_cycles_after = 1024
    live.maximum_attempts_per_sample, live.maximum_acquisition_ms = 3, 100
    live.acquisition_started_monotonic_ns, live.observed_monotonic_ns = 142, 148
    live.identity_bracket_verified = True
    live.delta_ticks = (second - first) & 0xffffffffffffffff
    live.advancing = 0 < live.delta_ticks < 1 << 63
    live.message = "diagnostic pair"
    for i, value in enumerate((first, second)):
        live.samples.add(quality=h.MEASUREMENT_GOOD, sequence_before=i, sequence_first=i + 1,
            sequence_after=i + 1, request_status_raw=0x13 if external else 0x11,
            status_raw=0x13 if external else 0x11, low_raw=value & 0xffffffff, high_raw=value >> 32,
            timestamp_ticks=value, source=h.NATIVE_TIMESTAMP_EXTERNAL_PDTS if external else h.NATIVE_TIMESTAMP_LOCAL_COUNTER,
            acquisition_started_monotonic_ns=143 + 2 * i, observed_monotonic_ns=144 + 2 * i,
            sample_index=i, attempt_index=1)
    return s


class NativeTimestampTests(unittest.TestCase):
    def check(self, s, now=200):
        decoded = h.SystemStatusSnapshot.FromString(s.SerializeToString())
        return check_progress(decoded, h, now)

    def test_local_external_zero_rollover_and_stall(self):
        for external in (False, True):
            for first, second, advancing in ((0, 1, True), (2**32 - 1, 2**32, True),
                    (2**64 - 1, 0, True), (100, 100, False), (100, 99, False),
                    (0, 2**63, False), (0, 2**63 - 1, True)):
                with self.subTest(external=external, first=first, second=second):
                    self.assertEqual(self.check(native_fixture(first, second, external)),
                                     h.HEALTH_CHECK_PASS if advancing else h.HEALTH_CHECK_FAIL)

    def test_sequence_rollover(self):
        s = native_fixture()
        sample = s.endpoint.live_timestamp.samples[0]
        sample.sequence_before, sample.sequence_first, sample.sequence_after = 0xffffffff, 0, 0
        self.assertEqual(self.check(s), h.HEALTH_CHECK_PASS)

    def test_abi22_retains_native_timestamp_contract(self):
        for external in (False, True):
            s = native_fixture(external=external)
            s.gateware_identity.abi = 0x20002
            self.assertEqual(self.check(s), h.HEALTH_CHECK_PASS)

    def test_complete_conflict_then_retry(self):
        for kind in ("sequence_first", "sequence_after", "request_status_raw"):
            s = native_fixture()
            live = s.endpoint.live_timestamp
            discarded = h.NativeTimestampSample()
            discarded.CopyFrom(live.samples[0])
            discarded.quality = h.MEASUREMENT_ERROR
            discarded.ClearField("timestamp_ticks")
            setattr(discarded, kind, 99)
            discarded.acquisition_started_monotonic_ns = discarded.observed_monotonic_ns = 142
            live.samples[0].attempt_index = 2
            live.samples.insert(0, discarded)
            self.assertEqual(self.check(s), h.HEALTH_CHECK_PASS)
            live.samples[0].quality = h.MEASUREMENT_UNAVAILABLE
            with self.assertRaises(RuntimeError):
                self.check(s)

    def test_each_required_raw_field_has_presence(self):
        for field in ("sequence_before", "sequence_first", "sequence_after", "request_status_raw",
                      "status_raw", "low_raw", "high_raw", "timestamp_ticks"):
            s = native_fixture(0, 1)
            s.endpoint.live_timestamp.samples[0].ClearField(field)
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                self.check(s)

    def test_bad_metadata_pair_flags_and_decoding_rejected(self):
        for mutate in (
            lambda l: l.ClearField("feature_abi_after"),
            lambda l: setattr(l, "timeout_cycles_after", 512),
            lambda l: setattr(l, "maximum_attempts_per_sample", 4),
            lambda l: setattr(l, "maximum_acquisition_ms", 101),
            lambda l: setattr(l, "delta_ticks", 99),
            lambda l: l.ClearField("advancing"),
            lambda l: setattr(l.samples[0], "status_raw", 0x91),
            lambda l: setattr(l.samples[0], "high_raw", 1),
            lambda l: setattr(l.samples[0], "source", h.NATIVE_TIMESTAMP_EXTERNAL_PDTS),
            lambda l: setattr(l.samples[0], "attempt_index", 2),
            lambda l: setattr(l.samples[1], "sample_index", 0),
            lambda l: setattr(l.samples[1], "acquisition_started_monotonic_ns", 142),
            lambda l: l.samples.pop(),
            lambda l: setattr(l, "observed_monotonic_ns", 100_000_143),
        ):
            s = native_fixture()
            mutate(s.endpoint.live_timestamp)
            with self.assertRaises(RuntimeError):
                self.check(s)

    def test_missing_context_and_stale_evidence_are_unknown(self):
        for mutate in (
            lambda s: setattr(s.endpoint.live_timestamp, "identity_bracket_verified", False),
            lambda s: setattr(s.gateware_identity, "matches_admitted_profile", False),
            lambda s: setattr(s.gateware_identity, "acquisition_started_monotonic_ns", 149),
            lambda s: setattr(s.fpga_programming, "acquisition_started_monotonic_ns", 147),
            lambda s: setattr(s.endpoint, "endpoint_clock_selected", True),
            lambda s: setattr(s.endpoint, "endpoint_clock_control_raw", 4),
            lambda s: setattr(s.endpoint, "observed_monotonic_ns", 149),
        ):
            s = native_fixture()
            mutate(s)
            self.assertEqual(self.check(s), h.HEALTH_CHECK_UNKNOWN)
        self.assertEqual(self.check(native_fixture(), 6_000_000_000), h.HEALTH_CHECK_UNKNOWN)

    def test_failed_observation_never_supplies_usable_values(self):
        for quality in (h.MEASUREMENT_UNAVAILABLE, h.MEASUREMENT_ERROR, h.MEASUREMENT_STALE):
            s = native_fixture()
            live = s.endpoint.live_timestamp
            live.quality = s.endpoint.live_timestamp_quality = quality
            with self.assertRaises(RuntimeError):
                self.check(s)
            live.ClearField("advancing")
            live.ClearField("delta_ticks")
            for sample in live.samples:
                sample.quality = quality
                sample.ClearField("timestamp_ticks")
            self.assertEqual(self.check(s), h.HEALTH_CHECK_UNKNOWN)

    def test_old_abi_does_not_claim_extension_reads(self):
        s = h.SystemStatusSnapshot()
        s.gateware_identity.abi = 0x20000
        self.assertEqual(self.check(s), h.HEALTH_CHECK_UNKNOWN)
        s.endpoint.live_timestamp.feature_abi = 0
        with self.assertRaises(RuntimeError):
            self.check(s)
        s.endpoint.ClearField("live_timestamp")
        s.gateware_identity.abi = 0x20003
        with self.assertRaises(RuntimeError):
            self.check(s)


if __name__ == "__main__":
    unittest.main()
