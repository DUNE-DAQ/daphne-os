"""Independent parser-history wire checks; no hardware/network access."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import daphneV3_high_level_confs_pb2 as h
from protocol_errors import check_history, RAW_FIELDS, FEATURE_FIELDS, DECODED_FIELDS


def protocol_fixture(count=0, detail=0):
    s = h.SystemStatusSnapshot()
    s.gateware_identity.CopyFrom(h.GatewareIdentityStatus(magic=0x44415048, abi=0x20002, variant=1,
        build_id=0x1234567, quality=h.MEASUREMENT_GOOD, matches_admitted_profile=True,
        acquisition_started_monotonic_ns=100, observed_monotonic_ns=195))
    s.fpga_programming.CopyFrom(h.FpgaProgrammingStatus(manager_quality=h.MEASUREMENT_GOOD,
        manager_state="operating", manager_observed_monotonic_ns=185, acquisition_started_monotonic_ns=180,
        configuration_observed_monotonic_ns=190, configuration_quality=h.MEASUREMENT_GOOD,
        configuration_status_raw=0x16907ffc))
    s.endpoint.observation_quality, s.endpoint.observed_monotonic_ns = h.MEASUREMENT_GOOD, 110
    live = s.endpoint.protocol_errors
    live.quality, live.message = h.MEASUREMENT_GOOD, "history only"
    live.feature_abi = live.feature_abi_after = 0x50450100
    live.timeout_cycles = live.timeout_cycles_after = 1024
    live.maximum_attempts, live.maximum_acquisition_ms = 3, 100
    live.counter_width_bits, live.counted_scope, live.lifetime = 32, h.PROTOCOL_ERROR_RX_PARSER_EPISODES, h.PROTOCOL_ERROR_PLATFORM_RESET
    live.acquisition_started_monotonic_ns, live.observed_monotonic_ns = 130, 160
    live.identity_bracket_verified = True
    live.count, live.reasons_seen = count, detail & 31
    live.saturated, live.overflowed, live.receiver_reset = bool(detail & 32), bool(detail & 64), bool(detail & 128)
    live.attempts.add(quality=h.MEASUREMENT_GOOD, sequence_before=40, sequence_first=41, sequence_after=41,
        request_status_raw=0x11, status_raw=0x11, count_raw=count, detail_raw=detail, attempt_index=1,
        acquisition_started_monotonic_ns=140, observed_monotonic_ns=150)
    return s


class ProtocolErrorTests(unittest.TestCase):
    def check(self, s, now=200):
        return check_history(h.SystemStatusSnapshot.FromString(s.SerializeToString()), h, now)

    def test_zero_reasons_reset_and_saturation_are_history_not_verdict(self):
        for count, detail in ((0, 0), (0, 128), (1, 1), (1, 31), (42, 155),
                              (0xffffffff, 33), (0xffffffff, 127), (0xffffffff, 255)):
            for variant in (1, 2):
                s = protocol_fixture(count, detail)
                s.gateware_identity.variant = variant
                s.board_identity.management.mac_address = "private-test-must-not-escape"
                s.endpoint.protocol_errors.message = "private-message-must-not-escape"
                report = self.check(s)
                self.assertTrue(report["available"])
                self.assertEqual(report["count"], count)
                self.assertEqual(report["reasons_mask"], detail & 31)
                self.assertEqual(report["receiver_reset_at_capture"], bool(detail & 128))
                self.assertFalse(report["reset_epoch_known"])
                self.assertNotIn("state", report)  # No health verdict, even if saturated.
                self.assertNotIn("private", str(report))

    def test_every_required_optional_has_presence(self):
        for field in FEATURE_FIELDS + DECODED_FIELDS:
            s = protocol_fixture()
            s.endpoint.protocol_errors.ClearField(field)
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                self.check(s)
        for field in RAW_FIELDS:
            s = protocol_fixture()
            s.endpoint.protocol_errors.attempts[0].ClearField(field)
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                self.check(s)

    def test_invalid_status_and_payload_never_marked_usable(self):
        for status in list(range(256)) + [0x10011, 0xffffffff]:
            if status == 0x11:
                continue
            s = protocol_fixture()
            a = s.endpoint.protocol_errors.attempts[0]
            a.request_status_raw = a.status_raw = status
            with self.subTest(status=status), self.assertRaises(RuntimeError):
                self.check(s)
        for count, detail in ((0, 1), (1, 0), (1, 33), (1, 65), (0xffffffff, 1),
                              (0xffffffff, 32), (1, 0x101), (0, 0x100)):
            with self.subTest(count=count, detail=detail), self.assertRaises(RuntimeError):
                self.check(protocol_fixture(count, detail))

    def test_sequence_wrap_and_conflict_retry(self):
        s = protocol_fixture()
        a = s.endpoint.protocol_errors.attempts[0]
        a.sequence_before, a.sequence_first, a.sequence_after = 0xffffffff, 0, 0
        self.assertTrue(self.check(s)["available"])
        for field in ("sequence_first", "sequence_after", "request_status_raw"):
            s = protocol_fixture(7, 1)
            live = s.endpoint.protocol_errors
            retry = h.ProtocolErrorAttempt()
            retry.CopyFrom(live.attempts[0])
            retry.quality = h.MEASUREMENT_ERROR
            retry.acquisition_started_monotonic_ns = retry.observed_monotonic_ns = 130
            setattr(retry, field, 99)
            live.attempts[0].attempt_index = 2
            live.attempts.insert(0, retry)
            self.assertEqual(self.check(s)["count"], 7)
            live.attempts[0].quality = h.MEASUREMENT_UNAVAILABLE
            with self.assertRaises(RuntimeError):
                self.check(s)

    def test_contract_times_and_decoding_checked_independently(self):
        for field, value in (("feature_abi", 0), ("feature_abi_after", 0x50450101),
                             ("timeout_cycles", 7), ("timeout_cycles_after", 512),
                             ("maximum_attempts", 4), ("maximum_acquisition_ms", 101),
                             ("counter_width_bits", 64), ("counted_scope", 0), ("lifetime", 0),
                             ("reset_epoch_known", True), ("count", 1), ("reasons_seen", 1),
                             ("saturated", True), ("overflowed", True), ("receiver_reset", True),
                             ("quality", 999), ("acquisition_started_monotonic_ns", 0),
                             ("observed_monotonic_ns", 100_000_131)):
            s = protocol_fixture()
            setattr(s.endpoint.protocol_errors, field, value)
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                self.check(s)
        for field, value in (("attempt_index", 2), ("acquisition_started_monotonic_ns", 129),
                             ("observed_monotonic_ns", 161), ("sequence_first", 42),
                             ("sequence_after", 42), ("request_status_raw", 4)):
            s = protocol_fixture()
            setattr(s.endpoint.protocol_errors.attempts[0], field, value)
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                self.check(s)
        s = protocol_fixture()
        s.endpoint.protocol_errors.attempts.pop()
        with self.assertRaises(RuntimeError):
            self.check(s)
        s = protocol_fixture()
        for _ in range(3):
            s.endpoint.protocol_errors.attempts.add()
        with self.assertRaises(RuntimeError):
            self.check(s)

    def test_failed_observation_has_raw_evidence_but_no_usable_values(self):
        for quality in (h.MEASUREMENT_UNAVAILABLE, h.MEASUREMENT_ERROR, h.MEASUREMENT_STALE):
            s = protocol_fixture()
            live = s.endpoint.protocol_errors
            live.quality = quality
            with self.assertRaises(RuntimeError):
                self.check(s)
            for field in DECODED_FIELDS:
                live.ClearField(field)
            with self.assertRaises(RuntimeError):
                self.check(s)  # GOOD attempt must also be invalidated.
            live.attempts[0].quality = quality
            self.assertFalse(self.check(s)["available"])
            self.assertNotIn("count", self.check(s))
            live.attempts[0].ClearField("count_raw")  # Partial read failure remains representable.
            self.assertFalse(self.check(s)["available"])

    def test_stale_or_missing_outer_context_never_exports_count(self):
        for group, field, value in (
            ("history", "identity_bracket_verified", False),
            ("identity", "matches_admitted_profile", False), ("identity", "magic", 0),
            ("identity", "variant", 3), ("identity", "build_id", 0xf1234567),
            ("identity", "quality", h.MEASUREMENT_ERROR), ("identity", "acquisition_started_monotonic_ns", 111),
            ("identity", "observed_monotonic_ns", 189), ("endpoint", "observed_monotonic_ns", 131),
            ("endpoint", "observation_quality", h.MEASUREMENT_ERROR),
            ("programming", "acquisition_started_monotonic_ns", 159),
            ("programming", "manager_observed_monotonic_ns", 179), ("programming", "manager_state", "reset"),
            ("programming", "configuration_status_raw", 0), ("programming", "manager_error_raw", 1),
            ("programming", "configuration_quality", h.MEASUREMENT_UNAVAILABLE),
        ):
            s = protocol_fixture(7, 1)
            target = {"history": s.endpoint.protocol_errors, "identity": s.gateware_identity,
                      "endpoint": s.endpoint, "programming": s.fpga_programming}[group]
            setattr(target, field, value)
            with self.subTest(group=group, field=field):
                self.assertFalse(self.check(s)["available"])
                self.assertNotIn("count", self.check(s))
        for now in (0, 194, 6_000_000_000):
            self.assertFalse(self.check(protocol_fixture(), now)["available"])

    def test_old_and_unknown_abi_do_not_claim_extension_reads(self):
        for abi in (0x20000, 0x20001):
            s = h.SystemStatusSnapshot()
            s.gateware_identity.abi = abi
            self.assertFalse(self.check(s)["available"])
            s.endpoint.protocol_errors.feature_abi = 0
            with self.assertRaises(RuntimeError):
                self.check(s)
            s.endpoint.ClearField("protocol_errors")
            s.endpoint.protocol_errors.count = 0
            with self.assertRaises(RuntimeError):
                self.check(s)
        for abi in (0, 0x10000, 0x20003, 0xffffffff):
            s = protocol_fixture()
            s.gateware_identity.abi = abi
            with self.assertRaises(RuntimeError):
                self.check(s)


if __name__ == "__main__":
    unittest.main()
