#!/usr/bin/env python3
"""One-shot bounded TCP baseline, synthetic bytes only (no acquisition)."""
import argparse
import json
import os
from pathlib import Path
import socket
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('mode', choices=('send', 'receive', 'disk'))
parser.add_argument('--host', default='193.206.157.36')
parser.add_argument('--port', type=int, default=44881)
parser.add_argument('--bytes', type=int, default=128*1024*1024)
parser.add_argument('--file', type=Path)
args = parser.parse_args()
assert 0 < args.bytes <= 256*1024*1024
if args.mode == 'send':
    listener = socket.socket(); listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.settimeout(30); listener.bind((args.host, args.port)); listener.listen(1)
    print('READY', flush=True)
    peer, address = listener.accept(); peer.settimeout(20)
    block = bytes(1024*1024); sent = 0; begin = time.monotonic()
    with peer:
        while sent < args.bytes:
            count = min(len(block), args.bytes-sent); peer.sendall(block[:count]); sent += count
        peer.shutdown(socket.SHUT_WR)
    listener.close()
    elapsed = time.monotonic()-begin
    print(json.dumps(dict(mode='send', bytes=sent, elapsed_s=elapsed, MB_s=sent/elapsed/1e6, peer=address)), flush=True)
elif args.mode == 'receive':
    with socket.create_connection((args.host, args.port), timeout=20) as peer:
        received = 0; begin = time.monotonic()
        while received < args.bytes:
            block = peer.recv(1024*1024)
            if not block:
                break
            assert not any(block)
            received += len(block)
        assert received == args.bytes
        elapsed = time.monotonic()-begin
    print(json.dumps(dict(mode='receive', client_host=socket.gethostname(), bytes=received, elapsed_s=elapsed,
                         MB_s=received/elapsed/1e6)), flush=True)
else:
    assert args.file is not None and not args.file.exists()
    block = bytes(1024*1024); written = 0; begin = time.monotonic()
    with args.file.open('xb') as output:
        while written < args.bytes:
            count = min(len(block), args.bytes-written); output.write(block[:count]); written += count
        output.flush(); os.fsync(output.fileno())
    elapsed = time.monotonic()-begin
    args.file.unlink()
    print(json.dumps(dict(mode='disk_fsync', client_host=socket.gethostname(), bytes=written, elapsed_s=elapsed,
                         MB_s=written/elapsed/1e6)), flush=True)
