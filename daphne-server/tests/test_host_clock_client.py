"""Run the actual host-clock CLI against a localhost synthetic ROUTER."""
import json
from pathlib import Path
import subprocess
import sys
import time
import unittest

import zmq
import daphneV3_high_level_confs_pb2 as h
from test_host_clock import fixture
from test_software_build_client import build_info
from test_timesync import fixture as timesync_fixture
from timesync import META_FIELDS

ROOT = Path(__file__).resolve().parents[1]


class HostClockClientTests(unittest.TestCase):
    def exercise(self, case="valid", exchanges=3, require_service=False):
        context = zmq.Context()
        socket = context.socket(zmq.ROUTER)
        socket.setsockopt(zmq.LINGER, 0)
        socket.setsockopt(zmq.RCVTIMEO, 4500)
        port = socket.bind_to_random_port("tcp://127.0.0.1")
        args = [sys.executable, str(ROOT / "scripts/verify_host_clock.py"), "--endpoint", f"tcp://127.0.0.1:{port}",
                "--proto-dir", str(Path(h.__file__).parent), "--server-source", str(ROOT), "--expected-server-commit", "a" * 40]
        if require_service:
            args.append("--require-timesync-service")
        child = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        kinds = []
        try:
            for index in range(exchanges):
                peer, raw = socket.recv_multipart()
                request = h.ControlEnvelopeV2.FromString(raw)
                self.assertEqual(request.version, 2); self.assertEqual(request.dir, h.DIR_REQUEST)
                kinds.append(request.type)
                self.assertEqual(request.type, h.MT2_READ_SERVER_STATE_REQ if index == 0 else h.MT2_READ_SYSTEM_STATUS_REQ)
                now = time.monotonic_ns()
                info = build_info()
                if case == "schema": info.high_level_schema_sha256 = "0" * 64
                state = h.ServerState(success=True, instance_id="1" * 32, boot_id="00000000-0000-0000-0000-000000000000",
                    heartbeat_sequence=index + 1, heartbeat_monotonic_ns=now, observed_monotonic_ns=now, server_build=info)
                if case == "restart" and index: state.instance_id = "2" * 32
                if case == "stalled": state.heartbeat_sequence = 1
                if index == 0:
                    response = state
                else:
                    selected = h.ReadSystemStatusRequest.FromString(request.payload)
                    self.assertEqual(selected, h.ReadSystemStatusRequest())  # No opt-ins, private fields or writes.
                    response = fixture()
                    response.host_time.timesync.CopyFrom(timesync_fixture(case == "historical").host_time.timesync)
                    response.success = case != "fpga-failed"
                    response.server_build.CopyFrom(info); response.server_state.CopyFrom(state)
                    response.hostname = "private-secret"
                    response.host_time.clock.acquisition_started_monotonic_ns = now - 400
                    response.host_time.clock.observed_monotonic_ns = now - 300
                    response.host_time.kernel.acquisition_started_monotonic_ns = now - 200
                    response.host_time.kernel.observed_monotonic_ns = now - 100
                    response.host_time.timesync.acquisition_started_monotonic_ns = now - 90
                    response.host_time.timesync.observed_monotonic_ns = now - 80
                    if case == "no-service":
                        item = response.host_time.timesync
                        item.quality = h.MEASUREMENT_UNAVAILABLE
                        for field in META_FIELDS + ("bus_id", "unique_owner", "owner_bracket_verified", "observed_monotonic_ns"):
                            item.ClearField(field)
                    if case == "old": response.ClearField("host_time")
                    if case == "private": response.board_identity.details_included = True
                    if case == "stale": response.host_time.clock.observed_monotonic_ns = now - 6_000_000_000
                    if case == "alias": response.ps_local_time = "private-secret"
                    if case == "ntp-private": response.host_time.timesync.details_included = True
                    if case == "ntp-old": response.host_time.ClearField("timesync")
                reply = h.ControlEnvelopeV2(version=2, dir=h.DIR_RESPONSE, type=request.type + 1, task_id=request.task_id,
                    correl_id=request.msg_id, payload=response.SerializeToString())
                if case == "correlation": reply.correl_id += 1
                if case == "transport": reply.transport_error = "private-secret"
                socket.send_multipart([peer, reply.SerializeToString()])
            stdout, stderr = child.communicate(timeout=6)
        finally:
            if child.poll() is None:
                child.kill(); child.communicate(timeout=5)
            socket.close(); context.term()
        self.assertNotIn("private-secret", stdout + stderr)
        if case in ("valid", "fpga-failed", "historical") or (case == "no-service" and not require_service):
            self.assertEqual(child.returncode, 0, stderr)
            report = json.loads(stdout)
            self.assertTrue(report["reporting_verified"])
            self.assertFalse(report["utc_accuracy_verified"] or report["fpga_timing_verified"])
            self.assertEqual(report["exchanges"], 3)
            self.assertFalse(report["observations"][1]["kernel"]["reports_synchronized"])
            timesync = report["observations"][1]["timesync"]
            self.assertEqual(timesync["service_observed"], case != "no-service")
            self.assertIsNone(timesync["sample_age_upper_bound_ns"])
            if case == "historical":
                self.assertEqual(timesync["processed_packet_count"], (1 << 64) - 1)
                self.assertTrue(timesync["historical_sample"]["ignored_spike"])
            else:
                self.assertIsNone(timesync["historical_sample"]["offset_ns"])
        else:
            self.assertEqual(child.returncode, 1); self.assertEqual(stdout, "")
            self.assertIn("details suppressed", stderr)
        return kinds

    def test_only_bookkeeping_and_two_default_status_reads(self):
        self.assertEqual(self.exercise(), [h.MT2_READ_SERVER_STATE_REQ] + [h.MT2_READ_SYSTEM_STATUS_REQ] * 2)

    def test_host_clock_still_reports_when_fpga_status_fails(self):
        self.exercise("fpga-failed")

    def test_historical_spike_is_not_reported_as_current_accuracy(self):
        self.exercise("historical", require_service=True)

    def test_missing_service_is_valid_unavailable_reporting(self):
        self.exercise("no-service")

    def test_explicit_service_requirement_is_enforced(self):
        self.exercise("valid", require_service=True)
        self.exercise("no-service", exchanges=2, require_service=True)

    def test_schema_and_envelope_errors_fail_without_echo(self):
        for case in ("schema", "correlation", "transport"):
            with self.subTest(case=case): self.exercise(case, 1)

    def test_restart_stall_old_stale_alias_and_private_reply_fail(self):
        for case in ("restart", "stalled", "old", "stale", "alias", "private", "ntp-private", "ntp-old"):
            with self.subTest(case=case): self.exercise(case, 2)


if __name__ == "__main__":
    unittest.main()
