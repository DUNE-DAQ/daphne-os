#!/usr/bin/env python3
"""Small file operations shared by project setup and artifact collection."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile


STAGED_PATHS = (
    "recipes-apps/daphne-server/files/staged",
    "recipes-apps/daphne-server/daphne-server-version.inc",
    "recipes-firmware/daphne-overlay/files/staged",
    "recipes-firmware/daphne-overlay/daphne-overlay-version.inc",
)
PROFILE_DIR = "recipes-core/daphne-services/files"


def replace_block(text: str, begin: str, end: str, content: str) -> str:
    """Replace one complete managed block, refusing ambiguous/broken markers."""
    lines = text.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if line.rstrip("\r\n") == begin]
    ends = [i for i, line in enumerate(lines) if line.rstrip("\r\n") == end]
    block = begin + "\n" + content.rstrip("\n") + "\n" + end + "\n"
    if not starts and not ends:
        return text + ("\n" if text and not text.endswith("\n") else "") + "\n" + block
    if len(starts) != 1 or len(ends) != 1 or starts[0] >= ends[0]:
        raise ValueError(f"malformed managed block: {begin}")
    return "".join(lines[:starts[0]]) + block + "".join(lines[ends[0] + 1:])


def update_block(path: Path, begin: str, end: str, content: str) -> None:
    if path.is_symlink():
        raise ValueError(f"refusing to replace a symlinked config: {path}")
    updated = replace_block(path.read_text(), begin, end, content)
    with tempfile.TemporaryDirectory(prefix=".config-", dir=path.parent) as temporary:
        staged = Path(temporary) / path.name
        staged.write_text(updated)
        staged.chmod(path.stat().st_mode & 0o777)
        os.replace(staged, path)


def publish_directory(staged: Path, destination: Path, *, allow_symlink: bool = False,
                      marker: str | None = None) -> None:
    """Publish a prepared sibling directory; restore the old output on failure."""
    staged, destination = staged.absolute(), destination.absolute()
    if staged.is_symlink() or not staged.is_dir() or staged.parent != destination.parent:
        raise ValueError("publication requires a regular staging directory beside the destination")
    if staged == destination or destination.name in {"", ".", ".."}:
        raise ValueError("staging and destination must be distinct named directories")
    existed = destination.exists() or destination.is_symlink()
    if existed:
        if destination.is_symlink() and not allow_symlink:
            raise ValueError(f"refusing to replace a symlink: {destination}")
        if not destination.is_dir():
            raise ValueError(f"destination is not a directory: {destination}")
        if marker and not (destination / marker).is_file():
            raise ValueError(f"refusing to replace an output directory not created by this collector: {destination}")
    backup_dir = Path(tempfile.mkdtemp(prefix=f".{destination.name}.previous-", dir=destination.parent))
    backup = backup_dir / destination.name
    published = False
    try:
        if existed:
            os.replace(destination, backup)
        os.replace(staged, destination)
        published = True
    except BaseException:
        if (backup.exists() or backup.is_symlink()) and not destination.exists():
            os.replace(backup, destination)
        raise
    finally:
        # Never delete the last good output if restoring it failed.
        if backup.exists() or backup.is_symlink():
            if published:
                shutil.rmtree(backup_dir)
            else:
                print(f"Previous output retained for recovery: {backup}", file=sys.stderr)
        else:
            backup_dir.rmdir()


def refresh_layer(source: Path, destination: Path) -> None:
    """Refresh layer code, retaining this project's payloads and app bindings."""
    source = source.resolve(strict=True)
    if not source.is_dir():
        raise ValueError(f"layer source is not a directory: {source}")
    previous = destination.resolve(strict=True) if destination.exists() else None
    if destination.is_symlink() and previous is None:
        raise ValueError(f"broken layer symlink: {destination}")
    if previous == source and not destination.is_symlink():
        raise ValueError("cannot refresh the source checkout in place")
    if previous is not None and not previous.is_dir():
        raise ValueError(f"existing layer is not a directory: {destination}")
    with tempfile.TemporaryDirectory(prefix=".layer-refresh-", dir=destination.parent) as temporary:
        staged = Path(temporary) / "layer"
        shutil.copytree(source, staged, symlinks=True)
        if previous is not None:
            for relative in STAGED_PATHS:
                old = previous / relative
                if any(path.is_symlink() for path in (old, *old.parents)
                       if path != previous and previous in path.parents):
                    raise ValueError(f"symlink in staged inputs: {old}")
                if old.is_dir():
                    shutil.rmtree(staged / relative)
                    shutil.copytree(old, staged / relative, symlinks=True)
                elif old.is_file():
                    shutil.copy2(old, staged / relative)
            for mode in ("self-trigger", "full-stream"):
                relative = f"{PROFILE_DIR}/daphne-gateware-{mode}.conf"
                old = previous / relative
                if old.is_file():
                    apps = re.findall(r"^APP=([A-Za-z0-9_.-]+)$", old.read_text(), re.MULTILINE)
                    if len(apps) != 1:
                        raise ValueError(f"expected one APP binding in {old}")
                    target = staged / relative
                    updated, count = re.subn(r"^APP=.*$", "APP=" + apps[0], target.read_text(), flags=re.MULTILINE)
                    if count != 1:
                        raise ValueError(f"expected one APP binding in {target}")
                    target.write_text(updated)
        # Use a sibling for the rollback-capable publication operation.
        sibling = Path(tempfile.mkdtemp(prefix=".meta-daphne-ready-", dir=destination.parent))
        os.replace(staged, sibling)
        try:
            publish_directory(sibling, destination, allow_symlink=True)
        finally:
            if sibling.exists():
                shutil.rmtree(sibling)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    block = commands.add_parser("block")
    block.add_argument("path", type=Path)
    block.add_argument("begin")
    block.add_argument("end")
    content = block.add_mutually_exclusive_group(required=True)
    content.add_argument("--file", type=Path)
    content.add_argument("--text")
    layer = commands.add_parser("layer")
    layer.add_argument("source", type=Path)
    layer.add_argument("destination", type=Path)
    publish = commands.add_parser("publish")
    publish.add_argument("staged", type=Path)
    publish.add_argument("destination", type=Path)
    publish.add_argument("--marker", required=True)
    args = parser.parse_args()
    try:
        if args.command == "block":
            update_block(args.path, args.begin, args.end,
                         args.file.read_text() if args.file else args.text)
        elif args.command == "layer":
            refresh_layer(args.source, args.destination)
        else:
            publish_directory(args.staged, args.destination, marker=args.marker)
    except (ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
