#!/usr/bin/env python3
"""Verify host-clock reporting through two ordinary read-only status requests.

Uses a bookkeeping request to bind process, boot and exact source/schema. Does
not set time, start services, request private details or configure hardware.
System status still samples its usual read-only FPGA/temperature collectors.
An unsynchronized clock is a valid observation, not a successful UTC check.
"""
import argparse
import json
from pathlib import Path
import sys
import time

from host_clock import check_host_time, require
from software_build import check_build
from verify_server_bookkeeping import check_state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--proto-dir", type=Path, required=True)
    parser.add_argument("--server-source", type=Path, required=True)
    parser.add_argument("--expected-server-commit", required=True, help="Full expected clean Git revision")
    args = parser.parse_args()
    sys.path.insert(0, str(args.proto_dir.resolve()))
    import zmq
    import daphneV3_high_level_confs_pb2 as high
    context = zmq.Context()
    socket = context.socket(zmq.DEALER)
    socket.setsockopt(zmq.LINGER, 0)
    socket.setsockopt(zmq.RCVTIMEO, 3000)
    socket.setsockopt(zmq.SNDTIMEO, 3000)
    sequence, task = 0, 0x434C4F434B
    try:
        socket.connect(args.endpoint)
        def call(kind, request, response_type):
            nonlocal sequence
            sequence += 1
            request = high.ControlEnvelopeV2(version=2, dir=high.DIR_REQUEST, type=kind,
                task_id=task, msg_id=sequence, payload=request.SerializeToString())
            socket.send(request.SerializeToString())
            frames = socket.recv_multipart()
            require(len(frames) == 1 and len(frames[0]) <= 1_048_576)
            reply = high.ControlEnvelopeV2.FromString(frames[0])
            require(reply.version == 2 and reply.dir == high.DIR_RESPONSE and reply.type == kind + 1
                    and reply.task_id == task and reply.correl_id == sequence and not reply.transport_error)
            response = response_type.FromString(reply.payload)
            require(response.HasField("server_build"))
            check_build(response.server_build, high, expected_commit=args.expected_server_commit,
                        require_clean=True, source_root=args.server_source)
            return response
        before = call(high.MT2_READ_SERVER_STATE_REQ, high.ReadServerStateRequest(), high.ServerState)
        check_state(before)
        reports, prior = [], before
        for _ in range(2):
            time.sleep(1.1)
            status = call(high.MT2_READ_SYSTEM_STATUS_REQ, high.ReadSystemStatusRequest(), high.SystemStatusSnapshot)
            # FPGA failure does not invalidate separately collected host-clock
            # observations. Never require or synthesize an FPGA healthy verdict.
            require(status.HasField("server_state") and not status.board_identity.details_included)
            state = status.server_state
            check_state(state)
            require(state.instance_id == before.instance_id and state.boot_id == before.boot_id)
            require(state.server_build == before.server_build == status.server_build)
            require(state.heartbeat_sequence > prior.heartbeat_sequence and
                    state.observed_monotonic_ns > prior.observed_monotonic_ns)
            report = check_host_time(status, high, now_monotonic_ns=state.observed_monotonic_ns)
            require(status.host_time.clock.acquisition_started_monotonic_ns > prior.observed_monotonic_ns)
            reports.append(report)
            prior = state
        print(json.dumps({"reporting_verified": True, "exchanges": sequence, "same_process_and_boot": True,
            "observations": reports, "utc_accuracy_verified": False, "fpga_timing_verified": False}, indent=2))
    finally:
        socket.close()
        context.term()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("Host-clock verification failed; response and private details suppressed", file=sys.stderr)
        raise SystemExit(1)
