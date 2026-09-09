#!/usr/bin/env python3
"""Shared, hardware-free validation for collected and deployed image bundles."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from pathlib import Path, PurePosixPath
import re
import sys


REQUIRED_BUNDLE_PATHS = frozenset({
    "boot/Image",
    "boot/system.dtb",
    "boot/ramdisk.cpio.gz.u-boot",
    "rootfs/rootfs.ext4",
})
CHECKSUM_RE = re.compile(r"^([0-9a-fA-F]{64}) ([ *])(.+)$")


class BundleError(ValueError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_directory(value: str, base: Path, label: str) -> Path:
    try:
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = base / path
        path = path.resolve(strict=True)
    except (OSError, ValueError, RuntimeError) as exc:
        raise BundleError(f"{label} does not exist: {value}") from exc
    if not path.is_dir():
        raise BundleError(f"{label} is not a directory: {value}")
    return path


def normalize_manifest_path(raw_name: str, bundle: Path, line_number: int) -> tuple[str, Path]:
    relative = PurePosixPath(raw_name)
    if relative.is_absolute() or ".." in relative.parts or "\\" in raw_name:
        raise BundleError(
            f"unsafe path in {bundle / 'SHA256SUMS'} line {line_number}: {raw_name!r}"
        )
    normalized = str(relative)
    if normalized in {"", "."}:
        raise BundleError(f"empty path in {bundle / 'SHA256SUMS'} line {line_number}")
    candidate = bundle.joinpath(*relative.parts)
    if any(bundle.joinpath(*relative.parts[:i]).is_symlink()
           for i in range(1, len(relative.parts) + 1)) or not candidate.is_file():
        raise BundleError(f"missing regular bundle artifact (or symlink): {candidate}")
    try:
        candidate.resolve(strict=True).relative_to(bundle)
    except (OSError, ValueError, RuntimeError) as exc:
        raise BundleError(f"bundle manifest path escapes bundle: {raw_name}") from exc
    return normalized, candidate


def verify_bundle(bundle_arg: Path, *, require_wic: bool = False) -> tuple[Path, dict[str, object]]:
    bundle = resolve_directory(str(bundle_arg), Path.cwd(), "release bundle")
    manifest = bundle / "SHA256SUMS"
    if manifest.is_symlink() or not manifest.is_file():
        raise BundleError(f"release bundle has no SHA256SUMS: {bundle}")
    manifest_bytes = manifest.read_bytes()
    verified: dict[str, str] = {}
    for line_number, line in enumerate(manifest_bytes.decode("utf-8").splitlines(), start=1):
        if not line:
            continue
        match = CHECKSUM_RE.fullmatch(line)
        if not match:
            raise BundleError(f"malformed checksum record in {manifest} line {line_number}")
        expected, _, raw_name = match.groups()
        normalized, artifact = normalize_manifest_path(raw_name, bundle, line_number)
        if normalized in verified:
            raise BundleError(f"duplicate bundle checksum path: {normalized}")
        actual = sha256_file(artifact)
        if actual != expected.lower():
            raise BundleError(f"bundle checksum mismatch: {normalized}")
        verified[normalized] = actual

    required = REQUIRED_BUNDLE_PATHS | ({"rootfs/rootfs.wic.gz"} if require_wic else set())
    missing = sorted(required - set(verified))
    if missing:
        raise BundleError(
            f"bundle manifest does not cover required artifacts: {', '.join(missing)}"
        )
    return bundle, {
        "manifest": str(manifest),
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "verified_utc": utc_now(),
        "verified_entries": len(verified),
        "required_entries": sorted(required),
        "artifacts_sha256": verified,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--require-wic", action="store_true", help="also require the whole-eMMC image")
    args = parser.parse_args()
    try:
        _, evidence = verify_bundle(args.bundle, require_wic=args.require_wic)
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(f"Bundle verification: PASS ({evidence['verified_entries']} manifest entries)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
