#!/usr/bin/env python3
"""Verify the unsquashed server import and every archived source reference."""

import json
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def git(*args: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True).strip()


def main() -> int:
    record = json.loads((ROOT / "docs/daphne-server-history.json").read_text())
    source_commits = set(record["commits"])
    if len(source_commits) != record["commit_count"] or any(
        not re.fullmatch(r"[0-9a-f]{40}", value) for value in source_commits
    ):
        raise ValueError("Invalid original commit inventory")
    actual_refs = []
    for item in record["refs"]:
        destination = item["destination"]
        if not re.fullmatch(r"refs/(?:heads|tags)/archive/daphneZMQ/[A-Za-z0-9_./-]+", destination):
            raise ValueError("Invalid archived reference")
        candidates = [destination]
        if destination.startswith("refs/heads/"):
            candidates.append(destination.replace("refs/heads/", "refs/remotes/origin/", 1))
        for candidate in candidates:
            result = subprocess.run(
                ["git", "-C", str(ROOT), "show-ref", "--verify", "--hash", candidate],
                text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            )
            if result.returncode == 0:
                if result.stdout.strip() != item["object"]:
                    raise ValueError(f"Archived reference changed: {candidate}")
                actual_refs.append(candidate)
                break
        else:
            raise ValueError(f"Missing archived reference: {destination}; fetch all branches/tags")
    reachable = set(git("rev-list", *actual_refs).splitlines())
    missing = source_commits - reachable
    if missing:
        raise ValueError(f"Original server commits not reachable: {len(missing)}")
    import_commit = record["import_commit"]
    subprocess.run(
        ["git", "-C", str(ROOT), "merge-base", "--is-ancestor", import_commit, "HEAD"],
        check=True,
    )
    if git("rev-parse", f"{import_commit}:{record['import_prefix']}") != record["active_source_tree"]:
        raise ValueError("Original imported server tree does not match its provenance")
    if git("rev-parse", f"{record['active_source_commit']}^{{tree}}") != record["active_source_tree"]:
        raise ValueError("Original source commit/tree mismatch")
    print(f"Server history: PASS ({len(source_commits)} original commits, {len(actual_refs)} refs)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as exc:
        print(f"Server history: FAIL ({exc})", file=sys.stderr)
        sys.exit(1)
