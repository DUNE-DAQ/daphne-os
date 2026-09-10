#!/usr/bin/env python3
"""Extract explicit DAPHNE identity assignments for review; never configure hardware.

This is a deliberately limited OKS data reader, not an OKS schema/default/include
resolver. The three input files and application/board selectors are explicit.
Stdout is redacted. Private output is opt-in, exclusive-create, mode 0600.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import stat
import sys
import time
import xml.etree.ElementTree as ET

MAX_FILE_BYTES = 4 * 1024 * 1024


class IdentityError(ValueError):
    """Messages deliberately exclude attribute values/private addresses."""


def canonical_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


class ExplicitOks:
    def __init__(self, root, files):
        self.objects = {}
        self.sources = []
        root = Path(root).resolve(strict=True)
        seen = set()
        for filename in files:
            path = (root / filename).resolve(strict=True)
            if not path.is_relative_to(root) or path in seen:
                raise IdentityError("Input paths must be distinct and inside the selected root")
            seen.add(path)
            if not stat.S_ISREG(path.stat().st_mode):
                raise IdentityError("Input must be a regular file")
            with path.open("rb") as stream:
                raw = stream.read(MAX_FILE_BYTES + 1)
            if len(raw) > MAX_FILE_BYTES:
                raise IdentityError("Input exceeds the bounded file size")
            # Permit the usual OKS DTD declarations, but not entity declarations
            # or alternate encodings that could bypass this byte-level check.
            try:
                xml = raw.decode("utf-8")
            except UnicodeError:
                raise IdentityError("Only UTF-8/ASCII OKS data is supported") from None
            if "\x00" in xml or re.search(r"<!\s*ENTITY\b", xml, re.I):
                raise IdentityError("XML entity declarations/alternate encodings are unsupported")
            try:
                document = ET.fromstring(xml)
            except ET.ParseError:
                raise IdentityError("Invalid OKS XML") from None
            if document.tag != "oks-data":
                raise IdentityError("Expected an OKS data document, not a schema")
            relative = path.relative_to(root).as_posix()
            digest = hashlib.sha256(raw).hexdigest()
            self.sources.append({"file": relative, "sha256": digest, "bytes": len(raw)})
            for obj in document.findall("obj"):
                key = (obj.get("class"), obj.get("id"))
                if not all(key) or key in self.objects:
                    raise IdentityError("Missing or duplicate OKS object identity")
                self.objects[key] = (obj, {"file": relative, "sha256": digest,
                                          "class": key[0], "object_id": key[1]})
        self.sources.sort(key=lambda item: item["file"])

    def obj(self, key):
        if key not in self.objects:
            raise IdentityError("A selected relationship refers to an unavailable object")
        return self.objects[key][0]

    def attr(self, key, name, *, many=False, types=None):
        attrs = [item for item in self.obj(key).findall("attr") if item.get("name") == name]
        if len(attrs) != 1:
            raise IdentityError(f"Required explicit attribute {name} is missing or duplicated")
        attr = attrs[0]
        if types is not None and attr.get("type") not in types:
            raise IdentityError(f"Attribute {name} has an unsupported explicit type")
        children = list(attr)
        if children:
            if attr.get("val") not in (None, "") or any(item.tag != "data" for item in children):
                raise IdentityError(f"Ambiguous attribute {name}")
            values = [item.get("val") for item in children]
        else:
            values = [attr.get("val")]
        if not values or any(not isinstance(v, str) or not v or v != v.strip() for v in values):
            raise IdentityError(f"Empty or malformed explicit attribute {name}")
        if not many and len(values) != 1:
            raise IdentityError(f"Attribute {name} must have exactly one explicit value")
        return values if many else values[0]

    def relation(self, key, name, expected_class, *, many=False):
        rels = [item for item in self.obj(key).findall("rel") if item.get("name") == name]
        if len(rels) != 1:
            raise IdentityError(f"Required relationship {name} is missing or duplicated")
        rel = rels[0]
        children = list(rel)
        if children:
            if rel.get("class") or rel.get("id") or any(item.tag != "ref" for item in children):
                raise IdentityError(f"Ambiguous relationship {name}")
            refs = [(item.get("class"), item.get("id")) for item in children]
        else:
            refs = [(rel.get("class"), rel.get("id"))]
        if (not refs or len(set(refs)) != len(refs) or
                any(cls != expected_class or not ident for cls, ident in refs)):
            raise IdentityError(f"Invalid relationship {name}")
        for ref in refs:
            self.obj(ref)
        if not many and len(refs) != 1:
            raise IdentityError(f"Relationship {name} is not unique")
        return refs if many else refs[0]

    def assignment(self, key, name, value):
        return {"value": value, "source": {**self.objects[key][1], "attribute": name}}

    def uint(self, key, name):
        value = self.attr(key, name, types={"u8", "u16", "u32"})
        if not re.fullmatch(r"0|[1-9][0-9]{0,9}", value) or int(value) > 0xffffffff:
            raise IdentityError(f"Attribute {name} is not an explicit uint32")
        kind = next(item.get("type") for item in self.obj(key).findall("attr") if item.get("name") == name)
        if int(value) >= 1 << int(kind[1:]):
            raise IdentityError(f"Attribute {name} exceeds its declared unsigned type")
        return int(value)


def ipv4(value):
    if not isinstance(value, str) or not re.fullmatch(r"(?:0|[1-9][0-9]{0,2})(?:\.(?:0|[1-9][0-9]{0,2})){3}", value):
        raise IdentityError("An assigned IPv4 address is invalid")
    try:
        address = ipaddress.IPv4Address(value)
    except ValueError:
        raise IdentityError("An assigned IPv4 address is invalid") from None
    if address.is_multicast or address.is_unspecified or address.is_loopback or int(address) == 0xffffffff:
        raise IdentityError("An assigned IPv4 address is not a usable unicast identity")
    return str(address)


def hostname_or_ipv4(value):
    if re.fullmatch(r"[0-9.]+", value):
        return ipv4(value)
    candidate = value.removesuffix(".")
    if (len(candidate) > 253 or not candidate or
            any(not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", part)
                for part in candidate.split("."))):
        raise IdentityError("A management host must be a hostname or IPv4 literal")
    return value


def mac_address(value):
    if not re.fullmatch(r"[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5}", value):
        raise IdentityError("An assigned MAC address is malformed")
    number = int(value.replace(":", ""), 16)
    if not number or (number >> 40) & 1:
        raise IdentityError("An assigned MAC address must be nonzero unicast")
    return value.lower()


def extract_identity(root, files, application_id, board_id):
    db = ExplicitOks(root, files)
    app = ("DaphneApplication", application_id)
    config = db.relation(app, "configuration", "DaphneConf")
    board = ("DaphneV2BoardConf", board_id)
    entries = db.relation(config, "boards", "DaphneMapEntry", many=True)
    matching = [entry for entry in entries if db.relation(entry, "conf", "DaphneV2BoardConf") == board]
    if len(matching) != 1:
        raise IdentityError("Selected board must occur exactly once in the application configuration")
    placement = {name: db.uint(board, name) for name in ("crate_id", "slot_id", "detector_id")}
    expected_key = ".".join(str(placement[name]) for name in ("detector_id", "crate_id", "slot_id"))
    if db.attr(matching[0], "key", types={"string"}) != expected_key:
        raise IdentityError("Board map key disagrees with explicit placement")
    management = hostname_or_ipv4(db.attr(board, "address", types={"string"}))
    connections = db.relation(app, "detector_connections", "NetworkDetectorToDaqConnection", many=True)
    senders = []
    for connection in connections:
        senders.extend((connection, sender) for sender in
                       db.relation(connection, "net_senders", "HermesDataSender", many=True))
    interfaces = []
    selected_senders = set()
    selected_interfaces = set()
    for connection, sender in senders:
        streams = db.relation(sender, "streams", "DetectorStream", many=True)
        geos = [db.relation(stream, "geo_id", "GeoId") for stream in streams]
        matches = [{name: db.uint(geo, name) for name in placement} == placement for geo in geos]
        if not any(matches):
            continue
        if not all(matches) or sender in selected_senders:
            raise IdentityError("Hermes sender has mixed placements or duplicate application connections")
        selected_senders.add(sender)
        interface = db.relation(sender, "uses", "NetworkInterface")
        if interface in selected_interfaces:
            raise IdentityError("Selected senders ambiguously share a network-interface assignment")
        selected_interfaces.add(interface)
        ips = [ipv4(value) for value in db.attr(interface, "ip_address", many=True, types={"string"})]
        if len(set(ips)) != len(ips):
            raise IdentityError("Duplicate assigned interface IPv4 addresses")
        interfaces.append({
            "connection_object_id": connection[1], "sender_object_id": sender[1],
            "interface_object_id": interface[1],
            "stream_object_ids": [stream[1] for stream in streams],
            "geo_object_ids": [geo[1] for geo in geos],
            "control_host": db.assignment(sender, "control_host", hostname_or_ipv4(db.attr(sender, "control_host", types={"string"}))),
            "mac_address": db.assignment(interface, "mac_address", mac_address(db.attr(interface, "mac_address", types={"string"}))),
            "ip_addresses": db.assignment(interface, "ip_address", ips),
            "physical_connector": None, "hermes_link_id": None,
        })
    if not interfaces:
        raise IdentityError("No connected Hermes sender agrees with the selected board placement")
    return {
        "format": "daphne-explicit-oks-identity-review-v1",
        "scope": "Explicit assignments only; not a schema-resolved configuration or deployment manifest",
        "application_object_id": application_id, "board_object_id": board_id,
        "sources": db.sources,
        "source_revision_sha256": hashlib.sha256(canonical_bytes(db.sources)).hexdigest(),
        "placement": {name: db.assignment(board, name, value) for name, value in placement.items()},
        "management_address": db.assignment(board, "address", management),
        "management_mac_address": None,
        "timing_endpoint_address": None,
        "hermes_interfaces": sorted(interfaces, key=lambda item: item["interface_object_id"]),
        "unresolved": [
            "Management MAC is not supplied by this explicit-field mapping",
            "Timing-endpoint assignment needs a separately established source; tp_conf is not that address",
            "Physical connector and Hermes LinkId mapping are not inferred from interface/stream names",
            "Schema defaults, includes and active run-control/session selection are not evaluated",
        ],
        "target_check": {"status": "not_checked"},
    }


def resolve_one_ipv4(host):
    try:
        answers = {item[4][0] for item in socket.getaddrinfo(host, None, socket.AF_INET, socket.SOCK_STREAM)}
    except OSError:
        raise IdentityError("Management DNS lookup failed") from None
    if len(answers) != 1:
        raise IdentityError("Management DNS lookup must return one unique IPv4 address")
    return ipv4(answers.pop())


def verify_target(snapshot, target_host, resolver=resolve_one_ipv4):
    snapshot["target_check"] = {"status": "not_checked"}
    expected = ipv4(resolver(hostname_or_ipv4(target_host)))
    hosts = [snapshot["management_address"]["value"]]
    hosts += [item["control_host"]["value"] for item in snapshot["hermes_interfaces"]]
    if any(ipv4(resolver(host)) != expected for host in hosts):
        raise IdentityError("Board/sender management identities do not match the selected target")
    snapshot["target_check"] = {
        "status": "matched", "target_host": target_host, "resolved_ipv4": expected,
        "observed_host_unix_ns": time.time_ns(),
        "scope": "DNS/literal comparison only, not live NIC readback or cryptographic hardware identity",
    }


def write_private(path, snapshot):
    # No overwrite, symlink following, stdout dump or permissive creation mode.
    payload = json.dumps(snapshot, indent=2, sort_keys=True) + "\n"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        output.write(payload)
        output.flush()
        os.fsync(output.fileno())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--segment-file", default="segments/pds-vst.data.xml")
    parser.add_argument("--connections-file", default="hw/pds-vst-connections.data.xml")
    parser.add_argument("--senders-file", default="hw/senders/pds-vst-senders.data.xml")
    parser.add_argument("--application-id", required=True)
    parser.add_argument("--board-object-id", required=True)
    parser.add_argument("--verify-target", help="Explicit opt-in DNS comparison; no SSH or board access")
    parser.add_argument("--private-output", type=Path, help="New mode-0600 review JSON; never overwritten")
    args = parser.parse_args(argv)
    try:
        snapshot = extract_identity(args.root, [args.segment_file, args.connections_file, args.senders_file],
                                    args.application_id, args.board_object_id)
        if args.verify_target:
            verify_target(snapshot, args.verify_target)
        if args.private_output:
            write_private(args.private_output, snapshot)
    except IdentityError as error:
        print(f"Identity extraction refused: {error}", file=sys.stderr)
        return 1
    except OSError:
        print("Identity extraction refused: file or resolver operation failed (private details suppressed)", file=sys.stderr)
        return 1
    print(json.dumps({
        "result": "review_snapshot_only", "network_values": "redacted",
        "source_revision_sha256": snapshot["source_revision_sha256"],
        "placement": {name: item["value"] for name, item in snapshot["placement"].items()},
        "hermes_interface_count": len(snapshot["hermes_interfaces"]),
        "target_check": snapshot["target_check"]["status"],
        "private_output_written": bool(args.private_output), "unresolved": snapshot["unresolved"],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
