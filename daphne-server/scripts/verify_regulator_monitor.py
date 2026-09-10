#!/usr/bin/env python3
"""Opt-in onboard PMBus readout qualification; no regulator/network/BIAS writes.

Reports regulator evidence only, never the complete private system-status reply.
PASS validates readout, not overall rail health or latched-fault clearance.
"""
import argparse
import json
import math
from pathlib import Path
import sys

ROUTES = (("+3.3VD", "U39", 0x12), ("+2.1V analog intermediate", "U42", 0x16),
          ("+3.6V analog intermediate", "U33", 0x32), ("+1.8VD", "U36", 0x36))
IDENTITY = (("MFR_SPECIFIC_00", 0xd0, 16), ("PMBUS_REVISION", 0x98, 8),
            ("CAPABILITY", 0x19, 8), ("VOUT_MODE", 0x20, 8))
READS = (("STATUS_MFR_SPECIFIC", 0x80, 8),) + tuple((n + "_BEFORE", c, w) for n, c, w in IDENTITY) + (
    ("STATUS_CML_BEFORE", 0x7e, 8), ("STATUS_WORD_BEFORE", 0x79, 16),
    ("READ_VOUT", 0x8b, 16), ("READ_IOUT", 0x8c, 16), ("READ_TEMPERATURE_2", 0x8e, 16),
    ("IOUT_CAL_GAIN", 0x38, 16), ("IOUT_CAL_OFFSET", 0x39, 16), ("STATUS_VOUT", 0x7a, 8),
    ("STATUS_IOUT", 0x7b, 8), ("STATUS_TEMPERATURE", 0x7d, 8), ("STATUS_CML_AFTER", 0x7e, 8),
    ("STATUS_WORD_AFTER", 0x79, 16)) + tuple((n + "_AFTER", c, w) for n, c, w in IDENTITY)
FLAGS = {
    0x79: ((15,"VOUT"),(14,"IOUT_POUT"),(12,"MANUFACTURER"),(11,"POWER_NOT_GOOD"),
           (6,"OFF"),(5,"VOUT_OV"),(4,"IOUT_OC"),(3,"VIN_UV"),(2,"TEMPERATURE"),(1,"CML")),
    0x7a: ((7,"VOUT_OV"),(4,"VOUT_UV")),
    0x7b: ((7,"IOUT_OC_FAULT"),(5,"IOUT_OC_WARNING")),
    0x7d: ((7,"OT_FAULT"),(6,"OT_WARNING")),
    0x7e: ((7,"INVALID_COMMAND"),(6,"INVALID_DATA"),(5,"PEC_FAILURE"),(4,"MEMORY_FAULT"),(1,"OTHER_COMMUNICATION_FAULT")),
}


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def linear11(raw):
    exponent, mantissa = divmod(raw, 2048)
    if exponent >= 16:
        exponent -= 32
    if mantissa >= 1024:
        mantissa -= 2048
    return mantissa * 2.0 ** exponent


def expected_flags(readouts):
    result = []
    for r in readouts:
        if r.command not in FLAGS:
            continue
        known = 0
        for bit, label in FLAGS[r.command]:
            known |= 1 << bit
            if r.raw & (1 << bit):
                result.append(r.name + ": " + label)
        if r.raw & (((1 << r.width_bits) - 1) ^ known):
            result.append(r.name + ": " + ("OTHER_OR_UNDOCUMENTED_BITS" if r.command == 0x79 else "UNDOCUMENTED_BITS"))
    return result


def check_profile(s, mode, build):
    i = s.gateware_identity
    require(s.success and (i.magic, i.abi, i.variant, i.build_id) ==
            (0x44415048, 0x20000, {"self-trigger": 1, "full-stream": 2}[mode], build),
            "Unexpected board/profile or status failure")


def check_regulator(r, h, index):
    require((r.name, r.schematic_reference, r.address) == ROUTES[index], "Wrong regulator/rail mapping")
    require(r.pec_required and "9c000000" in r.source and r.source and r.message,
            "Missing PEC/bus/source contract")
    require(r.identity_quality == h.MEASUREMENT_GOOD and r.identity_bracket_verified,
            "Module identity/mode bracket not verified")
    require(0 < r.acquisition_started_monotonic_ns <= r.observed_monotonic_ns
            and r.observed_monotonic_ns - r.acquisition_started_monotonic_ns <= 5_000_000_000
            and r.observed_host_unix_ns, "Invalid regulator acquisition age")
    require(tuple((v.name, v.command, v.width_bits) for v in r.registers) == READS,
            "Missing/duplicate/unexpected PMBus readout")
    previous = r.acquisition_started_monotonic_ns
    values = {}
    for v in r.registers:
        if v.command == 0x80:
            require(v.quality == h.MEASUREMENT_UNAVAILABLE and not v.HasField("raw")
                    and not v.observed_monotonic_ns and v.message, "Unqualified manufacturer status looks measured")
            continue
        require(v.quality == h.MEASUREMENT_GOOD and v.HasField("raw") and v.raw < 2 ** v.width_bits,
                "PMBus read failed or exceeds wire width: " + v.name)
        require(previous <= v.observed_monotonic_ns <= r.observed_monotonic_ns,
                "Invalid per-register observation time")
        previous = v.observed_monotonic_ns
        values[v.name] = v.raw
    for name, _, _ in IDENTITY:
        require(values[name + "_BEFORE"] == values[name + "_AFTER"], "Identity/mode changed during acquisition")
    require(values["MFR_SPECIFIC_00_BEFORE"] & 0xfc == 0x54 and values["PMBUS_REVISION_BEFORE"] == 0x11
            and values["CAPABILITY_BEFORE"] & 0x80 and values["VOUT_MODE_BEFORE"] == 0x17,
            "Unexpected PMBus module/type/format")
    voltage = values["READ_VOUT"] / 512.0  # unsigned L16, qualified mode -9.
    current = linear11(values["READ_IOUT"])
    require(0 <= voltage <= 6 and r.voltage_quality == h.MEASUREMENT_GOOD
            and r.HasField("output_voltage_v") and r.output_voltage_v == voltage, "VOUT decoding/presence mismatch")
    require(values["READ_IOUT"] >> 11 == 28 and 0 <= current <= 6 and r.current_quality == h.MEASUREMENT_GOOD
            and r.HasField("output_current_a") and r.output_current_a == current, "IOUT decoding/presence mismatch")
    t = r.temperature
    require(values["READ_TEMPERATURE_2"] >> 11 == 0 and t.valid and t.quality == h.MEASUREMENT_GOOD
            and math.isfinite(t.temperature_c) and t.temperature_c == linear11(values["READ_TEMPERATURE_2"]),
            "Regulator temperature decoding/quality mismatch")
    require(t.name == r.schematic_reference + " regulator READ_TEMPERATURE_2" and t.source and t.message
            and t.observed_host_unix_ns == r.observed_host_unix_ns
            and t.observed_monotonic_ns == next(v.observed_monotonic_ns for v in r.registers if v.command == 0x8e),
            "Temperature provenance/time mismatch")
    from verify_server_v05 import check_temperature_alarm
    check_temperature_alarm(t, h, True)
    require(r.HasField("status_changed") and r.status_changed == any(values[n + "_BEFORE"] != values[n + "_AFTER"]
            for n in ("STATUS_WORD", "STATUS_CML")), "Wrong status-change indicator")
    require(list(r.asserted_status_flags) == expected_flags(r.registers), "Status flags lost or invented")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--proto-dir", type=Path, required=True)
    parser.add_argument("--expected-build-id", type=lambda s: int(s, 0), required=True)
    parser.add_argument("--mode", choices=("self-trigger", "full-stream"), required=True)
    parser.add_argument("--read-regulators", action="store_true", required=True)
    parser.add_argument("--with-sfp", action="store_true", help="Also test one combined regulator/SFP acquisition")
    args = parser.parse_args()
    sys.path.insert(0, str(args.proto_dir.resolve()))
    import zmq
    import daphneV3_high_level_confs_pb2 as h
    from google.protobuf.json_format import MessageToDict
    context = zmq.Context()
    socket = context.socket(zmq.DEALER)
    socket.setsockopt(zmq.LINGER, 0); socket.setsockopt(zmq.RCVTIMEO, 30000); socket.setsockopt(zmq.SNDTIMEO, 3000)
    socket.connect(args.endpoint)
    sequence = 0
    report = {"success": False, "scope": "PMBus readout qualification, not overall rail/FPGA health; flags retained", "runs": []}

    def call(kind, body, cls):
        nonlocal sequence
        sequence += 1
        request = h.ControlEnvelopeV2(version=2, dir=h.DIR_REQUEST, type=kind, task_id=47,
                                      msg_id=sequence, payload=body.SerializeToString())
        socket.send(request.SerializeToString())
        reply = h.ControlEnvelopeV2.FromString(socket.recv())
        require(reply.version == 2 and reply.dir == h.DIR_RESPONSE and reply.type == kind + 1
                and reply.task_id == 47 and reply.correl_id == sequence and not reply.transport_error,
                "Bad reply/correlation or transport failure")
        return cls.FromString(reply.payload)

    try:
        before = call(h.MT2_READ_SERVER_STATE_REQ, h.ReadServerStateRequest(), h.ServerState)
        default = call(h.MT2_READ_SYSTEM_STATUS_REQ, h.ReadSystemStatusRequest(), h.SystemStatusSnapshot)
        check_profile(default, args.mode, args.expected_build_id)
        require(not default.regulators and not default.sfps, "Unexpected opt-in bus access")
        require(any(c.name == "OnboardRegulatorTelemetry" and c.supported for c in default.capabilities), "Missing regulator capability")
        previous = {}
        for repeat in range(3 if args.with_sfp else 2):
            combined = args.with_sfp and repeat == 2
            s = call(h.MT2_READ_SYSTEM_STATUS_REQ, h.ReadSystemStatusRequest(include_regulator_telemetry=True,
                     include_sfp_diagnostics=combined), h.SystemStatusSnapshot)
            check_profile(s, args.mode, args.expected_build_id)
            report["runs"].append({"regulators": [MessageToDict(r, preserving_proto_field_name=True) for r in s.regulators]})
            require(len(s.regulators) == 4, "Missing regulators")
            for index, r in enumerate(s.regulators):
                check_regulator(r, h, index)
                require(r.observed_monotonic_ns > previous.get(r.name, 0), "Regulator acquisition was reused")
                previous[r.name] = r.observed_monotonic_ns
            if combined:
                from verify_sfp_monitor import NAMES, check_port
                require(tuple(p.name for p in s.sfps) == NAMES, "Missing combined SFP routes")
                for port in s.sfps:
                    check_port(port, h)
            else:
                require(not s.sfps, "Unrequested SFP access")
        rejected = call(h.MT2_READ_SYSTEM_STATUS_REQ, h.ReadSystemStatusRequest(level=1, include_regulator_telemetry=True), h.SystemStatusSnapshot)
        require(not rejected.success and not rejected.regulators and not rejected.sfps, "Invalid request collected hardware")
        after = call(h.MT2_READ_SERVER_STATE_REQ, h.ReadServerStateRequest(), h.ServerState)
        require(before.success and after.success and before.instance_id == after.instance_id
                and before.applied_configuration_hash == after.applied_configuration_hash
                and before.applied_configuration_valid == after.applied_configuration_valid
                and not before.configuration_in_progress and not after.configuration_in_progress,
                "Monitoring changed FE evidence/process or raced configuration")
        report["success"] = True
    except Exception as e:
        report["error"] = str(e)
    finally:
        report["requests_checked"] = sequence
        print(json.dumps(report, indent=2))
        socket.close(); context.term()
    return 0 if report["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
