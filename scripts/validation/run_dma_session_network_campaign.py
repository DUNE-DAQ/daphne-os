#!/usr/bin/env python3
"""Physical persistent RPC tests; run from daphne-dev, one acquisition at a time."""
import argparse
import json
from pathlib import Path
import socket
import sys
import time
import uuid
import numpy as np
from google.protobuf.json_format import MessageToDict

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'daphne-server/client'))
from protobuf_loader import load_protobuf_modules
from v2_client import V2Client
from dma_client import DmaClient

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--ip', default='193.206.157.36')
parser.add_argument('--port', type=int, default=40001)
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
pb, _ = load_protobuf_modules(require_dma=True)


def rejected(link, name, request, cls):
    reply = link.rpc(getattr(pb, 'MT2_'+name+'_REQ'), request,
                     getattr(pb, 'MT2_'+name+'_RESP'), cls)
    assert not reply.success, f'{name} unexpectedly accepted'
    return reply.message


def capture(name, channels, length, pretrigger, n, chunk, slow=False):
    with V2Client(pb, args.ip, args.port, timeout_ms=10000, identity=uuid.uuid4().hex) as link:
        client = DmaClient(pb, link.rpc)
        started = time.monotonic()
        client.start_session(channels, length, n, pretrigger=pretrigger, job_timeout_ms=60000)
        done = 0
        batches = []
        generations = set()
        segments = set()
        rejected_messages = []
        read_running = False
        max_status_rtt = 0.
        try:
            if slow:
                deadline = time.monotonic()+10
                status = client.session_status()
                while len(status.available_events) < 16 and time.monotonic() < deadline:
                    time.sleep(.01)
                    status = client.session_status()
                assert len(status.available_events) == 16 and status.state == pb.DMA_JOB_RUNNING
                time.sleep(.4)
                status = client.session_status()
                assert status.session_progress.pauses > 0
                assert status.session_progress.accepted <= status.session_progress.driver_released+8
            while done < n:
                status = client.session_status()
                read_running |= status.state == pb.DMA_JOB_RUNNING
                data, metadata = client.read_batch(min(chunk, n-done))
                assert data.shape[1:] == (len(channels), length)
                assert int(data.min()) >= 0 and int(data.max()) < 16384
                batches.append(len(data))
                for w, waveform in enumerate(metadata['waveforms']):
                    event = waveform['trigger']
                    identity = event['event_id']
                    assert identity['sequence'] == done+w+1
                    generations.add(identity['generation'])
                    segments.add(event['segment'])
                    assert event['window_first'] == event['trigger_index']-pretrigger
                    assert event['fence_end'] % 8192 == 0
                if slow and not done:
                    pending = list(client._stream_pending)
                    assert len(pending) >= 2
                    bad = pb.DmaEventId()
                    bad.CopyFrom(pending[1]); bad.generation += 1
                    rejected_messages.append(rejected(link, 'DMA_CONTROL', pb.DmaControlRequest(
                        job_id=client.job_id, action=pb.DMA_ACK, event_ids=[pending[0], bad]), pb.DmaJobResponse))
                    assert client.session_status().session_progress.acknowledged == 0
                    rejected_messages.append(rejected(link, 'DMA_READ', pb.DmaReadRequest(
                        job_id=client.job_id, event_id=bad, route=0, maximum_bytes=4096), pb.DmaReadResponse))
                    time.sleep(.2)
                client.ack_batch()
                if slow and not done:
                    rejected_messages.append(rejected(link, 'DMA_CONTROL', pb.DmaControlRequest(
                        job_id=client.job_id, action=pb.DMA_ACK, event_ids=pending), pb.DmaJobResponse))
                    rejected_messages.append(rejected(link, 'DMA_READ', pb.DmaReadRequest(
                        job_id=client.job_id, event_id=pending[0], route=0, maximum_bytes=4096), pb.DmaReadResponse))
                done += len(data)
            while True:
                begin = time.monotonic(); status = client.session_status()
                max_status_rtt = max(max_status_rtt, time.monotonic()-begin)
                if status.state == pb.DMA_JOB_READY:
                    break
                time.sleep(.01)
            final = client.finish_session()
            assert max_status_rtt < 1., 'Router blocked during final stop'
            if n > 8:
                assert max(generations) > 1 and read_running
            if slow:
                assert len(segments) > 1
            record = dict(case=name, client_host=socket.gethostname(), bindings=pb.__file__,
                channels=channels, length=length, pretrigger=pretrigger, events=done,
                batches=batches, generations=sorted(generations), segments=sorted(segments),
                elapsed_s=time.monotonic()-started, bytes=done*len(channels)*length*2,
                read_while_running=read_running, max_final_status_rtt_s=max_status_rtt,
                rejected=rejected_messages, read_rpc_s=client._stream_read_rpc_ns/1e9,
                validation_decode_s=client._stream_decode_ns/1e9,
                final=MessageToDict(final, preserving_proto_field_name=True))
            (args.output/(name+'.json')).write_text(json.dumps(record, indent=2)+'\n')
            print(json.dumps(record), flush=True)
        finally:
            client.cancel()


capture('two-one-route', [0, 1], 2048, 0, 2, 2)
capture('wrap-last-partial', [39, 0, 17], 2048, 1024, 37, 5)
capture('all40-long', list(reversed(range(40))), 32769, 1000, 19, 7)
capture('slow-and-invalid-ids', [39, 0, 17], 32000, 4096, 37, 5, slow=True)
with V2Client(pb, args.ip, args.port, timeout_ms=10000, identity=uuid.uuid4().hex) as link:
    client = DmaClient(pb, link.rpc)
    client.start_session([0, 17], 2048, (1<<32)+1, pretrigger=1024, job_timeout_ms=60000)
    try:
        time.sleep(.1)
    finally:
        client.cancel()
    client.probe('software', 'finite')
    data, _ = client.acquire([0, 17], 2048, 2, 'software', capture_mode='finite')
    assert data.shape == (2, 2, 2048)
    client.acknowledge()
    client.probe('software', 'triggered', 1024)
    data, _ = client.acquire([0, 17], 2048, 1, 'software', capture_mode='triggered', pretrigger=1024)
    assert data.shape == (1, 2, 2048)
    client.acknowledge()
    (args.output/'cancel64-and-legacy.json').write_text(json.dumps(dict(result='PASS', target=(1<<32)+1,
        client_host=socket.gethostname(), finite_events=2, triggered_events=1))+'\n')
    print('PASS cancel64, finite and triggered after persistent', flush=True)
