#!/usr/bin/env python3
"""MAINTENANCE: full Configure with five BIAS=0 values and BIASCTRL=0.

No low-level bias-write workaround and no nonzero bias values. Applies the
reference FE profile twice, in different AFE orders, then checks alignment,
fresh AFE registers, bias command caches and all 40 spybuffer channels.
Leaves offset=2200/x1, trim=0, VGAIN=1700. Requires the pinned corrected server;
checks fresh BiasEnable samples before/after Configure and after capture without
toggling enable. Equal endpoint samples do not prove absence of short glitches.
Successful command/cache checks do NOT constitute analog voltage readback.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import time

from verify_offset_gain_spybuffer import summarize, usable_capture, zero_bias_profile
from afe_global import check_afe_global, require
from software_build import check_build
from verify_server_bookkeeping import check_state


def make_zero_bias_request(order):
    if sorted(order) != list(range(5)):
        raise ValueError("Exactly one entry for each board AFE 0..4 is required")
    profile = zero_bias_profile(2200, 1)
    profile["afes"] = [profile["afes"][afe] for afe in order]
    return profile


def check_bias_acknowledgements(message, order):
    observed = [(int(afe), int(code)) for afe, code in re.findall(
        r"^AFE BIAS command sent for AFE (\d+)\. BIAS code: (\d+)\.", message, re.MULTILINE)]
    if observed != [(afe, 0) for afe in order]:
        raise ValueError("Missing, duplicate, nonzero or wrongly ordered aggregate BIAS command acknowledgement")
    return observed


def check_bias_control_acknowledgement(message):
    matches = re.findall(
        r"^Bias Control command sent\. BIASCTRL code: (\d+)\. Returned command-register value: (\d+)\. "
        r"BiasEnable not written \(SC-owned\); no physical voltage readback\.$", message, re.MULTILINE)
    require(len(matches) == 1 and matches[0][0] == "0", "Missing or nonzero SC-owned BIASCTRL acknowledgement")
    require("and Enable:" not in message, "Legacy implicit-enable acknowledgement")


def check_bias_enable_preserved(before, after, configured, high):
    """Compare admitted samples across a successful Configure, never write enable."""
    for sample in (before, after):
        require(sample.HasField("server_state") and sample.HasField("server_build"))
        check_state(sample.server_state)
        require(sample.server_state.server_build == sample.server_build)
        check_build(sample.server_build, high, require_clean=True)
    a, b = before.server_state, after.server_state
    require(not a.configuration_in_progress and not b.configuration_in_progress,
            "Configure still in progress at a boundary sample")
    require(a.instance_id == b.instance_id and a.boot_id == b.boot_id and before.server_build == after.server_build,
            "Server process, boot or build changed across Configure")
    require(all(getattr(before.gateware_identity, key) == getattr(after.gateware_identity, key)
                for key in ("magic", "abi", "variant", "build_id")), "Gateware changed across Configure")
    prior = check_afe_global(before, high, a.observed_monotonic_ns)
    current = check_afe_global(after, high, b.observed_monotonic_ns)
    require(configured.success and configured.HasField("execution") and configured.applied_configuration_valid and
            configured.execution.outcome == high.CONFIGURATION_SUCCEEDED and configured.execution.hardware_started and
            configured.execution.attempt_sequence > a.last_configuration_result.attempt_sequence and
            b.last_configuration_result == configured.execution and b.applied_configuration_valid and
            b.applied_configuration_hash == configured.applied_configuration_hash,
            "Missing successful applied Configure evidence")
    require(a.observed_monotonic_ns <= configured.execution.started_monotonic_ns <=
            configured.execution.completed_monotonic_ns < current["acquisition_started_monotonic_ns"],
            "AFE samples do not bracket this Configure")
    require(prior["bias_enabled"] == current["bias_enabled"], "BiasEnable changed across Configure")
    return {"bias_enabled_before": prior["bias_enabled"], "bias_enabled_after": current["bias_enabled"],
            "before_observed_monotonic_ns": prior["observed_monotonic_ns"],
            "after_observed_monotonic_ns": current["observed_monotonic_ns"],
            "scope": "equal fresh register samples; no enable command sent by this client; not a physical glitch test"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--proto-dir", type=Path, required=True)
    parser.add_argument("--server-source", type=Path, required=True)
    parser.add_argument("--expected-server-commit", required=True)
    parser.add_argument("--expected-build-id", type=lambda value: int(value, 0), required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--apply-zero-bias-configuration", action="store_true", required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.proto_dir.resolve()))
    import zmq
    import daphneV3_high_level_confs_pb2 as high
    import daphneV3_low_level_confs_pb2 as low
    from google.protobuf.json_format import ParseDict

    args.output_dir.mkdir(parents=True, exist_ok=True)
    if (args.output_dir / "summary.json").exists():
        parser.error("Existing summary must not be overwritten")
    raw = (args.output_dir / "captures.jsonl").open("x")
    report = {"expected_build_id": hex(args.expected_build_id), "runs": [],
              "scope": "Zero BIAS/BIASCTRL aggregate commands, not physical voltage measurements",
              "low_level_bias_writes_sent": 0, "final_offset": "2200/x1"}
    context = zmq.Context()
    socket = context.socket(zmq.DEALER)
    socket.setsockopt(zmq.LINGER, 0)
    socket.setsockopt(zmq.RCVTIMEO, 45000)
    socket.setsockopt(zmq.SNDTIMEO, 5000)
    socket.connect(args.endpoint)
    sequence = 0

    def call(kind, request, response_class):
        nonlocal sequence
        sequence += 1
        envelope = high.ControlEnvelopeV2(version=2, dir=high.DIR_REQUEST, type=kind,
                                          msg_id=sequence, task_id=22, payload=request.SerializeToString())
        socket.send(envelope.SerializeToString())
        reply = high.ControlEnvelopeV2.FromString(socket.recv())
        require(not getattr(reply, "transport_error", ""), getattr(reply, "transport_error", ""))
        require(reply.version == 2 and reply.dir == high.DIR_RESPONSE and reply.type == kind + 1
                and reply.correl_id == sequence and reply.task_id == 22, "Wrong response envelope")
        response = response_class.FromString(reply.payload)
        require(response.success, response.message)
        return response

    def status_sample():
        status = call(high.MT2_READ_SYSTEM_STATUS_REQ, high.ReadSystemStatusRequest(), high.SystemStatusSnapshot)
        require(status.HasField("server_build") and status.HasField("server_state"))
        check_build(status.server_build, high, expected_commit=args.expected_server_commit,
                    require_clean=True, source_root=args.server_source)
        require(status.server_state.server_build == status.server_build)
        check_state(status.server_state)
        check_afe_global(status, high, status.server_state.observed_monotonic_ns)
        identity = status.gateware_identity
        require(identity.magic == 0x44415048 and identity.abi == 0x20000 and identity.variant == 1
                and identity.build_id == args.expected_build_id, "Unexpected self-trigger firmware; no Configure sent")
        return status

    try:
        for order in ([0, 1, 2, 3, 4], [4, 1, 3, 0, 2]):
            before = status_sample()
            entry = {"request": make_zero_bias_request(order)}
            report["runs"].append(entry)
            configured = call(high.MT2_CONFIGURE_FE_REQ,
                              ParseDict(entry["request"], high.ConfigureRequest()), high.ConfigureResponse)
            require(configured.execution.task_id == 22 and configured.execution.request_msg_id == sequence,
                    "Configure execution record does not match this request")
            entry["configure_response"] = configured.message
            entry["aggregate_bias_acknowledgements"] = check_bias_acknowledgements(configured.message, order)
            check_bias_control_acknowledgement(configured.message)
            entry["bias_enable_after_configure"] = check_bias_enable_preserved(before, status_sample(), configured, high)
            require(configured.message.count("Offset DAC gain: x1") == 40, "Missing offset gain acknowledgement")
            aligned = call(high.MT2_ALIGN_AFE_REQ, low.cmd_alignAFEs(), low.cmd_alignAFEs_response)
            entry["alignment_response"] = aligned.message
            entry["delay_pl_order"], entry["bitslip_pl_order"] = list(aligned.delay), list(aligned.bitslip)
            require(len(aligned.delay) == 5 and len(aligned.bitslip) == 5
                    and aligned.message.count("verify=PASS") == 5, "Not all five AFEs aligned")
            control = call(high.MT2_READ_VBIAS_CONTROL_REQ, low.cmd_readVbiasControl(), low.cmd_readVbiasControl_response)
            require(control.vBiasControlValue == 0, "BIASCTRL command cache is not zero")
            entry["biasctrl_cached"] = control.vBiasControlValue
            entry["bias_cached"], entry["afe_registers"] = {}, {}
            for afe in range(5):
                bias = call(high.MT2_READ_AFE_BIAS_SET_REQ, low.cmd_readAFEBiasSet(afeBlock=afe),
                            low.cmd_readAFEBiasSet_response)
                require(bias.afeBlock == afe and bias.biasValue == 0, "Wrong BIAS command cache")
                entry["bias_cached"][str(afe)] = bias.biasValue
                registers = {}
                for address, expected in {1: 0, 2: 0, 3: 0x2000, 4: 8, 51: 0x58, 52: 0x5400}.items():
                    for _ in range(2):
                        value = call(high.MT2_READ_AFE_REG_REQ,
                                     low.cmd_readAFEReg(afeBlock=afe, regAddress=address), low.cmd_readAFEReg_response)
                        require(value.hardware_readback and value.afeBlock == afe and value.regAddress == address
                                and value.regValue == expected, "Unexpected fresh AFE register readback")
                        registers[str(address)] = value.regValue
                entry["afe_registers"][str(afe)] = registers
            time.sleep(1)
            frames = {str(ch): [] for ch in range(40)}
            for wave in range(4):
                call(high.MT2_DUMP_SPYBUFFER_REQ,
                     high.DumpSpyBuffersRequest(channelList=[0], numberOfSamples=1,
                                               numberOfWaveforms=1, softwareTrigger=True), high.DumpSpyBuffersResponse)
                time.sleep(0.01)
                captured = call(high.MT2_DUMP_SPYBUFFER_REQ,
                                high.DumpSpyBuffersRequest(channelList=list(range(40)), numberOfSamples=1024,
                                                          numberOfWaveforms=1, softwareTrigger=False),
                                high.DumpSpyBuffersResponse)
                require(list(captured.channelList) == list(range(40)) and captured.numberOfSamples == 1024
                        and captured.numberOfWaveforms == 1 and not captured.softwareTrigger
                        and len(captured.data) == 40 * 1024, "Invalid spybuffer metadata")
                data = {str(ch): list(captured.data[ch * 1024:(ch + 1) * 1024]) for ch in range(40)}
                raw.write(json.dumps({"afe_order": order, "waveform": wave, "host_monotonic_ns": time.monotonic_ns(),
                                      "channels": data}) + "\n")
                raw.flush()
                for ch, values in data.items():
                    frames[ch].append(values)
            entry["captures"] = {ch: summarize(values) for ch, values in frames.items()}
            require(all(usable_capture(value) for value in entry["captures"].values()), "Clipped or stale captures")
            entry["bias_enable_after_capture"] = check_bias_enable_preserved(before, status_sample(), configured, high)
            entry["success"] = True
            print(f"PASS AFE order {order}: five aggregate zero writes, alignment, registers and 40 channels", flush=True)
    except Exception as error:
        report["error"] = str(error)
    finally:
        raw.close()
        socket.close()
        context.term()
        report["requests_checked"] = sequence
        report["captures_sha256"] = hashlib.sha256((args.output_dir / "captures.jsonl").read_bytes()).hexdigest()
        report["success"] = "error" not in report and len(report["runs"]) == 2
        with (args.output_dir / "summary.json").open("x") as output:
            json.dump(report, output, indent=2)
    if not report["success"]:
        print(report.get("error", "Incomplete test"), file=sys.stderr)
        return 1
    print(f"PASS: {sequence} exchanges; no low-level bias-write workaround or nonzero bias commands")
    return 0


if __name__ == "__main__":
    sys.exit(main())
