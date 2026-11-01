"""Offline bounded revision-3 transport, file/append and Qt tests."""
import copy
import json
import contextlib
import io
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import importlib.util
import numpy as np
from test_dma_client import FakeServer, DmaClient, pb, ROOT
from dma_acquire_cli import run_dma_acquire


class StreamServer(FakeServer):
    def __init__(self):
        super().__init__()
        self.request = None
        self.starts = self.acked = self.read = self.produced = 0
        self.cancelled = False
        self.ids = []
        self.slow = False

    def _produce(self):
        if not self.slow:
            self.produced = min(self.request.target_waveforms, self.acked + 8)
        self.ids = [pb.DmaEventId(session=888, sequence=s, slot=(s-1)%8, generation=(s-1)//8+1)
                    for s in range(self.acked+1, self.produced+1)]

    def _status(self):
        self._produce()
        r = self.request
        out = pb.DmaJobResponse(success=True, job_id=7, backend=pb.ACQUISITION_DMA,
            state=pb.DMA_JOB_READY if self.produced == r.target_waveforms else pb.DMA_JOB_RUNNING,
            contract_version=3, capture_mode=r.capture_mode, trigger_source=r.trigger_source,
            pretrigger_samples=r.pretrigger_samples, job_timeout_ms=r.job_timeout_ms, available_events=self.ids)
        out.session_progress.CopyFrom(pb.DmaSessionProgress(session=888, target=r.target_waveforms,
            accepted=self.produced, completed=self.produced, driver_delivered=self.produced,
            driver_released=self.produced, staged=self.produced, acknowledged=self.acked, delivered=self.read,
            staged_events=len(self.ids), staged_bytes=len(self.ids)*r.samples*len(r.channels)*2,
            producer_complete=self.produced==r.target_waveforms, starts=1,
            stops=int(self.produced==r.target_waveforms), guards_ok=True))
        return out

    def rpc(self, mtype, req, response_type, response_class):
        self.calls.append((mtype, copy.deepcopy(req)))
        if mtype == pb.MT2_ACQUISITION_CAPABILITIES_REQ:
            c = pb.AcquisitionCapabilitiesResponse(success=True, protocol_revision=3,
                backend=pb.ACQUISITION_DMA, available_backends=[pb.ACQUISITION_DMA],
                dma_trigger_sources=[pb.DMA_TRIGGER_SOFTWARE], gateware_build_id=0x630a9da,
                gateware_abi=0x20000, gateware_capabilities=144, sample_format=1,
                maximum_job_bytes=64<<20, maximum_samples=1<<24, maximum_waveforms=256,
                maximum_fragment_bytes=8192, dma_available=True, session_abi=1, session_features=31,
                session_slots=8, maximum_staged_events=16, maximum_target_waveforms=(1<<64)-1,
                period_ticks=8192, maximum_ring_bytes=448<<20, session_pool_bytes=448<<20,
                session_route_bytes=256<<20, lease_ms=1000, cleanup_timeout_ms=10000)
            c.capture_modes.add(mode=pb.DMA_CAPTURE_PERSISTENT, available=True, pretrigger_available=True,
                trigger_sources=[pb.DMA_TRIGGER_SOFTWARE,pb.DMA_TRIGGER_EXTERNAL,pb.DMA_TRIGGER_TIMING])
            return c
        if mtype == pb.MT2_DMA_ACQUIRE_REQ:
            self.request = req
            self.starts += 1
            self.sequence = self.acked = self.read = self.produced = 0
            self.cancelled = False
            return self._status()
        if mtype == pb.MT2_DMA_STATUS_REQ:
            return self._status()
        if mtype == pb.MT2_DMA_CONTROL_REQ:
            if req.action == pb.DMA_CANCEL:
                self.cancelled = True
                return pb.DmaJobResponse(success=True, job_id=7, state=pb.DMA_JOB_IDLE)
            if req.action == pb.DMA_KEEPALIVE:
                return self._status()
            if not req.event_ids:
                assert self.acked == self.request.target_waveforms
                return pb.DmaJobResponse(success=True, job_id=7, state=pb.DMA_JOB_IDLE)
            assert list(req.event_ids) == self.ids[:len(req.event_ids)]
            assert req.event_ids[-1].sequence <= self.read
            self.acked += len(req.event_ids)
            return self._status()
        if mtype == pb.MT2_DMA_READ_REQ:
            r = self.request
            event = req.event_id
            assert event in self.ids
            channels = sorted(ch for ch in r.channels if ch//16 == req.route)
            count = min(r.samples-req.tick_offset, req.maximum_bytes//(2*len(channels)))
            ticks = np.arange(req.tick_offset, req.tick_offset+count, dtype=np.uint16)
            raw = np.stack([(((ticks+ch*100+(event.sequence-1)*10)&0x3fff)^0x2000)<<2 for ch in channels], axis=1)
            final = req.tick_offset+count == r.samples
            final_wave = final and req.route == max(ch//16 for ch in r.channels)
            out = pb.DmaReadResponse(success=True, job_id=7, backend=pb.ACQUISITION_DMA, route=req.route,
                fragment_sequence=self.sequence, target_waveforms=r.target_waveforms, channels=channels,
                samples=r.samples, tick_offset=req.tick_offset, tick_count=count, raw16_le=raw.astype('<u2').tobytes(),
                final_route=final, final_waveform=final_wave, final_job=final_wave and event.sequence==r.target_waveforms,
                sample_format=1, gateware_build_id=0x630a9da)
            cursor=(event.sequence-1)*65536
            segment=(event.sequence-1)//8
            trigger=cursor+r.pretrigger_samples+segment*123456
            out.waveform_metadata.CopyFrom(pb.DmaWaveformMetadata(contract_version=3, capture_mode=r.capture_mode,
                trigger_source=r.trigger_source, samples=r.samples, pretrigger_samples=r.pretrigger_samples,
                trigger_index=trigger, window_first=trigger-r.pretrigger_samples, period_ticks=8192,
                event_id=event, channel_mask=sum(1<<ch for ch in r.channels), first_cursor=cursor,
                fence_end=cursor+((r.samples+8191)//8192)*8192, segment=segment,
                valid_bytes=[r.samples*2*sum(ch//16==i for ch in r.channels) for i in range(3)], ignored=[0,0,0,0]))
            self.sequence += 1
            if final_wave:
                self.read += 1
            if self.corrupt:
                self.corrupt(out)
            return out
        raise AssertionError(mtype)


class PedestalDmaTests(unittest.TestCase):
    def make_client(self, server, echo_force=True):
        original = server.rpc

        def rpc(message_type, request, *rest):
            response = original(message_type, request, *rest)
            if message_type == pb.MT2_ACQUISITION_CAPABILITIES_REQ:
                response.force_acquisition_supported = True
            if echo_force and message_type in (pb.MT2_DMA_ACQUIRE_REQ, pb.MT2_DMA_STATUS_REQ, pb.MT2_DMA_CONTROL_REQ):
                response.force_acquisition = server.request.force_acquisition
            return response

        return DmaClient(pb, rpc)

    def test_pedestal_500_events_preserve_estimator_channel_order_and_force(self):
        import protobuf_configure_pedestal_level as pedestal
        server = StreamServer()
        client = self.make_client(server)
        channels = [33, 1, 17]

        def analog_data(reply):
            event = reply.waveform_metadata.event_id.sequence
            # The first waveform changes the mode of the final mean vector.
            # Reducing modes per batch would incorrectly give .000 instead of .002.
            values = [101, 101, 201, 100] if event == 1 else [100, 100, 200, 100]
            adc = np.stack([np.array(values, dtype=np.uint16) + 8000 + ch * 10
                            for ch in reply.channels], axis=1)
            reply.raw16_le = ((adc ^ 0x2000) << 2).astype('<u2').tobytes()

        server.corrupt = analog_data
        # Force transport batches of three, including a final batch of two.
        with patch.object(pedestal, 'MAX_ACQUISITION_BYTES', 3 * 2 * len(channels) * 4):
            for iteration in range(2):
                result = pedestal._measure_pedestals_dma(client, channels, 4, force_acq=True)
                self.assertEqual(result, {ch: 8100.002 + ch * 10 for ch in channels})
                self.assertEqual(server.acked, 500)
                self.assertEqual(server.starts, iteration + 1)
                self.assertIsNone(client.job_id)
                self.assertFalse(server.cancelled)
        acquisitions = [request for t, request in server.calls if t == pb.MT2_DMA_ACQUIRE_REQ]
        self.assertEqual(len(acquisitions), 2)
        for request in acquisitions:
            self.assertEqual(request.target_waveforms, 500)
            self.assertEqual(request.trigger_source, pb.DMA_TRIGGER_SOFTWARE)
            self.assertEqual(request.pretrigger_samples, 0)
            self.assertTrue(request.force_acquisition)
        event_acks = [request for t, request in server.calls
                      if t == pb.MT2_DMA_CONTROL_REQ and request.event_ids]
        self.assertTrue(all(len(request.event_ids) <= 3 for request in event_acks))
        self.assertEqual(len(event_acks[-1].event_ids), 2)

    def test_pedestal_default_does_not_force_acquisition(self):
        import protobuf_configure_pedestal_level as pedestal
        server = StreamServer()
        client = DmaClient(pb, server.rpc)
        result = pedestal._measure_pedestals_dma(client, [0], 4)
        self.assertEqual(result, {0: 2495.0})
        self.assertFalse(server.request.force_acquisition)
        self.assertEqual(server.starts, 1)
        self.assertIsNone(client.job_id)

    def test_pedestal_corrupt_event_cancels_without_acknowledging_it(self):
        import protobuf_configure_pedestal_level as pedestal
        server = StreamServer()
        client = self.make_client(server)

        def corrupt(reply):
            if reply.waveform_metadata.event_id.sequence == 9:
                reply.raw16_le = b'\x01\x00' + reply.raw16_le[2:]

        server.corrupt = corrupt
        with self.assertRaisesRegex(RuntimeError, 'framing'):
            pedestal._measure_pedestals_dma(client, [0], 4, force_acq=True)
        self.assertEqual(server.acked, 8)
        self.assertTrue(server.cancelled)
        self.assertIsNone(client.job_id)

    def test_pedestal_requires_force_confirmation_from_server(self):
        import protobuf_configure_pedestal_level as pedestal
        server = StreamServer()
        client = self.make_client(server, echo_force=False)
        with self.assertRaisesRegex(RuntimeError, 'acknowledgement missing'):
            pedestal._measure_pedestals_dma(client, [0], 4, force_acq=True)
        self.assertTrue(server.cancelled)
        self.assertEqual(server.acked, 0)

    def test_pedestal_interrupt_and_finalization_failure_cancel_session(self):
        import protobuf_configure_pedestal_level as pedestal
        for error in (KeyboardInterrupt(), RuntimeError('finalization failed')):
            with self.subTest(error=type(error).__name__):
                server = StreamServer()
                client = self.make_client(server)
                method = 'read_batch' if isinstance(error, KeyboardInterrupt) else 'finish_session'
                with patch.object(client, method, side_effect=error), self.assertRaises(type(error)):
                    pedestal._measure_pedestals_dma(client, [0], 4, force_acq=True)
                self.assertTrue(server.cancelled)
                self.assertIsNone(client.job_id)

    def test_pedestal_reports_failed_cleanup(self):
        import protobuf_configure_pedestal_level as pedestal
        server = StreamServer()
        client = self.make_client(server)
        with patch.object(client, 'read_batch', side_effect=RuntimeError('read failed')), \
                patch.object(client, 'cancel', side_effect=RuntimeError('stop failed')):
            with self.assertRaisesRegex(RuntimeError, 'read failed; DMA cleanup unconfirmed: stop failed'):
                pedestal._measure_pedestals_dma(client, [0], 4, force_acq=True)
        client.cancel()

    def test_pedestal_rejects_invalid_decoded_batches_before_ack(self):
        import protobuf_configure_pedestal_level as pedestal
        invalid = (
            (np.zeros((0, 1, 4), dtype=np.uint16), 'batch shape'),
            (np.zeros((1, 2, 4), dtype=np.uint16), 'batch shape'),
            (np.zeros((1, 1, 3), dtype=np.uint16), 'batch shape'),
            (np.full((1, 1, 4), 16384, dtype=np.uint16), '14-bit range'),
        )
        for data, message in invalid:
            with self.subTest(shape=data.shape, message=message):
                server = StreamServer()
                client = self.make_client(server)
                with patch.object(client, 'read_batch', return_value=(data, {})):
                    with self.assertRaisesRegex((RuntimeError, ValueError), message):
                        pedestal._measure_pedestals_dma(client, [0], 4, force_acq=True)
                self.assertEqual(server.acked, 0)
                self.assertTrue(server.cancelled)

    def test_pedestal_memory_budget_rejection_does_not_start_session(self):
        import protobuf_configure_pedestal_level as pedestal
        server = StreamServer()
        client = self.make_client(server)
        with patch.object(pedestal, 'MAX_ACQUISITION_BYTES', 7):
            with self.assertRaisesRegex(ValueError, 'memory budget'):
                pedestal._measure_pedestals_dma(client, [0], 4, force_acq=True)
        self.assertEqual(server.starts, 0)


class PersistentTests(unittest.TestCase):
    def test_readback_warning_is_retained_in_persistent_metadata(self):
        server = StreamServer()
        def rpc(*args):
            response = server.rpc(*args)
            response.message = 'WARNING: DMA AFE readback policy=warn; configuration not guaranteed.'
            return response
        client = DmaClient(pb, rpc)
        with patch('sys.stderr', new_callable=io.StringIO) as stderr:
            client.probe('software', 'persistent')
            client.start_session([0], 2048, 1)
            data, metadata = client.read_batch(1)
            client.ack_batch()
            client.finish_session()
        self.assertEqual(data.shape, (1,1,2048))
        self.assertEqual(metadata['afe_readback_policy'], 'warn')
        self.assertFalse(metadata['afe_register_configuration_verified'])
        self.assertEqual(stderr.getvalue().count('policy=warn'), 1)

    @classmethod
    def setUpClass(cls):
        # Qt permits one application per process. Keep a strong reference when
        # this suite is combined with the window tests on Linux/PyQt6.
        cls.qt_app=None
        if importlib.util.find_spec('PyQt6') and importlib.util.find_spec('pyqtgraph'):
            from PyQt6 import QtWidgets
            cls.qt_app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_unbounded_session_stays_open_until_cancel(self):
        server=StreamServer();client=DmaClient(pb,server.rpc)
        from dma_persistent_client import UNBOUNDED_SESSION_TARGET
        initial=client.start_session([32,33,34,35],10000,0,'external',pretrigger=1024)
        self.assertEqual(initial.session_progress.target,UNBOUNDED_SESSION_TARGET)
        for _ in range(20):
            data,metadata=client.read_batch(1)
            self.assertEqual(data.shape,(1,4,10000))
            self.assertTrue(metadata['unbounded_session'])
            client.ack_batch()
        self.assertEqual(server.starts,1)
        self.assertEqual(server.acked,20)
        with self.assertRaisesRegex(RuntimeError,'end with cancel'):
            client.finish_session()
        client.cancel()
        self.assertTrue(server.cancelled)
        self.assertIsNone(client.job_id)

    def test_unbounded_rejects_limited_target_before_start(self):
        server=StreamServer();client=DmaClient(pb,server.rpc)
        client.probe('external','persistent',1024)
        client.capabilities.maximum_target_waveforms=1000
        with self.assertRaisesRegex(RuntimeError,'full uint64'):
            client.start_session([0],2048,0,'external',pretrigger=1024)
        self.assertEqual(server.starts,0)

    @unittest.skipUnless(importlib.util.find_spec('PyQt6') and importlib.util.find_spec('pyqtgraph'),'Qt optional')
    def test_osc_unbounded_counter_signal_and_user_stop(self):
        import osc
        from PyQt6 import QtWidgets
        from dma_persistent_client import UNBOUNDED_SESSION_TARGET
        app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        server=StreamServer()
        request=pb.DumpSpyBuffersRequest(numberOfSamples=10000,numberOfWaveforms=1,channelList=[32,33,34,35])
        worker=osc.AcquisitionWorker('fake','mezz/0','fake',1000,request,1,max_waveforms=0,
            dma=True,dma_capture_mode='persistent',dma_trigger_source='external',dma_pretrigger=1024)
        worker._link=SimpleNamespace(close=lambda:None)
        worker._dma_client=DmaClient(pb,server.rpc,worker._stop_evt.is_set,worker._dma_progress)
        plots=[];messages=[];finished=[]
        worker.plot_update.connect(lambda data,timing,frame,stamp:plots.append((frame,stamp)))
        worker.status.connect(messages.append);worker.acquisition_finished.connect(finished.append)
        worker._frames_acquired=1<<31
        worker._poll_once()
        worker._dma_last_plot=0;worker._poll_once()
        self.assertEqual(server.starts,1)
        self.assertEqual(server.request.target_waveforms,UNBOUNDED_SESSION_TARGET)
        self.assertEqual(plots[-1][0],(1<<31)+2)
        self.assertGreater(plots[-1][1],1<<32)
        self.assertTrue(any('/infinite wf' in msg for msg in messages))
        self.assertFalse(finished)
        worker.request_stop();worker.stop();worker._poll_once()
        self.assertTrue(server.cancelled);self.assertEqual(server.starts,1)
        app.processEvents()

    def test_file_cli_force_is_transmitted_and_saved(self):
        server=StreamServer();original=server.rpc
        def rpc(t,req,*rest):
            response=original(t,req,*rest)
            if t==pb.MT2_ACQUISITION_CAPABILITIES_REQ:response.force_acquisition_supported=True
            if t in (pb.MT2_DMA_ACQUIRE_REQ,pb.MT2_DMA_STATUS_REQ,pb.MT2_DMA_CONTROL_REQ):
                response.force_acquisition=server.request.force_acquisition
            return response
        class Transport:
            def __init__(self,*args,**kwargs):pass
            def __enter__(self):return self
            def __exit__(self,*args):pass
        Transport.rpc=staticmethod(rpc)
        with tempfile.TemporaryDirectory(dir=ROOT.parent/'build') as folder,patch('dma_acquire_cli.V2Client',Transport):
            args=SimpleNamespace(v2=True,legacy=False,legacy_only=False,channel_list=['32,33'],N=3,L=10000,chunk=2,
                foldername=folder,ip='fake',port=1,route='mezz/0',timeout_ms=1000,trigger_source='external',
                append_data=False,compress=False,osc_mode=False,capture_mode='persistent',pretrigger=1024,
                trigger_timeout_ms=30000,job_timeout_ms=0,pressure_timeout_ms=0,force_acq=True)
            with contextlib.redirect_stdout(io.StringIO()):self.assertEqual(run_dma_acquire(args,pb),0)
            self.assertTrue(server.request.force_acquisition);self.assertEqual(server.starts,1)
            contract=json.loads((Path(folder)/'dma_format.json').read_text())['capture_contracts']['32']
            self.assertTrue(contract['force_acquisition'])
            self.assertEqual((Path(folder)/'channel_32.dat').stat().st_size,3*10000*2)

    def test_persistent_force_is_negotiated_and_echoed_in_status(self):
        server=StreamServer();client=DmaClient(pb,server.rpc)
        with self.assertRaisesRegex(RuntimeError,'does not support force'):
            client.start_session([0],2048,2,force_acq=True)
        self.assertEqual(server.starts,0)
        original=server.rpc
        def rpc(t,req,*rest):
            response=original(t,req,*rest)
            if t==pb.MT2_ACQUISITION_CAPABILITIES_REQ:
                response.force_acquisition_supported=True
            if t in (pb.MT2_DMA_ACQUIRE_REQ,pb.MT2_DMA_STATUS_REQ,pb.MT2_DMA_CONTROL_REQ):
                response.force_acquisition=server.request.force_acquisition
            return response
        client=DmaClient(pb,rpc)
        client.start_session([0],2048,2,force_acq=True)
        self.assertTrue(server.request.force_acquisition)
        data,_=client.read_batch(2);self.assertEqual(len(data),2)
        client.ack_batch();client.finish_session()

    def test_incremental_wrap_partial_final_and_encoding(self):
        server=StreamServer();client=DmaClient(pb,server.rpc)
        client.start_session([39,0,17],32769,19,pretrigger=1000)
        done=0
        while done<19:
            data,meta=client.read_batch(min(5,19-done))
            self.assertLessEqual(data.shape[0],5)
            for w in range(data.shape[0]):
                for i,ch in enumerate([39,0,17]):
                    np.testing.assert_array_equal(data[w,i],(np.arange(32769)+ch*100+(done+w)*10)&0x3fff)
                self.assertEqual(meta['waveforms'][w]['trigger']['event_id']['generation'],(done+w)//8+1)
            with self.assertRaisesRegex(RuntimeError,'ACK'):
                client.read_batch(1)
            client.ack_batch();done+=data.shape[0]
        result=client.finish_session()
        self.assertEqual(result.session_progress.acknowledged,19)
        self.assertEqual(server.starts,1)
        self.assertIsNone(client.job_id)

    def test_no_fallback_and_large_N(self):
        with self.assertRaisesRegex(RuntimeError,'PERSISTENT_UNAVAILABLE'):
            DmaClient(pb,FakeServer().rpc).start_session([0],2048,1)
        server=StreamServer();client=DmaClient(pb,server.rpc)
        client.start_session([0],2048,(1<<32)+1)
        self.assertEqual(client.session_status().session_progress.target,(1<<32)+1)
        client.cancel();self.assertTrue(server.cancelled)

    def test_corrupt_event_fragment_and_stop_never_ACK(self):
        mutations=[lambda r:setattr(r,'fragment_sequence',9),lambda r:setattr(r,'target_waveforms',99),
            lambda r:r.waveform_metadata.event_id.__setattr__('generation',9),
            lambda r:r.waveform_metadata.__setattr__('first_cursor',8192),
            lambda r:r.waveform_metadata.__setattr__('channel_mask',0),lambda r:r.waveform_metadata.ClearField('valid_bytes'),
            lambda r:setattr(r,'raw16_le',r.raw16_le[:-1]),lambda r:setattr(r,'independently_software_triggered',True),
            lambda r:setattr(r,'raw16_le',bytes([r.raw16_le[0]|1])+r.raw16_le[1:])]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                server=StreamServer();server.corrupt=mutation;client=DmaClient(pb,server.rpc)
                client.start_session([0],17,1)
                with self.assertRaises(RuntimeError):client.read_batch(1)
                client.cancel()
                self.assertFalse(any(t==pb.MT2_DMA_CONTROL_REQ and r.action==pb.DMA_ACK for t,r in server.calls))

    def test_file_client_one_session_per_N_and_append(self):
        server=StreamServer()
        class Transport:
            def __init__(self,*args,**kwargs):pass
            def __enter__(self):return self
            def __exit__(self,*args):pass
            rpc=server.rpc
        with tempfile.TemporaryDirectory(dir=ROOT.parent/'build') as folder,patch('dma_acquire_cli.V2Client',Transport):
            args=SimpleNamespace(v2=True,legacy=False,legacy_only=False,channel_list=['17,0'],N=19,L=17,chunk=5,
                foldername=folder,ip='fake',port=1,route='mezz/0',timeout_ms=1000,trigger_source='software',
                append_data=False,compress=False,osc_mode=False,capture_mode='persistent',pretrigger=8,
                trigger_timeout_ms=30000,job_timeout_ms=0,pressure_timeout_ms=0)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(run_dma_acquire(args,pb),0)
                args.append_data=True;args.N=3
                self.assertEqual(run_dma_acquire(args,pb),0)
            self.assertEqual(server.starts,2)
            for ch in [17,0]:
                data=np.fromfile(Path(folder)/f'channel_{ch}.dat',dtype='<u2').reshape(22,17)
                for w in range(22):
                    seq=w if w<19 else w-19
                    np.testing.assert_array_equal(data[w],(np.arange(17)+ch*100+seq*10)&0x3fff)
            records=[json.loads(line) for f in Path(folder).glob('dma_metadata_*.jsonl') for line in f.read_text().splitlines()]
            self.assertEqual(sum(len(r['waveforms']) for r in records if 'waveforms'in r),22)

    @unittest.skipUnless(importlib.util.find_spec('PyQt6') and importlib.util.find_spec('pyqtgraph'),'Qt optional')
    def test_osc_one_session_and_all_frames_saved(self):
        import osc
        from PyQt6 import QtWidgets
        app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        server=StreamServer()
        request=pb.DumpSpyBuffersRequest(numberOfSamples=2048,numberOfWaveforms=1,channelList=[0,17])
        contract=dict(capture_mode='persistent',samples=2048,pretrigger_samples=1024,trigger_source='software')
        with tempfile.TemporaryDirectory(dir=ROOT.parent/'build') as folder:
            writer=osc.WaveformDiskWriter(folder,[0,17],dma=True,dma_contract=contract)
            writer.start();self.assertTrue(writer.wait_ready())
            worker=osc.AcquisitionWorker('fake','mezz/0','fake',1000,request,10000,max_waveforms=11,
                save_queue=writer.queue,save_health_checker=lambda:writer.snapshot()['error'],dma=True,
                dma_capture_mode='persistent',dma_pretrigger=1024)
            worker._link=object();worker._dma_client=DmaClient(pb,server.rpc,worker._stop_evt.is_set)
            messages=[];worker.status.connect(messages.append)
            for _ in range(11):worker._poll_once()
            self.assertEqual(worker._frames_acquired,11);self.assertEqual(server.starts,1)
            self.assertGreater(worker._dma_skipped_plots,0)
            self.assertTrue(writer.stop());writer.join(2)
            self.assertEqual(writer.snapshot()['written_frames'],11)
            self.assertEqual((Path(folder)/'channel_0.dat').stat().st_size,11*2048*2)
            from dma_options import relative_sample_axis
            self.assertEqual(relative_sample_axis(2048,1024,62.5e6)[1024],0.)
            app.processEvents()


if __name__=='__main__': unittest.main()
