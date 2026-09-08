#!/usr/bin/env python3
"""Render runtime files from a versioned DAPHNE board configuration."""

from __future__ import annotations

import argparse
import csv
import hashlib
import ipaddress
import json
import re
import shlex
import uuid
from pathlib import Path
from typing import Any


MAC_RE = re.compile(r"^(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$")
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
SAFE_VALUE_RE = re.compile(r"^[A-Za-z0-9_.:/-]+$")
MAC_SOURCES = {"som_eeprom", "daphne_pool", "legacy_override"}

RECORD_FIELDS = {
    "asset": {"asset_id", "carrier_revision"},
    "som": {"uuid", "serial", "product", "factory_mac_id_0"},
    "network": {
        "mac_source",
        "production_mac",
        "ipv4_address",
        "hostname",
        "vlan",
        "authorized",
    },
    "runtime": {"timing_endpoint", "firmware_release"},
    "source": {"assignment_revision", "asset_record_revision"},
}
ROOT_FIELDS = {"contract", "version", *RECORD_FIELDS}
INVENTORY_FIELDS = {
    "asset_id",
    "som_uuid",
    "factory_mac_id_0",
    "mac_source",
    "production_mac",
    "ipv4_address",
    "hostname",
    "timing_endpoint",
    "firmware_release",
    "network_admission_approved",
}


class DuplicateKeyError(ValueError):
    """Raised when strict JSON parsing encounters a duplicate object key."""


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"duplicate object key: {key}")
        result[key] = value
    return result


def require_exact_fields(value: object, expected: set[str], path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        fail(f"{path} must be an object")
    keys = set(value)
    missing = sorted(expected - keys)
    extra = sorted(keys - expected)
    if missing:
        fail(f"{path} is missing required field(s): {', '.join(missing)}")
    if extra:
        fail(f"{path} contains unsupported field(s): {', '.join(extra)}")
    return value


def require_nonempty_string(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        fail(f"{path} must be a nonempty string")
    return value


def require_canonical_uuid(value: object, path: str) -> str:
    text = require_nonempty_string(value, path)
    try:
        parsed = uuid.UUID(text)
    except (ValueError, AttributeError):
        fail(f"{path} must be a valid UUID")
    if text != str(parsed):
        fail(f"{path} must use canonical lowercase UUID form")
    return text


def require_mac(value: object, path: str) -> str:
    text = require_nonempty_string(value, path)
    if not MAC_RE.fullmatch(text):
        fail(f"{path} must be a colon-separated 48-bit MAC address")
    return text.lower()


def require_ipv4(value: object, path: str) -> str:
    text = require_nonempty_string(value, path)
    try:
        address = ipaddress.IPv4Address(text)
    except ipaddress.AddressValueError:
        fail(f"{path} must be a valid IPv4 address")
    return str(address)


def require_positive_integer(value: object, path: str) -> int:
    if type(value) is not int or value <= 0:
        fail(f"{path} must be a positive integer")
    return value


def validate_record(record: object) -> dict[str, str]:
    root = require_exact_fields(record, ROOT_FIELDS, "board configuration")

    contract = require_nonempty_string(root["contract"], "contract")
    if contract != "daphne.board-config":
        fail("unsupported board configuration contract")
    if type(root["version"]) is not int or root["version"] != 1:
        fail("unsupported board configuration version")

    sections = {
        name: require_exact_fields(root[name], fields, name)
        for name, fields in RECORD_FIELDS.items()
    }
    asset = sections["asset"]
    som = sections["som"]
    network = sections["network"]
    runtime = sections["runtime"]
    source = sections["source"]

    asset_id = require_nonempty_string(asset["asset_id"], "asset.asset_id")
    require_nonempty_string(asset["carrier_revision"], "asset.carrier_revision")
    som_uuid = require_canonical_uuid(som["uuid"], "som.uuid")
    require_nonempty_string(som["serial"], "som.serial")
    require_nonempty_string(som["product"], "som.product")
    factory_mac = require_mac(som["factory_mac_id_0"], "som.factory_mac_id_0")

    mac_source = require_nonempty_string(network["mac_source"], "network.mac_source")
    if mac_source not in MAC_SOURCES:
        fail(f"network.mac_source must be one of: {', '.join(sorted(MAC_SOURCES))}")
    production_mac = require_mac(network["production_mac"], "network.production_mac")
    ipv4_address = require_ipv4(network["ipv4_address"], "network.ipv4_address")
    hostname = require_nonempty_string(network["hostname"], "network.hostname")
    vlan = network["vlan"]
    if vlan is not None and (type(vlan) is not int or not 1 <= vlan <= 4094):
        fail("network.vlan must be null or an integer from 1 through 4094")
    if type(network["authorized"]) is not bool:
        fail("network.authorized must be a boolean")

    timing_endpoint = require_nonempty_string(
        runtime["timing_endpoint"], "runtime.timing_endpoint"
    )
    firmware_release = require_nonempty_string(
        runtime["firmware_release"], "runtime.firmware_release"
    )
    require_positive_integer(source["assignment_revision"], "source.assignment_revision")
    require_positive_integer(source["asset_record_revision"], "source.asset_record_revision")

    return {
        "asset_id": asset_id,
        "som_uuid": som_uuid,
        "factory_mac_id_0": factory_mac,
        "mac_source": mac_source,
        "production_mac": production_mac,
        "ipv4_address": ipv4_address,
        "hostname": hostname,
        "timing_endpoint": timing_endpoint,
        "firmware_release": firmware_release,
        "network_admission_approved": "1" if network["authorized"] is True else "0",
    }


def read_asset(path: Path, asset_id: str) -> dict[str, str]:
    with path.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        fields = reader.fieldnames or []
        if len(fields) != len(set(fields)):
            fail(f"duplicate column name in {path}")
        missing = sorted(INVENTORY_FIELDS - set(fields))
        if missing:
            fail(f"inventory is missing required column(s): {', '.join(missing)}")
        rows = [row for row in reader if row.get("asset_id") == asset_id]
    if len(rows) != 1:
        fail(f"expected one {asset_id} row in {path}, found {len(rows)}")
    row = rows[0]
    normalized: dict[str, str] = {}
    for field in INVENTORY_FIELDS:
        normalized[field] = require_nonempty_string(row.get(field), f"inventory.{field}")
    normalized["som_uuid"] = require_canonical_uuid(
        normalized["som_uuid"], "inventory.som_uuid"
    )
    normalized["factory_mac_id_0"] = require_mac(
        normalized["factory_mac_id_0"], "inventory.factory_mac_id_0"
    )
    normalized["production_mac"] = require_mac(
        normalized["production_mac"], "inventory.production_mac"
    )
    normalized["ipv4_address"] = require_ipv4(
        normalized["ipv4_address"], "inventory.ipv4_address"
    )
    if normalized["mac_source"] not in MAC_SOURCES:
        fail(f"inventory.mac_source must be one of: {', '.join(sorted(MAC_SOURCES))}")
    return normalized


def read_record(path: Path, expected_sha256: str) -> dict[str, str]:
    if not SHA256_RE.fullmatch(expected_sha256):
        fail("--record-sha256 must be exactly 64 hexadecimal characters")
    raw = path.read_bytes()
    actual_sha256 = hashlib.sha256(raw).hexdigest()
    if actual_sha256 != expected_sha256.lower():
        fail(
            f"board configuration checksum mismatch: expected {expected_sha256}, "
            f"got {actual_sha256}"
        )
    try:
        record = json.loads(raw, object_pairs_hook=reject_duplicate_keys)
    except (json.JSONDecodeError, UnicodeDecodeError, DuplicateKeyError) as exc:
        fail(f"invalid board configuration JSON: {exc}")
    result = validate_record(record)
    result["board_config_sha256"] = actual_sha256
    return result


def env_line(key: str, value: str) -> str:
    if not value or not SAFE_VALUE_RE.fullmatch(value):
        fail(f"unsafe or empty {key}: {value!r}")
    return f"{key}={shlex.quote(value)}\n"


def parse_ipv4_argument(value: str, option: str) -> ipaddress.IPv4Address:
    try:
        return ipaddress.IPv4Address(value)
    except ipaddress.AddressValueError:
        fail(f"{option} must be a valid IPv4 address")


def render_files(
    row: dict[str, str],
    prefix: int,
    gateway_text: str,
    dns_texts: list[str],
) -> dict[str, str]:
    if not 0 <= prefix <= 32:
        fail("--prefix must be from 0 through 32")
    address = ipaddress.IPv4Address(row["ipv4_address"])
    gateway = parse_ipv4_argument(gateway_text, "--gateway")
    network = ipaddress.IPv4Network(f"{address}/{prefix}", strict=False)
    if gateway not in network:
        fail(f"gateway {gateway} is not in {network}")
    dns_servers = [str(parse_ipv4_argument(value, "--dns")) for value in dns_texts]

    factory_mac = require_mac(row["factory_mac_id_0"], "factory MAC")
    expected_mac = require_mac(row["production_mac"], "expected MAC")

    board_env = "".join(
        [
            env_line("BOARD_ID", row["asset_id"]),
            env_line("HOSTNAME_FQDN", row["hostname"]),
            env_line("SOM_UUID", row["som_uuid"]),
            env_line("FACTORY_MAC_ID_0", factory_mac),
            env_line("IPV4_CIDR", f"{address}/{prefix}"),
            env_line("GW4", str(gateway)),
            env_line("ENDPOINT_ADDR_HEX", row["timing_endpoint"]),
            env_line("APP", "daphne"),
        ]
        + [env_line(f"DNS{index}", value) for index, value in enumerate(dns_servers, 1)]
    )
    dns_lines = "".join(f"DNS={value}\n" for value in dns_servers)
    manifest = "".join(
        [
            env_line("ASSET_ID", row["asset_id"]),
            env_line("HOSTNAME_FQDN", row["hostname"]),
            env_line("SOM_UUID", row["som_uuid"]),
            env_line("FACTORY_MAC_ID_0", factory_mac),
            env_line("EXPECTED_BOOT_MAC", expected_mac),
            env_line("MAC_SOURCE", row["mac_source"]),
            env_line("IPV4_CIDR", f"{address}/{prefix}"),
            env_line("FIRMWARE_RELEASE", row["firmware_release"]),
        ]
        + (
            [env_line("BOARD_CONFIG_SHA256", row["board_config_sha256"])]
            if row.get("board_config_sha256")
            else []
        )
    )
    return {
        "daphne-board.env": board_env,
        "hostname": f"{row['hostname']}\n",
        "20-daphne-mgmt.network": (
            "[Match]\n"
            "Name=eth0\n\n"
            "[Network]\n"
            f"Address={address}/{prefix}\n"
            f"Gateway={gateway}\n"
            f"{dns_lines}"
        ),
        "21-daphne-unused.network": (
            "[Match]\n"
            "Name=eth1\n\n"
            "[Network]\n"
            "DHCP=no\n"
            "LinkLocalAddressing=no\n"
            "IPv6AcceptRA=no\n"
        ),
        "manifest.env": manifest,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--record", type=Path, help="daphne.board-config v1 JSON")
    source.add_argument("--inventory", type=Path, help="legacy staging inventory CSV")
    parser.add_argument("--record-sha256", help="expected SHA-256 of --record")
    parser.add_argument("--asset", help="asset ID selected from --inventory")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--prefix", required=True, type=int)
    parser.add_argument("--gateway", required=True)
    parser.add_argument("--dns", action="append", required=True)
    parser.add_argument("--expected-firmware-release", required=True)
    parser.add_argument(
        "--allow-unapproved",
        action="store_true",
        help="render a lab trial config while network_admission_approved is false",
    )
    args = parser.parse_args()

    expected_release = require_nonempty_string(
        args.expected_firmware_release, "--expected-firmware-release"
    )
    if args.record:
        if not args.record_sha256:
            fail("--record-sha256 is required with --record")
        if args.asset:
            fail("--asset is valid only with --inventory")
        row = read_record(args.record, args.record_sha256)
        source_name = "record"
    else:
        if not args.asset:
            fail("--asset is required with --inventory")
        if args.record_sha256:
            fail("--record-sha256 is valid only with --record")
        row = read_asset(args.inventory, args.asset)
        source_name = "inventory"

    if row["firmware_release"] != expected_release:
        fail(
            f"{source_name} firmware_release mismatch: expected {expected_release!r}, "
            f"got {row['firmware_release']!r}"
        )
    if row["network_admission_approved"] not in {"1", "true", "True"}:
        if not args.allow_unapproved:
            fail(f"network admission is not approved in the {source_name}")

    files = render_files(row, args.prefix, args.gateway, args.dns)

    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (output / name).write_text(content, encoding="utf-8")

    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
