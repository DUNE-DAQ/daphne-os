#!/usr/bin/env python3
"""Flash a chunked WIC image to eMMC from a U-Boot serial prompt."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


PROMPT_DEFAULT = "ZynqMP>"
LOADADDR_DEFAULT = "0x10000000"
VERIFYADDR_DEFAULT = "0x18000000"
BAD_PATTERNS = (
    "ERROR",
    "Error",
    "TFTP error",
    "Retry count exceeded",
    "Unknown command",
    "Bad device",
    "Card did not respond",
    "MMC write failed",
    "MMC read failed",
)


@dataclass(frozen=True)
class FlashOptions:
    manifest: Path
    tftp_prefix: str
    loadaddr: str
    verifyaddr: str
    mmc_dev: int
    mmc_hwpart: int
    serverip: str | None
    ipaddr: str | None
    netmask: str | None
    gatewayip: str | None
    ethaddr: str | None
    use_dhcp: bool
    erase: bool
    verify_readback: bool
    reset_after: bool
    tftp_dst_port: int | None = None
    tftp_blocksize: int | None = None
    tftp_windowsize: int | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True, help="Manifest from prepare_uboot_wic_chunks.py")
    parser.add_argument("--tftp-prefix", required=True, help="Path prefix as seen by the TFTP client")
    parser.add_argument("--device", default="/dev/ttyUSB2", help="Serial device path")
    parser.add_argument("--baudrate", type=int, default=115200, help="Serial baud rate")
    parser.add_argument("--prompt", default=PROMPT_DEFAULT, help="U-Boot prompt string")
    parser.add_argument("--timeout", type=float, default=60.0, help="Per-command timeout")
    parser.add_argument("--idle", type=float, default=0.5, help="Drain delay before starting")
    parser.add_argument("--log", help="Optional serial transcript path")
    parser.add_argument("--loadaddr", default=LOADADDR_DEFAULT)
    parser.add_argument("--verifyaddr", default=VERIFYADDR_DEFAULT)
    parser.add_argument("--mmc-dev", type=int, default=0)
    parser.add_argument("--mmc-hwpart", type=int, default=0)
    parser.add_argument("--serverip")
    parser.add_argument("--ipaddr")
    parser.add_argument("--netmask")
    parser.add_argument("--gatewayip")
    parser.add_argument("--ethaddr")
    parser.add_argument(
        "--tftp-dst-port",
        type=lambda value: int(value, 0),
        help="Set U-Boot tftpdstp before TFTP transfers, if supported by U-Boot",
    )
    parser.add_argument("--tftp-blocksize", type=lambda value: int(value, 0), help="Set U-Boot tftpblocksize")
    parser.add_argument("--tftp-windowsize", type=lambda value: int(value, 0), help="Set U-Boot tftpwindowsize")
    parser.add_argument("--dhcp", action="store_true", help="Run dhcp before flashing")
    parser.add_argument("--erase", action="store_true", help="Erase the target block span before writes")
    parser.add_argument("--verify-readback", action="store_true", help="Read back and CRC each chunk after write")
    parser.add_argument("--reset-after", action="store_true", help="Issue reset after flashing")
    parser.add_argument("--dry-run", action="store_true", help="Print the command plan as JSON and exit")
    return parser.parse_args()


def load_manifest(path: Path) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("contract") != "daphne.uboot-wic-flash-manifest":
        raise ValueError("unsupported flash manifest contract")
    if manifest.get("version") != 1:
        raise ValueError("unsupported flash manifest version")
    if manifest.get("block_size_bytes") != 512:
        raise ValueError("U-Boot mmc write plan requires 512-byte blocks")
    chunks = manifest.get("chunks")
    if not isinstance(chunks, list) or not chunks:
        raise ValueError("flash manifest has no chunks")
    expected_start = 0
    for index, chunk in enumerate(chunks):
        if chunk.get("index") != index:
            raise ValueError(f"chunk index mismatch at entry {index}")
        if chunk.get("emmc_start_block") != expected_start:
            raise ValueError(f"chunk {index} is not contiguous")
        block_count = int(chunk["block_count"])
        padded_size = int(chunk["padded_size_bytes"])
        if block_count <= 0 or block_count * 512 != padded_size:
            raise ValueError(f"chunk {index} has invalid block sizing")
        if not re.fullmatch(r"[0-9a-fA-F]{8}", str(chunk["crc32"])):
            raise ValueError(f"chunk {index} has invalid crc32")
        expected_start += block_count
    return manifest


def build_command_plan(manifest: dict[str, Any], options: FlashOptions) -> list[dict[str, str]]:
    commands: list[dict[str, str]] = [
        {"stage": "wake", "command": "version"},
    ]
    if options.serverip:
        commands.append({"stage": "network", "command": f"setenv serverip {options.serverip}"})
    if options.ipaddr:
        commands.append({"stage": "network", "command": f"setenv ipaddr {options.ipaddr}"})
    if options.netmask:
        commands.append({"stage": "network", "command": f"setenv netmask {options.netmask}"})
    if options.gatewayip:
        commands.append({"stage": "network", "command": f"setenv gatewayip {options.gatewayip}"})
    if options.ethaddr:
        commands.append({"stage": "network", "command": f"setenv ethaddr {options.ethaddr}"})
    if options.tftp_dst_port is not None:
        commands.append({"stage": "network", "command": f"setenv tftpdstp {options.tftp_dst_port}"})
    if options.tftp_blocksize is not None:
        commands.append({"stage": "network", "command": f"setenv tftpblocksize {options.tftp_blocksize}"})
    if options.tftp_windowsize is not None:
        commands.append({"stage": "network", "command": f"setenv tftpwindowsize {options.tftp_windowsize}"})
    if options.use_dhcp:
        commands.append({"stage": "network", "command": "dhcp"})
    commands.extend(
        [
            {"stage": "mmc", "command": f"mmc dev {options.mmc_dev} {options.mmc_hwpart}"},
            {"stage": "mmc", "command": "mmc rescan"},
        ]
    )
    if options.erase:
        padded_blocks = int(manifest["image"]["padded_block_count"])
        commands.append({"stage": "erase", "command": f"mmc erase 0x0 0x{padded_blocks:x}"})

    for chunk in manifest["chunks"]:
        filename = _join_tftp(options.tftp_prefix, str(chunk["filename"]))
        padded_size = int(chunk["padded_size_bytes"])
        block_count = int(chunk["block_count"])
        start_block = int(chunk["emmc_start_block"])
        expected_crc = str(chunk["crc32"]).lower()
        commands.extend(
            [
                {
                    "stage": f"chunk-{chunk['index']}",
                    "command": f"mw.b {options.loadaddr} 0x00 0x{padded_size:x}",
                },
                {
                    "stage": f"chunk-{chunk['index']}",
                    "command": f"tftpboot {options.loadaddr} {filename}",
                    "expect_filesize": f"0x{padded_size:x}",
                },
                {
                    "stage": f"chunk-{chunk['index']}",
                    "command": f"crc32 {options.loadaddr} 0x{padded_size:x}",
                    "expect_crc32": expected_crc,
                },
                {
                    "stage": f"chunk-{chunk['index']}",
                    "command": f"mmc write {options.loadaddr} 0x{start_block:x} 0x{block_count:x}",
                },
            ]
        )
        if options.verify_readback:
            commands.extend(
                [
                    {
                        "stage": f"verify-{chunk['index']}",
                        "command": f"mmc read {options.verifyaddr} 0x{start_block:x} 0x{block_count:x}",
                    },
                    {
                        "stage": f"verify-{chunk['index']}",
                        "command": f"crc32 {options.verifyaddr} 0x{padded_size:x}",
                        "expect_crc32": expected_crc,
                    },
                ]
            )
    if options.reset_after:
        commands.append({"stage": "reset", "command": "reset", "no_prompt": "true"})
    return commands


def _join_tftp(prefix: str, filename: str) -> str:
    return "/".join(part.strip("/") for part in (prefix, filename) if part.strip("/"))


def run_plan(
    plan: list[dict[str, str]],
    *,
    device: str,
    baudrate: int,
    prompt: str,
    timeout: float,
    idle: float,
    log_path: str | None,
) -> int:
    import serial

    prompt_bytes = prompt.encode()
    log_handle = open(log_path, "a", encoding="utf-8") if log_path else None
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
                    print(f"error: prompt not found before command: {command}", file=sys.stderr)
                    return 2

                _write_banner(log_handle, command)
                print(f"\n>>> {command}")
                ser.write(command.encode("ascii") + b"\r")
                if step.get("no_prompt") == "true":
                    return 0
                reply = _read_until_prompt(ser, prompt_bytes, timeout, log_handle)
                sys.stdout.buffer.write(reply)
                sys.stdout.buffer.flush()
                if prompt_bytes not in reply:
                    print(f"error: timed out waiting for prompt after: {command}", file=sys.stderr)
                    return 3
                text = reply.decode("utf-8", errors="replace")
                if any(pattern in text for pattern in BAD_PATTERNS):
                    print(f"error: U-Boot reported a failure during: {command}", file=sys.stderr)
                    return 4
                if "expect_filesize" in step and not _filesize_matches(text, step["expect_filesize"]):
                    print(
                        f"error: TFTP filesize mismatch during {command}; expected {step['expect_filesize']}",
                        file=sys.stderr,
                    )
                    return 5
                if "expect_crc32" in step and _crc32_value(text) != step["expect_crc32"]:
                    print(
                        f"error: CRC mismatch during {command}; expected {step['expect_crc32']}",
                        file=sys.stderr,
                    )
                    return 6
                baseline = reply
            return 0
    finally:
        if log_handle is not None:
            log_handle.close()


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


def _filesize_matches(text: str, expected_hex: str) -> bool:
    expected = int(expected_hex, 16)
    bytes_transferred = re.search(r"Bytes transferred =\s*(\d+)", text)
    if bytes_transferred and int(bytes_transferred.group(1), 10) == expected:
        return True

    filesize_env = re.search(r"(?:^|\s)filesize=([0-9a-fA-F]+)(?:\s|$)", text)
    if filesize_env and int(filesize_env.group(1), 16) == expected:
        return True

    return False


def _crc32_value(text: str) -> str | None:
    match = re.search(r"==>\s*([0-9a-fA-F]{8})", text)
    if match:
        return match.group(1).lower()
    matches = re.findall(r"\b([0-9a-fA-F]{8})\b", text)
    return matches[-1].lower() if matches else None


def main() -> int:
    args = parse_args()
    try:
        manifest = load_manifest(args.manifest)
        options = FlashOptions(
            manifest=args.manifest,
            tftp_prefix=args.tftp_prefix,
            loadaddr=args.loadaddr,
            verifyaddr=args.verifyaddr,
            mmc_dev=args.mmc_dev,
            mmc_hwpart=args.mmc_hwpart,
            serverip=args.serverip,
            ipaddr=args.ipaddr,
            netmask=args.netmask,
            gatewayip=args.gatewayip,
            ethaddr=args.ethaddr,
            use_dhcp=args.dhcp,
            erase=args.erase,
            verify_readback=args.verify_readback,
            reset_after=args.reset_after,
            tftp_dst_port=args.tftp_dst_port,
            tftp_blocksize=args.tftp_blocksize,
            tftp_windowsize=args.tftp_windowsize,
        )
        plan = build_command_plan(manifest, options)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.dry_run:
        print(json.dumps({"manifest": str(args.manifest), "commands": plan}, indent=2))
        return 0

    return run_plan(
        plan,
        device=args.device,
        baudrate=args.baudrate,
        prompt=args.prompt,
        timeout=args.timeout,
        idle=args.idle,
        log_path=args.log,
    )


if __name__ == "__main__":
    raise SystemExit(main())
