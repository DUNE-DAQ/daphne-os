#!/usr/bin/env python3
"""Check repository Markdown for portable links and stable heading style."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

DEFAULT_ROOT = Path(__file__).resolve().parents[1]
NUMBERED_HEADING = re.compile(
    r"^\s{0,3}#{1,6}\s+\d+(?:\.\d+)*(?:[.)])?\s+"
)
DEVELOPER_PATH = re.compile(
    r"(?:/Users/[^/\s]+|/home/(?:marroyav|neutrino)/|/tmp/(?:arroyave|marroyav|neutrino)/)"
)
LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
FENCE = re.compile(r"^\s*((?:\x60){3,}|~{3,})")


def markdown_files(root: Path) -> list[Path]:
    result = subprocess.run(
        [
            "git",
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
            "--",
            "*.md",
        ],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
    )
    # The server is an unsquashed upstream import. Keep its documentation and
    # source tree unchanged; this checker owns only daphne-os documentation.
    return [
        root / name.decode()
        for name in result.stdout.split(b"\0")
        if name and not name.startswith(b"daphne-server/")
    ]


def link_target(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("<"):
        end = raw.find(">")
        return raw[1:end] if end >= 0 else raw[1:]
    return raw.split(maxsplit=1)[0]


def main() -> int:
    if len(sys.argv) > 2:
        print(f"Usage: {Path(sys.argv[0]).name} [REPOSITORY]", file=sys.stderr)
        return 2

    root = Path(sys.argv[1]).resolve() if len(sys.argv) == 2 else DEFAULT_ROOT
    errors: list[str] = []
    for path in markdown_files(root):
        relative = path.relative_to(root)
        in_fence = False
        fence_char = ""
        fence_length = 0
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if DEVELOPER_PATH.search(line):
                errors.append(
                    f"{relative}:{line_number}: replace the developer-local path"
                )
            fence = FENCE.match(line)
            if fence:
                marker = fence.group(1)
                if not in_fence:
                    in_fence = True
                    fence_char = marker[0]
                    fence_length = len(marker)
                elif marker[0] == fence_char and len(marker) >= fence_length:
                    in_fence = False
                continue
            if in_fence:
                continue
            if NUMBERED_HEADING.match(line):
                errors.append(
                    f"{relative}:{line_number}: use an unnumbered heading"
                )
            for match in LINK.finditer(line):
                target = unquote(link_target(match.group(1)))
                if (
                    not target
                    or target.startswith("#")
                    or re.match(r"^[a-z][a-z0-9+.-]*:", target, re.IGNORECASE)
                ):
                    continue
                target = target.split("#", 1)[0].split("?", 1)[0]
                if not target:
                    continue
                candidate = (path.parent / target).resolve()
                if not candidate.exists() and not candidate.suffix:
                    candidate = candidate.with_suffix(".md")
                if not candidate.exists():
                    errors.append(
                        f"{relative}:{line_number}: missing link target {target!r}"
                    )

    if errors:
        print("\n".join(errors))
        print(f"RESULT: FAIL - {len(errors)} documentation problem(s)")
        return 1
    print("RESULT: PASS - Markdown links and headings are consistent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
