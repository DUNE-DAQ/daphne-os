#!/usr/bin/env python3
"""MAINTENANCE: offset-only analog comparison via EnvelopeV2 and spybuffer.

Writes only offset DACs on explicitly selected board AFEs, then software-triggers
spybuffer captures. Does NOT configure/reset/align AFEs, change clocks, PGA,
trim or HV, or send an aggregate Configure request. Requires prior alignment.
Sequence: 2200/x1, 1100/x2, 1100/x1 control, 2200/x1 repeat. Final setting is
2200/x1, NOT restoration of unknown previous DAC state (there is no readback).
This qualifies the low-level DAC path, not aggregate Configure end-to-end.
"""

import argparse
import hashlib
import json
import statistics
import sys
import time
from pathlib import Path


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
    args = parser.parse_args()
    if len(set(args.afes)) != len(args.afes) or any(afe not in range(5) for afe in args.afes):
        parser.error("AFE indices must be unique and in 0..4")
    if not 2 <= args.waveforms <= 100 or not 1 <= args.samples <= 2048 or args.tolerance_adc <= 0:
        parser.error("Require 2..100 waveforms, 1..2048 samples and positive tolerance")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents overwriting an earlier qualification run.
    raw = (args.output_dir / "captures.jsonl").open("x")
    sys.path.insert(0, str(args.proto_dir.resolve()))
    import zmq
    import daphneV3_high_level_confs_pb2 as high
    import daphneV3_low_level_confs_pb2 as low

    context = zmq.Context()
    socket = context.socket(zmq.DEALER)
    socket.setsockopt(zmq.LINGER, 0)
    socket.setsockopt(zmq.RCVTIMEO, 10000)
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
              "final_requested_setting": {"offset": 2200, "gain": 1}}

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

    def read_afe_state():
        state = {}
        for afe in args.afes:
            registers = {}
            for address in (2, 4, 51):
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
        report["afe_registers_before"] = read_afe_state()
        report["adc_output_formats"] = {
            afe: "offset-binary" if registers["4"] & 8 else "twos-complement"
            for afe, registers in report["afe_registers_before"].items()}
        for label, code, gain in (("a_2200_x1", 2200, 1), ("b_1100_x2", 1100, 2),
                                  ("control_1100_x1", 1100, 1), ("repeat_2200_x1", 2200, 1)):
            for afe in args.afes:
                if afe not in touched:
                    touched.append(afe)  # Include an AFE even if its write times out.
                write_offset(afe, code, gain)
            time.sleep(0.2)
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
            print(label, {ch: values["baseline"] for ch, values in results[label].items()}, flush=True)
        report["afe_registers_after"] = read_afe_state()
        require(report["afe_registers_after"] == report["afe_registers_before"],
                "AFE format/test-pattern/PGA registers changed during the comparison")
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
