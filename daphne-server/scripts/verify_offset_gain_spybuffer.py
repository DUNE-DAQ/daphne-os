#!/usr/bin/env python3
"""MAINTENANCE: offset-only analog comparison via EnvelopeV2 and spybuffer.

Writes only offset DACs on explicitly selected board AFEs, then software-triggers
spybuffer captures. Does NOT configure/reset/align AFEs, change clocks, PGA,
trim or HV, or send an aggregate Configure request. Requires prior alignment.
Sequence: 2200/x1, 1100/x2, 2200/x1 repeat, 1100/x1 control. Final setting is
2200/x1, NOT restoration of unknown previous DAC state (there is no readback).
The potentially clipping control follows A/B/A, so its recovery cannot affect
the repeatability measurement. A final offset write follows the control.
This qualifies the low-level DAC path, not aggregate Configure end-to-end.
With --configure-zero-bias, instead run full self-trigger Configure + AlignAFE
for each setting, including AFE reset/power, trim=0, VGAIN=1700 and the reference
AFE profile. Explicitly write all five BIAS=0 and BIASCTRL=0 first. The existing
Configure enable behavior is retained. This option changes the full FE setup.
With --sweep-equivalent-codes, instead bracket each even x1 code as A/B/A,
using half that code at x2. No clipping control or full configuration is sent.
This requires the reference AFE profile and cached BIAS/BIASCTRL commands zero.
"""

import argparse
import hashlib
import json
import math
import statistics
import sys
import time
from pathlib import Path


def setting_sequence():
    """Measure repeatability before the potentially saturating control."""
    return (("a_2200_x1", 2200, 1), ("b_1100_x2", 1100, 2),
            ("repeat_2200_x1", 2200, 1), ("control_1100_x1", 1100, 1))


def sweep_sequence(codes):
    if (not 3 <= len(codes) <= 7 or len(set(codes)) != len(codes)
            or any(type(code) is not int or code % 2 or not 2 <= code <= 2700 for code in codes)):
        raise ValueError("Require 3..7 distinct even x1 codes in 2..2700")
    return tuple((f"eq_{code}_{phase}", code // gain, gain)
                 for code in codes for phase, gain in (("a", 1), ("b", 2), ("repeat", 1))) + (
                     ("final_2200_x1", 2200, 1),)


def usable_capture(result):
    return (result["rail_fraction"] < 0.01 and result["distinct_frames"] > 1
            and result["low_rail"] < result["baseline"] < result["high_rail"])


def fit_line(xs, ys):
    center_x, center_y = statistics.mean(xs), statistics.mean(ys)
    slope = sum((x - center_x) * (y - center_y) for x, y in zip(xs, ys)) / sum(
        (x - center_x) ** 2 for x in xs)
    intercept = center_y - slope * center_x
    return {"slope": slope, "intercept": intercept,
            "max_residual_adc": max(abs(y - slope * x - intercept) for x, y in zip(xs, ys))}


def analyze_sweep(results, codes, channels, tolerance):
    """Diagnostic local slopes, not a calibration or an automatic correction."""
    output = {}
    for ch in map(str, channels):
        points, x1, x2 = {}, [], []
        for code in codes:
            a, b, repeat = (results[f"eq_{code}_{phase}"][ch] for phase in ("a", "b", "repeat"))
            reference = (a["baseline"] + repeat["baseline"]) / 2
            delta, drift = b["baseline"] - a["baseline"], repeat["baseline"] - a["baseline"]
            points[str(code)] = {
                "equivalent_delta_adc": delta, "repeat_delta_adc": drift,
                "bracket_delta_adc": b["baseline"] - reference,
                "usable_captures": all(usable_capture(row) for row in (a, b, repeat)),
                "within_tolerance": abs(delta) <= tolerance and abs(drift) <= tolerance,
            }
            x1.append(reference)
            x2.append(b["baseline"])
        fit_x1, fit_x2 = fit_line(codes, x1), fit_line([code / 2 for code in codes], x2)
        noise = max(results[label][ch]["within_frame_rms"] for label in results)
        drift = max(abs(row["repeat_delta_adc"]) for row in points.values())
        responsive = min(max(x1) - min(x1), max(x2) - min(x2)) > 5 * max(noise, drift, 1)
        same_direction = fit_x1["slope"] * fit_x2["slope"] > 0
        for row in points.values():
            row["equivalent_x1_code_difference"] = (
                row["bracket_delta_adc"] / fit_x1["slope"] if responsive and same_direction else None)
        output[ch] = {
            "points": points, "x1_fit_per_dac_code": fit_x1, "x2_fit_per_dac_code": fit_x2,
            "slope_ratio_x2_over_x1": fit_x2["slope"] / fit_x1["slope"]
                if responsive and same_direction else None,
            "offset_response_observed": responsive, "same_slope_direction": same_direction,
            "comparison_pass": responsive and same_direction and usable_capture(results["final_2200_x1"][ch])
                and all(row["usable_captures"] and row["within_tolerance"] for row in points.values()),
        }
    return output


def zero_bias_profile(code, gain):
    """Reference FE profile with the user's explicit zero-bias settings."""
    if gain not in (1, 2) or not 0 <= code <= (2700 if gain == 1 else 1500):
        raise ValueError("Invalid offset/gain for full zero-bias test")
    return {
        "slot": 0, "timeout_ms": 30000, "biasctrl": 0,
        "self_trigger_threshold": 0xC, "self_trigger_xcorr": 0x68,
        "tp_conf": 0x0010DB35, "compensator": 0xFFFFFFFFFF, "inverters": 0xFF00000000,
        "channels": [{"id": ch, "trim": 0, "offset": code, "gain": gain} for ch in range(40)],
        "afes": [{"id": afe, "attenuators": 1700, "v_bias": 0,
                  "adc": {"resolution": False, "output_format": True, "sb_first": False},
                  "pga": {"lpf_cut_frequency": 4, "integrator_disable": True, "gain": False},
                  "lna": {"clamp": 2, "gain": 2, "integrator_disable": True}} for afe in range(5)],
    }


def summarize(frames, output_format="offset-binary"):
    raw_values = [value for frame in frames for value in frame]
    if not frames or any(not frame for frame in frames) or any(not 0 <= value <= 16383 for value in raw_values):
        raise ValueError("Expected nonempty unsigned 14-bit spybuffer samples")
    if output_format not in ("offset-binary", "twos-complement"):
        raise ValueError("Unknown ADC output format")
    if output_format == "twos-complement":
        frames = [[value - 16384 if value & 0x2000 else value for value in frame] for frame in frames]
        low_rail, high_rail = -8192, 8191
    else:
        low_rail, high_rail = 0, 16383
    values = [value for frame in frames for value in frame]
    medians = [statistics.median(frame) for frame in frames]
    return {
        "baseline": statistics.median(medians),
        "frame_medians": medians,
        "within_frame_rms": statistics.mean(statistics.pstdev(frame) for frame in frames),
        "min": min(values), "max": max(values),
        "output_format": output_format, "low_rail": low_rail, "high_rail": high_rail,
        "rail_fraction": sum(value in (low_rail, high_rail) for value in values) / len(values),
        "distinct_frames": len({tuple(frame) for frame in frames}),
    }


def compare(a, b, control, repeat, tolerance):
    delta = b["baseline"] - a["baseline"]
    drift = repeat["baseline"] - a["baseline"]
    shift = control["baseline"] - a["baseline"]
    usable = all(s["rail_fraction"] < 0.01 and s["distinct_frames"] > 1
                 and s["low_rail"] < s["baseline"] < s["high_rail"] for s in (a, b, repeat))
    # A control at half the nominal DAC output must move the measured baseline.
    # A saturated control is still diagnostic, but not used as a noise estimate.
    responsive = abs(shift) > 5 * max(abs(delta), abs(drift), 1)
    return {
        "equivalent_delta_adc": delta, "repeat_delta_adc": drift,
        "control_delta_adc": shift, "usable_captures": usable,
        "offset_response_observed": responsive,
        "within_tolerance": abs(delta) <= tolerance,
        "repeat_within_tolerance": abs(drift) <= tolerance,
        "comparison_pass": usable and responsive and abs(delta) <= tolerance
                           and abs(drift) <= tolerance,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--proto-dir", type=Path, required=True)
    parser.add_argument("--expected-build-id", type=lambda text: int(text, 0), required=True)
    parser.add_argument("--mode", choices=("self-trigger", "full-stream"), required=True)
    parser.add_argument("--afes", type=int, nargs="+", required=True,
                        help="Aligned board AFE indices (0..4); all eight channels are tested")
    parser.add_argument("--waveforms", type=int, default=12)
    parser.add_argument("--samples", type=int, default=1024)
    parser.add_argument("--tolerance-adc", type=float, default=164,
                        help="Comparison criterion, not a calibration spec; default ~1%% of 14-bit span")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--apply-offsets", action="store_true", required=True,
                        help="Acknowledge analog writes and final 2200/x1 setting")
    parser.add_argument("--configure-zero-bias", action="store_true",
                        help="Full self-trigger FE configuration + alignment at every setting; all 40 channels; BIAS/BIASCTRL=0")
    parser.add_argument("--sweep-equivalent-codes", type=int, nargs="+",
                        help="Diagnostic A/B/A sweep: 3..7 distinct even x1 codes; x2 uses half each code")
    parser.add_argument("--settle-seconds", type=float, default=0.2,
                        help="Wait after each offset setting before capturing (0.2..10 seconds)")
    args = parser.parse_args()
    if len(set(args.afes)) != len(args.afes) or any(afe not in range(5) for afe in args.afes):
        parser.error("AFE indices must be unique and in 0..4")
    if (not 2 <= args.waveforms <= 100 or not 1 <= args.samples <= 2048
            or not math.isfinite(args.tolerance_adc) or args.tolerance_adc <= 0):
        parser.error("Require 2..100 waveforms, 1..2048 samples and positive tolerance")
    if not 0.2 <= args.settle_seconds <= 10:
        parser.error("Settling interval must be 0.2..10 seconds")
    if args.configure_zero_bias and (args.mode != "self-trigger" or args.afes != list(range(5))):
        parser.error("Full configuration requires self-trigger mode and --afes 0 1 2 3 4")
    if args.configure_zero_bias and args.sweep_equivalent_codes:
        parser.error("Sweep requires prior full initialization; cannot combine with full Configure")
    try:
        settings = sweep_sequence(args.sweep_equivalent_codes) if args.sweep_equivalent_codes else setting_sequence()
    except ValueError as error:
        parser.error(str(error))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents overwriting an earlier qualification run.
    raw = (args.output_dir / "captures.jsonl").open("x")
    sys.path.insert(0, str(args.proto_dir.resolve()))
    import zmq
    import daphneV3_high_level_confs_pb2 as high
    import daphneV3_low_level_confs_pb2 as low
    from google.protobuf.json_format import ParseDict

    context = zmq.Context()
    socket = context.socket(zmq.DEALER)
    socket.setsockopt(zmq.LINGER, 0)
    socket.setsockopt(zmq.RCVTIMEO, 45000 if args.configure_zero_bias else 10000)
    socket.setsockopt(zmq.SNDTIMEO, 5000)
    socket.connect(args.endpoint)
    sequence = 0
    channels = [afe * 8 + ch for afe in args.afes for ch in range(8)]
    touched = []
    results = {}
    report = {"firmware_build": hex(args.expected_build_id), "mode": args.mode,
              "afes": args.afes, "channels": channels, "waveforms_per_setting": args.waveforms,
              "samples_per_waveform": args.samples, "tolerance_adc": args.tolerance_adc,
              "scope": "Low-level offset DAC path; not aggregate Configure",
              "setting_order": [label for label, _, _ in settings],
              "settle_seconds": args.settle_seconds,
              "final_requested_setting": {"offset": 2200, "gain": 1}}
    if args.configure_zero_bias:
        report["scope"] = "Full zero-bias Configure + explicit AlignAFE at every offset/gain setting"
        report["aggregate_configurations"] = {}
    if args.sweep_equivalent_codes:
        report["scope"] = "Offset-only A/B/A sweep on reference-configured zero-bias FE; no calibration claim"
        report["sweep_equivalent_codes"] = args.sweep_equivalent_codes

    def require(ok, message):
        if not ok:
            raise RuntimeError(message)

    def call(kind, request, response_class):
        nonlocal sequence
        sequence += 1
        envelope = high.ControlEnvelopeV2(version=2, dir=high.DIR_REQUEST,
                                          type=kind, msg_id=sequence, task_id=19,
                                          payload=request.SerializeToString())
        socket.send(envelope.SerializeToString())
        reply = high.ControlEnvelopeV2.FromString(socket.recv())
        require(not getattr(reply, "transport_error", ""), getattr(reply, "transport_error", ""))
        require(reply.version == 2 and reply.dir == high.DIR_RESPONSE and reply.type == kind + 1
                and reply.correl_id == sequence and reply.task_id == 19, "Wrong response envelope")
        result = response_class.FromString(reply.payload)
        require(result.success, result.message)
        return result

    def write_offset(afe, code, gain):
        result = call(high.MT2_WRITE_OFFSET_ALL_AFE_REQ,
                      low.cmd_writeOFFSET_allAFE(afeBlock=afe, offsetValue=code, offsetGain=(gain == 2)),
                      low.cmd_writeOFFSET_allAFE_response)
        require(result.afeBlock == afe and result.offsetValue == code and result.offsetGain == (gain == 2),
                "Offset command acknowledgement mismatch (not hardware readback)")

    def require_zero_bias_cache():
        ctrl = call(high.MT2_READ_VBIAS_CONTROL_REQ, low.cmd_readVbiasControl(), low.cmd_readVbiasControl_response)
        require(ctrl.vBiasControlValue == 0, "BIASCTRL command cache is not zero; no bias changes authorized here")
        biases = {}
        for afe in range(5):
            value = call(high.MT2_READ_AFE_BIAS_SET_REQ, low.cmd_readAFEBiasSet(afeBlock=afe),
                         low.cmd_readAFEBiasSet_response)
            require(value.afeBlock == afe and value.biasValue == 0, "BIAS command cache is not zero")
            biases[str(afe)] = value.biasValue
        return {"biasctrl": ctrl.vBiasControlValue, "bias_by_afe": biases,
                "source": "Server command cache, NOT physical voltage readback"}

    def configure_zero_bias(label, code, gain):
        entry = {"request": zero_bias_profile(code, gain), "explicit_zero_bias_commands": []}
        report["aggregate_configurations"][label] = entry
        # Do not rely on v_bias=0 in aggregate Configure: legacy code skips it.
        ctrl = call(high.MT2_WRITE_VBIAS_CONTROL_REQ,
                    low.cmd_writeVbiasControl(vBiasControlValue=0, enable=True),
                    low.cmd_writeVbiasControl_response)
        require(ctrl.vBiasControlValue == 0, "Zero BIASCTRL command acknowledgement mismatch")
        entry["biasctrl_zero_acknowledged"] = True
        for afe in args.afes:
            bias = call(high.MT2_WRITE_AFE_BIAS_SET_REQ,
                        low.cmd_writeAFEBiasSet(afeBlock=afe, biasValue=0),
                        low.cmd_writeAFEBiasSet_response)
            require(bias.afeBlock == afe and bias.biasValue == 0, "Zero BIAS command acknowledgement mismatch")
            entry["explicit_zero_bias_commands"].append(afe)
        touched[:] = args.afes
        configured = call(high.MT2_CONFIGURE_FE_REQ,
                          ParseDict(entry["request"], high.ConfigureRequest()), high.ConfigureResponse)
        entry["configure_response"] = configured.message
        require(configured.message.count("Offset DAC gain: x" + str(gain)) == 40,
                "Full Configure did not report the requested gain on all 40 channels")
        aligned = call(high.MT2_ALIGN_AFE_REQ, low.cmd_alignAFEs(), low.cmd_alignAFEs_response)
        entry["alignment_response"] = aligned.message
        entry["delay_pl_order"] = list(aligned.delay)
        entry["bitslip_pl_order"] = list(aligned.bitslip)
        require(len(aligned.delay) == 5 and len(aligned.bitslip) == 5
                and aligned.message.count("verify=PASS") == 5,
                "Not all five AFEs passed settled alignment verification")
        print(label + ": full zero-bias Configure and all five AFEs aligned", flush=True)

    def read_afe_state():
        state = {}
        for afe in args.afes:
            registers = {}
            for address in (1, 2, 3, 4, 51, 52):
                observed = []
                for _ in range(2):
                    result = call(high.MT2_READ_AFE_REG_REQ,
                                  low.cmd_readAFEReg(afeBlock=afe, regAddress=address),
                                  low.cmd_readAFEReg_response)
                    require(result.hardware_readback and result.afeBlock == afe and result.regAddress == address,
                            "AFE response is not hardware readback")
                    observed.append(result.regValue)
                require(observed[0] == observed[1], "Unstable AFE register readback")
                registers[str(address)] = observed[0]
            require((registers["2"] >> 13) == 0, "AFE is emitting a test pattern, not analog samples")
            require((registers["4"] & 2) == 0, "This verifier requires 14-bit ADC resolution")
            if args.configure_zero_bias or args.sweep_equivalent_codes:
                for address, expected in {1: 0, 2: 0, 3: 0x2000, 4: 8, 51: 0x58, 52: 0x5400}.items():
                    require(registers[str(address)] == expected,
                            "Unexpected configured AFE {} register {}: 0x{:x}".format(
                                afe, address, registers[str(address)]))
            state[str(afe)] = registers
        return state

    def capture():
        # Trigger/discard, wait for a complete capture, then read the same frozen
        # buffer. Avoid treating an immediate post-trigger read as settled data.
        call(high.MT2_DUMP_SPYBUFFER_REQ,
             high.DumpSpyBuffersRequest(channelList=[channels[0]], numberOfSamples=1,
                                       numberOfWaveforms=1, softwareTrigger=True),
             high.DumpSpyBuffersResponse)
        time.sleep(0.01)
        result = call(high.MT2_DUMP_SPYBUFFER_REQ,
                      high.DumpSpyBuffersRequest(channelList=channels, numberOfSamples=args.samples,
                                                numberOfWaveforms=1, softwareTrigger=False),
                      high.DumpSpyBuffersResponse)
        require(list(result.channelList) == channels and result.numberOfSamples == args.samples
                and result.numberOfWaveforms == 1 and not result.softwareTrigger,
                "Unexpected capture metadata")
        require(len(result.data) == len(channels) * args.samples, "Unexpected capture length")
        return {str(ch): list(result.data[i * args.samples:(i + 1) * args.samples])
                for i, ch in enumerate(channels)}

    try:
        status = call(high.MT2_READ_SYSTEM_STATUS_REQ, high.ReadSystemStatusRequest(), high.SystemStatusSnapshot)
        identity = status.gateware_identity
        require(identity.magic == 0x44415048 and identity.abi == 0x20000
                and identity.build_id == args.expected_build_id
                and identity.variant == (1 if args.mode == "self-trigger" else 2),
                "Unexpected firmware identity; no offset writes sent")
        report["aggregate_gain_capability"] = next(
            (item.supported for item in status.capabilities if item.name == "ChannelConfig.gain"), None)
        if args.configure_zero_bias:
            require(report["aggregate_gain_capability"] is True, "Server does not advertise aggregate offset gain support")
        else:
            report["afe_registers_before"] = read_afe_state()
        if args.sweep_equivalent_codes:
            report["zero_bias_cache_before"] = require_zero_bias_cache()
        for label, code, gain in settings:
            if args.configure_zero_bias:
                configure_zero_bias(label, code, gain)
                registers = read_afe_state()
                report["aggregate_configurations"][label]["afe_registers"] = registers
                if "afe_registers_before" not in report:
                    report["afe_registers_before"] = registers
                require(registers == report["afe_registers_before"], "Full configuration changed the fixed AFE profile")
            else:
                for afe in args.afes:
                    if afe not in touched:
                        touched.append(afe)  # Include an AFE even if its write times out.
                    write_offset(afe, code, gain)
            report["adc_output_formats"] = {
                afe: "offset-binary" if registers["4"] & 8 else "twos-complement"
                for afe, registers in report["afe_registers_before"].items()}
            time.sleep(args.settle_seconds)
            frames = {str(ch): [] for ch in channels}
            for number in range(args.waveforms):
                data = capture()
                record = {"setting": label, "waveform": number,
                          "host_monotonic_ns": time.monotonic_ns(), "channels": data}
                raw.write(json.dumps(record) + "\n")
                raw.flush()
                for ch, values in data.items():
                    frames[ch].append(values)
            results[label] = {ch: summarize(values, report["adc_output_formats"][str(int(ch) // 8)])
                              for ch, values in frames.items()}
            if args.sweep_equivalent_codes:
                baseline = [value["baseline"] for value in results[label].values()]
                print(f"{label}: baseline range {min(baseline)}..{max(baseline)}", flush=True)
                require(all(usable_capture(value) for value in results[label].values()),
                        "Sweep stopped: clipped or stale captures; remaining sweep settings were not sent")
            else:
                print(label, {ch: values["baseline"] for ch, values in results[label].items()}, flush=True)
        report["afe_registers_after"] = read_afe_state()
        require(report["afe_registers_after"] == report["afe_registers_before"],
                "AFE format/test-pattern/PGA registers changed during the comparison")
        if args.sweep_equivalent_codes:
            report["zero_bias_cache_after"] = require_zero_bias_cache()
            report["channels_compared"] = analyze_sweep(results, args.sweep_equivalent_codes, channels,
                                                      args.tolerance_adc)
        else:
            report["channels_compared"] = {
                str(ch): compare(*(results[label][str(ch)] for label in
                                  ("a_2200_x1", "b_1100_x2", "control_1100_x1", "repeat_2200_x1")),
                                 args.tolerance_adc) for ch in channels}
    except Exception as error:
        report["error"] = str(error)
    finally:
        report["final_offset_command_acknowledgements"] = {}
        for afe in touched:
            try:
                write_offset(afe, 2200, 1)
                report["final_offset_command_acknowledgements"][str(afe)] = "2200/x1 acknowledged, not DAC readback"
            except Exception as error:
                report["final_offset_command_acknowledgements"][str(afe)] = "FAILED: " + str(error)
                report["error"] = "Could not confirm final offset command on every touched AFE"
        raw.close()
        socket.close()
        context.term()
        report["settings"] = results
        report["requests_checked"] = sequence
        report["captures_sha256"] = hashlib.sha256((args.output_dir / "captures.jsonl").read_bytes()).hexdigest()
        with (args.output_dir / "summary.json").open("x") as output:
            json.dump(report, output, indent=2)
    if "error" in report:
        print(report["error"], file=sys.stderr)
        return 1
    for ch, result in report["channels_compared"].items():
        print(ch, json.dumps(result), flush=True)
    return 0 if all(item["comparison_pass"] for item in report["channels_compared"].values()) else 2


if __name__ == "__main__":
    sys.exit(main())
