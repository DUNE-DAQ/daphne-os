#!/usr/bin/env python3
"""Read capabilities from the test server; never start an acquisition."""
import argparse
import json
from pathlib import Path
import sys
import socket
from google.protobuf.json_format import MessageToDict

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'daphne-server/client'))
from protobuf_loader import load_protobuf_modules
from v2_client import V2Client

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--ip', default='193.206.157.36')
parser.add_argument('--port', type=int, default=40001)
parser.add_argument('--require-persistent', action='store_true')
args = parser.parse_args()
pb, _ = load_protobuf_modules(require_dma=True)
with V2Client(pb, args.ip, args.port, timeout_ms=10000, identity='persistent-caps-probe') as link:
    c = link.rpc(pb.MT2_ACQUISITION_CAPABILITIES_REQ,
                 pb.AcquisitionCapabilitiesRequest(maximum_protocol_revision=3),
                 pb.MT2_ACQUISITION_CAPABILITIES_RESP, pb.AcquisitionCapabilitiesResponse)
    print(json.dumps({'client_host': socket.gethostname(), 'bindings': pb.__file__,
                      'endpoint': f'{args.ip}:{args.port}',
                      'capabilities': MessageToDict(c, preserving_proto_field_name=True)}, indent=2))
    if not c.success:
        raise RuntimeError(c.message)
    if args.require_persistent:
        assert c.gateware_build_id == 0x0630a9da
        assert c.protocol_revision == 3 and c.session_abi == 1 and c.session_features == 31
        assert c.session_slots == 8
        assert any(m.mode == pb.DMA_CAPTURE_PERSISTENT and m.available for m in c.capture_modes)
