#!/usr/bin/env python3
"""Reject secret findings except byte-verified public ZeroMQ test fixtures.

Never print matches, secret values, author details, or report payloads.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys


FIXTURES = {
    "third_party/zeromq-4.3.4/doc/zmq_curve.7": (
        "82d8c7e238b0e820c1a7e16844074d073eafa633974ffd93cfa710a8fb5ad29a",
        {("generic-api-key", 63), ("generic-api-key", 81)},
    ),
    "third_party/zeromq-4.3.4/tests/test_wss_transport.cpp": (
        "3cc4eec529ab24f12f83ea80b203f8a302557e768e13018fa894bbc0d128bfe1",
        {("private-key", 38)},
    ),
}


def is_public_fixture(finding: dict, root: Path) -> bool:
    path = finding.get("File", "")
    if not isinstance(path, str):
        return False
    candidate = Path(path)
    if candidate.is_absolute():
        try:
            path = str(candidate.resolve().relative_to(root.resolve()))
        except ValueError:
            return False
    fixture_path = path.removeprefix("daphne-server/")
    if fixture_path not in FIXTURES:
        return False
    expected_sha, expected_locations = FIXTURES[fixture_path]
    if (finding.get("RuleID"), finding.get("StartLine")) not in expected_locations:
        return False
    commit = finding.get("Commit", "")
    if commit:
        if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
            return False
        result = subprocess.run(
            ["git", "-C", str(root), "show", f"{commit}:{path}"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        if result.returncode:
            return False
        data = result.stdout
    else:
        resolved = (root / path).resolve()
        if not resolved.is_relative_to(root.resolve()):
            return False
        try:
            data = resolved.read_bytes()
        except OSError:
            return False
    return hashlib.sha256(data).hexdigest() == expected_sha


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--repository", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    try:
        findings = json.loads(args.report.read_text())
        if not isinstance(findings, list) or any(not isinstance(item, dict) for item in findings):
            raise ValueError("Expected a findings list")
        rejected = [item for item in findings if not is_public_fixture(item, args.repository)]
    except (ValueError, TypeError, OSError):
        print("Credential audit: FAIL (invalid report or unreadable source)", file=sys.stderr)
        return 1
    for item in rejected:
        print(json.dumps({
            "blocked_rule": item.get("RuleID"), "file": item.get("File"),
            "line": item.get("StartLine"), "commit": item.get("Commit"),
        }), file=sys.stderr)
    if rejected:
        print(f"Credential audit: FAIL ({len(rejected)} finding(s) need review)", file=sys.stderr)
        return 1
    print(f"Credential audit: PASS ({len(findings)} byte-verified public fixture occurrence(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
