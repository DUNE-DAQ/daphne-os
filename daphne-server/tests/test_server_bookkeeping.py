"""Run with matching generated protobuf modules on PYTHONPATH; no hardware."""
from pathlib import Path
import sys
import unittest
import daphneV3_high_level_confs_pb2 as high
import daphneV3_low_level_confs_pb2 as low
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from verify_server_bookkeeping import check_state, make_offset_rewrite


def sample():
    return high.ServerState(success=True, instance_id="a" * 32, boot_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                            heartbeat_sequence=1, heartbeat_monotonic_ns=10, observed_monotonic_ns=20)


class BookkeepingTests(unittest.TestCase):
    def test_initial_state(self):
        check_state(sample())

    def test_identity_time_and_heartbeat_failures(self):
        for key, value in (("success", False), ("instance_id", ""), ("boot_id", ""),
                           ("heartbeat_sequence", 0), ("heartbeat_monotonic_ns", 0),
                           ("heartbeat_monotonic_ns", 30), ("observed_monotonic_ns", 4_000_000_000)):
            state = sample()
            setattr(state, key, value)
            with self.assertRaises(RuntimeError):
                check_state(state)

    def test_valid_configuration_requires_evidence(self):
        state = sample()
        state.applied_configuration_valid = True
        with self.assertRaises(RuntimeError):
            check_state(state)
        state.applied_configuration_hash = "c" * 64
        check_state(state)
        state.invalidation_reason = "reset"
        with self.assertRaises(RuntimeError):
            check_state(state)

    def test_visible_configuration_requires_executor(self):
        state = sample()
        state.configuration_in_progress = True
        with self.assertRaises(RuntimeError):
            check_state(state)
        state.executor_busy = True
        state.executor_request_type = high.MT2_CONFIGURE_FE_REQ
        state.last_configuration_result.outcome = high.CONFIGURATION_RUNNING
        check_state(state)

    def test_offset_probe_is_only_same_zero_bias_profile_offset(self):
        command = make_offset_rewrite(low)
        self.assertEqual(command.offsetChannel, 0)
        self.assertEqual(command.offsetValue, 2200)
        self.assertFalse(command.offsetGain)


if __name__ == "__main__":
    unittest.main()
