#!/usr/bin/env python3
"""Read-only v0.5 checks; optional invalid requests, AFE reads and gain-only test.

No clock resets, valid Configure requests, DAC writes or bus scans are sent.
The explicit --exercise-pga-gain option temporarily changes PGA gain only.
Run only against the intended board with the expected firmware build ID.
"""

import argparse
import json
import math
from pathlib import Path
import sys
import time


def check_temperature_alarm(item, high, required=False):
    """Validate policy and severity independently of acquisition quality."""
    from google.protobuf.json_format import MessageToDict
    if not item.HasField("alarm"):
        if required:
            raise RuntimeError("Missing temperature alarm evaluation: " + item.name)
        return None
    a = item.alarm
    if (not all(math.isfinite(x) for x in (a.warning_c, a.high_c, a.critical_c))
            or not -273.15 <= a.warning_c < a.high_c < a.critical_c <= 1000
            or not 1 <= a.maximum_age_ms <= 60000 or not a.evaluated_monotonic_ns
            or not a.policy_source or not a.message):
        raise RuntimeError("Invalid temperature alarm policy: " + item.name)
    if (item.quality == high.MEASUREMENT_UNAVAILABLE and not item.valid
            and math.isnan(item.temperature_c) and not item.observed_monotonic_ns
            and not item.observed_host_unix_ns):
        expected = high.TEMPERATURE_ALARM_MISSING
        age = None
    elif (item.quality != high.MEASUREMENT_GOOD or not item.valid
          or not math.isfinite(item.temperature_c) or item.temperature_c < -273.15
          or not 0 < item.observed_monotonic_ns <= a.evaluated_monotonic_ns):
        expected = high.TEMPERATURE_ALARM_INVALID
        age = None
    else:
        age = a.evaluated_monotonic_ns - item.observed_monotonic_ns
        expected = (high.TEMPERATURE_ALARM_STALE if age > a.maximum_age_ms * 1_000_000 else
                    high.TEMPERATURE_ALARM_CRITICAL if item.temperature_c >= a.critical_c else
                    high.TEMPERATURE_ALARM_HIGH if item.temperature_c >= a.high_c else
                    high.TEMPERATURE_ALARM_WARNING if item.temperature_c >= a.warning_c else
                    high.TEMPERATURE_ALARM_GOOD)
    if (a.state != expected or a.HasField("observation_age_ns") != (age is not None)
            or (age is not None and a.observation_age_ns != age)):
        raise RuntimeError("Temperature alarm disagrees with observation: " + item.name)
    return MessageToDict(a, preserving_proto_field_name=True)


def check_ams_temperatures(readings, high, require_all=False):
    """Validate the named-sensor contract without equating die and ambient temperature."""
    expected = {"Temp_LPD", "Temp_FPD", "Temp_PL"}
    names = [item.name for item in readings]
    if len(names) != len(set(names)) or (readings and set(names) != expected):
        raise RuntimeError("Incorrect AMS temperature identities")
    if require_all and set(names) != expected:
        raise RuntimeError("Missing AMS temperatures; update the server")
    report = []
    for item in readings:
        good = item.quality == high.MEASUREMENT_GOOD
        if item.valid != good or (require_all and not good):
            raise RuntimeError("Invalid AMS temperature quality: " + item.name)
        if good:
            if (not math.isfinite(item.temperature_c) or item.temperature_c < -273.15
                    or not item.observed_host_unix_ns or not item.observed_monotonic_ns):
                raise RuntimeError("Invalid AMS value or observation time: " + item.name)
            if "xilinx-ams" not in item.source or item.name not in item.source or "_input" not in item.source:
                raise RuntimeError("Missing AMS sensor provenance: " + item.name)
        elif (not math.isnan(item.temperature_c) or item.observed_host_unix_ns
              or item.observed_monotonic_ns or item.quality not in
              (high.MEASUREMENT_UNAVAILABLE, high.MEASUREMENT_ERROR)):
            raise RuntimeError("Unavailable AMS temperature looks measured: " + item.name)
        if not item.source or not item.message:
            raise RuntimeError("Missing AMS source/detail: " + item.name)
        report.append({"name": item.name, "temperature_c": item.temperature_c if good else None,
                       "quality": high.MeasurementQuality.Name(item.quality), "source": item.source,
                       "message": item.message, "observed_host_unix_ns": item.observed_host_unix_ns,
                       "observed_monotonic_ns": item.observed_monotonic_ns})
    return report


def check_carrier_temperature(readings, high, required=False):
    if not readings and not required:
        return None
    if len(readings) != 1 or readings[0].name != "Carrier_U9_MCP9808":
        raise RuntimeError("Missing or ambiguous carrier temperature identity")
    item = readings[0]
    good = item.quality == high.MEASUREMENT_GOOD
    if item.valid != good or (required and not good):
        raise RuntimeError("Carrier temperature unavailable or inconsistent")
    if good:
        if (not math.isfinite(item.temperature_c) or not -256 <= item.temperature_c < 256
                or not item.observed_monotonic_ns or not item.observed_host_unix_ns
                or not all(value in item.source for value in ("U9 MCP9808", "ff030000", "0x18"))):
            raise RuntimeError("Invalid carrier temperature/source/time")
    elif not math.isnan(item.temperature_c) or item.observed_monotonic_ns or item.observed_host_unix_ns:
        raise RuntimeError("Invalid carrier reading looks measured")
    return {"name": item.name, "temperature_c": item.temperature_c if good else None,
            "quality": high.MeasurementQuality.Name(item.quality), "source": item.source,
            "observed_monotonic_ns": item.observed_monotonic_ns}


def check_service_status(status, high, required=False):
    from google.protobuf.json_format import MessageToDict
    units = {"daphne-runtime.target", "daphne-gateware-prepare.service", "firmware.service",
             "daphne-gateware-verify.service", "clockchip.service", "endpoint.service",
             "hermes.service", "daphne.service"}
    names = [item.name for item in status.services]
    if not names and not required:
        return []
    if set(names) != units or len(names) != len(units):
        raise RuntimeError("Missing, duplicate or unexpected runtime-chain unit")
    for item in status.services:
        if item.quality == high.MEASUREMENT_GOOD:
            if not all((item.load_state, item.active_state, item.sub_state, item.observed_monotonic_ns,
                        item.observed_host_unix_ns, item.message)):
                raise RuntimeError("Incomplete good service observation")
        elif required or item.observed_monotonic_ns or item.HasField("main_pid"):
            raise RuntimeError("Service observation unavailable or falsely measured")
    if required:
        server = next(item for item in status.services if item.name == "daphne.service")
        if (server.active_state != "active" or server.sub_state != "running" or not server.main_pid
                or not server.HasField("automatic_restarts") or len(server.invocation_id) != 32
                or status.server_instance_id != server.invocation_id or not status.server_uptime_ms
                or not status.hostname or not status.kernel_release or not status.petalinux_version):
            raise RuntimeError("Missing server process identity, uptime or host metadata")
    return [MessageToDict(item, preserving_proto_field_name=True) for item in status.services]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--proto-dir", type=Path, required=True)
    parser.add_argument("--expected-build-id", type=lambda text: int(text, 0), required=True)
    parser.add_argument("--mode", choices=("self-trigger", "full-stream"), required=True)
    parser.add_argument("--require-ams-temperatures", action="store_true",
                        help="Require all three named AMS die sensors and advancing host observation times")
    parser.add_argument("--require-carrier-temperature", action="store_true")
    parser.add_argument("--require-voltages", action="store_true",
                        help="Require good voltage acquisition and refreshed cache timestamps")
    parser.add_argument("--require-services", action="store_true",
                        help="Require eight service observations and matching server process identity")
    parser.add_argument("--require-temperature-alarms", action="store_true",
                        help="Require active policy and correct alarm evaluation on all named temperature observations")
    parser.add_argument("--check-rejections", action="store_true",
                        help="Send intentionally invalid configuration requests; no writes expected")
    parser.add_argument("--afe-readback", action="store_true",
                        help="Read AFE register 51 via SPI (controller writes implement these reads)")
    parser.add_argument("--exercise-pga-gain", action="store_true",
                        help="MAINTENANCE ONLY: exercise both PGA gain codes on all AFEs and restore register 51")
    args = parser.parse_args()
    sys.path.insert(0, str(args.proto_dir.resolve()))
    import zmq
    import daphneV3_high_level_confs_pb2 as high
    import daphneV3_low_level_confs_pb2 as low

    def require(ok, message):
        if not ok:
            raise RuntimeError(message)

    context = zmq.Context()
    socket = context.socket(zmq.DEALER)
    socket.setsockopt(zmq.LINGER, 0)
    socket.setsockopt(zmq.RCVTIMEO, 5000)
    socket.setsockopt(zmq.SNDTIMEO, 5000)
    socket.connect(args.endpoint)
    sequence = 0

    def call(kind, request, response_class):
        nonlocal sequence
        sequence += 1
        payload = request if isinstance(request, bytes) else request.SerializeToString()
        envelope = high.ControlEnvelopeV2(version=2, dir=high.DIR_REQUEST,
                                          type=kind, msg_id=sequence, task_id=1, payload=payload)
        socket.send(envelope.SerializeToString())
        reply = high.ControlEnvelopeV2.FromString(socket.recv())
        require(not getattr(reply, "transport_error", ""), getattr(reply, "transport_error", ""))
        require(reply.version == 2 and reply.dir == high.DIR_RESPONSE and reply.type == kind + 1,
                "Wrong response envelope")
        require(reply.correl_id == sequence and reply.task_id == 1, "Wrong response correlation")
        return response_class.FromString(reply.payload)

    try:
        status = call(high.MT2_READ_SYSTEM_STATUS_REQ, high.ReadSystemStatusRequest(), high.SystemStatusSnapshot)
        require(status.success, status.message)
        identity = status.gateware_identity
        require(identity.magic == 0x44415048 and identity.abi == 0x20000, "Not ABI 2")
        require(identity.build_id == args.expected_build_id, "Firmware build mismatch")
        require(identity.variant == (1 if args.mode == "self-trigger" else 2), "Firmware variant mismatch")
        timing = status.endpoint
        require(timing.observation_quality == high.MEASUREMENT_GOOD, "Timing read unavailable")
        expected_ready = (timing.endpoint_clock_control_raw & 7) == 4
        expected_ready &= (timing.endpoint_clock_status_raw & 3) == 3
        expected_ready &= (timing.endpoint_control_raw & 0x10000) == 0
        expected_ready &= (timing.endpoint_status_raw & 31) == 24
        require(timing.ready == expected_ready, "Timing readiness contradicts raw registers")
        require(timing.live_timestamp_quality == high.MEASUREMENT_UNAVAILABLE, "Live timestamp must be unavailable")
        capabilities = {item.name: item.supported for item in status.capabilities}
        for name in ("LiveTimingTimestamp", "ProtocolErrorCount", "CommandDecoderMap", "CrateSlotDetectorReadback"):
            require(capabilities.get(name) is False, "Incorrect capability: " + name)
        def die_readings(snapshot):
            return [item for item in snapshot.temperatures if item.name != "Carrier_U9_MCP9808"]
        temperatures = check_ams_temperatures(die_readings(status), high, args.require_ams_temperatures)
        carrier = check_carrier_temperature([item for item in status.temperatures if item.name == "Carrier_U9_MCP9808"],
                                            high, args.require_carrier_temperature)
        services = check_service_status(status, high, args.require_services)
        if args.require_ams_temperatures:
            require(capabilities.get("AMSTemperatures") is True, "Missing AMS capability")
            again = call(high.MT2_READ_SYSTEM_STATUS_REQ, high.ReadSystemStatusRequest(), high.SystemStatusSnapshot)
            require(again.success, again.message)
            newer = check_ams_temperatures(die_readings(again), high, True)
            previous_times = {item["name"]: item["observed_monotonic_ns"] for item in temperatures}
            require(all(item["observed_monotonic_ns"] > previous_times[item["name"]] for item in newer),
                    "AMS observation times did not advance")

        info = call(high.MT2_READ_GENERAL_INFO_REQ, high.InfoRequest(), high.GeneralInfo)
        require(info.HasField("board_voltage_status"), "Missing telemetry quality metadata")
        if info.temperature_quality == high.MEASUREMENT_GOOD:
            require(math.isfinite(info.temperature) and "U9 MCP9808" in info.temperature_detail,
                    "Unnamed temperature has no identified carrier source")
        else:
            require(math.isnan(info.temperature), "Invalid temperature looks measured")
        if args.require_carrier_temperature:
            require(info.temperature_quality == high.MEASUREMENT_GOOD, "GeneralInfo carrier binding unavailable")
            require(info.HasField("temperature_status"), "Missing carrier observation metadata")
            check_carrier_temperature([info.temperature_status], high, True)
            require(info.temperature == info.temperature_status.temperature_c, "Mixed carrier temperature observations")
        volts = info.board_voltage_status
        require(len(volts.named_voltages) == 10, "Expected ten named voltage channels")
        legacy = [info.v_bias_0, info.v_bias_1, info.v_bias_2, info.v_bias_3, info.v_bias_4,
                  info.power_minus5v, info.power_plus2p5v, info.power_ce]
        if volts.quality == high.MEASUREMENT_GOOD:
            require(all(math.isfinite(value) for value in legacy), "Good telemetry contains invalid numbers")
            require(volts.observed_monotonic_ns > 0, "Missing acquisition time")
        else:
            require(all(math.isnan(value) for value in legacy), "Unavailable telemetry contains apparent measurements")
            require(all(math.isnan(item.volts) for item in volts.named_voltages), "Invalid named voltage")
        if args.require_voltages:
            require(volts.quality == high.MEASUREMENT_GOOD, "Voltage acquisition unavailable")
            require(all("ff030000" in item.source for item in volts.named_voltages), "Wrong ADC controller provenance")
            require([item.source.rsplit(" ", 1)[-1] for item in volts.named_voltages[7:]] == ["2", "5", "7"],
                    "Wrong physical ADC channel labels")
            time.sleep(0.6)
            fresh = call(high.MT2_READ_GENERAL_INFO_REQ, high.InfoRequest(), high.GeneralInfo)
            require(fresh.board_voltage_status.quality == high.MEASUREMENT_GOOD and
                    fresh.board_voltage_status.observed_monotonic_ns > volts.observed_monotonic_ns,
                    "Voltage acquisition did not refresh")

        counters = call(high.MT2_READ_TRIGGER_COUNTERS_REQ, high.ReadTriggerCountersRequest(),
                        high.ReadTriggerCountersResponse)
        if args.mode == "self-trigger":
            require(counters.success, counters.message)
            require([item.channel for item in counters.snapshots] == list(range(40)), "Missing counter channels")
            require(all(item.threshold <= 0xFFFFFFF for item in counters.snapshots), "Invalid threshold width")
        else:
            require(not counters.success and not counters.snapshots, "Full-stream returned self-trigger counters")

        report = {"firmware_build": hex(identity.build_id), "mode": args.mode,
                  "timing_ready": timing.ready, "timing_raw": [timing.endpoint_clock_control_raw,
                   timing.endpoint_clock_status_raw, timing.endpoint_control_raw, timing.endpoint_status_raw],
                  "voltage_quality": high.MeasurementQuality.Name(volts.quality),
                  "voltage_detail": volts.detail, "counter_channels": len(counters.snapshots)}
        report["ams_temperatures"] = temperatures
        report["carrier_temperature"] = carrier
        report["general_info_temperature_c"] = info.temperature if math.isfinite(info.temperature) else None
        if args.require_temperature_alarms and len(status.temperatures) != 4:
            raise RuntimeError("Missing named temperature observations for alarm qualification")
        report["temperature_alarms"] = {
            item.name: check_temperature_alarm(item, high, args.require_temperature_alarms)
            for item in status.temperatures}
        report["general_info_temperature_alarm"] = check_temperature_alarm(
            info.temperature_status, high, args.require_temperature_alarms)
        report["voltages"] = [{"name": item.name, "volts": item.volts if math.isfinite(item.volts) else None,
                               "source": item.source} for item in volts.named_voltages]
        report["services"] = services
        report["server_instance_id"] = status.server_instance_id
        report["server_uptime_ms"] = status.server_uptime_ms
        report["kernel_release"] = status.kernel_release
        report["petalinux_version"] = status.petalinux_version
        report["host_values"] = [{"name": item.name, "value": item.value, "source": item.source,
                                  "valid": item.valid} for item in status.ps_values]
        if args.require_voltages:
            report["voltage_observation_times_advanced"] = True
        if args.require_ams_temperatures:
            report["ams_observation_times_advanced"] = True
        if args.check_rejections:
            for request in (high.ReadTriggerCountersRequest(channels=[40]),
                            high.ReadTriggerCountersRequest(base_addr=0x94000000)):
                result = call(high.MT2_READ_TRIGGER_COUNTERS_REQ, request, high.ReadTriggerCountersResponse)
                require(not result.success and not result.snapshots, "Invalid counter request accepted")
            bad = call(high.MT2_READ_GENERAL_INFO_REQ, b"\x80", high.GeneralInfo)
            require(bad.board_voltage_status.quality == high.MEASUREMENT_ERROR and math.isnan(bad.v_bias_0),
                    "Malformed info request returned apparent measurements")
            bad = call(high.MT2_READ_SYSTEM_STATUS_REQ, high.ReadSystemStatusRequest(include_i2c_scan=True),
                       high.SystemStatusSnapshot)
            require(not bad.success, "Unsupported bus scan accepted")
            # A valid full-stream list gets past mode validation to exercise analog preflight.
            config = high.ConfigureRequest(full_stream_channels=[0] if args.mode == "full-stream" else [])
            # Gain 1/2 are valid offset multipliers now. Never send those as a
            # rejection-only probe: a valid Configure request also enables HV.
            config.channels.add(id=0, gain=3)
            result = call(high.MT2_CONFIGURE_FE_REQ, config, high.ConfigureResponse)
            require(not result.success and "ChannelConfig.gain" in result.message, "Invalid gain accepted")
            config.channels[0].gain = 0
            config.biasctrl = 4096
            result = call(high.MT2_CONFIGURE_FE_REQ, config, high.ConfigureResponse)
            require(not result.success and "Bias Control out of range" in result.message, "Invalid bias accepted")
            report["rejection_checks"] = "passed"
        if args.afe_readback or args.exercise_pga_gain:
            report["afe_register_51"] = []
            for afe in range(5):
                result = call(high.MT2_READ_AFE_REG_REQ, low.cmd_readAFEReg(afeBlock=afe, regAddress=51),
                              low.cmd_readAFEReg_response)
                require(result.success, result.message)
                require(result.hardware_readback and result.observed_monotonic_ns > 0,
                        "AFE response is not fresh hardware readback; do not exercise gain")
                report["afe_register_51"].append(result.regValue)
        if args.exercise_pga_gain:
            report["pga_gain_restore"] = []
            for afe, original in enumerate(report["afe_register_51"]):
                try:
                    for gain in (0, 1):
                        written = call(high.MT2_WRITE_AFE_FUNCTION_REQ,
                                       low.cmd_writeAFEFunction(afeBlock=afe, function="PGA_GAIN_CONTROL", configValue=gain),
                                       low.cmd_writeAFEFunction_response)
                        require(written.success and written.configValue == gain and written.afeBlock == afe,
                                "PGA gain write/readback failed for AFE " + str(afe) + ": " + written.message)
                        read = call(high.MT2_READ_AFE_REG_REQ, low.cmd_readAFEReg(afeBlock=afe, regAddress=51),
                                    low.cmd_readAFEReg_response)
                        expected = (original & ~0x2000) | (gain << 13)
                        require(read.success and read.hardware_readback and read.regValue == expected,
                                "PGA register mismatch for AFE {}: expected {}, got {}".format(
                                    afe, hex(expected), hex(read.regValue)))
                finally:
                    restored = call(high.MT2_WRITE_AFE_REG_REQ,
                                    low.cmd_writeAFEReg(afeBlock=afe, regAddress=51, regValue=original),
                                    low.cmd_writeAFEReg_response)
                    read = call(high.MT2_READ_AFE_REG_REQ, low.cmd_readAFEReg(afeBlock=afe, regAddress=51),
                                low.cmd_readAFEReg_response)
                    require(restored.success and read.success and read.hardware_readback and read.regValue == original,
                            "STOP: could not verify restoring AFE " + str(afe) + " register 51")
                report["pga_gain_restore"].append("verified")
        report["requests_checked"] = sequence
        print(json.dumps(report, indent=2))
    finally:
        socket.close()
        context.term()


if __name__ == "__main__":
    main()
