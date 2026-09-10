"""Actual CLI against localhost synthetic ROUTER; never touches a board."""
import json
from pathlib import Path
import subprocess
import sys
import time
import unittest
import zmq
import daphneV3_high_level_confs_pb2 as h
from test_host_software import fixture
from test_software_build_client import build_info

ROOT = Path(__file__).resolve().parents[1]


class HostSoftwareClientTests(unittest.TestCase):
    def exercise(self, case="valid", exchanges=3):
        context = zmq.Context()
        socket = context.socket(zmq.ROUTER)
        socket.setsockopt(zmq.LINGER, 0)
        socket.setsockopt(zmq.RCVTIMEO, 4500)
        port = socket.bind_to_random_port("tcp://127.0.0.1")
        args = [sys.executable, str(ROOT / "scripts/verify_host_software.py"), "--endpoint", f"tcp://127.0.0.1:{port}",
                "--proto-dir", str(Path(h.__file__).parent), "--server-source", str(ROOT), "--expected-server-commit", "a" * 40]
        child = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            for index in range(exchanges):
                peer, raw = socket.recv_multipart()
                request = h.ControlEnvelopeV2.FromString(raw)
                self.assertEqual(request.type, h.MT2_READ_SERVER_STATE_REQ if index == 0 else h.MT2_READ_SYSTEM_STATUS_REQ)
                self.assertEqual(request.dir, h.DIR_REQUEST); self.assertEqual(request.version, 2)
                now = time.monotonic_ns()
                info = build_info()
                if case == "schema": info.high_level_schema_sha256 = "0" * 64
                state = h.ServerState(success=True, instance_id="1" * 32, boot_id="00000000-0000-0000-0000-000000000000",
                    heartbeat_sequence=index + 1, heartbeat_monotonic_ns=now, observed_monotonic_ns=now, server_build=info)
                if index and case == "restart": state.instance_id = "2" * 32
                if case == "stalled": state.heartbeat_sequence = 1
                response = state
                if index:
                    self.assertEqual(h.ReadSystemStatusRequest.FromString(request.payload), h.ReadSystemStatusRequest())
                    response = fixture(); response.success = case != "fpga-failed"
                    response.server_build.CopyFrom(info); response.server_state.CopyFrom(state)
                    response.hostname = "private-secret"; response.message = "private-secret"
                    for item in response.host_software:
                        item.acquisition_started_monotonic_ns = now - 200
                        item.observed_monotonic_ns = now - 100
                    if case == "old": response.ClearField("host_software")
                    if case == "private": response.board_identity.details_included = True
                    if case == "ntp-private": response.host_time.timesync.details_included = True
                    if case == "stale": response.host_software[0].observed_monotonic_ns = now - 6_000_000_000
                    if case == "alias": response.kernel_release = "private-secret"
                    if case == "optional-missing":
                        item = response.host_software[4]; item.quality = h.MEASUREMENT_UNAVAILABLE
                        for key in ("value", "observed_monotonic_ns", "observed_host_unix_ns"): item.ClearField(key)
                reply = h.ControlEnvelopeV2(version=2, dir=h.DIR_RESPONSE, type=request.type + 1, task_id=request.task_id,
                    correl_id=request.msg_id, payload=response.SerializeToString())
                if case == "correlation": reply.correl_id += 1
                if case == "transport": reply.transport_error = "private-secret"
                socket.send_multipart([peer, reply.SerializeToString()])
            stdout, stderr = child.communicate(timeout=6)
        finally:
            if child.poll() is None: child.kill(); child.communicate(timeout=5)
            socket.close(); context.term()
        self.assertNotIn("private-secret", stdout + stderr)
        if case in ("valid", "fpga-failed", "optional-missing"):
            self.assertEqual(child.returncode, 0, stderr)
            report = json.loads(stdout)
            self.assertTrue(report["reporting_verified"] and report["same_process_and_boot"])
            self.assertEqual(report["exchanges"], 3)
            self.assertFalse(report["observations"][0]["rootfs_integrity_verified"])
        else:
            self.assertEqual(child.returncode, 1); self.assertEqual(stdout, "")
            self.assertIn("details suppressed", stderr)

    def test_read_only_reporting(self):
        self.exercise()

    def test_fpga_failure_does_not_hide_os_metadata(self):
        self.exercise("fpga-failed")

    def test_missing_build_id_is_not_fabricated(self):
        self.exercise("optional-missing")

    def test_bad_envelope_and_schema(self):
        for case in ("correlation", "transport", "schema"):
            with self.subTest(case=case): self.exercise(case, 1)

    def test_restart_stale_private_alias_and_old_server(self):
        for case in ("restart", "stalled", "old", "private", "ntp-private", "stale", "alias"):
            with self.subTest(case=case): self.exercise(case, 2)


if __name__ == "__main__":
    unittest.main()
