"""Qt worker and disk integration with an offline raw DMA transport."""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
import numpy as np
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'client'))
from test_dma_client import FakeServer, pb


@unittest.skipUnless(importlib.util.find_spec('PyQt6') and importlib.util.find_spec('pyqtgraph'), 'Qt optional on the test host')
class DmaOscTests(unittest.TestCase):
    def test_long_waveform_full_fft_and_flushed_files(self):
        from PyQt6 import QtWidgets
        import osc
        from dma_client import DmaClient
        app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        server=FakeServer()
        request=pb.DumpSpyBuffersRequest(numberOfSamples=32769,numberOfWaveforms=1,channelList=[39,0,17])
        with tempfile.TemporaryDirectory(dir=ROOT.parent/'build') as directory:
            writer=osc.WaveformDiskWriter(directory,[39,0,17])
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
            app.processEvents()


if __name__=='__main__':unittest.main()
