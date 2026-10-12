"""Triggered adapter invariants against an offline, revision-2 server."""
import json
import argparse
import contextlib
import io
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import numpy as np
from test_dma_client import FakeServer, DmaClient, pb, ROOT
from dma_acquire_cli import run_dma_acquire
from dma_output import prepare_dma_output, record_dma_output
from dma_options import relative_sample_axis
from dma_options import add_dma_capture_arguments, validate_dma_capture_arguments


class TriggerServer(FakeServer):
    def __init__(self):
        super().__init__()
        self.request = None
        self.drop_metadata = False
        self.bad_echo = False

    def rpc(self, mtype, req, response_type, response_class):
        corrupt, self.corrupt = self.corrupt, None
        reply = super().rpc(mtype, req, response_type, response_class)
        self.corrupt = corrupt
        if mtype == pb.MT2_ACQUISITION_CAPABILITIES_REQ:
            reply.protocol_revision = 2
            reply.gateware_capabilities |= 64
            reply.period_ticks = 8192
            reply.maximum_ring_bytes = 448 << 20
            reply.lease_ms = 30000
            reply.cleanup_timeout_ms = 10000
            reply.capture_modes.add(mode=pb.DMA_CAPTURE_FINITE, available=True,
                                    trigger_sources=[pb.DMA_TRIGGER_SOFTWARE])
            reply.capture_modes.add(mode=pb.DMA_CAPTURE_TRIGGERED, available=True, pretrigger_available=True,
                trigger_sources=[pb.DMA_TRIGGER_SOFTWARE, pb.DMA_TRIGGER_EXTERNAL, pb.DMA_TRIGGER_TIMING])
        elif mtype == pb.MT2_DMA_ACQUIRE_REQ:
            self.request = req
        if mtype in (pb.MT2_DMA_ACQUIRE_REQ, pb.MT2_DMA_STATUS_REQ, pb.MT2_DMA_CONTROL_REQ) and self.request:
            r = self.request
            reply.capture_mode = pb.DMA_CAPTURE_FINITE if self.bad_echo else r.capture_mode
            reply.trigger_source = r.trigger_source
            reply.pretrigger_samples = r.pretrigger_samples
            reply.contract_version = 2
            reply.job_timeout_ms = r.job_timeout_ms or r.waveforms * (r.timeout_ms + 10000) + 5000
            reply.phase = pb.DMA_PHASE_WAITING_TRIGGER
        if mtype == pb.MT2_DMA_READ_REQ and self.request:
            r = self.request
            reply.independently_software_triggered = r.trigger_source == pb.DMA_TRIGGER_SOFTWARE
            if r.capture_mode == pb.DMA_CAPTURE_TRIGGERED and not self.drop_metadata:
                d = 8192
                t = 49152 + req.waveform*d  # Window spans ring wrap for short captures.
                first = t-r.pretrigger_samples
                stream = ((first+r.samples+d-1)//d)*d
                reply.waveform_metadata.CopyFrom(pb.DmaWaveformMetadata(contract_version=1,
                    capture_mode=r.capture_mode, trigger_source=r.trigger_source,
                    samples=r.samples, pretrigger_samples=r.pretrigger_samples,
                    trigger_index=t, window_first=first, stream_ticks=stream,
                    period_ticks=d, ring_ticks=((r.samples+3*d-1)//d)*d, ignored_triggers=3))
            if corrupt:
                corrupt(reply)
        return reply


class TriggerClientTests(unittest.TestCase):
    def test_cli_options_preserve_default_and_reject_incompatible_requests(self):
        parser=argparse.ArgumentParser()
        parser.add_argument('--dma',action='store_true')
        parser.add_argument('--trigger-source',default='software')
        parser.add_argument('-L',type=int,default=2048)
        add_dma_capture_arguments(parser)
        validate_dma_capture_arguments(parser,parser.parse_args([]))
        validate_dma_capture_arguments(parser,parser.parse_args(['--dma']))
        for flag in ('--force_acq', '--force-acq'):
            validate_dma_capture_arguments(parser,parser.parse_args(['--dma',flag]))
        validate_dma_capture_arguments(parser,parser.parse_args(['--dma','--capture-mode','triggered',
                                                                '--trigger-source','timing','--pretrigger','1024']))
        for argv in (['--force_acq'],['--pretrigger','10'],['--dma','--pretrigger','10'],
                     ['--dma','--trigger-source','external'],['--dma','--capture-mode','triggered','--pretrigger','2048'],
                     ['--dma','--capture-mode','triggered','--trigger-source','all'],['--dma','--trigger-timeout-ms','9']):
            with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):
                validate_dma_capture_arguments(parser,parser.parse_args(argv))
    def test_all_sources_and_per_waveform_metadata(self):
        for source in ('software', 'external', 'timing'):
            with self.subTest(source=source):
                server=TriggerServer(); client=DmaClient(pb,server.rpc)
                data, meta=client.acquire([17,0,32],4097,2,source,capture_mode='triggered',pretrigger=2048)
                self.assertEqual(data.shape,(2,3,4097))
                self.assertEqual(meta['capture_mode'],'triggered')
                self.assertEqual(meta['independent_software_triggers'],source=='software')
                for wave in meta['waveforms']:
                    t=wave['trigger']; self.assertEqual(t['window_first'],t['trigger_index']-2048)
                    self.assertFalse(t['trigger_timestamp_valid'])
                client.acknowledge()
                self.assertEqual(server.calls[-1][1].action,pb.DMA_ACK)

    def test_old_server_never_receives_triggered_acquire(self):
        server=FakeServer();client=DmaClient(pb,server.rpc)
        with self.assertRaisesRegex(RuntimeError,'TRIGGERED_UNAVAILABLE'):
            client.acquire([0],2048,capture_mode='triggered',pretrigger=100)
        self.assertEqual([t for t,_ in server.calls],[pb.MT2_ACQUISITION_CAPABILITIES_REQ])

    def test_old_bindings_and_missing_capability_reject_before_start(self):
        server=TriggerServer()
        class OldBindings:
            def __getattr__(self,name):
                if name in ('DMA_CAPTURE_TRIGGERED','DmaWaveformMetadata'):
                    raise AttributeError(name)
                return getattr(pb,name)
        with self.assertRaisesRegex(RuntimeError,'TRIGGERED_UNAVAILABLE'):
            DmaClient(OldBindings(),server.rpc).acquire([0],2048,capture_mode='triggered')
        self.assertFalse(any(t==pb.MT2_DMA_ACQUIRE_REQ for t,_ in server.calls))
        server=TriggerServer()
        def rpc(*args):
            r=server.rpc(*args)
            if args[0]==pb.MT2_ACQUISITION_CAPABILITIES_REQ: r.gateware_capabilities &= ~64
            return r
        with self.assertRaisesRegex(RuntimeError,'TRIGGERED_UNAVAILABLE'):
            DmaClient(pb,rpc).acquire([0],2048,capture_mode='triggered')
        self.assertFalse(any(t==pb.MT2_DMA_ACQUIRE_REQ for t,_ in server.calls))

    def test_cancel_never_claims_idle_on_quarantine(self):
        server=TriggerServer()
        def rpc(*args):
            r=server.rpc(*args)
            if args[0]==pb.MT2_DMA_CONTROL_REQ:
                r.state=pb.DMA_JOB_CANCELLED;r.message='DMA_QUARANTINED: stop failed'
            return r
        client=DmaClient(pb,rpc);client.probe();client.job_id=7
        with self.assertRaisesRegex(RuntimeError,'idle could not be proven'): client.cancel()
        self.assertEqual(client.job_id,7)

    def test_bad_echo_or_metadata_cancel_without_ack(self):
        mutations = [lambda r:r.ClearField('waveform_metadata'),
                     lambda r:setattr(r.waveform_metadata,'window_first',1),
                     lambda r:setattr(r.waveform_metadata,'period_ticks',4096),
                     lambda r:setattr(r.waveform_metadata,'ignored_triggers',r.sequence),
                     lambda r:setattr(r,'independently_software_triggered',True)]
        for corrupt in mutations:
            server=TriggerServer();server.corrupt=corrupt;client=DmaClient(pb,server.rpc)
            with self.assertRaises(RuntimeError):
                client.acquire([0,17],4097,trigger_source='external',capture_mode='triggered',pretrigger=2048)
            self.assertEqual(server.calls[-1][1].action,pb.DMA_CANCEL)
        server=TriggerServer();server.bad_echo=True
        with self.assertRaisesRegex(RuntimeError,'accepted mode'):
            DmaClient(pb,server.rpc).acquire([0],17,capture_mode='triggered')
        self.assertEqual(server.calls[-1][1].action,pb.DMA_CANCEL)

    def test_geometry_rejected_before_arm_and_relative_axis(self):
        server=TriggerServer();client=DmaClient(pb,server.rpc)
        for p in (-1,17):
            with self.assertRaises(ValueError): client.acquire([0],17,capture_mode='triggered',pretrigger=p)
        with self.assertRaises(ValueError): client.acquire([0],8192*511,capture_mode='triggered')
        self.assertFalse(any(t==pb.MT2_DMA_ACQUIRE_REQ for t,_ in server.calls))
        np.testing.assert_allclose(relative_sample_axis(5,2,62.5e6),[-.032,-.016,0,.016,.032])

    def test_lease_renewed_while_waiting_and_cancel_is_cooperative(self):
        server=TriggerServer();server.running=True
        stopped=[False]; phases=[]
        client=DmaClient(pb,server.rpc,lambda:stopped[0],lambda *v:phases.append(v))
        original=client._renew_lease
        def renew():
            client._last_keepalive -= 31
            original()
            stopped[0]=True
        with patch.object(client,'_renew_lease',side_effect=renew):
            with self.assertRaises(InterruptedError):
                client.acquire([0],2048,trigger_source='external',capture_mode='triggered',pretrigger=100)
        actions=[r.action for t,r in server.calls if t==pb.MT2_DMA_CONTROL_REQ]
        self.assertEqual(actions,[pb.DMA_KEEPALIVE,pb.DMA_CANCEL])
        self.assertTrue(phases)

    def test_cli_partial_batch_and_append_contract(self):
        server=TriggerServer()
        class Transport:
            rpc=server.rpc
            def __init__(self,*a,**kw): pass
            def __enter__(self): return self
            def __exit__(self,*a): pass
        with tempfile.TemporaryDirectory(dir=ROOT.parent/'build') as directory, patch('dma_acquire_cli.V2Client',Transport):
            args=SimpleNamespace(v2=True,legacy=False,legacy_only=False,channel_list=['0,17'],N=5,L=2048,
                chunk=2,foldername=directory,ip='fake',port=1,route='mezz/0',timeout_ms=1000,
                trigger_source='external',append_data=False,compress=False,capture_mode='triggered',
                pretrigger=1024,trigger_timeout_ms=30000,job_timeout_ms=0)
            self.assertEqual(run_dma_acquire(args,pb),0)
            requests=[r for t,r in server.calls if t==pb.MT2_DMA_ACQUIRE_REQ]
            self.assertEqual([r.waveforms for r in requests],[2,2,1])
            self.assertTrue(all(r.pretrigger_samples==1024 and r.timeout_ms==30000 for r in requests))
            file=Path(directory)/'channel_0.dat'; before=file.read_bytes()
            contract=json.loads((Path(directory)/'dma_format.json').read_text())['capture_contracts']['0']
            prepare_dma_output(directory,[0],True,contract)
            for change in ({'pretrigger_samples':0},{'samples':1024},{'capture_mode':'finite'}):
                with self.assertRaisesRegex(ValueError,'capture mode/L/P/source'):
                    prepare_dma_output(directory,[0],True,dict(contract,**change))
            self.assertEqual(file.read_bytes(),before)


if __name__=='__main__':unittest.main()
