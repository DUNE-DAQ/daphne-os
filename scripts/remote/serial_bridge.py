#!/usr/bin/env python3
"""Bridge stdin/stdout to a serial port."""

import argparse
import os
import select
import sys
from typing import Optional

import serial


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", default="/dev/ttyUSB2", help="Serial device path")
    parser.add_argument("--baudrate", type=int, default=115200, help="Serial baud rate")
    parser.add_argument("--log", help="Optional transcript path")
    return parser.parse_args()


def write_log(handle: Optional[object], payload: bytes) -> None:
    if handle is None or not payload:
        return
    handle.write(payload.decode("utf-8", errors="replace"))
    handle.flush()


def main() -> int:
    args = parse_args()
    log_handle = open(args.log, "a", encoding="utf-8") if args.log else None
    stdin_fd = sys.stdin.fileno()
    stdout = sys.stdout.buffer

    try:
        with serial.Serial(args.device, baudrate=args.baudrate, timeout=0) as ser:
            while True:
                readable, _, _ = select.select([stdin_fd, ser.fileno()], [], [])
                if stdin_fd in readable:
                    chunk = os.read(stdin_fd, 4096)
                    if not chunk:
                        return 0
                    ser.write(chunk)
                if ser.fileno() in readable:
                    waiting = ser.in_waiting or 1
                    chunk = ser.read(waiting)
                    if not chunk:
                        continue
                    stdout.write(chunk)
                    stdout.flush()
                    write_log(log_handle, chunk)
    finally:
        if log_handle is not None:
            log_handle.close()


if __name__ == "__main__":
    raise SystemExit(main())
