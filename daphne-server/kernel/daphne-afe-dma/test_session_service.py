#!/usr/bin/env python3
"""Run production service control flow with mocked MMIO on a Linux build host."""
import argparse
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source = Path(__file__).resolve().parent
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    implementation = (source / 'afe_session_impl.h').read_text()
    start = implementation.index('static void session_service(struct work_struct *work)')
    end = implementation.index('static void session_stop(struct work_struct *work)', start)
    (out / 'session_service_under_test.h').write_text(implementation[start:end])
    executable = out / 'session_service_test'
    result = subprocess.run(['gcc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-O2',
        '-I', str(out), str(source / 'session_service_test.c'), '-o', str(executable)],
        capture_output=True, text=True)
    (out / 'service-compile.log').write_text(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    result = subprocess.run([str(executable)], capture_output=True, text=True)
    (out / 'service-test.log').write_text(result.stdout + result.stderr)
    if result.returncode or 'AFE_DMA_SESSION_SERVICE_PASS' not in result.stdout:
        raise RuntimeError(result.stdout + result.stderr)
    print(result.stdout, end='')


if __name__ == '__main__':
    main()
