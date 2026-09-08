#!/usr/bin/env python3
"""Prepare block-aligned WIC chunks for U-Boot eMMC flashing."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import shutil
import zlib
from pathlib import Path
from typing import BinaryIO


BLOCK_SIZE = 512
DEFAULT_CHUNK_SIZE = 64 * 1024 * 1024


def parse_size(value: str) -> int:
    text = value.strip().lower()
    scale = 1
    for suffix, multiplier in (
        ("gib", 1024**3),
        ("gb", 1024**3),
        ("mib", 1024**2),
        ("mb", 1024**2),
        ("kib", 1024),
        ("kb", 1024),
    ):
        if text.endswith(suffix):
            scale = multiplier
            text = text[: -len(suffix)]
            break
    try:
        size = int(text, 0) * scale
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid size: {value!r}") from exc
    if size <= 0:
        raise argparse.ArgumentTypeError("size must be positive")
    if size % BLOCK_SIZE:
        raise argparse.ArgumentTypeError(f"size must be a multiple of {BLOCK_SIZE}")
    return size


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Input .wic or .wic.gz image")
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Chunk/manifest directory (local for JTAG or server-visible for TFTP)",
    )
    parser.add_argument(
        "--name",
        default=None,
        help="Chunk filename prefix. Default derives from the input filename.",
    )
    parser.add_argument(
        "--chunk-size",
        type=parse_size,
        default=DEFAULT_CHUNK_SIZE,
        help="Chunk size, block aligned. Default: 64MiB.",
    )
    parser.add_argument(
        "--manifest",
        default="manifest.json",
        help="Manifest filename under --output-dir. Default: manifest.json.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow replacing an existing manifest and chunk files with the same prefix.",
    )
    return parser.parse_args()


def open_input(path: Path) -> BinaryIO:
    if path.name.endswith(".gz"):
        return gzip.open(path, "rb")
    return path.open("rb")


def image_name(path: Path) -> str:
    name = path.name
    if name.endswith(".gz"):
        name = name[:-3]
    if name.endswith(".wic"):
        name = name[:-4]
    return "".join(char if char.isalnum() or char in "._-" else "_" for char in name)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        shutil.copyfileobj(handle, _HashWriter(digest))
    return digest.hexdigest()


class _HashWriter:
    def __init__(self, digest: "hashlib._Hash") -> None:
        self.digest = digest

    def write(self, data: bytes) -> int:
        self.digest.update(data)
        return len(data)


def prepare_chunks(
    input_path: Path,
    output_dir: Path,
    *,
    name: str,
    chunk_size: int,
    manifest_name: str,
    force: bool,
) -> dict[str, object]:
    if chunk_size % BLOCK_SIZE:
        raise ValueError(f"chunk size must be a multiple of {BLOCK_SIZE}")
    if not input_path.is_file():
        raise FileNotFoundError(input_path)

    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / manifest_name
    existing_chunks = sorted(output_dir.glob(f"{name}.part*"))
    if not force and (manifest_path.exists() or existing_chunks):
        raise FileExistsError(
            f"{output_dir} already contains {manifest_name} or {name}.part*; use --force"
        )

    chunks: list[dict[str, object]] = []
    image_digest = hashlib.sha256()
    image_size = 0
    offset = 0
    index = 0

    with open_input(input_path) as source:
        while True:
            payload = source.read(chunk_size)
            if not payload:
                break
            data_size = len(payload)
            image_digest.update(payload)
            image_size += data_size

            padded_size = _align(data_size, BLOCK_SIZE)
            if padded_size != data_size:
                payload += bytes(padded_size - data_size)

            chunk_name = f"{name}.part{index:04d}"
            chunk_path = output_dir / chunk_name
            chunk_path.write_bytes(payload)

            chunks.append(
                {
                    "index": index,
                    "filename": chunk_name,
                    "image_offset_bytes": offset,
                    "emmc_start_block": offset // BLOCK_SIZE,
                    "data_size_bytes": data_size,
                    "padded_size_bytes": padded_size,
                    "block_count": padded_size // BLOCK_SIZE,
                    "crc32": f"{zlib.crc32(payload) & 0xFFFFFFFF:08x}",
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            )
            offset += padded_size
            index += 1

    if not chunks:
        raise ValueError(f"input image is empty: {input_path}")

    manifest = {
        "contract": "daphne.uboot-wic-flash-manifest",
        "version": 1,
        "block_size_bytes": BLOCK_SIZE,
        "chunk_size_bytes": chunk_size,
        "image": {
            "source": str(input_path),
            "source_sha256": sha256_file(input_path),
            "raw_size_bytes": image_size,
            "raw_sha256": image_digest.hexdigest(),
            "padded_size_bytes": offset,
            "padded_block_count": offset // BLOCK_SIZE,
        },
        "chunks": chunks,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def _align(value: int, alignment: int) -> int:
    return int(math.ceil(value / alignment) * alignment)


def main() -> int:
    args = parse_args()
    name = args.name or image_name(args.input)
    try:
        manifest = prepare_chunks(
            args.input,
            args.output_dir,
            name=name,
            chunk_size=args.chunk_size,
            manifest_name=args.manifest,
            force=args.force,
        )
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=__import__("sys").stderr)
        return 2
    manifest_path = args.output_dir / args.manifest
    print(json.dumps({"manifest": str(manifest_path), "chunks": len(manifest["chunks"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
