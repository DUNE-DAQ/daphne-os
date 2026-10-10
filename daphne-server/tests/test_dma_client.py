"""Offline protocol tests; no physical driver, overlay or MMIO access."""
import copy
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from protobuf_loader import load_protobuf_modules
from dma_client import DmaClient
from dma_acquire_cli import run_dma_acquire
pb, _ = load_protobuf_modules(require_dma=True)


class FakeServer:
    def __init__(self):
        self.calls = []
        self.channels = []
        self.sequence = 0
        self.corrupt = None
        self.unsupported = False
        self.running = False

    def rpc(self, mtype, req, response_type, response_class):
        self.calls.append((mtype, copy.deepcopy(req)))
        if mtype == pb.MT2_ACQUISITION_CAPABILITIES_REQ:
            c = pb.AcquisitionCapabilitiesResponse(success=True, protocol_revision=1,
                backend=pb.ACQUISITION_DMA, available_backends=[pb.ACQUISITION_DMA],
                dma_trigger_sources=[pb.DMA_TRIGGER_SOFTWARE], gateware_build_id=0x1234567,
                gateware_abi=0x20000, gateware_capabilities=16, sample_format=1,
                maximum_job_bytes=64<<20, maximum_samples=1<<24, maximum_waveforms=256,
                maximum_fragment_bytes=8192, dma_available=not self.unsupported)
            return c
        if mtype == pb.MT2_DMA_ACQUIRE_REQ:
            self.channels = list(req.channels)
            self.samples, self.waves = req.samples, req.waveforms
            self.sequence = 0
            return pb.DmaJobResponse(success=True, job_id=7, backend=pb.ACQUISITION_DMA,
                state=pb.DMA_JOB_RUNNING if self.running else pb.DMA_JOB_READY,
                completed_waveforms=self.waves, expected_waveforms=self.waves)
        if mtype == pb.MT2_DMA_READ_REQ:
            channels = sorted(ch for ch in self.channels if ch//16 == req.route)
            count = min(self.samples-req.tick_offset, req.maximum_bytes//(2*len(channels)))
            ticks = np.arange(req.tick_offset, req.tick_offset+count, dtype=np.uint16)
            raw = np.stack([((ticks + ch*100 + req.waveform*10) & 0x3fff) << 2 for ch in channels], axis=1)
            last_route = max(ch//16 for ch in self.channels)
            final = req.tick_offset+count == self.samples
            r = pb.DmaReadResponse(success=True, job_id=7, backend=pb.ACQUISITION_DMA,
                waveform=req.waveform, route=req.route, sequence=self.sequence, channels=channels,
                samples=self.samples, expected_waveforms=self.waves, tick_offset=req.tick_offset,
                tick_count=count, raw16_le=raw.astype('<u2').tobytes(), final_route=final,
                final_waveform=final and req.route==last_route,
                final_job=final and req.route==last_route and req.waveform==self.waves-1,
                gateware_build_id=0x1234567, sample_format=1, independently_software_triggered=True)
            self.sequence += 1
            if self.corrupt:
                self.corrupt(r)
            return r
        if mtype == pb.MT2_DMA_CONTROL_REQ:
            self.running = False
            return pb.DmaJobResponse(success=True, job_id=7, backend=pb.ACQUISITION_DMA, state=pb.DMA_JOB_IDLE)
        if mtype == pb.MT2_DMA_STATUS_REQ:
            return pb.DmaJobResponse(success=True, job_id=7, backend=pb.ACQUISITION_DMA,
                state=pb.DMA_JOB_RUNNING if self.running else pb.DMA_JOB_READY,
                completed_waveforms=self.waves, expected_waveforms=self.waves)
        raise AssertionError(f"Unexpected RPC (legacy?): {mtype}")


class DmaClientTests(unittest.TestCase):
    def test_long_three_route_requested_order_and_explicit_ack(self):
        server = FakeServer(); client = DmaClient(pb, server.rpc)
        data, metadata = client.acquire([39,0,17,8], 32769, 2)
        self.assertEqual(data.shape, (2,4,32769))
        for w in range(2):
            for i,ch in enumerate([39,0,17,8]):
                np.testing.assert_array_equal(data[w,i], (np.arange(32769)+ch*100+w*10)&0x3fff)
        self.assertIsNone(metadata['waveforms'][0]['hardware_timestamp'])
        self.assertFalse(any(t==pb.MT2_DMA_CONTROL_REQ for t,_ in server.calls))
        client.acknowledge()
        self.assertEqual(server.calls[-1][1].action,pb.DMA_ACK)

    def test_corrupt_fragments_cancel_and_never_ack(self):
        mutations = [lambda r: setattr(r,'sequence',2), lambda r: setattr(r,'sample_format',2),
                     lambda r: setattr(r,'tick_count',0), lambda r: setattr(r,'raw16_le',r.raw16_le[:-1]),
                     lambda r: setattr(r,'gateware_build_id',99), lambda r: setattr(r,'final_job',False),
                     lambda r: r.channels.reverse(), lambda r: setattr(r,'tick_offset',1)]
        for corrupt in mutations:
            with self.subTest(corrupt=corrupt):
                server=FakeServer();server.corrupt=corrupt;client=DmaClient(pb,server.rpc)
                with self.assertRaises(RuntimeError): client.acquire([0,1],17)
                self.assertEqual(server.calls[-1][1].action,pb.DMA_CANCEL)
                self.assertFalse(any(getattr(r,'action',None)==pb.DMA_ACK for t,r in server.calls if t==pb.MT2_DMA_CONTROL_REQ))

    def test_all_future_sources_rejected_before_start(self):
        for source in ('external','timing','self','all'):
            server=FakeServer(); client=DmaClient(pb,server.rpc)
            with self.assertRaisesRegex(RuntimeError,'TRIGGER_UNSUPPORTED'): client.acquire([0],32768,trigger_source=source)
            self.assertEqual([t for t,_ in server.calls],[pb.MT2_ACQUISITION_CAPABILITIES_REQ])

    def test_duplicate_channels_and_memory_budget(self):
        client=DmaClient(pb,FakeServer().rpc)
        for channels,L in (([0,0],1),([40],1),([0],0),([0],1<<26)):
            with self.assertRaises(ValueError): client.acquire(channels,L)

    def test_cooperative_cancel_running_job(self):
        server=FakeServer();server.running=True
        client=DmaClient(pb,server.rpc,lambda: bool(server.channels))
        with self.assertRaises(InterruptedError): client.acquire([0],32768)
        self.assertEqual(server.calls[-1][1].action,pb.DMA_CANCEL)

    def test_cli_files_are_adc14_and_batch_count_exact(self):
        server=FakeServer()
        class Transport:
            rpc=server.rpc
            def __init__(self,*a,**kw): pass
            def __enter__(self): return self
            def __exit__(self,*a): pass
        with tempfile.TemporaryDirectory(dir=ROOT.parent / 'build') as directory, patch('dma_acquire_cli.V2Client',Transport):
            args=SimpleNamespace(v2=True,legacy=False,legacy_only=False,channel_list=['39,0,17'],N=5,L=32769,
                chunk=2,foldername=directory,ip='fake',port=1,route='mezz/0',timeout_ms=10000,
                trigger_source='software',append_data=False,compress=False)
            self.assertEqual(run_dma_acquire(args,pb),0)
            self.assertEqual([r.waveforms for t,r in server.calls if t==pb.MT2_DMA_ACQUIRE_REQ],[2,2,1])
            for ch in (39,0,17):
                values=np.fromfile(Path(directory)/f'channel_{ch}.dat',dtype='<u2').reshape(5,32769)
                self.assertTrue(np.all(values<=16383))
            self.assertEqual(len(list(Path(directory).glob('dma_metadata_*.jsonl'))),1)


if __name__=='__main__': unittest.main()
