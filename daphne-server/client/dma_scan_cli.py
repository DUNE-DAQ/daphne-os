"""Physical AFE eye scan through asynchronous DMA jobs, never legacy alignment."""
import csv
import json
from pathlib import Path
import time
import uuid
from dma_client import DmaClient
from protobuf_loader import load_protobuf_modules
from v2_client import V2Client
from afe_delay_sweep_analysis import TapWindow, summarize_afe_eye
from cli_presentation import (
    format_window, print_scan_channels, print_scan_apply, print_scan_artifacts,
)


def selected_eye(afe_result):
    points = sorted((p for p in afe_result.points if p.bitslip == afe_result.bitslip), key=lambda p: p.tap)
    if not points:
        return points, None
    failures = [[p.channelFailures[lane] + p.low_bit_failures[lane] + p.boundary_failures[lane]
                 for p in points] for lane in range(8)]
    eye = summarize_afe_eye([p.tap for p in points], failures,
                            [p.transitionsPerChannel for p in points])
    return points, eye


def lane_eyes(afe_result):
    _, eye = selected_eye(afe_result)
    windows = eye.channel_windows if eye else [None] * 8
    return [{"lane": lane, "channel": 8 * afe_result.afe + lane,
             "window": [window.first_tap, window.last_tap] if window else None,
             "tested_points": window.point_count if window else 0}
            for lane, window in enumerate(windows)]


def save_eye_plots(directory, result):
    try:
        import matplotlib
        matplotlib.use("Agg")
    except ImportError:
        print("[WARN] heatmap not generated: matplotlib is not installed; all metrics are in CSV/JSON")
        return {}
    from dma_eye_plot import save_channel_eye, save_bitslip_overview
    metrics = {}
    for a in result.afes:
        metrics[a.afe] = save_channel_eye(directory, a)
        save_bitslip_overview(directory, a)
    return metrics


def run_dma_scan(args, afes):
    pb, _ = load_protobuf_modules(require_dma=True)
    request = pb.AfeDelaySweepRequest(backend=pb.ACQUISITION_DMA, afes=afes,
        firstTap=args.first_tap, lastTap=args.last_tap, tapStep=args.tap_step,
        numberOfSamples=args.samples, numberOfWaveforms=args.waveforms,
        settleTimeUs=args.settle_us, coarse_step=args.coarse_step,
        apply_best=args.apply_best, accept_partial_config=args.accept_partial_config,
        verification_samples=args.verification_samples, timeout_ms=args.timeout_ms)
    with V2Client(pb, args.ip, args.port, route=args.route, timeout_ms=min(args.timeout_ms, 5000),
                  identity="dma-scan-" + uuid.uuid4().hex) as transport:
        client = DmaClient(pb, transport.rpc)
        try:
            result = client.scan(request)
            summary = {"backend": "dma", "build_id": client.capabilities.gateware_build_id,
                       "success": result.success, "message": result.message,
                       "verification_samples": args.verification_samples, "afes": []}
            for a in result.afes:
                item = {"afe": a.afe, "original_delay": a.originalDelay, "bitslip": a.bitslip,
                    "selected_delay": a.selected_delay, "first_passing_tap": a.first_passing_tap,
                    "last_passing_tap": a.last_passing_tap, "approved_lane_mask": a.approved_lane_mask,
                    "applied": a.applied, "lane_eyes": lane_eyes(a)}
                summary["afes"].append(item)
                points, eye = selected_eye(a)
                print_scan_channels(a.afe, a.originalDelay, a.bitslip,
                                    eye.channel_windows if eye else [None] * 8)
                if a.approved_lane_mask:
                    window = TapWindow(a.first_passing_tap, a.last_passing_tap,
                        sum(a.first_passing_tap <= p.tap <= a.last_passing_tap for p in points), a.selected_delay)
                    if a.approved_lane_mask == 255:
                        print("  [PASS] common eye " + format_window(window))
                    else:
                        channels = [a.afe * 8 + lane for lane in range(8) if a.approved_lane_mask & (1 << lane)]
                        print("  [FAIL] no delay window is valid for all eight channels")
                        print("  [PARTIAL CANDIDATE] channels " + ','.join(map(str, channels)) + "; eye " + format_window(window))
                else:
                    print("  [FAIL] no delay window is valid for all eight channels")
                if a.applied:
                    channels = None if a.approved_lane_mask == 255 else [a.afe * 8 + lane for lane in range(8) if a.approved_lane_mask & (1 << lane)]
                    print_scan_apply(a.afe, a.selected_delay, a.bitslip, channels)
                elif args.apply_best:
                    print(f"[APPLY] AFE{a.afe}: skipped")
            directory = None
            if args.summary:
                directory = Path(args.output_dir) / ("dma-eye-" + time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8])
                directory.mkdir(parents=True)
                with (directory / "points.csv").open("w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(["afe", "bitslip", "tap", "lane", "within_failures", "low_bit_failures", "boundary_failures", "within_transitions", "boundary_transitions"])
                    for a in result.afes:
                        for point in a.points:
                            for lane in range(8):
                                writer.writerow([a.afe, point.bitslip, point.tap, lane, point.channelFailures[lane],
                                    point.low_bit_failures[lane], point.boundary_failures[lane],
                                    point.transitionsPerChannel, point.boundary_transitions_per_channel])
                from dma_eye_plot import measured_margins
                for a, item in zip(result.afes, summary['afes']):
                    item['channel_margins'] = measured_margins(a)[2]
                (directory / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
                try:
                    save_eye_plots(directory, result)
                except Exception as error:
                    print(f"[WARN] heatmap not generated: {error}")
            print_scan_artifacts(directory)
            full = bool(result.afes) and result.success and all(a.approved_lane_mask == 255 for a in result.afes)
            if full:
                print("[PASS] every requested AFE has a common eight-channel eye")
            elif result.success and args.accept_partial_config:
                print("[PARTIAL] best available channel subsets configured; AFEs with no passing channel were left unchanged")
            else:
                print("[FAIL] at least one requested AFE has no common eight-channel eye")
                if result.message:
                    print(f"[FAIL] {result.message}")
            client.acknowledge()
            return 0 if result.success else 1
        finally:
            client.cancel()
