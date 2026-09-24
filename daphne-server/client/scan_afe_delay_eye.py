#!/usr/bin/env python3
"""Sweep AFE input delay using the synchronized AFE5808A ramp."""

from __future__ import annotations

import argparse
import csv
from contextlib import nullcontext
from dataclasses import asdict
import importlib
import json
import math
import os
from pathlib import Path
import random
import sys
import time
import uuid

import zmq

from afe_delay_sweep_analysis import (
    PartialAfeWindow,
    TapWindow,
    best_partial_passing_window,
    summarize_afe_eye,
)
from trigger_source import configure_trigger_source, read_trigger_source


REPO_ROOT = Path(__file__).resolve().parents[1]


def load_protobuf_module(*, require_timing_write: bool = False):
    candidates: list[Path] = []
    import_errors: list[str] = []
    if os.environ.get("DAPHNE_PROTO_PYTHON_DIR"):
        candidates.append(Path(os.environ["DAPHNE_PROTO_PYTHON_DIR"]))
    if os.environ.get("DAPHNE_BUILD_DIR"):
        candidates.append(
            Path(os.environ["DAPHNE_BUILD_DIR"]) / "srcs" / "protobuf"
        )
    for build_name in ("build-petalinux", "build-client", "build-test", "build"):
        candidates.append(REPO_ROOT / build_name / "srcs" / "protobuf")
    candidates.append(REPO_ROOT / "srcs" / "protobuf")

    visited: set[Path] = set()
    for candidate in candidates:
        candidate = candidate.resolve()
        if candidate in visited:
            continue
        visited.add(candidate)
        module_path = candidate / "daphneV3_high_level_confs_pb2.py"
        if not module_path.is_file():
            continue
        # protoc versions encode message names differently inside the
        # serialized descriptor, while enum names remain plain ASCII.
        descriptor = module_path.read_bytes()
        descriptor_names = [
            b"MT2_AFE_DELAY_SWEEP_REQ",
            b"MT2_WRITE_SPYBUFFER_TRIGGER_SOURCE_REQ",
            b"MT2_READ_SPYBUFFER_TRIGGER_SOURCE_REQ",
            b"SPY_TRIGGER_SOURCE_SOFTWARE",
        ]
        if require_timing_write:
            descriptor_names.extend(
                (
                    b"MT2_WRITE_AFE_TIMING_REQ",
                    b"WriteAfeTimingRequest",
                    b"WriteAfeTimingResponse",
                )
            )
        if any(name not in descriptor for name in descriptor_names):
            continue

        sys.path.insert(0, str(candidate))
        try:
            try:
                module = importlib.import_module(
                    "daphneV3_high_level_confs_pb2"
                )
            except Exception as error:
                import_errors.append(f"{module_path}: {error}")
                sys.modules.pop("daphneV3_high_level_confs_pb2", None)
                continue
        finally:
            sys.path.pop(0)
        required = [
            "AfeDelaySweepRequest",
            "AfeDelaySweepResponse",
            "ControlEnvelopeV2",
            "WriteSpyBufferTriggerSourceRequest",
            "WriteSpyBufferTriggerSourceResponse",
            "ReadSpyBufferTriggerSourceRequest",
            "ReadSpyBufferTriggerSourceResponse",
            "MT2_AFE_DELAY_SWEEP_REQ",
            "MT2_AFE_DELAY_SWEEP_RESP",
            "MT2_WRITE_SPYBUFFER_TRIGGER_SOURCE_REQ",
            "MT2_WRITE_SPYBUFFER_TRIGGER_SOURCE_RESP",
            "MT2_READ_SPYBUFFER_TRIGGER_SOURCE_REQ",
            "MT2_READ_SPYBUFFER_TRIGGER_SOURCE_RESP",
            "SPY_TRIGGER_SOURCE_SOFTWARE",
        ]
        if require_timing_write:
            required.extend(
                (
                    "AfeTimingSetting",
                    "WriteAfeTimingRequest",
                    "WriteAfeTimingResponse",
                    "MT2_WRITE_AFE_TIMING_REQ",
                    "MT2_WRITE_AFE_TIMING_RESP",
                )
            )
        if all(hasattr(module, name) for name in required):
            return module
        sys.modules.pop("daphneV3_high_level_confs_pb2", None)

    rpc_description = "AFE delay sweep and spybuffer trigger-source RPCs"
    if require_timing_write:
        rpc_description += ", including the AFE timing-write RPC"
    message = (
        f"Python protobuf bindings with the {rpc_description} were not found. "
        "Rebuild the protos or set DAPHNE_PROTO_PYTHON_DIR to the generated "
        "binding directory."
    )
    if import_errors:
        message += " Import errors: " + "; ".join(import_errors)
    raise RuntimeError(message)


def parse_indices(spec: str, *, maximum: int) -> list[int]:
    values: list[int] = []
    for token in spec.split(","):
        token = token.strip()
        if not token:
            continue
        if "-" in token:
            first_text, last_text = token.split("-", 1)
            first, last = int(first_text), int(last_text)
            if last < first:
                raise ValueError(f"descending range: {token}")
            values.extend(range(first, last + 1))
        else:
            values.append(int(token))
    values = list(dict.fromkeys(values))
    if not values:
        raise ValueError("at least one AFE is required")
    invalid = [value for value in values if value < 0 or value > maximum]
    if invalid:
        raise ValueError(f"AFE indices outside 0..{maximum}: {invalid}")
    return values


def next_ids() -> tuple[int, int]:
    now = time.time_ns()
    mask = (1 << 63) - 1
    return (
        ((now << 7) ^ random.getrandbits(31)) & mask,
        ((now << 1) ^ random.getrandbits(31)) & mask,
    )


def make_socket(
    context: zmq.Context,
    endpoint: str,
    timeout_ms: int,
    identity_prefix: str,
):
    socket = context.socket(zmq.DEALER)
    socket.setsockopt(zmq.LINGER, 0)
    socket.setsockopt(
        zmq.IDENTITY,
        f"{identity_prefix}-{uuid.uuid4()}".encode("ascii"),
    )
    socket.setsockopt(zmq.RCVTIMEO, timeout_ms)
    socket.setsockopt(zmq.SNDTIMEO, timeout_ms)
    socket.connect(endpoint)
    return socket


def send_v2_request(pb, socket, route: str, message_type: int, payload: bytes):
    envelope = pb.ControlEnvelopeV2()
    envelope.version = 2
    envelope.dir = pb.DIR_REQUEST
    envelope.type = message_type
    envelope.payload = payload
    envelope.task_id, envelope.msg_id = next_ids()
    envelope.route = route
    envelope.timestamp_ns = time.time_ns()

    socket.send(envelope.SerializeToString())
    frames = [socket.recv()]
    while socket.getsockopt(zmq.RCVMORE):
        frames.append(socket.recv())

    reply = pb.ControlEnvelopeV2()
    if not reply.ParseFromString(frames[-1]):
        raise RuntimeError("server returned an invalid V2 envelope")
    if reply.dir != pb.DIR_RESPONSE:
        raise RuntimeError("server reply is not a V2 response")
    if reply.correl_id != envelope.msg_id:
        raise RuntimeError("server reply correlation ID does not match request")
    return reply.type, reply.payload


def run_sweep(
    pb,
    args,
    afes: list[int],
    *,
    first_tap: int | None = None,
    last_tap: int | None = None,
    tap_step: int | None = None,
):
    endpoint = f"tcp://{args.ip}:{args.port}"
    context = zmq.Context()
    control_socket = make_socket(
        context,
        endpoint,
        args.timeout_ms,
        "afe-delay-trigger-control",
    )
    sweep_socket = make_socket(
        context,
        endpoint,
        args.timeout_ms,
        "afe-delay-sweep",
    )

    request = pb.AfeDelaySweepRequest()
    request.afes.extend(afes)
    request.firstTap = args.first_tap if first_tap is None else first_tap
    request.lastTap = args.last_tap if last_tap is None else last_tap
    request.tapStep = args.tap_step if tap_step is None else tap_step
    request.numberOfSamples = args.samples
    request.numberOfWaveforms = args.waveforms
    request.settleTimeUs = args.settle_us

    def send_trigger_source_request(message_type: int, payload: bytes):
        return send_v2_request(
            pb,
            control_socket,
            args.route,
            message_type,
            payload,
        )

    original_trigger_source = None
    operation_error: BaseException | None = None
    restore_error: Exception | None = None
    reply_type = None
    reply_payload = None
    try:
        original_trigger_source = read_trigger_source(
            pb,
            send_trigger_source_request,
        )
        configure_trigger_source(
            pb,
            send_trigger_source_request,
            "software",
        )
        print(
            "[TRIGGER] configured software "
            f"(initially {original_trigger_source})"
        )
        reply_type, reply_payload = send_v2_request(
            pb,
            sweep_socket,
            args.route,
            pb.MT2_AFE_DELAY_SWEEP_REQ,
            request.SerializeToString(),
        )
    except BaseException as error:
        operation_error = error
    finally:
        if original_trigger_source is not None:
            try:
                configure_trigger_source(
                    pb,
                    send_trigger_source_request,
                    original_trigger_source,
                )
                print(
                    f"[RESTORE] trigger source: {original_trigger_source}"
                )
            except Exception as error:
                restore_error = error
        sweep_socket.close(0)
        control_socket.close(0)
        context.term()

    if operation_error is not None:
        if restore_error is not None:
            print(
                "[FAIL] trigger-source cleanup: " + str(restore_error),
                file=sys.stderr,
            )
        raise operation_error
    if restore_error is not None:
        raise RuntimeError(
            "AFE delay sweep completed, but the original trigger source "
            f"could not be restored: {restore_error}"
        )
    if reply_type != pb.MT2_AFE_DELAY_SWEEP_RESP:
        raise RuntimeError(
            f"unexpected response type {reply_type}; "
            f"expected {pb.MT2_AFE_DELAY_SWEEP_RESP}"
        )

    response = pb.AfeDelaySweepResponse()
    if not response.ParseFromString(reply_payload):
        raise RuntimeError("server returned an invalid AfeDelaySweepResponse")
    return response, original_trigger_source


def fine_range_from_coarse_result(afe_result, args) -> tuple[int, int, str]:
    points = list(afe_result.points)
    taps = [int(point.tap) for point in points]
    transitions = [int(point.transitionsPerChannel) for point in points]
    failure_matrix = [
        [int(point.channelFailures[lane]) for point in points]
        for lane in range(8)
    ]

    passing_indices: list[int] = []
    for failures_by_tap in failure_matrix:
        channel_passing = [
            index
            for index, (failures, total) in enumerate(
                zip(failures_by_tap, transitions)
            )
            if failures / total <= args.max_error_rate
        ]
        if not channel_passing:
            return (
                args.first_tap,
                args.last_tap,
                "full-range fallback: at least one channel had no coarse pass",
            )
        passing_indices.extend(channel_passing)

    first_index = max(0, min(passing_indices) - 1)
    last_index = min(len(taps) - 1, max(passing_indices) + 1)
    first_tap = max(args.first_tap, taps[first_index])
    last_tap = min(args.last_tap, taps[last_index])
    if first_tap > last_tap:
        return (
            args.first_tap,
            args.last_tap,
            "full-range fallback: coarse passing points were inconsistent",
        )
    return (
        first_tap,
        last_tap,
        "expanded union of every per-channel coarse passing point",
    )


def result_has_common_window(afe_result, max_error_rate: float) -> bool:
    points = list(afe_result.points)
    taps = [int(point.tap) for point in points]
    transitions = [int(point.transitionsPerChannel) for point in points]
    failure_matrix = [
        [int(point.channelFailures[lane]) for point in points]
        for lane in range(8)
    ]
    return summarize_afe_eye(
        taps,
        failure_matrix,
        transitions,
        max_error_rate=max_error_rate,
    ).common_window is not None


def run_auto_sweep(pb, args, afes: list[int]):
    print(
        f"[AUTO] coarse scan {args.first_tap}..{args.last_tap} "
        f"with step {args.coarse_step}"
    )
    coarse_response, original_trigger_source = run_sweep(
        pb,
        args,
        afes,
        first_tap=args.first_tap,
        last_tap=args.last_tap,
        tap_step=args.coarse_step,
    )
    if not coarse_response.success:
        return coarse_response, original_trigger_source, {
            "mode": "coarse_to_fine",
            "coarse_step": args.coarse_step,
            "fine_step": 1,
            "fine_ranges": {},
        }

    coarse_by_afe = {
        int(afe_result.afe): afe_result
        for afe_result in coarse_response.afes
    }
    fine_responses = {}
    fine_ranges = {}
    for afe in afes:
        if afe not in coarse_by_afe:
            raise RuntimeError(f"coarse scan did not return AFE{afe}")
        first_tap, last_tap, reason = fine_range_from_coarse_result(
            coarse_by_afe[afe],
            args,
        )
        fine_ranges[str(afe)] = {
            "first_tap": first_tap,
            "last_tap": last_tap,
            "reason": reason,
        }
        print(
            f"[AUTO] AFE{afe} fine scan {first_tap}..{last_tap} "
            f"with step 1 ({reason})"
        )
        fine_response, _ = run_sweep(
            pb,
            args,
            [afe],
            first_tap=first_tap,
            last_tap=last_tap,
            tap_step=1,
        )
        if not fine_response.success:
            raise RuntimeError(
                f"AFE{afe} fine scan failed: {fine_response.message}"
            )
        if len(fine_response.afes) != 1:
            raise RuntimeError(
                f"AFE{afe} fine scan returned {len(fine_response.afes)} results"
            )

        fine_result = fine_response.afes[0]
        if (
            not result_has_common_window(fine_result, args.max_error_rate)
            and (first_tap, last_tap) != (args.first_tap, args.last_tap)
        ):
            print(
                f"[AUTO] AFE{afe} has no common eye in the refined region; "
                "retrying the complete range with step 1"
            )
            fine_response, _ = run_sweep(
                pb,
                args,
                [afe],
                first_tap=args.first_tap,
                last_tap=args.last_tap,
                tap_step=1,
            )
            if not fine_response.success or len(fine_response.afes) != 1:
                raise RuntimeError(
                    f"AFE{afe} full-range fine scan failed: "
                    f"{fine_response.message}"
                )
            fine_result = fine_response.afes[0]
            fine_ranges[str(afe)].update(
                {
                    "first_tap": args.first_tap,
                    "last_tap": args.last_tap,
                    "fallback_to_full_range": True,
                    "reason": (
                        "refined region had no common eight-channel window"
                    ),
                }
            )
        else:
            fine_ranges[str(afe)]["fallback_to_full_range"] = False
        fine_responses[afe] = fine_result

    combined = pb.AfeDelaySweepResponse()
    combined.success = True
    combined.message = (
        "Automatic coarse-to-fine AFE delay sweep completed; "
        "all fine results use unit IDELAY steps"
    )
    combined.originalVtcEnable = coarse_response.originalVtcEnable
    for afe in afes:
        combined.afes.add().CopyFrom(fine_responses[afe])

    return combined, original_trigger_source, {
        "mode": "coarse_to_fine",
        "coarse_step": args.coarse_step,
        "fine_step": 1,
        "fine_ranges": fine_ranges,
    }


def apply_timing_settings(pb, args, settings: list[dict]) -> dict:
    endpoint = f"tcp://{args.ip}:{args.port}"
    context = zmq.Context()
    socket = make_socket(
        context,
        endpoint,
        args.timeout_ms,
        "afe-delay-apply-best",
    )
    try:
        request = pb.WriteAfeTimingRequest()
        for setting in settings:
            item = request.settings.add()
            item.afe = setting["afe"]
            item.delay = setting["delay"]
            item.bitslip = setting["bitslip"]

        response_type, response_payload = send_v2_request(
            pb,
            socket,
            args.route,
            pb.MT2_WRITE_AFE_TIMING_REQ,
            request.SerializeToString(),
        )
        if response_type != pb.MT2_WRITE_AFE_TIMING_RESP:
            raise RuntimeError(
                f"unexpected timing-write response type {response_type}; "
                f"expected {pb.MT2_WRITE_AFE_TIMING_RESP}"
            )

        response = pb.WriteAfeTimingResponse()
        if not response.ParseFromString(response_payload):
            raise RuntimeError("server returned an invalid WriteAfeTimingResponse")
        if not response.success:
            raise RuntimeError(response.message)

        applied = [
            {
                "afe": int(item.afe),
                "delay": int(item.delay),
                "bitslip": int(item.bitslip),
            }
            for item in response.applied
        ]
        if applied != settings:
            raise RuntimeError(
                f"timing readback mismatch: requested={settings}, applied={applied}"
            )
        if int(response.currentVtcEnable) != 0:
            raise RuntimeError("server did not leave delay VTC disabled")

        return {
            "success": True,
            "message": response.message,
            "previous_vtc_enable": int(response.previousVtcEnable),
            "current_vtc_enable": int(response.currentVtcEnable),
            "settings": applied,
        }
    finally:
        socket.close(0)
        context.term()


def format_window(window: TapWindow | None) -> str:
    if window is None:
        return "none"
    return (
        f"{window.first_tap}..{window.last_tap} "
        f"({window.point_count} tested points, midpoint={window.recommended_tap})"
    )


def plot_heatmap(
    run_dir: Path,
    afe: int,
    taps: list[int],
    failure_matrix: list[list[int]],
    common_window: TapWindow | None,
) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    values = [
        [math.log10(failures + 1) for failures in channel]
        for channel in failure_matrix
    ]
    figure, axis = plt.subplots(figsize=(12, 5.5))
    image = axis.imshow(
        values,
        aspect="auto",
        origin="lower",
        interpolation="nearest",
        cmap="magma",
    )
    tick_count = min(12, len(taps))
    tick_indices = sorted(
        {round(index * (len(taps) - 1) / max(1, tick_count - 1))
         for index in range(tick_count)}
    )
    axis.set_xticks(tick_indices)
    axis.set_xticklabels([str(taps[index]) for index in tick_indices])
    axis.set_yticks(range(8))
    axis.set_yticklabels([f"ch{afe * 8 + lane}" for lane in range(8)])
    axis.set_xlabel("IDELAY tap")
    axis.set_ylabel("Board channel")
    axis.set_title(f"AFE{afe} ramp failures across input delay")
    colorbar = figure.colorbar(image, ax=axis)
    colorbar.set_label("log10(ramp failures + 1)")

    if common_window is not None:
        first_index = taps.index(common_window.first_tap)
        last_index = taps.index(common_window.last_tap)
        axis.axvspan(
            first_index - 0.5,
            last_index + 0.5,
            facecolor="none",
            edgecolor="cyan",
            linewidth=2,
            label="common passing window",
        )
        axis.axvline(
            taps.index(common_window.recommended_tap),
            color="cyan",
            linestyle="--",
            linewidth=1.5,
            label="recommended midpoint",
        )
        axis.legend(loc="upper right")

    figure.tight_layout()
    output = run_dir / f"afe{afe}_delay_eye.png"
    figure.savefig(output, dpi=160)
    plt.close(figure)
    return output


def save_results(
    pb,
    response,
    args,
    requested_afes: list[int],
    original_trigger_source: str,
    auto_metadata: dict | None,
) -> tuple[Path | None, bool, bool]:
    run_dir = None
    if args.summary:
        timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        run_dir = args.output_dir / f"{timestamp}_{uuid.uuid4().hex[:8]}"
        run_dir.mkdir(parents=True, exist_ok=False)

    summaries = []
    recommendations_by_afe: dict[int, dict] = {}
    timing_choices_by_afe: dict[int, dict] = {}
    partial_candidates_by_afe: dict[int, PartialAfeWindow] = {}
    all_afes_pass = True
    plot_errors: list[str] = []

    returned_afes = [int(afe_result.afe) for afe_result in response.afes]
    if len(returned_afes) != len(set(returned_afes)):
        raise RuntimeError("server response contains duplicate AFE results")
    if set(returned_afes) != set(requested_afes):
        raise RuntimeError(
            "server response AFE set does not match the request: "
            f"requested={requested_afes}, returned={returned_afes}"
        )

    csv_context = (
        (run_dir / "delay_sweep.csv").open(
            "w",
            newline="",
            encoding="utf-8",
        )
        if run_dir is not None
        else nullcontext()
    )
    with csv_context as output_file:
        writer = None
        if output_file is not None:
            writer = csv.DictWriter(
                output_file,
                fieldnames=(
                    "afe",
                    "channel",
                    "tap",
                    "failures",
                    "transitions",
                    "error_rate",
                    "passing",
                ),
            )
            writer.writeheader()

        for afe_result in response.afes:
            afe = int(afe_result.afe)
            points = list(afe_result.points)
            if not points:
                raise RuntimeError(f"AFE{afe} response contains no sweep points")
            taps = [int(point.tap) for point in points]
            transitions = [int(point.transitionsPerChannel) for point in points]
            if any(len(point.channelFailures) != 8 for point in points):
                raise RuntimeError(
                    f"AFE{afe} response does not contain eight channel counts per tap"
                )
            failure_matrix = [
                [int(point.channelFailures[lane]) for point in points]
                for lane in range(8)
            ]
            eye = summarize_afe_eye(
                taps,
                failure_matrix,
                transitions,
                max_error_rate=args.max_error_rate,
            )

            print(
                f"AFE{afe}: original_delay={afe_result.originalDelay}, "
                f"bitslip={afe_result.bitslip}"
            )
            for lane, window in enumerate(eye.channel_windows):
                status = "PASS" if window is not None else "FAIL"
                print(
                    f"  [{status}] ch{afe * 8 + lane:02d}: "
                    f"passing eye {format_window(window)}"
                )
            partial_candidate = None
            if eye.common_window is None:
                all_afes_pass = False
                print("  [FAIL] no delay window is valid for all eight channels")
                partial_candidate = best_partial_passing_window(
                    taps,
                    failure_matrix,
                    transitions,
                    max_error_rate=args.max_error_rate,
                )
                if partial_candidate is None:
                    print("  [BAD] no channel has a passing IDELAY tap")
                else:
                    partial_candidates_by_afe[afe] = partial_candidate
                    board_channels = [
                        afe * 8 + lane
                        for lane in partial_candidate.passing_lanes
                    ]
                    print(
                        "  [PARTIAL CANDIDATE] channels "
                        + ",".join(str(channel) for channel in board_channels)
                        + "; eye "
                        + format_window(partial_candidate.window)
                    )
                    if args.accept_partial_config:
                        recommendations_by_afe[afe] = {
                            "afe": afe,
                            "delay": partial_candidate.window.recommended_tap,
                            "bitslip": int(afe_result.bitslip),
                        }
                        timing_choices_by_afe[afe] = {
                            "mode": "partial",
                            "passing_lanes": list(
                                partial_candidate.passing_lanes
                            ),
                            "passing_channels": board_channels,
                            "excluded_lanes": list(
                                partial_candidate.excluded_lanes
                            ),
                        }
            else:
                print(
                    "  [PASS] common eye " + format_window(eye.common_window)
                )
                recommendations_by_afe[afe] = {
                    "afe": afe,
                    "delay": eye.common_window.recommended_tap,
                    "bitslip": int(afe_result.bitslip),
                }
                timing_choices_by_afe[afe] = {
                    "mode": "common",
                    "passing_lanes": list(range(8)),
                    "passing_channels": [afe * 8 + lane for lane in range(8)],
                    "excluded_lanes": [],
                }

            for lane, failures_by_tap in enumerate(failure_matrix):
                for tap, failures, total in zip(
                    taps, failures_by_tap, transitions
                ):
                    error_rate = failures / total
                    if writer is not None:
                        writer.writerow(
                            {
                                "afe": afe,
                                "channel": afe * 8 + lane,
                                "tap": tap,
                                "failures": failures,
                                "transitions": total,
                                "error_rate": f"{error_rate:.12g}",
                                "passing": int(
                                    error_rate <= args.max_error_rate
                                ),
                            }
                        )

            if args.summary:
                try:
                    plot_heatmap(
                        run_dir,
                        afe,
                        taps,
                        failure_matrix,
                        eye.common_window,
                    )
                except Exception as error:
                    plot_errors.append(f"AFE{afe}: {error}")

            summaries.append(
                {
                    "afe": afe,
                    "original_delay": int(afe_result.originalDelay),
                    "bitslip": int(afe_result.bitslip),
                    "tested_taps": taps,
                    "channel_windows": [
                        None if window is None else asdict(window)
                        for window in eye.channel_windows
                    ],
                    "common_window": (
                        None
                        if eye.common_window is None
                        else asdict(eye.common_window)
                    ),
                    "partial_window": (
                        None
                        if partial_candidate is None
                        else {
                            "window": asdict(partial_candidate.window),
                            "passing_lanes": list(
                                partial_candidate.passing_lanes
                            ),
                            "passing_channels": [
                                afe * 8 + lane
                                for lane in partial_candidate.passing_lanes
                            ],
                            "excluded_lanes": list(
                                partial_candidate.excluded_lanes
                            ),
                        }
                    ),
                }
            )

    strict_invalid_afes = [
        summary["afe"]
        for summary in summaries
        if summary["common_window"] is None
    ]
    partial_afes = [
        afe for afe in requested_afes if afe in partial_candidates_by_afe
    ]
    unusable_afes = [
        afe
        for afe in strict_invalid_afes
        if afe not in partial_candidates_by_afe
    ]
    if strict_invalid_afes:
        print(
            "[ALERT] no common eight-channel timing exists for AFE(s): "
            + ", ".join(str(afe) for afe in strict_invalid_afes)
        )
        if args.accept_partial_config:
            for afe in partial_afes:
                candidate = partial_candidates_by_afe[afe]
                board_channels = [
                    afe * 8 + lane for lane in candidate.passing_lanes
                ]
                print(
                    f"[WARN] AFE{afe} partial timing accepted for channel(s) "
                    + ",".join(str(channel) for channel in board_channels)
                )
            if unusable_afes:
                print(
                    "[ALERT] AFE(s) with no passing channel are in bad state "
                    "and will remain unchanged: "
                    + ", ".join(str(afe) for afe in unusable_afes)
                )
        else:
            print(
                "[HINT] Re-run with --apply_best --accept_partial_config "
                "to compute and apply the best window for the usable "
                "channels in each AFE."
            )

    if all_afes_pass or args.accept_partial_config:
        recommendations = [
            recommendations_by_afe[afe]
            for afe in requested_afes
            if afe in recommendations_by_afe
        ]
    else:
        recommendations = []
    selected_afes = [setting["afe"] for setting in recommendations]
    skipped_afes = [
        afe for afe in requested_afes if afe not in selected_afes
    ]
    timing_application = {
        "requested": bool(args.apply_best),
        "accept_partial_config": bool(args.accept_partial_config),
        "attempted": False,
        "partial": False,
        "success": not args.apply_best,
        "settings": [],
        "channel_coverage": [
            {
                "afe": afe,
                **timing_choices_by_afe[afe],
            }
            for afe in selected_afes
        ],
        "skipped_afes": skipped_afes,
        "bad_afes": unusable_afes,
    }
    may_apply = args.apply_best and bool(recommendations)
    if may_apply:
        timing_application["attempted"] = True
        timing_application["partial"] = not all_afes_pass
        timing_application["settings"] = recommendations
        try:
            timing_application.update(
                apply_timing_settings(pb, args, recommendations)
            )
            for setting in recommendations:
                choice = timing_choices_by_afe[setting["afe"]]
                coverage = ""
                if choice["mode"] == "partial":
                    coverage = ", channels=" + ",".join(
                        str(channel)
                        for channel in choice["passing_channels"]
                    )
                print(
                    f"[APPLY] AFE{setting['afe']}: IDELAY={setting['delay']}, "
                    f"BITSLIP={setting['bitslip']}{coverage}"
                )
        except Exception as error:
            timing_application["success"] = False
            timing_application["error"] = str(error)
            print(f"[FAIL] could not apply recommended timing: {error}")
    elif args.apply_best:
        timing_application["success"] = False
        if not args.accept_partial_config and strict_invalid_afes:
            timing_application["reason"] = (
                "not attempted because partial configuration was not accepted"
            )
        else:
            timing_application["reason"] = (
                "no requested AFE has even one channel with a passing window"
            )
        print("[APPLY] skipped; no hardware timing was changed")

    application_succeeded = bool(timing_application["success"])
    partial_configuration_applied = (
        bool(timing_application["partial"])
        and bool(timing_application["attempted"])
        and application_succeeded
    )
    summary = {
        "result": (
            "PASS"
            if all_afes_pass and application_succeeded
            else "PARTIAL"
            if partial_configuration_applied
            else "FAIL"
        ),
        "server_success": bool(response.success),
        "server_message": response.message,
        "original_vtc_enable": int(response.originalVtcEnable),
        "endpoint": f"tcp://{args.ip}:{args.port}",
        "route": args.route,
        "trigger_source": "software",
        "original_trigger_source": original_trigger_source,
        "requested_afes": requested_afes,
        "first_tap": args.first_tap,
        "last_tap": args.last_tap,
        "tap_step": 1 if args.auto else args.tap_step,
        "auto_scan": auto_metadata,
        "samples": args.samples,
        "waveforms_per_tap": args.waveforms,
        "settle_time_us": args.settle_us,
        "maximum_passing_error_rate": args.max_error_rate,
        "artifacts_generated": bool(args.summary),
        "afes": summaries,
        "timing_application": timing_application,
        "plot_errors": plot_errors,
    }
    if run_dir is not None:
        (run_dir / "summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    for error in plot_errors:
        print(f"[WARN] heatmap not generated: {error}")
    return run_dir, all_afes_pass, application_succeeded


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Sweep the common AFE IDELAY using synchronized ramp data and "
            "save per-channel error maps."
        )
    )
    parser.add_argument("--ip", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9876)
    parser.add_argument("--route", default="mezz/0")
    parser.add_argument("--afes", default="0,3,4")
    parser.add_argument("--first-tap", type=int, default=0)
    parser.add_argument("--last-tap", type=int, default=511)
    parser.add_argument("--tap-step", type=int, default=4)
    parser.add_argument(
        "--auto",
        action="store_true",
        help=(
            "Scan coarsely, then refine each AFE at IDELAY step 1; falls "
            "back to the full range if needed."
        ),
    )
    parser.add_argument(
        "--coarse-step",
        "--coarse_step",
        dest="coarse_step",
        type=int,
        default=10,
        help="Initial IDELAY step used by --auto (default: 10).",
    )
    parser.add_argument(
        "--apply-best",
        "--apply_best",
        dest="apply_best",
        action="store_true",
        help=(
            "Apply each AFE's common eight-channel midpoint and current "
            "BITSLIP after a successful scan."
        ),
    )
    parser.add_argument(
        "--accept-partial-config",
        "--accept_partial_config",
        dest="accept_partial_config",
        action="store_true",
        help=(
            "With --apply_best, choose the best window for the largest "
            "simultaneously passing channel subset in each AFE."
        ),
    )
    parser.add_argument("--samples", type=int, default=512)
    parser.add_argument("--waveforms", type=int, default=8)
    parser.add_argument("--settle-us", type=int, default=10)
    parser.add_argument("--timeout-ms", type=int, default=600000)
    parser.add_argument(
        "--max-error-rate",
        type=float,
        default=0.0,
        help="Maximum ramp error fraction for a tap to pass (default: zero).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("afe_delay_sweep_results"),
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help=(
            "Create a result directory containing summary.json, CSV data, "
            "and eye plots. By default no artifacts are generated."
        ),
    )
    args = parser.parse_args()

    try:
        afes = parse_indices(args.afes, maximum=4)
    except ValueError as error:
        parser.error(str(error))
    if args.first_tap < 0 or args.last_tap > 511:
        parser.error("tap range must be within 0..511")
    if args.first_tap > args.last_tap:
        parser.error("--first-tap cannot exceed --last-tap")
    if args.tap_step <= 0:
        parser.error("--tap-step must be greater than zero")
    if args.coarse_step <= 0:
        parser.error("--coarse-step must be greater than zero")
    if args.accept_partial_config and not args.apply_best:
        parser.error("--accept_partial_config requires --apply_best")
    if args.samples < 2 or args.samples > 2048:
        parser.error("--samples must be in 2..2048")
    if args.waveforms <= 0:
        parser.error("--waveforms must be greater than zero")
    if args.settle_us < 0 or args.settle_us > 1000000:
        parser.error("--settle-us must be in 0..1000000")
    if args.timeout_ms <= 0:
        parser.error("--timeout-ms must be greater than zero")
    if args.max_error_rate < 0.0 or args.max_error_rate > 1.0:
        parser.error("--max-error-rate must be in 0..1")

    try:
        pb = load_protobuf_module(require_timing_write=args.apply_best)
        print("DAPHNE AFE input-delay ramp sweep")
        print(f"  endpoint       : tcp://{args.ip}:{args.port}")
        print(f"  route          : {args.route}")
        print(f"  AFEs           : {afes}")
        if args.auto:
            print(
                f"  taps           : {args.first_tap}..{args.last_tap} "
                f"coarse step {args.coarse_step}, fine step 1"
            )
        else:
            print(
                f"  taps           : {args.first_tap}..{args.last_tap} "
                f"step {args.tap_step}"
            )
        print(f"  samples        : {args.samples}")
        print(f"  waveforms/tap  : {args.waveforms}")
        print("  trigger        : software (server-side)")
        if args.apply_best:
            print(
                "[INFO] A successful scan will apply each common-eye "
                "midpoint and leave delay VTC disabled."
            )
            if args.accept_partial_config:
                print(
                    "[WARN] partial configuration accepted: the best "
                    "simultaneously passing channel subset will be used."
                )
        else:
            print(
                "[INFO] The client will restore the trigger source; the "
                "server will restore AFE output, IDELAY and VTC state."
            )

        auto_metadata = None
        if args.auto:
            response, original_trigger_source, auto_metadata = run_auto_sweep(
                pb,
                args,
                afes,
            )
        else:
            response, original_trigger_source = run_sweep(pb, args, afes)
        if not response.success:
            print(f"[FAIL] {response.message}")
            return 1
        run_dir, passed, application_succeeded = save_results(
            pb,
            response,
            args,
            afes,
            original_trigger_source,
            auto_metadata,
        )
        if run_dir is not None:
            print(f"[INFO] detailed results: {run_dir}")
        else:
            print("[INFO] no artifacts generated; use --summary to create them")
        if passed and application_succeeded:
            print("[PASS] every requested AFE has a common eight-channel eye")
            return 0
        if args.accept_partial_config and application_succeeded:
            print(
                "[PARTIAL] best available channel subsets configured; "
                "AFEs with no passing channel were left unchanged"
            )
            return 0
        if passed:
            print("[FAIL] common eyes found, but timing application failed")
            return 1
        print("[FAIL] at least one requested AFE has no common eight-channel eye")
        return 1
    except KeyboardInterrupt:
        print(
            "[FAIL] interrupted by user; the server-side scan continues and "
            "restores the hardware before accepting another request"
        )
        return 130
    except Exception as error:
        print(f"[FAIL] {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
