#!/usr/bin/env python3
"""Validate a complete single-session CLI run with bounded memory and file hashes."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('folder', type=Path)
parser.add_argument('--events', type=int, required=True)
parser.add_argument('--samples', type=int, required=True)
parser.add_argument('--pretrigger', type=int, required=True)
parser.add_argument('--channels', default='0,1')
args = parser.parse_args()
channels = list(map(int, args.channels.split(',')))
count = 0; session = None; result = None
metadata = list(args.folder.glob('dma_metadata_*.jsonl'))
assert len(metadata) == 1, 'Single-session folder required'
with metadata[0].open() as source:
    for line in source:
        record = json.loads(line)
        if 'session_result' in record:
            assert result is None
            result = record
            continue
        assert result is None
        assert record['channels'] == channels and record['samples'] == args.samples
        assert record['first_waveform'] == count
        assert record['saved_encoding'] == 'offset_binary' and record['saved_format'] == 'adc14_u16_le'
        for channel in channels:
            assert record['file_first_waveform'][str(channel)] == count
        for waveform in record['waveforms']:
            event = waveform['trigger']; identity = event['event_id']; sequence = count+1
            if session is None:
                session = identity['session']
            assert identity == dict(session=session, sequence=sequence, generation=(sequence-1)//8+1, slot=(sequence-1)%8)
            assert event['samples'] == args.samples and event['pretrigger_samples'] == args.pretrigger
            assert event['window_first'] == event['trigger_index']-args.pretrigger
            assert event['fence_end'] % 8192 == 0
            assert args.samples <= event['fence_end']-event['first_cursor'] < args.samples+8192
            assert event['channel_mask'] == sum(1<<ch for ch in channels)
            assert event['valid_bytes'] == [args.samples*2*sum(ch//16 == r for ch in channels) for r in range(3)]
            assert not any(event['ignored'])
            count += 1
assert count == args.events and result is not None
progress = result['session_result']['session_progress']
for field in ('target', 'accepted', 'completed', 'driver_delivered', 'driver_released', 'staged', 'delivered', 'acknowledged'):
    assert int(progress[field]) == count, field
assert progress['guards_ok'] and progress['producer_complete']
assert int(progress['starts']) == int(progress['stops']) == 1
assert not int(progress.get('error', 0)) and not int(progress.get('hardware_error', 0))
assert not any(map(int, progress['ignored']))
files = {}
for channel in channels:
    path = args.folder/f'channel_{channel}.dat'
    assert path.stat().st_size == count*args.samples*2
    digest = hashlib.sha256(); minimum = 65535; maximum = 0; samples = 0; total = 0
    with path.open('rb') as data:
        while True:
            block = data.read(16*1024*1024)
            if not block:
                break
            digest.update(block)
            values = np.frombuffer(block, dtype='<u2')
            minimum = min(minimum, int(values.min())); maximum = max(maximum, int(values.max()))
            samples += len(values); total += int(values.sum(dtype=np.uint64))
    assert samples == count*args.samples and 0 <= minimum <= maximum < 16384
    files[str(channel)] = dict(bytes=path.stat().st_size, samples=samples, sha256=digest.hexdigest(),
                               minimum=minimum, maximum=maximum, mean=total/samples)
report = dict(result='PASS', events=count, session=session, files=files, acquisition=result)
(args.folder/'validation.json').write_text(json.dumps(report, indent=2)+'\n')
print(json.dumps(report), flush=True)
