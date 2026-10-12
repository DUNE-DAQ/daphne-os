"""Qt worker and disk integration with an offline raw DMA transport."""
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch
import unittest
import numpy as np
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'client'))
from test_dma_client import FakeServer, pb
from test_dma_trigger_client import TriggerServer


@unittest.skipUnless(importlib.util.find_spec('PyQt6') and importlib.util.find_spec('pyqtgraph'), 'Qt optional on the test host')
class DmaOscTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6 import QtWidgets
        cls.qt_app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_force_flag_reaches_triggered_worker_and_saved_contract(self):
        from PyQt6 import QtWidgets
        import osc
        from dma_client import DmaClient
        from dma_options import capture_contract
        app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        server=TriggerServer();original=server.rpc
        def rpc(t,req,*rest):
            response=original(t,req,*rest)
            if t==pb.MT2_ACQUISITION_CAPABILITIES_REQ:response.force_acquisition_supported=True
            if t==pb.MT2_DMA_ACQUIRE_REQ:
                self.assertTrue(req.force_acquisition);response.force_acquisition=True
            return response
        request=pb.DumpSpyBuffersRequest(numberOfSamples=2048,numberOfWaveforms=1,channelList=[0])
        worker=osc.AcquisitionWorker('fake','mezz/0','fake',1000,request,20,max_waveforms=1,
            dma=True,dma_capture_mode='triggered',dma_trigger_source='external',dma_pretrigger=1024,dma_force_acq=True)
        worker._link=object();worker._dma_client=DmaClient(pb,rpc)
        worker._poll_once();self.assertEqual(worker._frames_acquired,1)
        settings=SimpleNamespace(L=2048,capture_mode='triggered',pretrigger=1024,trigger_source='external',force_acq=True)
        self.assertTrue(capture_contract(settings)['force_acquisition'])
        app.processEvents()

    def test_unaligned_frontend_error_keeps_window_open_and_reports_to_terminal(self):
        from PyQt6 import QtWidgets
        import osc
        from dma_client import DmaClient
        app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        from test_dma_persistent_client import StreamServer
        server=StreamServer()
        original=server.rpc
        def rpc(*args):
            if args[0]==pb.MT2_DMA_ACQUIRE_REQ:
                server.calls.append(args)
                return pb.DmaJobResponse(success=False,message='ALIGNMENT_REQUIRED: run the DMA eye scan')
            return original(*args)
        def ensure_link(worker):
            if worker._dma_client is None:
                worker._link=object()
                worker._dma_client=DmaClient(pb,rpc,worker._stop_evt.is_set)
        args=SimpleNamespace(ip='fake',port=1,channels=[0],channel=0,L=2048,trigger_source='external',
            software_trigger=False,timeout_ms=1000,sampling_rate_hz=62.5e6,route='mezz/0',
            fft_every=1,autoscale=False,enable_fft=False,fft_channel=None,enable_charge_hist=False,
            disable_rms=True,rms_window=10,save_dir='',dma=True,capture_mode='triggered',pretrigger=1024,
            identity='fake',period_ms=20,max_waveforms=0,ui_period_ms=33,fft_full_scale_counts=16384,
            fft_keep_dc=False,trigger_timeout_ms=30000,job_timeout_ms=0)
        terminal=io.StringIO()
        with patch.object(osc.AcquisitionWorker,'_ensure_link',ensure_link), \
                patch.object(app,'quit') as quit_app, patch('sys.stderr',terminal):
            window=osc.DaphneOscApp(args);window.show()
            try:
                deadline=time.monotonic()+2
                while 'ALIGNMENT_REQUIRED' not in window._latest_worker_msg and time.monotonic()<deadline:
                    app.processEvents();time.sleep(.005)
                calls=len(server.calls)
                deadline=time.monotonic()+.3
                while time.monotonic()<deadline:
                    app.processEvents();time.sleep(.005)
                self.assertTrue(window.isVisible())
                quit_app.assert_not_called()
                self.assertIn('ALIGNMENT_REQUIRED',window.status.text())
                self.assertIn('L=2048 N=infinite',window.status.text())
                self.assertIn('mode=persistent',window.status.text())
                self.assertIn('acquireMs=',window.status.text())
                self.assertIn('ALIGNMENT_REQUIRED',terminal.getvalue())
                self.assertEqual(len(server.calls),calls)
                self.assertEqual(window.worker._frames_acquired,0)
            finally:
                window.close()
                deadline=time.monotonic()+3
                while window.worker_thread.isRunning() and time.monotonic()<deadline:
                    app.processEvents();time.sleep(.005)
                app.processEvents()
                self.assertFalse(window.worker_thread.isRunning())
                window.close();app.processEvents()

    def test_dma_failure_stays_visible_and_never_rearms_automatically(self):
        from PyQt6 import QtWidgets
        import osc
        from dma_client import DmaClient
        app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        server=TriggerServer();server.drop_metadata=True
        req=pb.DumpSpyBuffersRequest(numberOfSamples=2048,numberOfWaveforms=1,channelList=[0])
        worker=osc.AcquisitionWorker('fake','mezz/0','fake',1000,req,20,dma=True,
            dma_capture_mode='triggered',dma_pretrigger=1024)
        worker._link=object();worker._dma_client=DmaClient(pb,server.rpc)
        messages=[];worker.status.connect(messages.append)
        worker._poll_once()
        calls=len(server.calls);worker._poll_once()
        self.assertEqual(len(server.calls),calls)
        self.assertTrue(worker._stop_evt.is_set())
        self.assertEqual(worker._frames_acquired,0)
        self.assertIn('[DMA stopped] Missing triggered waveform metadata',messages[-1])
        app.processEvents()

    def test_close_before_dma_worker_starts_never_acquires(self):
        from PyQt6 import QtWidgets
        import osc
        app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        req=pb.DumpSpyBuffersRequest(numberOfSamples=2048,numberOfWaveforms=1,channelList=[0])
        worker=osc.AcquisitionWorker('fake','mezz/0','fake',1000,req,20,dma=True)
        stopped=[];worker.stopped.connect(lambda:stopped.append(True))
        worker.request_stop();worker.start()
        self.assertEqual(stopped,[True])
        self.assertIsNone(worker._timer)
        self.assertIsNone(worker._dma_client)
        app.processEvents()

    def test_trigger_axis_and_responsive_close_while_waiting(self):
        from PyQt6 import QtWidgets
        import osc
        from dma_client import DmaClient
        app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        from test_dma_persistent_client import StreamServer
        server=StreamServer();server.slow=True
        original=server.rpc
        def rpc(*args):
            if args[0]==pb.MT2_DMA_CONTROL_REQ and args[1].action==pb.DMA_CANCEL:
                time.sleep(.4)  # Driver finalization outlasts the GUI close event.
            return original(*args)
        def ensure_link(worker):
            if worker._dma_client is None:
                worker._link=object()
                worker._dma_client=DmaClient(pb,rpc,worker._stop_evt.is_set)
        args=SimpleNamespace(ip='fake',port=1,channels=[0],channel=0,L=2048,trigger_source='external',
            software_trigger=False,timeout_ms=1000,sampling_rate_hz=62.5e6,route='mezz/0',
            fft_every=1,autoscale=False,enable_fft=False,fft_channel=None,enable_charge_hist=False,
            disable_rms=True,rms_window=10,save_dir='',dma=True,capture_mode='triggered',pretrigger=1024,
            identity='fake',period_ms=20,max_waveforms=0,ui_period_ms=33,fft_full_scale_counts=16384,
            fft_keep_dc=False,trigger_timeout_ms=30000,job_timeout_ms=0)
        with patch.object(osc.AcquisitionWorker,'_ensure_link',ensure_link):
            window=osc.DaphneOscApp(args);window.show()
            try:
                deadline=time.monotonic()+2
                while server.request is None and time.monotonic()<deadline:
                    app.processEvents();time.sleep(.005)
                self.assertIsNotNone(server.request)
                self.assertEqual(window._x_axis[1024],0.)
                self.assertLess(window._x_axis[0],0.)
                started=time.monotonic();window.close()
                self.assertLess(time.monotonic()-started,.1)
                self.assertTrue(window.isVisible())
                deadline=time.monotonic()+3
                while window.isVisible() and time.monotonic()<deadline:
                    app.processEvents();time.sleep(.005)
                self.assertFalse(window.isVisible())
                self.assertFalse(window.worker_thread.isRunning())
                self.assertEqual(server.calls[-1][1].action,pb.DMA_CANCEL)
            finally:
                if window.worker_thread.isRunning():
                    window.worker.request_stop();window.worker_thread.quit();window.worker_thread.wait(3000)
                window.close();app.processEvents()

    def test_triggered_worker_preserves_pretrigger_and_disk_metadata(self):
        from PyQt6 import QtWidgets
        import osc
        from dma_client import DmaClient
        app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        server=TriggerServer()
        request=pb.DumpSpyBuffersRequest(numberOfSamples=2048,numberOfWaveforms=1,channelList=[0,17])
        contract=dict(capture_mode='triggered',samples=2048,pretrigger_samples=1024,trigger_source='external')
        with tempfile.TemporaryDirectory(dir=ROOT.parent/'build') as directory:
            writer=osc.WaveformDiskWriter(directory,[0,17],dma=True,dma_contract=contract)
            writer.start();self.assertTrue(writer.wait_ready())
            worker=osc.AcquisitionWorker('fake','mezz/0','fake',1000,request,20,max_waveforms=1,
                save_queue=writer.queue,save_health_checker=lambda:writer.snapshot()['error'],
                dma=True,dma_capture_mode='triggered',dma_trigger_source='external',dma_pretrigger=1024)
            worker._link=object();worker._dma_client=DmaClient(pb,server.rpc)
            plots=[];worker.plot_update.connect(lambda data,*_:plots.append(data.copy()))
            worker._poll_once()
            self.assertEqual(worker._frames_acquired,1)
            self.assertEqual(plots[0].shape,(2,2048))
            self.assertEqual(server.calls[-1][1].action,pb.DMA_ACK)
            self.assertTrue(writer.stop());writer.join(2)
            meta=json.loads((Path(directory)/'dma_waveforms.jsonl').read_text().splitlines()[0])
            self.assertEqual(meta['capture_mode'],'triggered')
            self.assertEqual(meta['waveforms'][0]['trigger']['pretrigger_samples'],1024)
            self.assertFalse(meta['waveforms'][0]['trigger']['trigger_timestamp_valid'])
            self.assertEqual(json.loads((Path(directory)/'dma_format.json').read_text())['capture_contracts']['0'],contract)
            app.processEvents()

    def test_long_waveform_full_fft_and_flushed_files(self):
        from PyQt6 import QtWidgets
        import osc
        from dma_client import DmaClient
        app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        server=FakeServer()
        request=pb.DumpSpyBuffersRequest(numberOfSamples=32769,numberOfWaveforms=1,channelList=[39,0,17])
        with tempfile.TemporaryDirectory(dir=ROOT.parent/'build') as directory:
            writer=osc.WaveformDiskWriter(directory,[39,0,17],dma=True)
            writer.start();self.assertTrue(writer.wait_ready())
            worker=osc.AcquisitionWorker('fake','mezz/0','fake',1000,request,20,max_waveforms=1,
                save_queue=writer.queue,save_health_checker=lambda: writer.snapshot()['error'],
                fft_config={'enabled':True,'window':np.ones(32769),'avg_waves':2,'channel_index':0},dma=True)
            worker._link=object()
            worker._dma_client=DmaClient(pb,server.rpc)
            plots=[];spectra=[]
            worker.plot_update.connect(lambda data,*_:plots.append(data.copy()))
            worker.fft_update.connect(lambda data,*_:spectra.append(data.copy()))
            worker._poll_once()
            self.assertEqual(worker._frames_acquired,1)
            self.assertEqual(plots[0].shape,(3,32769))
            self.assertEqual(spectra[0].size,16385)
            self.assertEqual(server.calls[-1][1].action,pb.DMA_ACK)
            self.assertEqual(writer.snapshot()['written_frames'],1)
            self.assertTrue(writer.stop());writer.join(2)
            self.assertFalse(writer.is_alive())
            np.testing.assert_array_equal(np.fromfile(Path(directory)/'channel_39.dat',dtype='<u2'),plots[0][0])
            self.assertTrue((Path(directory)/'dma_waveforms.jsonl').is_file())
            self.assertEqual(json.loads((Path(directory)/'dma_format.json').read_text())['saved_encoding'], 'offset_binary')
            app.processEvents()

    def test_writer_rejects_unknown_append_without_changing_data(self):
        import osc
        with tempfile.TemporaryDirectory(dir=ROOT.parent/'build') as directory:
            file=Path(directory)/'channel_0.dat'
            file.write_bytes(b'\x00\x00')
            writer=osc.WaveformDiskWriter(directory,[0],append_data=True,dma=True)
            writer.start();self.assertTrue(writer.wait_ready());writer.join(2)
            self.assertFalse(writer.is_alive())
            self.assertIn('existing ADC encoding',writer.snapshot()['error'])
            self.assertEqual(file.read_bytes(),b'\x00\x00')
            self.assertFalse((Path(directory)/'dma_format.json').exists())


if __name__=='__main__':unittest.main()
