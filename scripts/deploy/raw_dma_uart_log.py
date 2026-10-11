#!/usr/bin/env python3
"""Read-only UART recorder for the three stable DAPHNE FTDI interfaces."""
import argparse
from pathlib import Path
import signal
import threading
import time
import serial


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--serial-id', default='FNALDMezz10')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    stop = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stop.set())

    def reader(interface):
        path = f'/dev/serial/by-id/usb-Xilinx_DAPHNEMezz_{args.serial_id}-if{interface:02d}-port0'
        with serial.Serial(path, 115200, timeout=.2, exclusive=True) as port, \
                (args.output / f'if{interface:02d}.raw').open('ab', buffering=0) as raw, \
                (args.output / f'if{interface:02d}.log').open('a', buffering=1) as log:
            print(f'OPEN {path}', flush=True)
            while not stop.is_set():
                data = port.read(4096)
                if data:
                    raw.write(data)
                    log.write(f'{time.time_ns()} {data.decode("utf-8", errors="replace")}\n')

    threads = [threading.Thread(target=reader, args=(i,)) for i in (1, 2, 3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()


if __name__ == '__main__':
    main()
