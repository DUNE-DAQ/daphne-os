"""Physical AFE eye scan through asynchronous DMA jobs, never legacy alignment."""
import csv
import json
from pathlib import Path
import time
import uuid
from dma_client import DmaClient
from protobuf_loader import load_protobuf_modules
from v2_client import V2Client


def lane_eyes(afe_result):
    points = sorted((p for p in afe_result.points if p.bitslip == afe_result.bitslip), key=lambda p: p.tap)
    results = []
    for lane in range(8):
        best = None
        first = None
        previous = None
        for p in points:
            passing = not (p.channelFailures[lane] or p.low_bit_failures[lane] or p.boundary_failures[lane])
            if passing:
                if first is None:
                    first = p.tap
                if best is None or p.tap - first > best[1] - best[0]:
                    best = (first, p.tap)
            else:
                first = None
            previous = p.tap
        results.append({"lane": lane, "channel": 8 * afe_result.afe + lane,
                        "window": list(best) if best else None})
    return results


def save_eye_plots(directory, result):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError:
        print("Eye plots omitted: matplotlib is not installed; all metrics are in CSV/JSON")
        return
    for a in result.afes:
        values = np.full((16, 512), np.nan)
        for p in a.points:
            values[p.bitslip, p.tap] = sum(not (p.channelFailures[l] or p.low_bit_failures[l] or p.boundary_failures[l]) for l in range(8))
        fig, ax = plt.subplots(figsize=(12, 5))
        img = ax.imshow(values, origin="lower", aspect="auto", extent=(-.5,511.5,-.5,15.5), vmin=0, vmax=8)
        ax.set(xlabel="IDELAY tap", ylabel="BITSLIP", title=f"AFE{a.afe}: passing physical lanes (zero errors)")
        ax.set_yticks(range(16))
        if a.approved_lane_mask:
            ax.plot(a.selected_delay, a.bitslip, "rx", markersize=10)
        fig.colorbar(img, ax=ax, label="Passing lanes")
        fig.tight_layout()
        fig.savefig(directory / f"afe_{a.afe}_eye.png", dpi=150)
        plt.close(fig)


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
                print(f"AFE{a.afe}: slip={a.bitslip} eye={a.first_passing_tap}..{a.last_passing_tap} "
                      f"delay={a.selected_delay} lanes=0x{a.approved_lane_mask:02x} applied={a.applied}")
            if args.summary:
                directory = Path(args.output_dir) / ("dma-eye-" + time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8])
                directory.mkdir(parents=True)
                (directory / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
                with (directory / "points.csv").open("w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(["afe", "bitslip", "tap", "lane", "within_failures", "low_bit_failures", "boundary_failures", "within_transitions", "boundary_transitions"])
                    for a in result.afes:
                        for point in a.points:
                            for lane in range(8):
                                writer.writerow([a.afe, point.bitslip, point.tap, lane, point.channelFailures[lane],
                                    point.low_bit_failures[lane], point.boundary_failures[lane],
                                    point.transitionsPerChannel, point.boundary_transitions_per_channel])
                save_eye_plots(directory, result)
                print(f"DMA scan artifacts: {directory}")
            client.acknowledge()
            return 0 if result.success else 1
        finally:
            client.cancel()
