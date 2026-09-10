#!/usr/bin/env python3
"""Build a private, monitoring-only protobuf artifact from verified OKS evidence.

Inputs: a DNS-checked review, the same three source files, and copies of the
board's already approved .link/.network files. No DNS, SSH or hardware writes.
"""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import sys

from extract_oks_identity import IdentityError, extract_identity, ipv4, mac_address


def bounded_bytes(path, maximum=65536):
    with Path(path).open("rb") as source:
        data = source.read(maximum + 1)
    if not data or len(data) > maximum:
        raise IdentityError("Private input is empty or exceeds the size limit")
    return data


def no_duplicate_keys(items):
    result = {}
    for key, value in items:
        if key in result:
            raise IdentityError("Review JSON contains duplicate keys")
        result[key] = value
    return result


def read_review(path, source_root):
    try:
        review = json.loads(bounded_bytes(path), object_pairs_hook=no_duplicate_keys)
        files = [source["file"] for source in review["sources"]]
        if len(files) != 3:
            raise IdentityError("Expected the three explicit OKS source files")
        rebuilt = extract_identity(source_root, files, review["application_object_id"], review["board_object_id"])
        check = review["target_check"]
        actual = dict(review)
        actual["target_check"] = {"status": "not_checked"}
        if actual != rebuilt:
            raise IdentityError("Review does not match a fresh extraction of the selected source bytes")
        if (check["status"] != "matched" or type(check["observed_host_unix_ns"]) is not int or
                check["observed_host_unix_ns"] <= 0 or not check["target_host"]):
            raise IdentityError("Review needs an explicit successful target DNS comparison")
        ipv4(check["resolved_ipv4"])
    except IdentityError:
        raise
    except (ValueError, KeyError, TypeError, UnicodeError):
        raise IdentityError("Malformed review input; private values suppressed") from None
    return review


def baseline_file(path):
    data = bounded_bytes(path)
    result = {}
    section = None
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeError:
        raise IdentityError("Network baseline must be UTF-8 text") from None
    for line in lines:
        line = line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue
        if section is None or "=" not in line or line.endswith("\\"):
            raise IdentityError("Unsupported network baseline syntax; nothing was applied")
        key, value = line.split("=", 1)
        result.setdefault((section, key.strip()), []).append(value.strip())
    return result, {"file": Path(path).name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def one(values, section, key):
    entries = values.get((section, key), [])
    if len(entries) != 1 or not entries[0]:
        raise IdentityError("Required network baseline field is missing or ambiguous")
    return entries[0]


def prepare(review, link_path, network_path, interface, h):
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,15}", interface) or interface == "lo":
        raise IdentityError("Invalid management interface name")
    link, link_source = baseline_file(link_path)
    network, network_source = baseline_file(network_path)
    match = re.fullmatch(r"platform-([0-9a-f]{1,16})\.ethernet", one(link, "Match", "Path"))
    if not match or one(network, "Match", "Name") != interface:
        raise IdentityError("Approved baseline is not bound to the selected physical management interface")
    mac = mac_address(one(link, "Link", "MACAddress"))
    if one(link, "Link", "MACAddressPolicy") != "none" or one(network, "Network", "DHCP") != "no":
        raise IdentityError("This baseline importer requires the existing pinned MAC/static IPv4 profile")
    addresses = network.get(("Network", "Address"), [])
    cidrs = []
    try:
        for value in addresses:
            address = ipaddress.IPv4Interface(value)
            if "/" not in value or str(address) != value:
                raise ValueError()
            ipv4(str(address.ip))
            cidrs.append(str(address))
    except ValueError:
        raise IdentityError("Invalid/non-canonical IPv4 baseline address") from None
    if not cidrs or len(cidrs) > 16 or len(set(cidrs)) != len(cidrs):
        raise IdentityError("IPv4 baseline addresses are missing, duplicated or excessive")
    target = review["target_check"]["resolved_ipv4"]
    if target not in {value.split("/")[0] for value in cidrs}:
        raise IdentityError("The verified target address does not belong to the approved baseline")
    result = h.BoardIdentityAssignmentFile(format_version=1)
    assignments = result.assignments
    assignments.application_object_id = review["application_object_id"]
    assignments.board_object_id = review["board_object_id"]
    assignments.source_revision_sha256 = review["source_revision_sha256"]
    for source in review["sources"]:
        assignments.sources.add(**source)

    def fill(value, target, reason):
        if value is None:
            target.unavailable_reason = reason
            return
        if isinstance(value["value"], list):
            target.values.extend(value["value"])
        else:
            target.value = value["value"]
        source = dict(value["source"])
        source["object_class"] = source.pop("class")
        target.source.CopyFrom(h.IdentityValueSource(**source))

    for name in ("crate_id", "slot_id", "detector_id"):
        fill(review["placement"][name], getattr(assignments, name), "No explicit placement assignment")
    for name in ("management_address", "management_mac_address", "timing_endpoint_address"):
        fill(review[name], getattr(assignments, name), "No established explicit assignment source")
    for entry in review["hermes_interfaces"]:
        target_link = assignments.hermes_interfaces.add()
        for name in ("connection_object_id", "sender_object_id", "interface_object_id"):
            setattr(target_link, name, entry[name])
        target_link.stream_object_ids.extend(entry["stream_object_ids"])
        target_link.geo_object_ids.extend(entry["geo_object_ids"])
        for name in ("control_host", "mac_address", "ip_addresses", "hermes_link_id", "physical_connector"):
            fill(entry[name], getattr(target_link, name), "No approved assignment or physical-link mapping")
    assignments.limitations.extend(review["unresolved"])
    binding = result.binding
    binding.interface_name = interface
    binding.controller_node = "ethernet@" + match[1]
    binding.expected_mac_address = mac
    binding.expected_ipv4_cidrs.extend(sorted(cidrs))
    binding.approved_link_file.CopyFrom(h.IdentitySourceFile(**link_source))
    binding.approved_network_file.CopyFrom(h.IdentitySourceFile(**network_source))
    return result


def write_artifact(path, artifact):
    payload = artifact.SerializeToString(deterministic=True)
    if not payload or len(payload) > 65536:
        raise IdentityError("Identity artifact exceeds bounded size")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(payload).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-file", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--approved-link-file", required=True, type=Path)
    parser.add_argument("--approved-network-file", required=True, type=Path)
    parser.add_argument("--management-interface", required=True)
    parser.add_argument("--proto-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        sys.path.insert(0, str(args.proto_dir.resolve()))
        import daphneV3_high_level_confs_pb2 as h
        review = read_review(args.review_file, args.source_root)
        artifact = prepare(review, args.approved_link_file, args.approved_network_file, args.management_interface, h)
        digest = write_artifact(args.output, artifact)
    except IdentityError as error:
        print(f"Identity preparation refused: {error}", file=sys.stderr)
        return 1
    except (OSError, ValueError, TypeError, KeyError, ImportError, AttributeError):
        print("Identity preparation failed; check files and matching protobuf runtime (private details suppressed)", file=sys.stderr)
        return 1
    print(json.dumps({"artifact_sha256": digest, "source_revision_sha256": review["source_revision_sha256"],
                      "network_values": "redacted", "mode": "monitoring_only", "requires_board_identity_probe": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
