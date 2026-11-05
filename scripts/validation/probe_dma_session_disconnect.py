#!/usr/bin/env python3
"""Disconnect without CANCEL; prove lease cleanup with a later finite capture."""
import argparse
import json
from pathlib import Path
import socket
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'daphne-server/client'))
from protobuf_loader import load_protobuf_modules
from v2_client import V2Client
from identity_cli import add_identity_argument
from dma_client import DmaClient

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, required=True)
add_identity_argument(parser, default=None)
args = parser.parse_args()
pb, _ = load_protobuf_modules(require_dma=True)
link = V2Client(pb, '193.206.157.36', 40001, timeout_ms=10000, identity=args.identity or uuid.uuid4().hex)
client = DmaClient(pb, link.rpc)
client.start_session([39, 0, 17], 2048, 1000000, pretrigger=1024, job_timeout_ms=120000)
job = client.job_id
time.sleep(.1)
lease = client.capabilities.lease_ms/1000
link.close()  # Deliberately abandon ownership: no CANCEL, STATUS or KEEPALIVE.
began = time.monotonic()
time.sleep(lease+1)
with V2Client(pb, '193.206.157.36', 40001, timeout_ms=10000, identity=(args.identity + "-observer") if args.identity else uuid.uuid4().hex) as observer:
    recovered = DmaClient(pb, observer.rpc)
    recovered.probe('software', 'finite')
    deadline = time.monotonic()+20
    while True:
        try:
            data, _ = recovered.acquire([0, 17], 2048, 1, 'software', capture_mode='finite')
            break
        except RuntimeError as error:
            if 'BUSY' not in str(error) or time.monotonic() > deadline:
                raise
            time.sleep(.2)
    recovered.acknowledge()
    assert data.shape == (1, 2, 2048)
record = dict(result='PASS', client_host=socket.gethostname(), abandoned_job=job,
              lease_s=lease, recovery_s=time.monotonic()-began, finite_after_disconnect=1)
args.output.write_text(json.dumps(record, indent=2)+'\n')
print(json.dumps(record), flush=True)
