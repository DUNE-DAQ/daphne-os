#!/usr/bin/env python3
"""Bounded memory-sink benchmark from daphne-dev, with complete ID validation."""
import argparse
import json
from pathlib import Path
import socket
import sys
import time
import uuid
from google.protobuf.json_format import MessageToDict

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'daphne-server/client'))
from protobuf_loader import load_protobuf_modules
from dma_client import DmaClient
from v2_client import V2Client
from identity_cli import add_identity_argument

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--events', type=int, default=256)
parser.add_argument('--channels', default='0,1')
parser.add_argument('--samples', type=int, default=32000)
add_identity_argument(parser, default=None)
args = parser.parse_args()
assert 1 <= args.events <= 10000
channels = list(map(int, args.channels.split(',')))
pb, _ = load_protobuf_modules(require_dma=True)
with V2Client(pb, '193.206.157.36', 40001, timeout_ms=10000, identity=args.identity or uuid.uuid4().hex) as link:
    client = DmaClient(pb, link.rpc)
    start = time.monotonic(); count = 0
    client.start_session(channels, args.samples, args.events, pretrigger=4096, job_timeout_ms=180000)
    try:
        while count < args.events:
            data, _ = client.read_batch(min(16, args.events-count))
            count += len(data); client.ack_batch()
        delivery_s = time.monotonic()-start
        final = client.finish_session()
        total_s = time.monotonic()-start
    finally:
        client.cancel()
record = dict(client_host=socket.gethostname(), result='PASS', events=count, channels=channels,
    samples=args.samples, bytes=count*len(channels)*args.samples*2, capture_read_ack_s=delivery_s,
    final_drain_close_s=total_s-delivery_s, total_s=total_s,
    payload_MB_s=count*len(channels)*args.samples*2/total_s/1e6,
    read_rpc_s=client._stream_read_rpc_ns/1e9, validation_decode_s=client._stream_decode_ns/1e9,
    final=MessageToDict(final, preserving_proto_field_name=True))
args.output.write_text(json.dumps(record, indent=2)+'\n')
print(json.dumps(record), flush=True)
