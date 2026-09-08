#!/usr/bin/env python3
"""Flash a chunked WIC image to eMMC using XSDB data loads and U-Boot serial commands."""

from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from .uboot_flash_wic import (
        BAD_PATTERNS,
        LOADADDR_DEFAULT,
        PROMPT_DEFAULT,
        VERIFYADDR_DEFAULT,
        _crc32_value,
        _drain_existing,
        _read_until_prompt,
        _write_banner,
        load_manifest,
    )
except ImportError:
    from uboot_flash_wic import (  # type: ignore[no-redef]
        BAD_PATTERNS,
        LOADADDR_DEFAULT,
        PROMPT_DEFAULT,
        VERIFYADDR_DEFAULT,
        _crc32_value,
        _drain_existing,
        _read_until_prompt,
        _write_banner,
        load_manifest,
    )


DEFAULT_A53_TARGET = "*Cortex-A53*#0*"


@dataclass(frozen=True)
class JtagFlashOptions:
    manifest: Path
    chunk_dir: Path
    loadaddr: str
    verifyaddr: str
    mmc_dev: int
    mmc_hwpart: int
    erase: bool
    verify_readback: bool
    reset_after: bool


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--chunk-dir",
        type=Path,
        help="Directory containing manifest chunks. Default: manifest directory.",
    )
    parser.add_argument(
        "--device",
        required=True,
        help="Verified U-Boot serial device (prefer a stable /dev/serial/by-id path)",
    )
    parser.add_argument("--baudrate", type=int, default=115200)
    parser.add_argument("--prompt", default=PROMPT_DEFAULT)
    parser.add_argument("--timeout", type=float, default=60.0, help="Per-U-Boot-command timeout")
    parser.add_argument("--idle", type=float, default=0.5)
    parser.add_argument("--log", help="Optional combined serial/XSDB transcript")
    parser.add_argument("--loadaddr", default=LOADADDR_DEFAULT)
    parser.add_argument("--verifyaddr", default=VERIFYADDR_DEFAULT)
    parser.add_argument("--mmc-dev", type=int, default=0)
    parser.add_argument("--mmc-hwpart", type=int, default=0)
    parser.add_argument("--erase", action="store_true")
    parser.add_argument("--verify-readback", action="store_true")
    parser.add_argument("--reset-after", action="store_true")
    parser.add_argument("--xsdb", default="xsdb", help="XSDB executable path")
    parser.add_argument(
        "--xsdb-script",
        type=Path,
        default=Path(__file__).with_name("xsdb_load_data.tcl"),
        help="TCL helper used to halt A53, download one chunk, and resume U-Boot",
    )
    parser.add_argument("--hw-server", help="Optional XSDB hw_server URL")
    parser.add_argument("--a53-target", default=DEFAULT_A53_TARGET)
    parser.add_argument("--xsdb-timeout", type=float, default=600.0, help="Per-chunk XSDB timeout")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def validate_chunk_files(manifest: dict[str, Any], chunk_dir: Path) -> None:
    root = chunk_dir.resolve()
    for chunk in manifest["chunks"]:
        filename = str(chunk["filename"])
        if Path(filename).name != filename:
            raise ValueError(f"chunk filename must not contain a path: {filename}")
        path = (root / filename).resolve()
        if path.parent != root:
            raise ValueError(f"chunk escapes chunk directory: {filename}")
        if not path.is_file():
            raise FileNotFoundError(path)
        expected_size = int(chunk["padded_size_bytes"])
        if path.stat().st_size != expected_size:
            raise ValueError(
                f"chunk {filename} has size {path.stat().st_size}; expected {expected_size}"
            )
        expected_sha256 = str(chunk.get("sha256", "")).lower()
        if len(expected_sha256) != 64:
            raise ValueError(f"chunk {filename} has no valid SHA-256 in the manifest")
        digest_state = hashlib.sha256()
        with path.open("rb") as handle:
            while block := handle.read(1024 * 1024):
                digest_state.update(block)
        digest = digest_state.hexdigest()
        if digest != expected_sha256:
            raise ValueError(f"chunk {filename} SHA-256 mismatch")


def build_command_plan(
    manifest: dict[str, Any], options: JtagFlashOptions
) -> list[dict[str, str]]:
    commands: list[dict[str, str]] = [
        {"stage": "wake", "command": "version"},
        {
            "stage": "mmc",
            "command": f"mmc dev {options.mmc_dev} {options.mmc_hwpart}",
        },
        {"stage": "mmc", "command": "mmc rescan"},
    ]
    if options.erase:
        padded_blocks = int(manifest["image"]["padded_block_count"])
        commands.append(
            {"stage": "erase", "command": f"mmc erase 0x0 0x{padded_blocks:x}"}
        )

    for chunk in manifest["chunks"]:
        filename = str(chunk["filename"])
        padded_size = int(chunk["padded_size_bytes"])
        block_count = int(chunk["block_count"])
        start_block = int(chunk["emmc_start_block"])
        expected_crc = str(chunk["crc32"]).lower()
        commands.extend(
            [
                {
                    "stage": f"chunk-{chunk['index']}",
                    "host_load": str(options.chunk_dir / filename),
                    "address": options.loadaddr,
                    "size_bytes": str(padded_size),
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


def build_xsdb_command(
    *,
    xsdb: str,
    script: Path,
    data_file: Path,
    address: str,
    a53_target: str,
    hw_server: str | None,
) -> list[str]:
    command = [
        xsdb,
        str(script),
        "-file",
        str(data_file),
        "-address",
        address,
        "-a53-target",
        a53_target,
    ]
    if hw_server:
        command.extend(["-hw-server", hw_server])
    return command


def run_plan(
    plan: list[dict[str, str]],
    *,
    device: str,
    baudrate: int,
    prompt: str,
    timeout: float,
    idle: float,
    log_path: str | None,
    xsdb: str,
    xsdb_script: Path,
    a53_target: str,
    hw_server: str | None,
    xsdb_timeout: float,
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
                if prompt_bytes not in baseline:
                    ser.write(b"\r")
                    time.sleep(0.1)
                    baseline += _read_until_prompt(ser, prompt_bytes, timeout, log_handle)
                if prompt_bytes not in baseline:
                    print(f"error: prompt not found before stage: {step['stage']}", file=sys.stderr)
                    return 2

                if "host_load" in step:
                    command = build_xsdb_command(
                        xsdb=xsdb,
                        script=xsdb_script,
                        data_file=Path(step["host_load"]),
                        address=step["address"],
                        a53_target=a53_target,
                        hw_server=hw_server,
                    )
                    banner = "HOST: " + " ".join(shlex.quote(part) for part in command)
                    _write_banner(log_handle, banner)
                    print(f"\n>>> {banner}")
                    try:
                        result = subprocess.run(
                            command,
                            check=False,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT,
                            text=True,
                            timeout=xsdb_timeout,
                        )
                    except (OSError, subprocess.TimeoutExpired) as exc:
                        print(f"error: XSDB data load failed: {exc}", file=sys.stderr)
                        return 3
                    if result.stdout:
                        print(result.stdout, end="")
                        if log_handle is not None:
                            log_handle.write(result.stdout)
                            log_handle.flush()
                    if result.returncode != 0:
                        print(
                            f"error: XSDB data load returned {result.returncode}",
                            file=sys.stderr,
                        )
                        return 3
                    baseline = b""
                    continue

                command_text = step["command"]
                _write_banner(log_handle, command_text)
                print(f"\n>>> {command_text}")
                ser.write(command_text.encode("ascii") + b"\r")
                if step.get("no_prompt") == "true":
                    return 0
                reply = _read_until_prompt(ser, prompt_bytes, timeout, log_handle)
                sys.stdout.buffer.write(reply)
                sys.stdout.buffer.flush()
                if prompt_bytes not in reply:
                    print(
                        f"error: timed out waiting for prompt after: {command_text}",
                        file=sys.stderr,
                    )
                    return 4
                text = reply.decode("utf-8", errors="replace")
                if any(pattern in text for pattern in BAD_PATTERNS):
                    print(
                        f"error: U-Boot reported a failure during: {command_text}",
                        file=sys.stderr,
                    )
                    return 5
                if "expect_crc32" in step and _crc32_value(text) != step["expect_crc32"]:
                    print(
                        f"error: CRC mismatch during {command_text}; expected {step['expect_crc32']}",
                        file=sys.stderr,
                    )
                    return 6
                baseline = reply
            return 0
    finally:
        if log_handle is not None:
            log_handle.close()


def main() -> int:
    args = parse_args()
    chunk_dir = (args.chunk_dir or args.manifest.parent).resolve()
    options = JtagFlashOptions(
        manifest=args.manifest,
        chunk_dir=chunk_dir,
        loadaddr=args.loadaddr,
        verifyaddr=args.verifyaddr,
        mmc_dev=args.mmc_dev,
        mmc_hwpart=args.mmc_hwpart,
        erase=args.erase,
        verify_readback=args.verify_readback,
        reset_after=args.reset_after,
    )
    try:
        manifest = load_manifest(args.manifest)
        validate_chunk_files(manifest, chunk_dir)
        if not args.xsdb_script.is_file():
            raise FileNotFoundError(args.xsdb_script)
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
        xsdb=args.xsdb,
        xsdb_script=args.xsdb_script,
        a53_target=args.a53_target,
        hw_server=args.hw_server,
        xsdb_timeout=args.xsdb_timeout,
    )


if __name__ == "__main__":
    raise SystemExit(main())
