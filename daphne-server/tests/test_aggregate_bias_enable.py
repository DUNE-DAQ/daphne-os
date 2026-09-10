"""Synthetic wire-check tests; neither state is commanded on real hardware."""
import unittest

import daphneV3_high_level_confs_pb2 as h
from test_afe_global import fixture as afe_fixture
from test_software_build import fixture as build_fixture
from verify_aggregate_zero_bias import check_bias_control_acknowledgement, check_bias_enable_preserved


def sample(enable, shift=0):
    s = afe_fixture(enable=enable)
    for child in (s.gateware_identity, s.fpga_programming, s.afe_global):
        for field in child.DESCRIPTOR.fields:
            if field.name.endswith("monotonic_ns"):
                setattr(child, field.name, getattr(child, field.name) + shift)
    s.server_build.CopyFrom(build_fixture())
    s.server_state.CopyFrom(h.ServerState(success=True, instance_id="a" * 32,
        boot_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", heartbeat_sequence=1 + shift,
        heartbeat_monotonic_ns=190 + shift, observed_monotonic_ns=200 + shift,
        server_build=s.server_build))
    return s


def fixture(enable=0):
    before, after = sample(enable), sample(enable, 1000)
    configured = h.ConfigureResponse(success=True, applied_configuration_valid=True,
        applied_configuration_hash="c" * 64,
        execution=h.ConfigurationResult(outcome=h.CONFIGURATION_SUCCEEDED, hardware_started=True,
            attempt_sequence=1, task_id=22, request_msg_id=2, started_monotonic_ns=250, completed_monotonic_ns=900))
    after.server_state.last_configuration_result.CopyFrom(configured.execution)
    after.server_state.applied_configuration_valid = True
    after.server_state.applied_configuration_hash = configured.applied_configuration_hash
    return before, after, configured


class AggregateBiasEnableTests(unittest.TestCase):
    def check(self, before, after, configured):
        return check_bias_enable_preserved(h.SystemStatusSnapshot.FromString(before.SerializeToString()),
            h.SystemStatusSnapshot.FromString(after.SerializeToString()),
            h.ConfigureResponse.FromString(configured.SerializeToString()), h)

    def test_both_preserved_states_are_valid(self):
        for enable in (0, 1):
            report = self.check(*fixture(enable))
            self.assertIs(report["bias_enabled_before"], bool(enable))
            self.assertIs(report["bias_enabled_after"], bool(enable))
            self.assertNotIn("private", str(report))

    def test_both_transition_directions_are_rejected(self):
        for enable in (0, 1):
            before, after, configured = fixture(enable)
            after.afe_global.bias_enable_raw = 1 - enable
            after.afe_global.bias_enabled = not bool(enable)
            with self.assertRaisesRegex(RuntimeError, "BiasEnable changed"):
                self.check(before, after, configured)

    def test_missing_failed_stale_or_inconsistent_samples_cannot_pass(self):
        for side in (0, 1):
            for issue in ("missing", "quality", "bit", "admission", "stale"):
                values = fixture()
                s = values[side]
                if issue == "missing": s.afe_global.ClearField("bias_enabled")
                if issue == "quality": s.afe_global.quality = h.MEASUREMENT_ERROR
                if issue == "bit": s.afe_global.bias_enable_raw = 1
                if issue == "admission": s.gateware_identity.matches_admitted_profile = False
                if issue == "stale":
                    s.server_state.observed_monotonic_ns += 6_000_000_000
                    s.server_state.heartbeat_monotonic_ns += 6_000_000_000
                with self.subTest(side=side, issue=issue), self.assertRaises(RuntimeError):
                    self.check(*values)

    def test_restarts_changes_and_old_samples_cannot_pass(self):
        for issue in ("process", "boot", "firmware", "build", "timestamp", "dirty", "missing_state"):
            before, after, configured = fixture()
            if issue == "process": after.server_state.instance_id = "b" * 32
            if issue == "boot": after.server_state.boot_id = "bbbbbbbb-bbbb-cccc-dddd-eeeeeeeeeeee"
            if issue == "firmware": after.gateware_identity.build_id += 1
            if issue == "build": after.server_build.source_git_commit = "b" * 40
            if issue == "timestamp":
                configured.execution.completed_monotonic_ns = 1150
                after.server_state.last_configuration_result.CopyFrom(configured.execution)
            if issue == "dirty": after.server_build.source_worktree_dirty = True
            if issue == "missing_state": before.ClearField("server_state")
            with self.subTest(issue=issue), self.assertRaises(RuntimeError):
                self.check(before, after, configured)

    def test_failed_unrelated_or_missing_configuration_evidence_cannot_pass(self):
        for issue in ("success", "missing", "outcome", "started", "attempt", "hash", "valid", "correlation", "busy"):
            before, after, configured = fixture()
            if issue == "success": configured.success = False
            if issue == "missing": configured.ClearField("execution")
            if issue == "outcome": configured.execution.outcome = h.CONFIGURATION_FAILED
            if issue == "started": configured.execution.hardware_started = False
            if issue == "attempt": before.server_state.last_configuration_result.attempt_sequence = 1
            if issue == "hash": configured.applied_configuration_hash = "d" * 64
            if issue == "valid": configured.applied_configuration_valid = False
            if issue == "correlation": after.server_state.last_configuration_result.request_msg_id += 1
            if issue == "busy": before.server_state.configuration_in_progress = True
            with self.subTest(issue=issue), self.assertRaises(RuntimeError):
                self.check(before, after, configured)

    def test_acknowledgement_requires_exact_zero_and_no_implicit_enable(self):
        good = ("Bias Control command sent. BIASCTRL code: 0. Returned command-register value: 0. "
                "BiasEnable not written (SC-owned); no physical voltage readback.\n")
        check_bias_control_acknowledgement(good)
        for bad in ("", good + good, good.replace("code: 0", "code: 1"), good + "and Enable: 1\n",
                    good.replace("not written", "written")):
            with self.assertRaises(RuntimeError): check_bias_control_acknowledgement(bad)


if __name__ == "__main__":
    unittest.main()
