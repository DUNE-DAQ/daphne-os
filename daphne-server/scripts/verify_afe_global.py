#!/usr/bin/env python3
"""Verify fresh AFE global reporting with one bookkeeping and two status RPCs.

No private opt-ins, SC/bias/configuration writes, scans or service changes.
Exit zero verifies register reporting, not physical power or bias voltage.
"""
import argparse
import json
from pathlib import Path
import sys

from afe_global import check_afe_global, require
from software_build import check_build
from verify_server_bookkeeping import check_state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--proto-dir", type=Path, required=True)
    parser.add_argument("--server-source", type=Path, required=True)
    parser.add_argument("--expected-server-commit", required=True)
    parser.add_argument("--expected-build-id", type=lambda value: int(value, 0), required=True)
    parser.add_argument("--expected-abi", type=lambda value: int(value, 0), choices=(0x20000, 0x20001, 0x20002), required=True)
    parser.add_argument("--mode", choices=("self-trigger", "full-stream"), required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.proto_dir.resolve()))
    import zmq
    import daphneV3_high_level_confs_pb2 as high
    context = zmq.Context()
    socket = context.socket(zmq.DEALER)
    socket.setsockopt(zmq.LINGER, 0)
    socket.setsockopt(zmq.RCVTIMEO, 10000)
    socket.setsockopt(zmq.SNDTIMEO, 5000)
    sequence, task = 0, 0x414645
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
            require(reply.version == 2 and reply.dir == high.DIR_RESPONSE and reply.type == kind + 1 and
                    reply.task_id == task and reply.correl_id == sequence and not reply.transport_error)
            response = response_type.FromString(reply.payload)
            require(response.HasField("server_build"))
            check_build(response.server_build, high, expected_commit=args.expected_server_commit,
                        require_clean=True, source_root=args.server_source)
            return response

        before = call(high.MT2_READ_SERVER_STATE_REQ, high.ReadServerStateRequest(), high.ServerState)
        check_state(before)
        reports, prior = [], before
        for _ in range(2):
            status = call(high.MT2_READ_SYSTEM_STATUS_REQ, high.ReadSystemStatusRequest(), high.SystemStatusSnapshot)
            require(status.HasField("server_state") and not status.board_identity.details_included and
                    not status.host_time.timesync.details_included and not status.sfps and not status.regulators)
            state, identity = status.server_state, status.gateware_identity
            check_state(state)
            require(state.instance_id == before.instance_id and state.boot_id == before.boot_id and
                    state.server_build == before.server_build == status.server_build and
                    state.applied_configuration_hash == before.applied_configuration_hash and
                    state.applied_configuration_valid == before.applied_configuration_valid)
            require((identity.build_id, identity.abi, identity.variant) ==
                    (args.expected_build_id, args.expected_abi, 1 if args.mode == "self-trigger" else 2))
            reports.append(check_afe_global(status, high, state.observed_monotonic_ns))
            require(status.afe_global.acquisition_started_monotonic_ns > prior.observed_monotonic_ns)
            prior = state
        print(json.dumps({"reporting_verified": True, "exchanges": sequence,
                          "same_process_boot_and_configuration_evidence": True, "observations": reports}, indent=2))
    finally:
        socket.close()
        context.term()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("AFE global verification failed; response and private details suppressed", file=sys.stderr)
        raise SystemExit(1)
