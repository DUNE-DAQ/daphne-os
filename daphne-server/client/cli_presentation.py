"""User-facing wording shared by acquisition backends."""

def print_acquisition_start(args, channels, backend):
    print(f"[INFO] acquisition backend: {backend}")
    print(f"Configured trigger source: {args.trigger_source}")
    print(f"Requesting {args.N} waveforms (L={args.L}) on channels {channels}; "
          f"TRIGGER_SOURCE={args.trigger_source}")


def print_acquisition_done(completed, requested):
    print(f"Done. Received {completed}/{requested} waveforms per channel.")


def print_scan_header(args, afes):
    print("DAPHNE AFE input-delay ramp sweep")
    print(f"  backend        : {'dma' if args.dma else 'spybuffer'}")
    print(f"  endpoint       : tcp://{args.ip}:{args.port}")
    print(f"  route          : {args.route}")
    print(f"  AFEs           : {afes}")
    if args.dma or args.auto:
        fine = args.tap_step if args.dma else 1
        print(f"  taps           : {args.first_tap}..{args.last_tap} "
              f"coarse step {args.coarse_step}, fine step {fine}")
    else:
        print(f"  taps           : {args.first_tap}..{args.last_tap} step {args.tap_step}")
    print(f"  samples        : {args.samples}")
    print(f"  waveforms/tap  : {args.waveforms}")
    print("  trigger        : software (server-side)")
    if args.dma and args.apply_best:
        print(f"  verification   : {args.verification_samples} samples at selected timing")
    if args.apply_best:
        print("[INFO] A successful scan will apply each common-eye midpoint and leave delay VTC disabled.")
        if args.accept_partial_config:
            print("[WARN] partial configuration accepted: the best simultaneously passing channel subset will be used.")
    else:
        print("[INFO] The server will restore AFE output, IDELAY and VTC state.")


def format_window(window):
    if window is None:
        return "none"
    return (f"{window.first_tap}..{window.last_tap} "
            f"({window.point_count} tested points, midpoint={window.recommended_tap})")


def print_scan_channels(afe, original_delay, bitslip, windows):
    print(f"AFE{afe}: original_delay={original_delay}, bitslip={bitslip}")
    for lane, window in enumerate(windows):
        status = 'PASS' if window is not None else 'FAIL'
        print(f"  [{status}] ch{afe * 8 + lane:02d}: passing eye {format_window(window)}")


def print_scan_apply(afe, delay, bitslip, channels=None):
    coverage = '' if channels is None else ', channels=' + ','.join(map(str, channels))
    print(f"[APPLY] AFE{afe}: IDELAY={delay}, BITSLIP={bitslip}{coverage}")


def print_scan_artifacts(directory):
    if directory is None:
        print("[INFO] no artifacts generated; use --summary to create them")
    else:
        print(f"[INFO] detailed results: {directory}")
