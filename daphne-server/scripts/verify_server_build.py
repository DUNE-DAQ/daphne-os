#!/usr/bin/env python3
"""Read compiled build metadata through bookkeeping; optionally compare full status.

Default: exactly two bookkeeping requests, no hardware collectors. Optional
--include-system-status adds the ordinary read-only hardware-status request.
No private identity details, configuration commands or service changes.
"""
import argparse
import json
from pathlib import Path
import sys
import time

from software_build import check_build, require
from verify_server_bookkeeping import check_state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--proto-dir", type=Path, required=True)
    parser.add_argument("--server-source", type=Path, required=True, help="Server source directory for exact .proto hash comparison")
    parser.add_argument("--expected-server-commit", required=True, help="Full expected Git revision, not a short prefix")
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument("--include-system-status", action="store_true")
    args = parser.parse_args()
    sys.path.insert(0, str(args.proto_dir.resolve()))
    import zmq
    import daphneV3_high_level_confs_pb2 as high
    context = zmq.Context()
    socket = context.socket(zmq.DEALER)
    socket.setsockopt(zmq.LINGER, 0)
    socket.setsockopt(zmq.RCVTIMEO, 3000)
    socket.setsockopt(zmq.SNDTIMEO, 3000)
    sequence = 0
    task = 0x4255494C44
    try:
        socket.connect(args.endpoint)
        def call(kind, request, response_type):
            nonlocal sequence
            sequence += 1
            env = high.ControlEnvelopeV2(version=2, dir=high.DIR_REQUEST, type=kind,
                task_id=task, msg_id=sequence, payload=request.SerializeToString())
            socket.send(env.SerializeToString())
            frames = socket.recv_multipart()
            require(len(frames) == 1 and len(frames[0]) <= 1_048_576)
            reply = high.ControlEnvelopeV2.FromString(frames[0])
            require(reply.version == 2 and reply.dir == high.DIR_RESPONSE and reply.type == kind + 1
                    and reply.task_id == task and reply.correl_id == sequence and not reply.transport_error)
            response = response_type.FromString(reply.payload)
            require(response.success and response.HasField("server_build"))
            check_build(response.server_build, high, expected_commit=args.expected_server_commit,
                        require_clean=not args.allow_dirty, source_root=args.server_source)
            return response
        before = call(high.MT2_READ_SERVER_STATE_REQ, high.ReadServerStateRequest(), high.ServerState)
        check_state(before)
        time.sleep(1.1)
        after = call(high.MT2_READ_SERVER_STATE_REQ, high.ReadServerStateRequest(), high.ServerState)
        check_state(after)
        require(before.instance_id == after.instance_id and before.boot_id == after.boot_id)
        require(before.server_build == after.server_build and after.heartbeat_sequence > before.heartbeat_sequence)
        if args.include_system_status:
            status = call(high.MT2_READ_SYSTEM_STATUS_REQ, high.ReadSystemStatusRequest(), high.SystemStatusSnapshot)
            require(status.server_build == after.server_build and status.HasField("server_state"))
            require(status.server_state.instance_id == after.instance_id and status.server_state.boot_id == after.boot_id)
            require(status.server_state.server_build == after.server_build)
            require(not status.board_identity.details_included)
        report = check_build(after.server_build, high, expected_commit=args.expected_server_commit,
                             require_clean=not args.allow_dirty, source_root=args.server_source)
        print(json.dumps({"success": True, "exchanges": sequence, "build": report,
                          "same_process": True, "heartbeat_advanced": True}, indent=2))
    finally:
        socket.close()
        context.term()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("Server-build verification failed; response and private details suppressed", file=sys.stderr)
        raise SystemExit(1)
