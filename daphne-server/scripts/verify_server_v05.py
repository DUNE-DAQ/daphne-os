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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--proto-dir", type=Path, required=True)
    parser.add_argument("--expected-build-id", type=lambda text: int(text, 0), required=True)
    parser.add_argument("--mode", choices=("self-trigger", "full-stream"), required=True)
    parser.add_argument("--require-ams-temperatures", action="store_true",
                        help="Require all three named AMS die sensors and advancing host observation times")
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
        temperatures = check_ams_temperatures(status.temperatures, high, args.require_ams_temperatures)
        if args.require_ams_temperatures:
            require(capabilities.get("AMSTemperatures") is True, "Missing AMS capability")
            again = call(high.MT2_READ_SYSTEM_STATUS_REQ, high.ReadSystemStatusRequest(), high.SystemStatusSnapshot)
            require(again.success, again.message)
            newer = check_ams_temperatures(again.temperatures, high, True)
            previous_times = {item["name"]: item["observed_monotonic_ns"] for item in temperatures}
            require(all(item["observed_monotonic_ns"] > previous_times[item["name"]] for item in newer),
                    "AMS observation times did not advance")

        info = call(high.MT2_READ_GENERAL_INFO_REQ, high.InfoRequest(), high.GeneralInfo)
        require(info.HasField("board_voltage_status"), "Missing telemetry quality metadata")
        require(info.temperature_quality == high.MEASUREMENT_UNAVAILABLE and math.isnan(info.temperature),
                "Unbound temperature was reported as a measurement")
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
