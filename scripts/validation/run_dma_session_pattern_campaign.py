#!/usr/bin/env python3
"""Bounded local driver/DDR pattern tests; run as root on the idle test board."""
import json
from pathlib import Path
import subprocess
import time

ROOT = Path('/opt/daphne-dma-persistent-manual-20261012')
OUTPUT = Path('/home/petalinux/dma-persistent-stage-20261011/pattern-campaign')
OUTPUT.mkdir(exist_ok=True)
cases = [('two-one-route', 2, 2048, 0, '0,1', 0),
         ('eight-all-channels', 8, 2048, 1024, ','.join(map(str, range(40))), 0),
         ('wrap-three-routes', 37, 32000, 4096, '39,0,17', 0),
         ('pressure', 37, 2048, 1024, '39,0,17', 100)]
reports = []
for name, n, length, pretrigger, channels, pause in cases:
    command = [str(ROOT/'daphne-afe-session-probe'), '0x0630a9da', str(n),
               str(length), str(pretrigger), channels, 'pattern', str(pause)]
    before = Path('/proc/meminfo').read_text()
    start = time.monotonic()
    result = subprocess.run(command, capture_output=True, text=True, timeout=140)
    (OUTPUT/(name+'.log')).write_text(result.stdout+result.stderr)
    (OUTPUT/(name+'.mem-before')).write_text(before)
    (OUTPUT/(name+'.mem-after')).write_text(Path('/proc/meminfo').read_text())
    print(name, result.stdout+result.stderr, flush=True)
    if result.returncode:
        raise RuntimeError(f'{name} failed; retain image and inspect cleanup/quarantine')
    record = json.loads(result.stdout)
    assert record['events'] == n and record['starts'] == record['stops'] == 1 and record['guards_ok']
    assert record['bytes'] == n*length*len(channels.split(','))*2
    if pause:
        assert record['pauses'] > 0
    subprocess.run([str(ROOT/'daphne-afe-dma-quiesce')], check=True, timeout=15)
    record.update(case=name, length=length, pretrigger=pretrigger, channels=channels,
                  wall_seconds=time.monotonic()-start)
    reports.append(record)
    (OUTPUT/'summary.json').write_text(json.dumps(reports, indent=2)+'\n')
