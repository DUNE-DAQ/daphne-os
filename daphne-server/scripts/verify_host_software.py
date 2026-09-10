#!/usr/bin/env python3
"""Check kernel/OS metadata with bookkeeping and two ordinary status requests.

No private opt-ins, configuration writes or service changes. Ordinary status
still samples its usual read-only FPGA/temperature collectors. Exit zero proves
reporting, not rootfs integrity, boot-slot health, verified UTC or FPGA health.
"""
import argparse
import json
from pathlib import Path
import sys
import time

from host_software import check_host_software, require
from software_build import check_build
from verify_server_bookkeeping import check_state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--proto-dir", type=Path, required=True)
    parser.add_argument("--server-source", type=Path, required=True)
    parser.add_argument("--expected-server-commit", required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.proto_dir.resolve()))
    import zmq
    import daphneV3_high_level_confs_pb2 as high
    context = zmq.Context()
    socket = context.socket(zmq.DEALER)
    socket.setsockopt(zmq.LINGER, 0)
    socket.setsockopt(zmq.RCVTIMEO, 3000)
    socket.setsockopt(zmq.SNDTIMEO, 3000)
    sequence, task = 0, 0x4f53564552
    try:
        socket.connect(args.endpoint)
        def call(kind, request, response_type):
            nonlocal sequence
            sequence += 1
            envelope = high.ControlEnvelopeV2(version=2, dir=high.DIR_REQUEST, type=kind,
                task_id=task, msg_id=sequence, payload=request.SerializeToString())
            socket.send(envelope.SerializeToString())
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
            require(status.HasField("server_state") and not status.board_identity.details_included)
            require(not status.host_time.timesync.details_included)
            state = status.server_state
            check_state(state)
            require(state.instance_id == before.instance_id and state.boot_id == before.boot_id)
            require(state.server_build == before.server_build == status.server_build)
            require(state.heartbeat_sequence > prior.heartbeat_sequence and state.observed_monotonic_ns > prior.observed_monotonic_ns)
            reports.append(check_host_software(status, high, now_monotonic_ns=state.observed_monotonic_ns))
            require(all(item.acquisition_started_monotonic_ns > prior.observed_monotonic_ns for item in status.host_software))
            prior = state
        print(json.dumps({"reporting_verified": True, "exchanges": sequence,
                          "same_process_and_boot": True, "observations": reports}, indent=2))
    finally:
        socket.close()
        context.term()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("Host software verification failed; response and private details suppressed", file=sys.stderr)
        raise SystemExit(1)
