"""Shared explicit DMA capture contract for file acquisition and oscilloscope."""


def add_dma_capture_arguments(parser):
    parser.add_argument('--capture-mode', choices=('finite', 'triggered'), default='finite',
                        help='DMA finite START or event-synchronized triggered capture')
    parser.add_argument('--pretrigger', type=int, default=0, metavar='P',
                        help='Samples before the trigger; requires --dma --capture-mode triggered')
    parser.add_argument('--trigger-timeout-ms', type=int, default=10000,
                        help='Per-waveform DMA deadline including history fill and event wait (10..600000)')
    parser.add_argument('--job-timeout-ms', type=int, default=0,
                        help='Total DMA batch deadline; 0 derives it from N and the per-waveform deadline')


def validate_dma_capture_arguments(parser, args):
    mode, p = args.capture_mode, args.pretrigger
    if not args.dma:
        if mode != 'finite' or p or args.trigger_timeout_ms != 10000 or args.job_timeout_ms:
            parser.error('DMA capture options require --dma')
        return
    if p < 0 or p >= args.L:
        parser.error('--pretrigger requires 0 <= P < L')
    if mode == 'finite' and (p or args.trigger_source != 'software'):
        parser.error('Finite DMA requires software trigger and P=0; select triggered for external/timing')
    if mode == 'triggered' and args.trigger_source not in ('software', 'external', 'timing'):
        parser.error('Triggered DMA supports software, external and timing sources')
    if not 10 <= args.trigger_timeout_ms <= 600000 or args.job_timeout_ms < 0:
        parser.error('Invalid DMA deadline: per waveform 10..600000 ms, total >= 0')


def capture_contract(args):
    return dict(capture_mode=getattr(args, 'capture_mode', 'finite'), samples=args.L,
                pretrigger_samples=getattr(args, 'pretrigger', 0), trigger_source=args.trigger_source)


def relative_sample_axis(samples, pretrigger, sampling_rate_hz):
    import numpy as np
    return (np.arange(samples, dtype=float) - pretrigger) * (1e6 / sampling_rate_hz)


def phase_text(pb, phase):
    return {
        getattr(pb, 'DMA_PHASE_PREPARING', -1): 'Preparing',
        getattr(pb, 'DMA_PHASE_HISTORY', -2): 'Filling pretrigger history',
        getattr(pb, 'DMA_PHASE_WAITING_TRIGGER', -3): 'Waiting for trigger',
        getattr(pb, 'DMA_PHASE_CAPTURING', -4): 'Capturing',
        getattr(pb, 'DMA_PHASE_FINALIZING', -5): 'Finalizing DMA',
        getattr(pb, 'DMA_PHASE_READING', -6): 'Reading waveform',
    }.get(phase, 'Acquiring')
