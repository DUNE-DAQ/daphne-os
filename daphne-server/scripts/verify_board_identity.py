#!/usr/bin/env python3
"""Read-only identity API qualification. Private values are never printed.

Requires the exact private assignment artifact. Compares assigned values and
provenance byte-for-byte, checks live binding and default-response redaction.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys


def require(ok, reason):
    if not ok:
        raise RuntimeError(reason)


def same_gateware_image(first, second):
    # Observation times/quality are additive metadata, not image identity.
    return all(getattr(first, field) == getattr(second, field)
               for field in ("magic", "abi", "variant", "build_id"))


def check_status(status, artifact, artifact_sha, high, details):
    require(status.assignment_configured and status.assignment_artifact_sha256 == artifact_sha,
            "Missing/wrong configured identity artifact")
    require(status.source_revision_sha256 == artifact.assignments.source_revision_sha256,
            "Wrong assignment source revision")
    require(status.binding_state == high.IDENTITY_BINDING_MATCH, "Management identity binding is not a match")
    require(status.observed_monotonic_ns and status.message and status.details_included == details,
            "Missing identity timing/scope or wrong detail mode")
    require(all(status.HasField(name) == details for name in ("assignments", "binding", "management")),
            "Private details leaked or requested data is missing")
    if not details:
        encoded = status.SerializeToString()
        private = [artifact.binding.expected_mac_address, artifact.assignments.management_address.value,
                   *artifact.binding.expected_ipv4_cidrs]
        for value in private:
            require(not value or value.encode() not in encoded, "Default status contains a private identity value")
        return
    require(status.assignments == artifact.assignments and status.binding == artifact.binding,
            "Returned assignments/provenance differ from the private artifact")
    observed = status.management
    binding = artifact.binding
    require(observed.quality == high.MEASUREMENT_GOOD and observed.HasField("present") and observed.present,
            "Management identity is not an available observation")
    require(observed.interface_name == binding.interface_name and observed.controller_node == binding.controller_node
            and observed.HasField("mac_address") and observed.mac_address == binding.expected_mac_address
            and set(observed.ipv4_cidrs) == set(binding.expected_ipv4_cidrs)
            and len(observed.ipv4_cidrs) == len(set(observed.ipv4_cidrs)), "Observed management identity differs from baseline")
    require(observed.HasField("interface_index") and observed.interface_index > 0
            and observed.HasField("flags_raw") and observed.HasField("interface_up") and observed.HasField("running_flag"),
            "Missing management interface metadata")
    require(observed.interface_up == bool(observed.flags_raw & 1)
            and observed.running_flag == bool(observed.flags_raw & 0x40), "Wrong Linux interface flag decoding")
    require(0 < observed.acquisition_started_monotonic_ns <= observed.observed_monotonic_ns <= status.observed_monotonic_ns
            and status.observed_monotonic_ns - observed.observed_monotonic_ns <= 5_000_000_000
            and observed.observed_host_unix_ns, "Invalid/stale network acquisition times")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--proto-dir", type=Path, required=True)
    parser.add_argument("--identity-file", type=Path, required=True)
    parser.add_argument("--expected-build-id", type=lambda value: int(value, 0), required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.proto_dir.resolve()))
    import daphneV3_high_level_confs_pb2 as high
    import zmq
    raw = args.identity_file.read_bytes()
    artifact = high.BoardIdentityAssignmentFile.FromString(raw)
    artifact_sha = hashlib.sha256(raw).hexdigest()
    report = {"success": False, "network_values": "redacted", "runs": []}
    context = zmq.Context()
    socket = context.socket(zmq.DEALER)
    socket.setsockopt(zmq.LINGER, 0)
    socket.setsockopt(zmq.RCVTIMEO, 10000)
    socket.setsockopt(zmq.SNDTIMEO, 5000)
    socket.connect(args.endpoint)
    sequence = 0

    def call(kind, body, cls):
        nonlocal sequence
        sequence += 1
        envelope = high.ControlEnvelopeV2(version=2, dir=high.DIR_REQUEST, type=kind,
                                          task_id=46, msg_id=sequence, payload=body.SerializeToString())
        socket.send(envelope.SerializeToString())
        reply = high.ControlEnvelopeV2.FromString(socket.recv())
        require(reply.version == 2 and reply.dir == high.DIR_RESPONSE and reply.type == kind + 1
                and reply.task_id == 46 and reply.correl_id == sequence and not reply.transport_error,
                "Wrong envelope/correlation or transport failure")
        return cls.FromString(reply.payload)

    try:
        default = call(high.MT2_READ_SYSTEM_STATUS_REQ, high.ReadSystemStatusRequest(), high.SystemStatusSnapshot)
        ident = default.gateware_identity
        require(default.success and ident.magic == 0x44415048 and ident.abi == 0x20000 and ident.variant == 1
                and ident.build_id == args.expected_build_id, "Unexpected board/firmware identity")
        check_status(default.board_identity, artifact, artifact_sha, high, False)
        before = call(high.MT2_READ_SERVER_STATE_REQ, high.ReadServerStateRequest(), high.ServerState)
        previous = default.board_identity.observed_monotonic_ns
        for _ in range(2):
            reply = call(high.MT2_READ_SYSTEM_STATUS_REQ, high.ReadSystemStatusRequest(include_identity_details=True), high.SystemStatusSnapshot)
            require(reply.success and not reply.sfps and same_gateware_image(reply.gateware_identity, ident),
                    "Unexpected snapshot, firmware drift or SFP access")
            check_status(reply.board_identity, artifact, artifact_sha, high, True)
            require(reply.board_identity.observed_monotonic_ns > previous, "Repeated identity observation time")
            previous = reply.board_identity.observed_monotonic_ns
            require(reply.endpoint.observation_quality == high.MEASUREMENT_GOOD and reply.endpoint.HasField("endpoint_address")
                    and reply.endpoint.endpoint_address == reply.endpoint.endpoint_control_raw & 0xffff,
                    "Missing/wrong observed timing-endpoint address")
            report["runs"].append({"binding": "match", "source_revision_sha256": reply.board_identity.source_revision_sha256,
                                   "artifact_sha256": artifact_sha, "observed_monotonic_ns": previous,
                                   "private_response_sha256": hashlib.sha256(reply.board_identity.SerializeToString()).hexdigest()})
        after = call(high.MT2_READ_SERVER_STATE_REQ, high.ReadServerStateRequest(), high.ServerState)
        require(before.success and after.success and before.instance_id == after.instance_id
                and before.applied_configuration_hash == after.applied_configuration_hash
                and before.applied_configuration_valid == after.applied_configuration_valid,
                "Identity reads changed process/FE bookkeeping")
        report["success"] = True
    except Exception as error:
        # All local assertions use canned messages. Never echo server payloads.
        report["error"] = str(error) if isinstance(error, RuntimeError) else "Identity verification failed; private details suppressed"
    finally:
        report["requests_checked"] = sequence
        print(json.dumps(report, indent=2))
        socket.close()
        context.term()
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
