#!/usr/bin/env python3
"""Dump an I2C EEPROM from a U-Boot serial prompt."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


PROMPT_DEFAULT = "ZynqMP>"
EEPROM_SIZE_DEFAULT = 8192
CHUNK_SIZE_DEFAULT = 256
BAD_PATTERNS = (
    "ERROR",
    "Error",
    "Unknown command",
    "No chip found",
    "i2c_read: failed",
    "Failure",
)


@dataclass(frozen=True)
class DumpOptions:
    i2c_bus: int
    chip: str
    offset_width: int
    size: int
    chunk_size: int
    output: Path
    probe: bool


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", default="/dev/ttyUSB2", help="Serial device path")
    parser.add_argument("--baudrate", type=int, default=115200, help="Serial baud rate")
    parser.add_argument("--prompt", default=PROMPT_DEFAULT, help="U-Boot prompt string")
    parser.add_argument("--timeout", type=float, default=20.0, help="Per-command timeout")
    parser.add_argument("--idle", type=float, default=0.5, help="Drain delay before starting")
    parser.add_argument("--log", help="Optional serial transcript path")
    parser.add_argument("--i2c-bus", type=int, default=1, help="U-Boot I2C bus containing the SOM")
    parser.add_argument("--chip", default="0x50", help="I2C EEPROM chip address")
    parser.add_argument(
        "--offset-width",
        type=int,
        choices=(0, 1, 2),
        default=2,
        help="U-Boot I2C address-width suffix for the EEPROM offset",
    )
    parser.add_argument("--size", type=lambda value: int(value, 0), default=EEPROM_SIZE_DEFAULT)
    parser.add_argument(
        "--chunk-size",
        type=lambda value: int(value, 0),
        default=CHUNK_SIZE_DEFAULT,
        help="Bytes to request per U-Boot i2c md command",
    )
    parser.add_argument("--output", type=Path, required=True, help="Raw EEPROM dump path")
    parser.add_argument("--probe", action="store_true", help="Run i2c probe before reading")
    parser.add_argument("--dry-run", action="store_true", help="Print the command plan as JSON and exit")
    return parser.parse_args()


def build_command_plan(options: DumpOptions) -> list[dict[str, str]]:
    if options.size <= 0:
        raise ValueError("size must be positive")
    if options.chunk_size <= 0:
        raise ValueError("chunk size must be positive")

    plan = [
        {"stage": "wake", "command": "version"},
        {"stage": "i2c", "command": f"i2c dev {options.i2c_bus}"},
    ]
    if options.probe:
        plan.append({"stage": "i2c", "command": "i2c probe"})

    offset = 0
    while offset < options.size:
        length = min(options.chunk_size, options.size - offset)
        address = f"0x{offset:x}"
        if options.offset_width:
            address = f"{address}.{options.offset_width}"
        plan.append(
            {
                "stage": f"read-0x{offset:04x}",
                "command": f"i2c md {options.chip} {address} 0x{length:x}",
                "offset": f"0x{offset:x}",
                "length": f"0x{length:x}",
            }
        )
        offset += length
    return plan


def parse_i2c_md_bytes(text: str) -> bytes:
    payload = bytearray()
    for line in text.splitlines():
        if ":" not in line:
            continue
        address, body = line.split(":", 1)
        if not re.fullmatch(r"\s*[0-9a-fA-F]+\s*", address):
            continue
        for token in body.split():
            if not re.fullmatch(r"[0-9a-fA-F]{2}", token):
                break
            payload.append(int(token, 16))
    return bytes(payload)


def run_dump(
    options: DumpOptions,
    *,
    device: str,
    baudrate: int,
    prompt: str,
    timeout: float,
    idle: float,
    log_path: str | None,
) -> dict[str, object]:
    import serial

    prompt_bytes = prompt.encode()
    plan = build_command_plan(options)
    log_handle = open(log_path, "a", encoding="utf-8") if log_path else None
    image = bytearray()
    try:
        with serial.Serial(device, baudrate=baudrate, timeout=0) as ser:
            ser.write(b"\r")
            time.sleep(0.1)
            baseline = _drain_existing(ser, idle, log_handle)
            sys.stdout.buffer.write(baseline)
            sys.stdout.buffer.flush()

            for step in plan:
                command = step["command"]
                if prompt_bytes not in baseline:
                    ser.write(b"\r")
                    time.sleep(0.1)
                    baseline += _read_until_prompt(ser, prompt_bytes, timeout, log_handle)
                if prompt_bytes not in baseline:
                    raise RuntimeError(f"prompt not found before command: {command}")

                _write_banner(log_handle, command)
                print(f"\n>>> {command}")
                ser.write(command.encode("ascii") + b"\r")
                reply = _read_until_prompt(ser, prompt_bytes, timeout, log_handle)
                sys.stdout.buffer.write(reply)
                sys.stdout.buffer.flush()
                if prompt_bytes not in reply:
                    raise RuntimeError(f"timed out waiting for prompt after: {command}")
                text = reply.decode("utf-8", errors="replace")
                if any(pattern in text for pattern in BAD_PATTERNS):
                    raise RuntimeError(f"U-Boot reported a failure during: {command}")
                if step["stage"].startswith("read-"):
                    parsed = parse_i2c_md_bytes(text)
                    expected_len = int(step["length"], 16)
                    if len(parsed) != expected_len:
                        raise RuntimeError(
                            f"{command} returned {len(parsed)} bytes; expected {expected_len}"
                        )
                    image.extend(parsed)
                baseline = reply
    finally:
        if log_handle is not None:
            log_handle.close()

    if len(image) != options.size:
        raise RuntimeError(f"captured {len(image)} bytes; expected {options.size}")
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_bytes(image)
    digest = hashlib.sha256(image).hexdigest()
    return {
        "contract": "daphne.uboot-i2c-eeprom-dump",
        "version": 1,
        "output": str(options.output),
        "size_bytes": len(image),
        "sha256": digest,
        "i2c_bus": options.i2c_bus,
        "chip": options.chip,
    }


def _write_banner(log_handle: Optional[object], command: str) -> None:
    if log_handle is not None:
        log_handle.write(f"\n>>> {command}\n")
        log_handle.flush()


def _drain_existing(ser: Any, idle_s: float, log_handle: Optional[object]) -> bytes:
    deadline = time.time() + idle_s
    chunks = []
    while time.time() < deadline:
        waiting = ser.in_waiting
        if waiting:
            chunk = ser.read(waiting)
            chunks.append(chunk)
            if log_handle is not None:
                log_handle.write(chunk.decode("utf-8", errors="replace"))
                log_handle.flush()
            deadline = time.time() + idle_s
        else:
            time.sleep(0.05)
    return b"".join(chunks)


def _read_until_prompt(ser: Any, prompt: bytes, timeout_s: float, log_handle: Optional[object]) -> bytes:
    deadline = time.time() + timeout_s
    chunks = bytearray()
    while time.time() < deadline:
        waiting = ser.in_waiting
        if waiting:
            chunk = ser.read(waiting)
            chunks.extend(chunk)
            if log_handle is not None:
                log_handle.write(chunk.decode("utf-8", errors="replace"))
                log_handle.flush()
            if prompt in chunks:
                return bytes(chunks)
        else:
            time.sleep(0.05)
    return bytes(chunks)


def main() -> int:
    args = parse_args()
    options = DumpOptions(
        i2c_bus=args.i2c_bus,
        chip=args.chip,
        offset_width=args.offset_width,
        size=args.size,
        chunk_size=args.chunk_size,
        output=args.output,
        probe=args.probe,
    )
    try:
        plan = build_command_plan(options)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.dry_run:
        print(json.dumps({"commands": plan}, indent=2))
        return 0
    try:
        result = run_dump(
            options,
            device=args.device,
            baudrate=args.baudrate,
            prompt=args.prompt,
            timeout=args.timeout,
            idle=args.idle,
            log_path=args.log,
        )
    except (OSError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
