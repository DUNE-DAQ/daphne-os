#!/usr/bin/env python3
"""Catch a U-Boot prompt on a serial console by interrupting autoboot."""

import argparse
import sys
import time
from typing import Optional

import serial


AUTOSTOP_MARKERS = (
    b"U-Boot 2024.01",
    b"Hit any key to stop autoboot",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", default="/dev/ttyUSB2", help="Serial device path")
    parser.add_argument("--baudrate", type=int, default=115200, help="Serial baud rate")
    parser.add_argument("--prompt", default="ZynqMP>", help="Prompt string to catch")
    parser.add_argument("--timeout", type=float, default=180.0, help="Overall timeout in seconds")
    parser.add_argument(
        "--stop-sequence",
        default=" \r",
        help="Characters to spam once autoboot text appears",
    )
    parser.add_argument(
        "--initial-command",
        help="Optional command to send immediately after opening the serial port",
    )
    parser.add_argument("--log", help="Optional transcript path")
    return parser.parse_args()


def write_log(handle: Optional[object], payload: bytes) -> None:
    if handle is None or not payload:
        return
    handle.write(payload.decode("utf-8", errors="replace"))
    handle.flush()


def main() -> int:
    args = parse_args()
    prompt = args.prompt.encode()
    stop_sequence = args.stop_sequence.encode("ascii", errors="ignore")
    buffer = bytearray()
    entered_stop_mode = False
    next_stop_send = 0.0
    log_handle = open(args.log, "a", encoding="utf-8") if args.log else None

    try:
        with serial.Serial(args.device, baudrate=args.baudrate, timeout=0) as ser:
            if args.initial_command:
                ser.write(args.initial_command.encode("ascii") + b"\r")
                time.sleep(0.1)
            deadline = time.time() + args.timeout
            while time.time() < deadline:
                waiting = ser.in_waiting
                if waiting:
                    chunk = ser.read(waiting)
                    buffer.extend(chunk)
                    sys.stdout.buffer.write(chunk)
                    sys.stdout.buffer.flush()
                    write_log(log_handle, chunk)

                    if not entered_stop_mode and any(marker in buffer for marker in AUTOSTOP_MARKERS):
                        entered_stop_mode = True
                        next_stop_send = 0.0
                        sys.stdout.write("\n<<entered-autoboot-stop-mode>>\n")
                        sys.stdout.flush()

                    if prompt in buffer:
                        sys.stdout.write("\n<<caught-uboot-prompt>>\n")
                        sys.stdout.flush()
                        return 0
                else:
                    time.sleep(0.02)

                if entered_stop_mode and time.time() >= next_stop_send:
                    ser.write(stop_sequence)
                    next_stop_send = time.time() + 0.05

            sys.stderr.write("Timed out before catching U-Boot prompt\n")
            return 1
    finally:
        if log_handle is not None:
            log_handle.close()


if __name__ == "__main__":
    raise SystemExit(main())
