#!/usr/bin/env python3
"""Opt-in SFP diagnostics: six targeted mux routes, restored; no TX/reset/BIAS writes.

Checks transport/protocol integrity, not that every cage is populated or every
link is healthy. Factory warning/alarm flags are reported, never hidden by PASS.
"""
import argparse
import json
import math
from pathlib import Path
import struct
import sys

NAMES = ("GTH2", "GTH1", "GTH0", "TMG", "GTH3", "GTR")
QUANTITIES = ("temperature", "vcc", "tx_bias", "tx_power", "rx_power")
FIELDS = ("temperature_c", "vcc_v", "tx_bias_ma", "tx_power_mw", "rx_power_mw")
UNITS = ("degC", "V", "mA", "mW", "mW")


def require(ok, reason):
    if not ok:
        raise RuntimeError(reason)


def decoded_value(static, index, raw, external):
    value = raw - 65536 if index == 0 and raw & 0x8000 else raw
    if external:
        if index == 4:
            coefficients = struct.unpack(">5f", static[56:76])
            require(all(math.isfinite(c) for c in coefficients), "Bad external RX calibration")
            value = sum(c * raw ** power for c, power in zip(coefficients, (4, 3, 2, 1, 0)))
        else:
            offset = (84, 88, 76, 80)[index]
            slope, intercept = struct.unpack(">Hh", static[offset:offset + 4])
            require(slope != 0, "Zero external calibration slope")
            value = value * slope / 256 + intercept
    return value * (1 / 256, 1e-4, .002, 1e-4, 1e-4)[index]


def check_port(p, h):
    require(p.name in NAMES and p.mux_channel == NAMES.index(p.name), "Wrong connector/mux mapping")
    require(p.mux_address == 0x72 and p.a0_address == 0x50 and p.a2_address == 0x51
            and "9c000000" in p.source, "Wrong SFP bus provenance")
    require(p.HasField("mux_restored") and p.mux_restored and p.HasField("previous_mux_route"),
            "SFP mux restoration not proven")
    require(0 < p.acquisition_started_monotonic_ns <= p.observed_monotonic_ns and p.observed_host_unix_ns,
            "Missing acquisition-attempt times")
    if p.identity_quality != h.MEASUREMENT_GOOD:
        require(p.identity_quality == h.MEASUREMENT_ERROR and not p.HasField("present") and p.message,
                "Failed I2C/identity check is reported as physical absence")
        require(all(not p.HasField(f) for f in FIELDS), "Failed identity contains measurements")
        require(all(q.quality != h.MEASUREMENT_GOOD and not q.HasField("value") for q in p.quantities),
                "Failed identity contains typed measurements")
        return
    require(p.HasField("present") and p.present, "Verified identity lacks presence")
    a0 = p.a0_raw
    require(len(a0) == 96 and a0[0:2] == b"\x03\x04", "Missing SFP identity bytes")
    require(sum(a0[:63]) % 256 == a0[63] and sum(a0[64:95]) % 256 == a0[95], "Identity checksum mismatch")
    require(p.base_checksum_valid and p.extended_checksum_valid
            and p.diagnostic_type == a0[92] and p.enhanced_options == a0[93], "Wrong identity metadata")
    require(p.HasField("identity_eeprom_readable") and p.identity_eeprom_readable
            and p.HasField("dom_supported") and p.dom_supported == bool(a0[92] & 0x40), "Missing readability/DOM advertisement")
    oui = int.from_bytes(a0[37:40], "big")
    rate = a0[66] * 250 if a0[12] == 255 else a0[12] * 100
    wavelength = int.from_bytes(a0[60:62], "big") if not a0[8] & 0x0c else 0
    for field, expected in (("vendor_oui", oui), ("nominal_signaling_rate_mbd", rate), ("wavelength_nm", wavelength)):
        require(p.HasField(field) == bool(expected) and (not expected or getattr(p, field) == expected),
                "Wrong/missing or fabricated SFP inventory field: " + field)
    if not a0[92] & 0x40 or a0[92] & 0x84:
        require(p.diagnostic_quality == h.MEASUREMENT_UNAVAILABLE and not p.a2_static_raw
                and all(not p.HasField(f) for f in FIELDS), "Unsupported diagnostics look measured")
        return
    require((a0[92] & 0x30) in (0x10, 0x20), "Contradictory or missing calibration")
    static, live = p.a2_static_raw, p.a2_monitor_raw
    require(len(static) == 96 and sum(static[:95]) % 256 == static[95]
            and p.diagnostic_checksum_valid, "Diagnostic checksum mismatch")
    require(len(live) == 16 and not live[14] & 1 and p.HasField("data_ready") and p.data_ready,
            "Diagnostics are not ready")
    require(p.HasField("diagnostic_eeprom_readable") and p.diagnostic_eeprom_readable
            and p.HasField("rate_select_raw") and p.rate_select_raw == ((live[14] >> 3) & 7),
            "Missing DMI readability or raw rate-select bits")
    require(p.acquisition_started_monotonic_ns <= p.diagnostics_observed_monotonic_ns <= p.observed_monotonic_ns,
            "Wrong diagnostic acquisition time")
    require(p.status_a2_0x6e == live[14] and p.status_a2_0x6f == live[15], "Wrong raw status")
    require(len(p.quantities) == 5 and tuple(q.name for q in p.quantities) == QUANTITIES, "Wrong quantities")
    require(p.diagnostic_quality == (h.MEASUREMENT_UNAVAILABLE if p.HasField("tx_disabled") and p.tx_disabled
                                    else h.MEASUREMENT_GOOD), "Wrong aggregate diagnostic quality")
    external = bool(a0[92] & 0x10)
    require(p.calibration == (h.SFP_CALIBRATION_EXTERNAL if external else h.SFP_CALIBRATION_INTERNAL),
            "Wrong calibration source")
    for i, q in enumerate(p.quantities):
        raw = int.from_bytes(live[2 * i:2 * i + 2], "big")
        require(q.raw_code == raw and q.units == UNITS[i], "Wrong raw code/units")
        if i == 3 and p.HasField("tx_disabled") and p.tx_disabled:
            require(q.quality == h.MEASUREMENT_UNAVAILABLE and not q.HasField("value")
                    and not p.HasField(FIELDS[i]), "Disabled TX power looks valid")
        else:
            expected = decoded_value(static, i, raw, external)
            require(q.quality == h.MEASUREMENT_GOOD and q.HasField("value")
                    and math.isfinite(q.value) and math.isclose(q.value, expected, abs_tol=1e-9, rel_tol=1e-9),
                    "Calibrated value mismatch")
            require(p.HasField(FIELDS[i]) and getattr(p, FIELDS[i]) == q.value, "Legacy/typed value mismatch")
        if q.threshold_quality == h.MEASUREMENT_GOOD:
            for j, field in enumerate(("high_alarm", "low_alarm", "high_warning", "low_warning")):
                expected = decoded_value(static, i, int.from_bytes(static[8 * i + j * 2:8 * i + j * 2 + 2], "big"), external)
                require(q.HasField(field) and math.isclose(getattr(q, field), expected, abs_tol=1e-9, rel_tol=1e-9),
                        "Factory threshold scaling mismatch")
    for field, option, mask in (("tx_disabled", 0x40, 0xc0), ("tx_fault", 0x20, 4), ("loss_of_signal", 0x10, 2)):
        require(p.HasField(field) == bool(a0[93] & option), "Unadvertised status is not unknown")
        if p.HasField(field):
            require(getattr(p, field) == bool(live[14] & mask), "Wrong optional status")
    if a0[93] & 0x80:
        require(p.HasField("alarm_flags") and p.HasField("warning_flags"), "Missing advertised flags")
        require(p.diagnostics_observed_monotonic_ns <= p.flags_observed_monotonic_ns <= p.observed_monotonic_ns,
                "Invalid flag observation time")
        if (p.alarm_flags | p.warning_flags) & 0xffc0:
            require(p.HasField("alarm_flags_second") and p.HasField("warning_flags_second")
                    and p.flags_second_monotonic_ns - p.flags_observed_monotonic_ns >= 100_000_000
                    and p.flags_second_monotonic_ns <= p.observed_monotonic_ns,
                    "Asserted flags lack delayed confirmation")
        for i, q in enumerate(p.quantities):
            for field, value, mask in (
                ("high_alarm_flag", p.alarm_flags | p.alarm_flags_second, 0x8000 >> (2*i)),
                ("low_alarm_flag", p.alarm_flags | p.alarm_flags_second, 0x4000 >> (2*i)),
                ("high_warning_flag", p.warning_flags | p.warning_flags_second, 0x8000 >> (2*i)),
                ("low_warning_flag", p.warning_flags | p.warning_flags_second, 0x4000 >> (2*i))):
                require(q.HasField(field) and getattr(q, field) == bool(value & mask), "Wrong observed flag union")
    require(p.temperature_alarm.state != h.TEMPERATURE_ALARM_UNSPECIFIED, "Missing host temperature alarm")
    from verify_server_v05 import check_temperature_alarm
    t = h.TemperatureStatus(name=p.name + "_SFP", temperature_c=p.temperature_c,
                            valid=p.HasField("temperature_c"), quality=h.MEASUREMENT_GOOD,
                            observed_monotonic_ns=p.diagnostics_observed_monotonic_ns,
                            observed_host_unix_ns=p.observed_host_unix_ns)
    t.alarm.CopyFrom(p.temperature_alarm)
    check_temperature_alarm(t, h, True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--proto-dir", type=Path, required=True)
    parser.add_argument("--expected-build-id", type=lambda s: int(s, 0), required=True)
    parser.add_argument("--require-inventory", nargs="+", choices=NAMES, required=True)
    parser.add_argument("--read-sfp", action="store_true", required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.proto_dir.resolve()))
    import zmq
    import daphneV3_high_level_confs_pb2 as h
    from google.protobuf.json_format import MessageToDict
    context = zmq.Context()
    socket = context.socket(zmq.DEALER)
    socket.setsockopt(zmq.LINGER, 0)
    socket.setsockopt(zmq.RCVTIMEO, 20000)
    socket.setsockopt(zmq.SNDTIMEO, 3000)
    socket.connect(args.endpoint)
    sequence = 0
    report = {"success": False, "scope": "SFP readout, not proof of link health or unresponsive-cage absence", "runs": []}

    def call(kind, body, cls):
        nonlocal sequence
        sequence += 1
        request = h.ControlEnvelopeV2(version=2, dir=h.DIR_REQUEST, type=kind, task_id=45,
                                      msg_id=sequence, payload=body.SerializeToString())
        socket.send(request.SerializeToString())
        reply = h.ControlEnvelopeV2.FromString(socket.recv())
        require(reply.version == 2 and reply.dir == h.DIR_RESPONSE and reply.type == kind + 1
                and reply.task_id == 45 and reply.correl_id == sequence and not reply.transport_error,
                "Bad reply/correlation or transport failure")
        return cls.FromString(reply.payload)
    try:
        status = call(h.MT2_READ_SYSTEM_STATUS_REQ, h.ReadSystemStatusRequest(), h.SystemStatusSnapshot)
        ident = status.gateware_identity
        require(status.success and ident.magic == 0x44415048 and ident.abi == 0x20000 and ident.variant == 1
                and ident.build_id == args.expected_build_id and not status.sfps,
                "Unexpected board/profile or unrequested SFP collection")
        require(any(c.name == "SFPDiagnostics" and c.supported for c in status.capabilities), "Server lacks SFP capability")
        before = call(h.MT2_READ_SERVER_STATE_REQ, h.ReadServerStateRequest(), h.ServerState)
        previous = {}
        for repeat in range(2):
            snapshot = call(h.MT2_READ_SYSTEM_STATUS_REQ, h.ReadSystemStatusRequest(include_sfp_diagnostics=True), h.SystemStatusSnapshot)
            report["runs"].append({"sfps": [MessageToDict(p, preserving_proto_field_name=True) for p in snapshot.sfps]})
            require(snapshot.success and tuple(p.name for p in snapshot.sfps) == NAMES, "Missing/duplicate/wrong SFP routes")
            for port in snapshot.sfps:
                check_port(port, h)
                require(port.observed_monotonic_ns > previous.get(port.name, 0), "Repeated host acquisition time")
                previous[port.name] = port.observed_monotonic_ns
                if port.name in args.require_inventory:
                    require(port.identity_quality == h.MEASUREMENT_GOOD, "Required SFP identity unavailable: " + port.name)
        after = call(h.MT2_READ_SERVER_STATE_REQ, h.ReadServerStateRequest(), h.ServerState)
        require(before.success and after.success and before.instance_id == after.instance_id
                and before.applied_configuration_hash == after.applied_configuration_hash
                and before.applied_configuration_valid == after.applied_configuration_valid, "SFP reads changed FE evidence/process")
        report["success"] = True
    except Exception as e:
        report["error"] = str(e)
    finally:
        report["requests_checked"] = sequence
        print(json.dumps(report, indent=2))
        socket.close()
        context.term()
    return 0 if report["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
