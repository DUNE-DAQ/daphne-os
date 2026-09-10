"""Exercise the actual CLI against a private localhost synthetic ZMQ responder."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import unittest

import zmq
import daphneV3_high_level_confs_pb2 as h

ROOT = Path(__file__).resolve().parents[1]


def build_info():
    info = h.ServerBuildInfo(metadata_format_version=1, component="daphne-server",
        software_version="git:" + "a" * 40, source_git_commit="a" * 40,
        committed_source_tree="b" * 40, source_worktree_dirty=False,
        source_quality=h.MEASUREMENT_GOOD, source_detail="fixture",
        control_envelope_version=2, compiler_id="GNU", compiler_version="12.2.0",
        target_architecture="aarch64", protobuf_compile_version="6.30.1")
    for level in ("high", "low"):
        raw = (ROOT / "srcs/protobuf" / f"daphneV3_{level}_level_confs.proto").read_bytes()
        setattr(info, f"{level}_level_schema_sha256", hashlib.sha256(raw).hexdigest())
    return info


class SoftwareBuildClientTests(unittest.TestCase):
    def exercise(self, case="valid", exchanges=2, include_status=False):
        context = zmq.Context()
        socket = context.socket(zmq.ROUTER)
        socket.setsockopt(zmq.LINGER, 0)
        socket.setsockopt(zmq.RCVTIMEO, 4500)
        port = socket.bind_to_random_port("tcp://127.0.0.1")
        args = [sys.executable, str(ROOT / "scripts/verify_server_build.py"),
                "--endpoint", f"tcp://127.0.0.1:{port}", "--proto-dir", str(Path(h.__file__).parent),
                "--server-source", str(ROOT), "--expected-server-commit", "a" * 40]
        if include_status:
            args.append("--include-system-status")
        child = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        kinds = []
        try:
            for i in range(exchanges):
                peer, raw = socket.recv_multipart()
                req = h.ControlEnvelopeV2.FromString(raw)
                kinds.append(req.type)
                self.assertEqual(req.dir, h.DIR_REQUEST)
                self.assertIn(req.type, (h.MT2_READ_SERVER_STATE_REQ, h.MT2_READ_SYSTEM_STATUS_REQ))
                info = build_info()
                if case == "schema-mismatch":
                    info.high_level_schema_sha256 = "0" * 64
                if case == "dirty":
                    info.source_worktree_dirty = True
                    info.software_version += "-dirty"
                now = time.monotonic_ns()
                state = h.ServerState(success=True, instance_id="1" * 32,
                    boot_id="00000000-0000-0000-0000-000000000000", observed_monotonic_ns=now,
                    heartbeat_sequence=(1 if case == "stalled" else i + 1), heartbeat_monotonic_ns=now,
                    server_build=info)
                if case == "old":
                    state.ClearField("server_build")
                if case == "restart" and i:
                    state.instance_id = "2" * 32
                if req.type == h.MT2_READ_SYSTEM_STATUS_REQ:
                    request = h.ReadSystemStatusRequest.FromString(req.payload)
                    self.assertFalse(request.include_identity_details)
                    response = h.SystemStatusSnapshot(success=True, server_build=info, server_state=state)
                    if case == "private-status":
                        response.board_identity.details_included = True
                else:
                    response = state
                reply = h.ControlEnvelopeV2(version=2, dir=h.DIR_RESPONSE, type=req.type + 1,
                    task_id=req.task_id, correl_id=req.msg_id, payload=response.SerializeToString())
                if case == "correlation":
                    reply.correl_id += 1
                if case == "private-error":
                    reply.transport_error = "private-secret"
                socket.send_multipart([peer, reply.SerializeToString()])
            stdout, stderr = child.communicate(timeout=6)
        finally:
            if child.poll() is None:
                child.kill()
                child.communicate(timeout=5)
            socket.close()
            context.term()
        if case == "valid":
            self.assertEqual(child.returncode, 0, stderr)
            report = json.loads(stdout)
            self.assertEqual(report["exchanges"], exchanges)
            self.assertTrue(report["success"] and report["heartbeat_advanced"])
            self.assertTrue(report["build"]["schema_source_compared"])
        else:
            self.assertEqual(child.returncode, 1)
            self.assertEqual(stdout, "")
            self.assertNotIn("private-secret", stderr)
            self.assertIn("details suppressed", stderr)
        return kinds

    def test_default_only_sends_two_software_bookkeeping_reads(self):
        self.assertEqual(self.exercise(), [h.MT2_READ_SERVER_STATE_REQ] * 2)

    def test_optional_full_status_matches_same_process_and_build(self):
        self.assertEqual(self.exercise(exchanges=3, include_status=True),
                         [h.MT2_READ_SERVER_STATE_REQ] * 2 + [h.MT2_READ_SYSTEM_STATUS_REQ])

    def test_old_dirty_schema_mismatch_and_bad_envelopes_fail_closed(self):
        for case in ("old", "dirty", "schema-mismatch", "correlation", "private-error"):
            with self.subTest(case=case):
                self.exercise(case, exchanges=1)

    def test_stalled_heartbeat_and_process_change_fail(self):
        for case in ("stalled", "restart"):
            with self.subTest(case=case):
                self.exercise(case)

    def test_unrequested_private_status_is_not_accepted_or_echoed(self):
        self.exercise("private-status", exchanges=3, include_status=True)


if __name__ == "__main__":
    unittest.main()
