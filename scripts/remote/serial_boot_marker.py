#!/usr/bin/env python3
"""Drive a U-Boot boot sequence over serial and watch Linux output for a marker."""

import argparse
import sys
import time
from typing import Optional

import serial


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", default="/dev/ttyUSB2", help="Serial device path")
    parser.add_argument("--baudrate", type=int, default=115200, help="Serial baud rate")
    parser.add_argument("--prompt", default="ZynqMP>", help="U-Boot prompt string")
    parser.add_argument(
        "--command",
        action="append",
        default=[],
        help="U-Boot command to run and wait for a prompt afterwards. May be repeated.",
    )
    parser.add_argument(
        "--final-command",
        required=True,
        help="Final command to send without waiting for a prompt afterwards (for example booti).",
    )
    parser.add_argument("--marker", required=True, help="Byte sequence to watch for after the final command")
    parser.add_argument("--command-timeout", type=float, default=45.0, help="Per-command timeout")
    parser.add_argument("--marker-timeout", type=float, default=120.0, help="Timeout while waiting for marker")
    parser.add_argument("--idle", type=float, default=0.5, help="Drain delay before starting")
    parser.add_argument("--log", help="Optional transcript path")
    parser.add_argument("--no-wake", action="store_true", help="Skip the initial carriage return")
    return parser.parse_args()


def write_log(handle: Optional[object], payload: bytes) -> None:
    if handle is None or not payload:
        return
    handle.write(payload.decode("utf-8", errors="replace"))
    handle.flush()


def write_stdout(payload: bytes) -> None:
    if not payload:
        return
    sys.stdout.buffer.write(payload)
    sys.stdout.buffer.flush()


def drain_existing(ser: serial.Serial, idle_s: float, log_handle: Optional[object]) -> bytes:
    deadline = time.time() + idle_s
    chunks = []
    while time.time() < deadline:
        waiting = ser.in_waiting
        if waiting:
            chunk = ser.read(waiting)
            chunks.append(chunk)
            write_log(log_handle, chunk)
            deadline = time.time() + idle_s
        else:
            time.sleep(0.05)
    return b"".join(chunks)


def read_until_contains(
    ser: serial.Serial,
    needle: bytes,
    timeout_s: float,
    log_handle: Optional[object],
) -> bytes:
    deadline = time.time() + timeout_s
    chunks = bytearray()
    while time.time() < deadline:
        waiting = ser.in_waiting
        if waiting:
            chunk = ser.read(waiting)
            chunks.extend(chunk)
            write_log(log_handle, chunk)
            if needle in chunks:
                return bytes(chunks)
        else:
            time.sleep(0.05)
    return bytes(chunks)


def main() -> int:
    args = parse_args()
    prompt = args.prompt.encode()
    marker = args.marker.encode()
    log_handle = open(args.log, "a", encoding="utf-8") if args.log else None

    try:
        with serial.Serial(args.device, baudrate=args.baudrate, timeout=0) as ser:
            if not args.no_wake:
                ser.write(b"\r")
                time.sleep(0.1)

            baseline = drain_existing(ser, args.idle, log_handle)
            write_stdout(baseline)

            for command in args.command:
                if prompt not in baseline:
                    ser.write(b"\r")
                    time.sleep(0.1)
                    baseline += read_until_contains(ser, prompt, args.command_timeout, log_handle)
                if prompt not in baseline:
                    sys.stderr.write(f"Prompt not found before command: {command}\n")
                    return 2

                banner = f"\n>>> {command}\n"
                if log_handle is not None:
                    log_handle.write(banner)
                    log_handle.flush()
                sys.stdout.write(banner)
                sys.stdout.flush()

                ser.write(command.encode("ascii") + b"\r")
                reply = read_until_contains(ser, prompt, args.command_timeout, log_handle)
                write_stdout(reply)
                if prompt not in reply:
                    sys.stderr.write(f"Timed out waiting for prompt after: {command}\n")
                    return 3
                baseline = reply

            banner = f"\n>>> {args.final_command}\n"
            if log_handle is not None:
                log_handle.write(banner)
                log_handle.flush()
            sys.stdout.write(banner)
            sys.stdout.flush()
            ser.write(args.final_command.encode("ascii") + b"\r")

            after = read_until_contains(ser, marker, args.marker_timeout, log_handle)
            write_stdout(after)
            if marker not in after:
                sys.stderr.write(f"Timed out waiting for marker: {args.marker}\n")
                return 4

            sys.stdout.write(f"\n<<marker-seen:{args.marker}>>\n")
            sys.stdout.flush()
            return 0
    finally:
        if log_handle is not None:
            log_handle.close()


if __name__ == "__main__":
    raise SystemExit(main())
