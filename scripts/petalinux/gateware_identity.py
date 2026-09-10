#!/usr/bin/env python3
"""Bind build-declared identity to source and exported bytes, never infer from a name.

This is provenance/integrity evidence, not bitstream decoding, authentication,
or live FPGA readback. Capture before synthesis; seal only after routed checks.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import sys

INPUT_KEYS = {"schema_version", "magic", "abi", "variant", "build_id", "build_sha",
              "source_sha256", "vivado_version"}
SEALED_KEYS = INPUT_KEYS | {"binary_sha256", "xsa_sha256", "snapshot_report_sha256"}
REPORT_NAME = "post_route_timestamp_snapshot.rpt"


def require(ok, message):
    if not ok:
        raise ValueError(message)


def digest(path):
    require(path.is_file() and path.stat().st_size > 0, "Missing/empty evidence file")
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def read_small(path, limit):
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    require(len(data) <= limit, "Oversized metadata/source/report")
    return data


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate metadata key")
        result[key] = value
    return result


def read_record(path, sealed=False):
    record = json.loads(read_small(path, 16384), object_pairs_hook=unique_pairs)
    require(type(record) is dict and set(record) == (SEALED_KEYS if sealed else INPUT_KEYS), "Unexpected metadata fields")
    for name in ("schema_version", "magic", "abi", "variant", "build_id"):
        require(type(record[name]) is int, "Identity word is not an integer")
    require(record["schema_version"] == 1 and record["magic"] == 0x44415048 and
            record["abi"] in (0x20000, 0x20001, 0x20002) and record["variant"] in (1, 2), "Unsupported identity contract")
    sha = record["build_sha"]
    require(type(sha) is str and re.fullmatch(r"[0-9a-f]{7}", sha) and int(sha, 16) != 0 and
            record["build_id"] == int(sha, 16), "Build stamp mismatch")
    require(record["vivado_version"] == "2026.1", "Unqualified build tool version")
    for key in ("source_sha256", "binary_sha256", "xsa_sha256", "snapshot_report_sha256"):
        if key not in record:
            continue
        value = record[key]
        if key == "snapshot_report_sha256" and record["abi"] == 0x20000:
            require(value is None, "ABI 2.0 must not claim snapshot timing")
        else:
            require(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value), "Invalid evidence digest")
    return record


def source_identity(source):
    raw = read_small(source, 4 * 1024 * 1024)
    text = re.sub(r"--[^\n]*", "", raw.decode("utf-8"))
    result = {"source_sha256": hashlib.sha256(raw).hexdigest()}
    for key, constant in (("magic", "FW_ID_MAGIC_C"), ("abi", "FW_ABI_VERSION_C"), ("variant", "FW_VARIANT_ID_C")):
        require(len(re.findall(r"\bconstant\s+" + constant + r"\s*:", text, re.I)) == 1,
                "Duplicate/missing identity declaration")
        values = re.findall(r"\bconstant\s+" + constant + r'\s*:\s*std_logic_vector\s*\(31\s+downto\s+0\)\s*:=\s*X"([0-9a-f]{8})"\s*;', text, re.I)
        require(len(values) == 1, "Missing/ambiguous literal identity constant")
        result[key] = int(values[0], 16)
    return result


def write_record(path, record):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(record, stream, indent=2, sort_keys=True)
        stream.write("\n")


def check_report(path, abi=0x20001):
    require(abi in (0x20001, 0x20002), "Unsupported diagnostic timing ABI")
    widths = {"local_snapshot": 65, "external_snapshot": 65}
    header = "Native timestamp payload timing: per-bit routed checks"
    if abi == 0x20002:
        widths["protocol_snapshot"] = 40
        header = "Native diagnostic payload timing: per-bit routed checks"
    lines = read_small(path, 256 * 1024).decode("utf-8").splitlines()
    require(len(lines) == sum(widths.values()) + 1 and lines[0] == header,
            "Missing/incomplete timestamp routed report")
    seen, parents = set(), set()
    for line in lines[1:]:
        match = re.fullmatch(r"(.+)/(local_snapshot|external_snapshot|protocol_snapshot)/destination_data_reg\[([0-9]+)\] requirement_ns=(\S+) slack_ns=(\S+)", line)
        require(match is not None, "Unexpected timestamp timing row")
        parent, mailbox, bit, requirement, slack = match.groups()
        key = (mailbox, int(bit))
        require(mailbox in widths and key not in seen and 0 <= int(bit) < widths[mailbox], "Duplicate/invalid timestamp payload bit")
        requirement, slack = float(requirement), float(slack)
        require(math.isfinite(requirement) and requirement > 0 and math.isfinite(slack) and slack >= 0,
                "Non-finite/failing timestamp timing")
        seen.add(key)
        parents.add(parent)
    require(len(seen) == sum(widths.values()) and len(parents) == 1, "Unexpected mailbox population")
    return digest(path)


def capture(source, sha, version, output, build_word):
    require(re.fullmatch(r"[0-9a-f]{7}", sha) is not None, "Build SHA must be exactly seven lowercase hexadecimal characters")
    word = re.fullmatch(r"(?:32'[hH]|0[xX])([0-9a-fA-F]{1,8})", build_word)
    if word:
        build_id = int(word.group(1), 16)
    else:
        require(re.fullmatch(r"[0-9]{1,10}", build_word) is not None, "Unsupported build generic representation")
        build_id = int(build_word, 10)
    require(build_id == int(sha, 16), "BD build generic does not match declared stamp")
    record = dict(schema_version=1, build_sha=sha, build_id=int(sha, 16), vivado_version=version,
                  **source_identity(source))
    # Validate without creating a possibly misleading record on failure.
    require(record["magic"] == 0x44415048 and record["abi"] in (0x20000, 0x20001, 0x20002) and
            record["variant"] in (1, 2) and record["build_id"] != 0 and version == "2026.1", "Unsupported build identity/tool")
    write_record(output, record)


def seal(record_path, source, binary, xsa, report, output):
    record = read_record(record_path)
    require(all(record[key] == value for key, value in source_identity(source).items()), "Identity source changed after capture")
    prefix = "daphne_selftrigger" if record["variant"] == 1 else "daphne_fullstream"
    require(binary.name == f"{prefix}_{record['build_sha']}.bin" and xsa.name == f"{prefix}_{record['build_sha']}.xsa",
            "Export names disagree with captured build identity")
    record.update(binary_sha256=digest(binary), xsa_sha256=digest(xsa),
                  snapshot_report_sha256=check_report(report, record["abi"]) if record["abi"] != 0x20000 else None)
    write_record(output, record)


def verify(record_path, binary, report, sha, variant, xsa=None):
    record = read_record(record_path, sealed=True)
    require(record["build_sha"] == sha and record["variant"] == variant, "Bundle selection disagrees with identity metadata")
    require(record["binary_sha256"] == digest(binary), "Binary does not match sealed identity")
    if xsa is not None:
        require(record["xsa_sha256"] == digest(xsa), "XSA does not match sealed identity")
    if record["abi"] != 0x20000:
        require(record["snapshot_report_sha256"] == check_report(report, record["abi"]), "Timestamp report does not match sealed identity")
    return record["abi"] & 0xffff


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("capture")
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--build-sha", required=True)
    p.add_argument("--build-word", required=True)
    p.add_argument("--vivado-version", required=True)
    p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("seal")
    for arg in ("record", "source", "binary", "xsa", "report", "output"):
        p.add_argument("--" + arg, type=Path, required=True)
    p = sub.add_parser("verify")
    for arg in ("record", "binary", "report"):
        p.add_argument("--" + arg, type=Path, required=True)
    p.add_argument("--xsa", type=Path)
    p.add_argument("--build-sha", required=True)
    p.add_argument("--variant", type=int, choices=(1, 2), required=True)
    args = parser.parse_args()
    try:
        if args.command == "capture":
            capture(args.source, args.build_sha, args.vivado_version, args.output, args.build_word)
        elif args.command == "seal":
            seal(args.record, args.source, args.binary, args.xsa, args.report, args.output)
        else:
            print(verify(args.record, args.binary, args.report, args.build_sha, args.variant, args.xsa))
    except (OSError, ValueError, UnicodeError):
        print("Gateware identity evidence rejected; inspect source, build stamp and artifact/report integrity", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
