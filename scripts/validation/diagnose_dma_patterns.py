#!/usr/bin/env python3
"""Compare physical AFE patterns at fixed timing; never declare alignment.

Run on the board as root with all hardware clients stopped. Reuses the
operator's qualified Board/Capture helper, without loading firmware, changing
DACs or managing services. The expected build must match that helper.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import numpy as np

# Fixed patterns are raw ADC codes, before the normal-input offset conversion.
PATTERNS = (('ramp', 7, None), ('toggle', 5, None),
            ('zeros', 6, 0), ('ones', 4, 0x3fff),
            ('deskew', 2, 0x1555), ('sync', 1, 0x3f80),
            ('custom-negative', 3, 0x3fe0), ('custom-positive', 3, 0x0020),
            ('normal-adc', 0, None))


def analyze(words, kind, expected=None):
    """Report exact raw errors, including bit masks; no noise filtering."""
    raw = np.asarray(words, dtype=np.uint16)
    if raw.ndim != 2 or raw.shape[0] < 2:
        raise ValueError('expected [ticks >= 2, lanes]')
    rows = []
    for lane in range(raw.shape[1]):
        x = raw[:, lane]
        if kind == 'normal-adc':
            adc = ((x >> 2) ^ 0x2000).astype(np.int32)
            center = float(np.median(adc))
            bad = np.flatnonzero(np.abs(adc - center) > 256)
            rows.append({'lane': lane, 'errors': 0, 'nonzero_padding': int(np.count_nonzero(x & 3)),
                         'invalid_toggle_words': 0, 'mean_adc14': float(adc.mean()),
                         'std_adc14': float(adc.std()), 'median_adc14': center,
                         'outliers_gt_256': int(bad.size),
                         'outlier_windows': [{'tick': int(t), 'raw': x[max(0, t-2):t+3].tolist(),
                                               'adc14': adc[max(0, t-2):t+3].tolist()} for t in bad[:16]],
                         'note': 'Analog outliers are diagnostic observations, not proof of digital errors without a known stimulus'})
            continue
        if kind == 'ramp':
            # uint16 addition preserves the serializer wrap at 0xfffc -> 0.
            reference = ((x[:-1].astype(np.uint32) + 4) & 0xffff).astype(np.uint16)
            observed = x[1:]
            start = 1
        elif kind == 'toggle':
            # Phase is free, but every word must be a legal endpoint and
            # alternate. A repeated valid endpoint is still an error.
            reference = np.where(x[:-1] == 0, 0xfffc, 0).astype(np.uint16)
            observed = x[1:]
            start = 1
        else:
            if expected is None or not 0 <= expected <= 0x3fff:
                raise ValueError('constant pattern requires an ADC14 code')
            reference = np.full(x.size, expected << 2, dtype=np.uint16)
            observed = x
            start = 0
        mismatches = observed ^ reference
        bad = np.flatnonzero(mismatches)
        rows.append({
            'lane': lane, 'checks': int(observed.size), 'errors': int(bad.size),
            'nonzero_padding': int(np.count_nonzero(x & 3)),
            'invalid_toggle_words': int(np.count_nonzero((x != 0) & (x != 0xfffc))) if kind == 'toggle' else 0,
            'raw_bit_mismatches': [int(np.count_nonzero(mismatches & (1 << bit))) for bit in range(16)],
            'first_errors': [{'tick': int(t + start), 'raw': int(observed[t]),
                              'expected_raw': int(reference[t]), 'xor': int(mismatches[t])}
                             for t in bad[:16]],
            'first_raw_words': x[:16].tolist(),
        })
    return rows


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[name] = loaded
    spec.loader.exec_module(loaded)
    return loaded


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--board-helper', type=Path, required=True)
    ap.add_argument('--dma-helper', type=Path, required=True)
    ap.add_argument('--expected-build-id', type=lambda s: int(s, 0), required=True)
    ap.add_argument('--afes', default='0,1,2,3,4')
    ap.add_argument('--taps', help='comma-separated diagnostic taps; otherwise preserve each AFE current tap')
    ap.add_argument('--bitslip', type=int, help='diagnostic bitslip; otherwise preserve current value')
    ap.add_argument('--length', type=int, default=1048576)
    ap.add_argument('--repeat', type=int, default=3)
    ap.add_argument('--output', type=Path, required=True, help='new directory')
    args = ap.parse_args()
    afes = [int(s) for s in args.afes.split(',')]
    taps = None if args.taps is None else [int(s) for s in args.taps.split(',')]
    if (not afes or len(set(afes)) != len(afes) or any(a not in range(5) for a in afes)
            or not 2 <= args.length <= 1048576 or not 1 <= args.repeat <= 10
            or (taps is not None and (not taps or any(t not in range(512) for t in taps)))
            or (args.bitslip is not None and args.bitslip not in range(16))):
        ap.error('invalid AFE/timing/length/repeat selection')
    if os.geteuid() != 0:
        ap.error('root required for SPI/MMIO and the physical DMA device')
    for unit in ('daphne-dma-manual.service', 'daphne.service', 'hermes.service'):
        pid = subprocess.check_output(['systemctl', 'show', unit, '-p', 'MainPID', '--value'], text=True).strip()
        if pid and int(pid):
            raise RuntimeError(f'{unit} still owns hardware; stop it before this diagnostic')
    helper = module(args.board_helper, 'qualified_dma_board')
    if helper.BUILD_DMA != args.expected_build_id:
        raise RuntimeError('expected build does not match the supplied qualified helper')
    args.output.mkdir(parents=True, exist_ok=False)
    board = helper.Board()
    if board.build != args.expected_build_id:
        raise RuntimeError('loaded gateware differs from the expected build')
    original = board.snapshot()
    save(args.output / 'before.json', original)
    if original['global'] != 2 or not board.fe.read(4) & 1:
        raise RuntimeError('AFE power or IDELAY readiness missing')
    for a in afes:
        regs = original['afe_spi_order'][helper.AFE_TO_PL[a]]
        if regs['3'] & 0x6000 != 0x2000 or regs['4'] & 0x1a:
            raise RuntimeError('diagnostic requires the configured ADC14/16x/LSB-first/twos-complement format')
        if regs['2'] & 0xe000:
            raise RuntimeError('normal ADC baseline required before pattern comparison')
    capture = helper.Capture(module(args.dma_helper, 'qualified_dma_uapi'), args.output)
    report = {'build_id': board.build, 'source': 'physical-AFE', 'declares_alignment': False,
              'cases': [], 'restoration_verified': False}

    def interrupt(sig, _):
        raise KeyboardInterrupt(f'signal {sig}; restore after DMA abort')
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, interrupt)
    try:
        board.fe.write(0, original['frontend']['0'] & ~4)
        for a in afes:
            chip = helper.AFE_TO_PL[a]
            regs = original['afe_spi_order'][chip]
            slip = args.bitslip if args.bitslip is not None else original['frontend'][str(32 + 4 * chip)]
            for tap in taps if taps is not None else [original['frontend'][str(12 + 4 * chip)]]:
                board.position(a, tap, slip)
                for name, mode, code in PATTERNS:
                    board.write_reg(chip, 10, regs['10'] if mode == 0 else regs['10'] | 0x100)
                    if mode == 3:
                        board.write_reg(chip, 5, (regs['5'] & ~0x3fff) | code)
                    board.write_reg(chip, 2, (regs['2'] & ~0xe000) | (mode << 13))
                    time.sleep(.01)
                    for repeat in range(args.repeat):
                        metadata, chunks = capture.run(list(range(a * 8, a * 8 + 8)), args.length)
                        channels, words = chunks[a // 2]
                        lanes = analyze(words, name if name in ('ramp', 'toggle', 'normal-adc') else 'constant', code)
                        for row, channel in zip(lanes, channels):
                            row['channel'] = channel
                        case = {'afe': a, 'tap': tap, 'bitslip': slip, 'pattern': name,
                                'repeat': repeat, 'capture': metadata, 'lanes': lanes}
                        report['cases'].append(case)
                        save(args.output / 'report.json', report)
                        print(a, tap, slip, name, repeat, [r['errors'] for r in lanes], flush=True)
                board.write_reg(chip, 2, regs['2'])
                board.write_reg(chip, 5, regs['5'])
                board.write_reg(chip, 10, regs['10'])
    except BaseException as exc:
        report['error'] = str(exc)
        raise
    finally:
        # The qualified helper marks uncertain aborts. Do not access or
        # unload PL after quarantine; leave recovery to the operator.
        if (args.output / 'quarantined').exists():
            report['restoration_error'] = 'DMA halt unconfirmed; overlay must remain loaded'
        else:
            try:
                board.restore_patterns(original)
                for a in afes:
                    chip = helper.AFE_TO_PL[a]
                    board.position(a, original['frontend'][str(12 + 4 * chip)],
                                   original['frontend'][str(32 + 4 * chip)])
                board.fe.write(0, original['frontend']['0'])
                after = board.snapshot()
                save(args.output / 'after.json', after)
                report['restoration_verified'] = after == original
                if not report['restoration_verified']:
                    raise RuntimeError('snapshot restoration mismatch')
            except BaseException as exc:
                report['restoration_error'] = str(exc)
        save(args.output / 'report.json', report)
    return 0 if report['restoration_verified'] and all(
        not (r['errors'] or r['nonzero_padding'] or r['invalid_toggle_words'])
        for c in report['cases'] for r in c['lanes']) else 1


if __name__ == '__main__':
    sys.exit(main())
