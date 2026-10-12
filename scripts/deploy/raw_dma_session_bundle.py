#!/usr/bin/env python3
"""Snapshot server/client/driver sources and matching generated protobufs.

Includes the persistent driver sources and validation tools explicitly, never
data directories. LF-normalizes text for Linux and records original/packaged hashes.
"""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[2]
EXTRA = [
    'daphne-server/dma/afe_session_capture.cpp', 'daphne-server/dma/session_probe.cpp',
    'daphne-server/client/dma_persistent_client.py',
    'daphne-server/srcs/server_controller/dma_persistent_service.cpp',
    'daphne-server/tests/dma_persistent_tests.cpp',
    'daphne-server/tests/dma_persistent_rpc_fixture.cpp',
    'daphne-server/tests/test_dma_persistent_client.py',
    'daphne-server/tests/test_dma_persistent_transport.py',
    'docs/raw-dma-persistent-server-client-contract.md', 'docs/raw-dma-persistent-driver.md',
    'docs/raw-dma-persistent-integration-results-2026-10-11.md',
    'docs/raw-dma-persistent-physical-results-2026-10-12.md',
    'scripts/validation/probe_dma_session_caps.py',
    'scripts/deploy/raw_dma_session_bundle.py', 'scripts/deploy/raw_dma_session_build.sh',
    'scripts/deploy/raw_dma_session_driver_build.sh', 'scripts/deploy/raw_dma_uart_log.py',
    'scripts/deploy/raw_dma_session_activate.py',
    'scripts/deploy/daphne-mode', 'scripts/deploy/daphne_manual_mode.py',
    'scripts/deploy/daphne_dma_frontend.py', 'scripts/deploy/test_daphne_manual_mode.py',
    'docs/raw-dma-manual-mode-switch.md',
    'scripts/petalinux/prepare_afe_dma_dts.py', 'scripts/petalinux/prepare_raw_dma_dts.py',
    'scripts/validation/run_dma_session_network_campaign.py',
    'scripts/validation/run_dma_session_pattern_campaign.py',
    'scripts/validation/probe_dma_engine_caps.cpp',
    'scripts/validation/probe_dma_session_osc.py', 'scripts/validation/probe_dma_session_disconnect.py',
    'scripts/validation/benchmark_dma_session.py', 'scripts/validation/dma_link_baseline.py',
    'scripts/validation/monitor_dma_process.py',
    'scripts/validation/validate_dma_session_files.py',
]
DRIVER = 'daphne-server/kernel/daphne-afe-dma/'
EXTRA += [DRIVER+n for n in ('afe_session_contract.h', 'afe_session_impl.h', 'afe_session_private.h',
    'daphne_afe_session_uapi.h', 'session_contract_test.c', 'session_layout_test.c',
    'session_service_test.c', 'test_session_contract.py', 'test_session_service.py')]


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bindings', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    names = set(n.decode() for n in git('ls-files', '-z', 'daphne-server', 'scripts/validation').split(b'\0') if n)
    names.update(EXTRA)
    files = {}
    original_hashes = {}
    for name in sorted(names):
        source = ROOT / name
        if not source.is_file():
            raise FileNotFoundError(source)
        data = source.read_bytes()
        original_hashes[name] = hashlib.sha256(data).hexdigest()
        if source.suffix in ('.py', '.sh', '.c', '.h', '.hpp', '.cpp', '.proto', '.cmake', '.md', '.txt') or source.name in ('Makefile', 'CMakeLists.txt', 'daphne-mode'):
            data = data.replace(b'\r\n', b'\n')
        files[name] = data
    for stem in ('daphneV3_high_level_confs', 'daphneV3_low_level_confs'):
        for extension in ('_pb2.py', '.pb.h', '.pb.cc'):
            source = args.bindings / (stem+extension)
            # CMake places C++ outputs at build root and Python in srcs/protobuf.
            if not source.is_file() and extension != '_pb2.py':
                source = args.bindings.parent.parent / (stem+extension)
            files['generated/'+source.name] = source.read_bytes()
    manifest = {'git_head': git('rev-parse','HEAD').decode().strip(),
                'git_status': git('status','--short').decode(),
                'protocol_revision': 3, 'session_abi': 1, 'required_features': 31,
                'original_sha256': original_hashes,
                'sha256': {name: hashlib.sha256(data).hexdigest() for name,data in files.items()}}
    files['SOURCE_MANIFEST.json'] = (json.dumps(manifest,indent=2)+'\n').encode()
    files['SHA256SUMS'] = ''.join(hashlib.sha256(data).hexdigest()+'  '+name+'\n' for name,data in sorted(files.items())).encode()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('wb') as output, gzip.GzipFile(filename='',mode='wb',fileobj=output,mtime=0) as compressed:
        with tarfile.open(fileobj=compressed,mode='w') as archive:
            for name,data in sorted(files.items()):
                entry=tarfile.TarInfo(name);entry.size=len(data);entry.mtime=0
                entry.mode=0o755 if name.endswith(('.sh','.py')) or Path(name).name == 'daphne-mode' else 0o644
                archive.addfile(entry,io.BytesIO(data))
    digest = hashlib.sha256(args.output.read_bytes()).hexdigest()
    args.output.with_suffix(args.output.suffix+'.sha256').write_bytes((digest+'  '+args.output.name+'\n').encode('ascii'))
    print(json.dumps({'bundle':str(args.output.resolve()), 'sha256':digest, 'files':len(files), 'bytes':args.output.stat().st_size}))


if __name__=='__main__': main()
