#!/usr/bin/env python3
"""Real Qt acquisition/render/save and asynchronous close, on daphne-dev."""
import argparse
import json
import os
from pathlib import Path
import socket
import sys
import time
from types import SimpleNamespace
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'daphne-server/client'))
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PyQt6 import QtWidgets
import osc
from identity_cli import add_identity_argument

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--early-close', action='store_true')
add_identity_argument(parser, default='osc-persistent-live-20261012')
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
settings = SimpleNamespace(ip='193.206.157.36', port=40001, channels=[39, 0, 17], channel=0, L=32000,
    trigger_source='software', software_trigger=True, timeout_ms=10000, sampling_rate_hz=62.5e6,
    route='mezz/0', fft_every=1, autoscale=True, enable_fft=False, fft_channel=None,
    enable_charge_hist=False, disable_rms=False, rms_window=100, save_dir=str(args.output/'saved'), dma=True,
    capture_mode='persistent', pretrigger=4096, identity=args.identity, period_ms=100,
    max_waveforms=37, ui_period_ms=33, fft_full_scale_counts=16384, fft_keep_dc=False,
    fft_window_function='hann', trigger_timeout_ms=30000, job_timeout_ms=60000, pressure_timeout_ms=0,
    append_data=False, save_queue_frames=16, flush_every_frames=1, run_label='persistent-physical-37', run_notes='')
app = QtWidgets.QApplication([])
if args.early_close:
    settings.max_waveforms = 10000
window = osc.DaphneOscApp(settings)
window.resize(1250, 750); window.show()
deadline = time.monotonic()+70
try:
    if args.early_close:
        while window.worker._frames_acquired < 3 and time.monotonic() < deadline:
            app.processEvents(); time.sleep(.005)
        assert window.worker._frames_acquired >= 3, window._latest_worker_msg
        begin = time.monotonic(); window.close(); close_return = time.monotonic()-begin
        assert close_return < .2, 'GUI close blocked on DMA cleanup'
        while window.isVisible() and time.monotonic() < deadline:
            app.processEvents(); time.sleep(.005)
        assert not window.isVisible() and not window.worker_thread.isRunning()
        assert not window.worker.dma_cleanup_error, window.worker.dma_cleanup_error
        report = dict(result='PASS', mode='early-close', client_host=socket.gethostname(),
                      close_return_s=close_return, cleanup_s=time.monotonic()-begin,
                      acquired=window.worker._frames_acquired, writer=window.writer.snapshot())
        (args.output/'summary.json').write_text(json.dumps(report, indent=2)+'\n')
        print(json.dumps(report), flush=True)
        sys.exit(0)
    while not window.worker._stop_evt.is_set() and time.monotonic() < deadline:
        app.processEvents(); time.sleep(.005)
    for _ in range(5):
        app.processEvents(); time.sleep(.02)
    assert window.worker._frames_acquired == 37, window._latest_worker_msg
    assert window._last_rendered_frame_id == 37, window._latest_worker_msg
    assert not window.worker.dma_cleanup_error, window.worker.dma_cleanup_error
    assert window.worker._dma_skipped_plots > 0
    stats = []
    for ch, curve in zip(settings.channels, window.curves):
        displayed_x, displayed_y = curve.getData()
        assert len(displayed_y) > 0 and len(displayed_x) == len(displayed_y)
        x, y = curve.getOriginalDataset()
        assert len(y) == 32000 and x[4096] == 0 and int(np.min(y)) >= 0 and int(np.max(y)) < 16384
        stats.append(dict(channel=ch, minimum=int(np.min(y)), maximum=int(np.max(y)), mean=float(np.mean(y)),
                          source_samples=len(y), rendered_samples=len(displayed_y)))
    window.grab().save(str(args.output/'osc-persistent.png'))
    report = dict(result='PASS', client_host=socket.gethostname(), acquired=37,
                  rendered_frames=window._frames_rendered, last_frame=window._last_rendered_frame_id,
                  skipped_plots=window.worker._dma_skipped_plots, status=window._latest_worker_msg, stats=stats)
finally:
    window.close()
    deadline = time.monotonic()+25
    while window.worker_thread.isRunning() and time.monotonic() < deadline:
        app.processEvents(); time.sleep(.01)
    assert not window.worker_thread.isRunning(), 'DMA worker shutdown still pending'
    app.processEvents()
assert window.writer.snapshot()['written_frames'] == 37, window.writer.snapshot()
for ch in settings.channels:
    assert (args.output/'saved'/f'channel_{ch}.dat').stat().st_size == 37*32000*2
report['writer'] = window.writer.snapshot()
(args.output/'summary.json').write_text(json.dumps(report, indent=2)+'\n')
print(json.dumps(report), flush=True)
