#!/usr/bin/env python3
"""Explicit ADC/carrier-mux qualification; no BIAS, DAC or power writes.

Requires a previously configured zero-BIAS bench and expected self-trigger build.
Checks all 40 physical channels twice. Raw ADC voltages are not calibrated SiPM current.
"""
import argparse
import json
import math
from pathlib import Path
import sys


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def check_current_sample(r, channel, low):
    require(r.success and r.quality == low.CURRENT_MONITOR_GOOD, r.message)
    require(r.currentMonitorChannel == channel, "Wrong physical channel")
    require(r.HasField("carrier_mux_restored") and r.carrier_mux_restored, "Carrier mux not restored")
    require(r.carrier_mux_enable == (1 if channel % 8 < 4 else 2)
            and r.carrier_mux_address == channel % 4, "Wrong carrier mux selection")
    require(r.HasField("adc_id") and r.adc_id >> 4 == 8
            and r.HasField("adc_input_mux") and r.adc_input_mux == 0x21 + 0x22 * (channel // 8)
            and r.HasField("adc_status") and r.adc_status == 4, "ADC identity/mux/status mismatch")
    require(r.HasField("raw_code") and -8388608 < r.raw_code < 8388607 and not r.saturated,
            "Missing or saturated raw code")
    require(r.currentValue == (r.raw_code & 0xffffffff), "Legacy raw encoding mismatch")
    require(r.HasField("differential_volts") and math.isfinite(r.differential_volts)
            and abs(r.differential_volts - r.raw_code * 2.5 / 8388608) < 1e-12,
            "Wrong nominal ADC voltage scaling")
    require(r.pga_gain == 1 and r.pga_bypassed and r.nominal_reference_volts == 2.5,
            "Unexpected measurement profile")
    require(r.observed_monotonic_ns and r.observed_host_unix_ns and "ADS1261" in r.source
            and "9c020000" in r.source, "Missing acquisition provenance")
    require(not r.HasField("current_amperes") and r.current_quality == low.CURRENT_MONITOR_UNAVAILABLE
            and r.current_detail, "Uncalibrated current looks measured")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--proto-dir", type=Path, required=True)
    parser.add_argument("--expected-build-id", type=lambda x: int(x, 0), required=True)
    parser.add_argument("--measure-current", action="store_true", required=True,
                        help="Authorize ADC setup and temporary carrier-mux selection, restored after each read")
    args = parser.parse_args()
    sys.path.insert(0, str(args.proto_dir.resolve()))
    import zmq
    import daphneV3_high_level_confs_pb2 as high
    import daphneV3_low_level_confs_pb2 as low
    from google.protobuf.json_format import MessageToDict
    context = zmq.Context()
    socket = context.socket(zmq.DEALER)
    socket.setsockopt(zmq.LINGER, 0)
    socket.setsockopt(zmq.RCVTIMEO, 5000)
    socket.setsockopt(zmq.SNDTIMEO, 5000)
    socket.connect(args.endpoint)
    sequence = 0
    report = {"success": False, "samples": [], "scope": "Onboard ADC and carrier mux, not calibrated SiPM current"}

    def call(kind, request, response_class):
        nonlocal sequence
        sequence += 1
        env = high.ControlEnvelopeV2(version=2, dir=high.DIR_REQUEST, type=kind,
                                     task_id=44, msg_id=sequence, payload=request.SerializeToString())
        socket.send(env.SerializeToString())
        reply = high.ControlEnvelopeV2.FromString(socket.recv())
        require(reply.version == 2 and reply.dir == high.DIR_RESPONSE and reply.type == kind + 1
                and reply.task_id == 44 and reply.correl_id == sequence, "Wrong response envelope")
        require(not reply.transport_error, reply.transport_error)
        return response_class.FromString(reply.payload)

    try:
        status = call(high.MT2_READ_SYSTEM_STATUS_REQ, high.ReadSystemStatusRequest(), high.SystemStatusSnapshot)
        i = status.gateware_identity
        require(status.success and i.magic == 0x44415048 and i.abi == 0x20000 and i.variant == 1
                and i.build_id == args.expected_build_id, "Unexpected self-trigger firmware; no ADC request sent")
        biasctrl = call(high.MT2_READ_VBIAS_CONTROL_REQ, low.cmd_readVbiasControl(), low.cmd_readVbiasControl_response)
        require(biasctrl.success and biasctrl.vBiasControlValue == 0, "Configure full zero-BIAS profile before testing")
        for afe in range(5):
            bias = call(high.MT2_READ_AFE_BIAS_SET_REQ, low.cmd_readAFEBiasSet(afeBlock=afe), low.cmd_readAFEBiasSet_response)
            require(bias.success and bias.biasValue == 0, "Nonzero BIAS cache; no ADC request sent")
        before = call(high.MT2_READ_SERVER_STATE_REQ, high.ReadServerStateRequest(), high.ServerState)
        require(before.applied_configuration_valid, "Full FE configuration evidence is required before testing")
        for request in (low.cmd_readCurrentMonitor(), low.cmd_readCurrentMonitor(currentMonitorChannel=1),
                        low.cmd_readCurrentMonitor(physical_channel=40),
                        low.cmd_readCurrentMonitor(physical_channel=0, currentMonitorChannel=1)):
            rejected = call(high.MT2_READ_CURRENT_MONITOR_REQ, request, low.cmd_readCurrentMonitor_response)
            require(not rejected.success and rejected.quality == low.CURRENT_MONITOR_ERROR
                    and not rejected.HasField("raw_code") and not rejected.HasField("carrier_mux_restored"),
                    "Invalid/ambiguous request was not rejected before measurement")
        observations = {}
        for repeat in range(2):
            for channel in range(40):
                reading = call(high.MT2_READ_CURRENT_MONITOR_REQ, low.cmd_readCurrentMonitor(physical_channel=channel),
                               low.cmd_readCurrentMonitor_response)
                report["samples"].append({"repeat": repeat, "physical_channel": channel,
                    "response": MessageToDict(reading, preserving_proto_field_name=True)})
                check_current_sample(reading, channel, low)
                require(reading.observed_monotonic_ns > observations.get(channel, 0), "Stale/repeated acquisition metadata")
                observations[channel] = reading.observed_monotonic_ns
        after = call(high.MT2_READ_SERVER_STATE_REQ, high.ReadServerStateRequest(), high.ServerState)
        require(after.applied_configuration_valid and after.applied_configuration_hash == before.applied_configuration_hash
                and after.instance_id == before.instance_id, "Monitor operation altered FE evidence or restarted server")
        report["unchanged_fe_configuration"] = True
        report["success"] = True
    except Exception as error:
        report["error"] = str(error)
    finally:
        report["requests_checked"] = sequence
        socket.close()
        context.term()
        print(json.dumps(report, indent=2))
    return 0 if report["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
