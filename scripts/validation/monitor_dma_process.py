#!/usr/bin/env python3
"""Sample only CPU, memory and CMA counters during a bounded acquisition test."""
import argparse
import json
from pathlib import Path
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--pid', type=int, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--stop-file', type=Path, required=True)
parser.add_argument('--seconds', type=int, default=2500)
args = parser.parse_args()
assert 0 < args.seconds <= 3600 and args.pid > 0
deadline = time.monotonic()+args.seconds
previous = {}
with args.output.open('w', buffering=1) as output:
    while time.monotonic() < deadline and not args.stop_file.exists():
        cpus = {}
        for row in Path('/proc/stat').read_text().splitlines():
            fields = row.split()
            if fields and fields[0].startswith('cpu'):
                values = list(map(int, fields[1:9])); total = sum(values); idle = values[3]+values[4]
                old = previous.get(fields[0], (total, idle))
                delta = total-old[0]
                cpus[fields[0]] = 100*(delta-(idle-old[1]))/delta if delta else 0
                previous[fields[0]] = (total, idle)
        memory = {row.split(':')[0]: int(row.split()[1]) for row in Path('/proc/meminfo').read_text().splitlines()
                  if row.startswith(('MemAvailable:', 'CmaTotal:', 'CmaFree:'))}
        status = Path(f'/proc/{args.pid}/status')
        if not status.exists():
            break
        process = {row.split(':')[0]: int(row.split()[1]) for row in status.read_text().splitlines()
                   if row.startswith(('VmRSS:', 'VmHWM:', 'VmSize:'))}
        output.write(json.dumps(dict(time_ns=time.time_ns(), pid=args.pid, cpu_percent=cpus,
                                     memory_kib=memory, process_kib=process))+'\n')
        time.sleep(1)
