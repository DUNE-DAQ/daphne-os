#!/usr/bin/env python3
"""Check heartbeat/status; optional explicit maintenance test applies full zero-BIAS twice.

The maintenance test also rejects gain=3 and rewrites channel 0's existing
2200/x1 offset to verify invalidation. No nonzero BIAS/BIASCTRL command.
"""
import argparse
import json
from pathlib import Path
import re
import sys
import time


def require(ok, reason):
    if not ok:
        raise RuntimeError(reason)


def check_state(state):
    require(state.success, state.message)
    require(bool(re.fullmatch(r"[0-9a-f]{32}", state.instance_id)), "Missing process identity")
    require(bool(re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", state.boot_id)), "Missing boot identity")
    require(0 < state.heartbeat_monotonic_ns <= state.observed_monotonic_ns,
            "Invalid heartbeat observation time")
    require(state.observed_monotonic_ns - state.heartbeat_monotonic_ns < 3_000_000_000,
            "Router heartbeat is stale")
    require(state.heartbeat_sequence > 0, "No router heartbeat")
    if state.applied_configuration_valid:
        require(bool(re.fullmatch(r"[0-9a-f]{64}", state.applied_configuration_hash)), "Invalid applied digest")
        require(not state.invalidation_reason, "Valid configuration has an invalidation reason")
    if state.configuration_in_progress:
        require(state.executor_busy and state.executor_request_type == 202
                and state.last_configuration_result.outcome == 1, "Configuration progress has no executor")


def make_offset_rewrite(low):
    return low.cmd_writeOFFSET_singleChannel(offsetChannel=0, offsetValue=2200, offsetGain=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--proto-dir", type=Path, required=True)
    parser.add_argument("--expected-build-id", type=lambda x: int(x, 0), required=True)
    parser.add_argument("--apply-zero-bias-configuration", action="store_true")
    args = parser.parse_args()
    sys.path.insert(0, str(args.proto_dir.resolve()))
    import zmq
    import daphneV3_high_level_confs_pb2 as high
    import daphneV3_low_level_confs_pb2 as low
    from google.protobuf.json_format import ParseDict, MessageToDict
    from verify_aggregate_zero_bias import make_zero_bias_request, check_bias_acknowledgements

    context = zmq.Context()
    sockets = []

    class Client:
        def __init__(self, task):
            self.socket = context.socket(zmq.DEALER)
            sockets.append(self.socket)
            self.socket.setsockopt(zmq.LINGER, 0)
            self.socket.setsockopt(zmq.RCVTIMEO, 2000)
            self.socket.setsockopt(zmq.SNDTIMEO, 2000)
            self.socket.connect(args.endpoint)
            self.task, self.sequence = task, 0

        def send(self, kind, body):
            self.sequence += 1
            env = high.ControlEnvelopeV2(version=2, dir=high.DIR_REQUEST, type=kind,
                                         task_id=self.task, msg_id=self.sequence, payload=body.SerializeToString())
            self.socket.send(env.SerializeToString())

        def receive(self, kind, cls):
            reply = high.ControlEnvelopeV2.FromString(self.socket.recv())
            require(reply.version == 2 and reply.dir == high.DIR_RESPONSE and reply.type == kind + 1
                    and reply.task_id == self.task and reply.correl_id == self.sequence, "Reply correlation mismatch")
            require(not reply.transport_error, reply.transport_error)
            return cls.FromString(reply.payload)

        def call(self, kind, body, cls):
            self.send(kind, body)
            return self.receive(kind, cls)

    control, observer = Client(36), Client(37)
    latencies = []

    def state():
        start = time.monotonic()
        value = observer.call(high.MT2_READ_SERVER_STATE_REQ, high.ReadServerStateRequest(), high.ServerState)
        latencies.append((time.monotonic() - start) * 1000)
        check_state(value)
        return value

    def rejected_preserves_configuration():
        before = state()
        bad = high.ConfigureRequest()
        bad.channels.add(id=0, gain=3)  # Deliberately invalid; never use gain=1 as a rejection test.
        result = control.call(high.MT2_CONFIGURE_FE_REQ, bad, high.ConfigureResponse)
        require(not result.success and result.execution.outcome == high.CONFIGURATION_REJECTED,
                "Invalid gain was not rejected before hardware")
        require(not result.execution.hardware_started, "Rejected request touched hardware")
        require(result.execution.task_id == control.task and result.execution.request_msg_id == control.sequence,
                "Rejected attempt lost request correlation")
        after = state()
        require((after.applied_configuration_hash, after.applied_configuration_valid) ==
                (before.applied_configuration_hash, before.applied_configuration_valid), "Rejection altered applied state")

    def configure(order):
        before = state()
        request = ParseDict(make_zero_bias_request(order), high.ConfigureRequest())
        control.send(high.MT2_CONFIGURE_FE_REQ, request)
        deadline = time.monotonic() + 60
        progress = []
        while not control.socket.poll(0, zmq.POLLIN):
            require(time.monotonic() < deadline, "Configure exceeded test deadline; inspect board before retrying")
            current = state()
            if current.configuration_in_progress:
                require(current.executor_task_id == control.task and current.executor_request_msg_id == control.sequence,
                        "In-progress configuration has wrong correlation")
                progress.append(current.heartbeat_sequence)
            time.sleep(0.05)
        response = control.receive(high.MT2_CONFIGURE_FE_REQ, high.ConfigureResponse)
        require(response.success, response.message)
        check_bias_acknowledgements(response.message, order)
        require(response.execution.outcome == high.CONFIGURATION_SUCCEEDED and response.execution.hardware_started,
                "Successful execution metadata missing")
        require(response.execution.task_id == control.task and response.execution.request_msg_id == control.sequence,
                "Successful attempt lost request correlation")
        require(response.applied_configuration_valid, "Complete configuration not marked valid")
        after = state()
        require(after.applied_configuration_hash == response.applied_configuration_hash and after.applied_configuration_valid,
                "Response and status disagree on applied evidence")
        require(progress and max(progress) > min(progress), "Heartbeat did not advance while Configure was observable")
        require(before.instance_id == after.instance_id, "Server restarted during Configure")
        return {"afe_order": order, "progress_observations": len(progress), "heartbeat_advances": max(progress) - min(progress),
                "execution": MessageToDict(response.execution, preserving_proto_field_name=True),
                "applied_configuration_hash": after.applied_configuration_hash}

    try:
        status = control.call(high.MT2_READ_SYSTEM_STATUS_REQ, high.ReadSystemStatusRequest(), high.SystemStatusSnapshot)
        require(status.success and status.gateware_identity.magic == 0x44415048 and
                status.gateware_identity.abi == 0x20000 and status.gateware_identity.variant == 1 and
                status.gateware_identity.build_id == args.expected_build_id, "Unexpected self-trigger board; no writes sent")
        initial = state()
        time.sleep(1.1)
        newer = state()
        require(newer.heartbeat_sequence > initial.heartbeat_sequence and newer.instance_id == initial.instance_id,
                "Heartbeat did not advance in one process")
        report = {"initial": MessageToDict(initial, preserving_proto_field_name=True), "runs": []}
        if args.apply_zero_bias_configuration:
            rejected_preserves_configuration()
            report["runs"].append(configure([0, 1, 2, 3, 4]))
            rejected_preserves_configuration()
            rewrite = control.call(high.MT2_WRITE_OFFSET_CH_REQ,
                                   make_offset_rewrite(low), low.cmd_writeOFFSET_singleChannel_response)
            require(rewrite.success, rewrite.message)
            require(not state().applied_configuration_valid, "Direct offset write did not invalidate aggregate evidence")
            report["runs"].append(configure([4, 1, 3, 0, 2]))
            require(report["runs"][0]["applied_configuration_hash"] == report["runs"][1]["applied_configuration_hash"],
                    "Canonical digest changed for equivalent AFE ordering")
            report["rejected_requests_preserve_applied_state"] = True
            report["direct_write_invalidates"] = True
        report["final"] = MessageToDict(state(), preserving_proto_field_name=True)
        report["maximum_status_round_trip_ms"] = max(latencies)
        require(max(latencies) < 1500, "Bookkeeping status exceeded the 1.5-second test response limit")
        print(json.dumps(report, indent=2))
    finally:
        for socket in sockets:
            socket.close()
        context.term()

if __name__ == "__main__":
    main()
