#!/usr/bin/env python3
"""Run one or more U-Boot commands over a serial console and capture replies."""

import argparse
import pathlib
import sys
import time
from typing import List, Optional

import serial


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "commands",
        nargs="*",
        help="U-Boot commands to run sequentially",
    )
    parser.add_argument(
        "--device",
        default="/dev/ttyUSB2",
        help="Serial device path",
    )
    parser.add_argument(
        "--baudrate",
        type=int,
        default=115200,
        help="Serial baud rate",
    )
    parser.add_argument(
        "--prompt",
        default="ZynqMP>",
        help="Prompt string that marks command completion",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=12.0,
        help="Per-command timeout in seconds",
    )
    parser.add_argument(
        "--idle",
        type=float,
        default=0.8,
        help="Settle time to drain existing serial data before running commands",
    )
    parser.add_argument(
        "--log",
        help="Optional transcript path",
    )
    parser.add_argument(
        "--no-wake",
        action="store_true",
        help="Skip the initial carriage return used to elicit a prompt",
    )
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


def read_until_prompt(
    ser: serial.Serial,
    prompt: bytes,
    timeout_s: float,
    log_handle: Optional[object],
) -> bytes:
    deadline = time.time() + timeout_s
    chunks = []
    while time.time() < deadline:
        waiting = ser.in_waiting
        if waiting:
            chunk = ser.read(waiting)
            chunks.append(chunk)
            write_log(log_handle, chunk)
            if prompt in b"".join(chunks):
                return b"".join(chunks)
        else:
            time.sleep(0.05)
    return b"".join(chunks)


def run_commands(
    device: str,
    baudrate: int,
    prompt: str,
    timeout_s: float,
    idle_s: float,
    commands: List[str],
    wake: bool,
    log_path: Optional[str],
) -> int:
    prompt_bytes = prompt.encode()
    log_handle = open(log_path, "a", encoding="utf-8") if log_path else None

    try:
        with serial.Serial(device, baudrate=baudrate, timeout=0) as ser:
            if wake:
                ser.write(b"\r")
                time.sleep(0.1)
            baseline = drain_existing(ser, idle_s, log_handle)

            if log_handle is not None:
                log_handle.write(
                    "\n== session {} ==\n".format(time.strftime("%Y-%m-%d %H:%M:%S"))
                )
                if baseline:
                    log_handle.write("== drained existing output above ==\n")
                log_handle.flush()

            if not commands:
                write_stdout(baseline)
                return 0 if prompt_bytes in baseline else 1

            saw_prompt = prompt_bytes in baseline
            for command in commands:
                if not saw_prompt:
                    ser.write(b"\r")
                    time.sleep(0.1)
                    extra = read_until_prompt(ser, prompt_bytes, timeout_s, log_handle)
                    baseline += extra
                    saw_prompt = prompt_bytes in baseline or prompt_bytes in extra
                if not saw_prompt:
                    sys.stderr.write("Prompt not found before command: {}\n".format(command))
                    return 2

                banner = "\n>>> {}\n".format(command)
                if log_handle is not None:
                    log_handle.write(banner)
                    log_handle.flush()
                sys.stdout.write(banner)
                sys.stdout.flush()

                ser.write(command.encode("ascii") + b"\r")
                reply = read_until_prompt(ser, prompt_bytes, timeout_s, log_handle)
                write_stdout(reply)

                if prompt_bytes not in reply:
                    sys.stderr.write("Timed out waiting for prompt after: {}\n".format(command))
                    return 3

            return 0
    finally:
        if log_handle is not None:
            log_handle.close()


def main() -> int:
    args = parse_args()
    log_path = str(pathlib.Path(args.log).expanduser()) if args.log else None
    return run_commands(
        device=args.device,
        baudrate=args.baudrate,
        prompt=args.prompt,
        timeout_s=args.timeout,
        idle_s=args.idle,
        commands=args.commands,
        wake=not args.no_wake,
        log_path=log_path,
    )


if __name__ == "__main__":
    raise SystemExit(main())
