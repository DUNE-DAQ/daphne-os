#!/usr/bin/env python3
"""Run the single-board DAPHNE deployer over a validated CSV campaign."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time


REQUIRED_COLUMNS = {"board", "host", "board_config", "host_key_sha256"}
OPTIONAL_COLUMNS = {"user", "control_host"}
BOARD_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
HOST_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")
USER_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*$")
CONTROL_HOST_RE = re.compile(
    r"^(?:[A-Za-z0-9_.-]+@)?[A-Za-z0-9_.:-]+$"
)
HOST_KEY_RE = re.compile(r"^SHA256:[A-Za-z0-9+/]{43}$")
MANIFEST_VALUE_RE = re.compile(r"^[A-Za-z0-9_.:/-]+$")
MAC_RE = re.compile(r"^(?:[0-9a-f]{2}:){5}[0-9a-f]{2}$")
FORBIDDEN_MAC_SETTER_RE = re.compile(
    r"^[ \t]*(?:MACAddress|ethaddr|eth1addr)[ \t]*=", re.MULTILINE
)
CHECKSUM_RE = re.compile(r"^([0-9a-fA-F]{64}) ([ *])(.+)$")
REQUIRED_BUNDLE_PATHS = {
    "boot/Image",
    "boot/system.dtb",
    "boot/ramdisk.cpio.gz.u-boot",
    "rootfs/rootfs.ext4",
}
REQUIRED_BOARD_CONFIG_FILES = {
    "manifest.env",
    "hostname",
    "daphne-board.env",
    "20-daphne-mgmt.network",
    "21-daphne-unused.network",
}


class CampaignError(ValueError):
    pass


class CampaignSignal(Exception):
    def __init__(self, signum: int) -> None:
        super().__init__(signum)
        self.signum = signum


@dataclass(frozen=True)
class BoardTarget:
    index: int
    source_line: int
    board: str
    host: str
    board_config: Path
    host_key_sha256: str
    user: str
    control_host: str | None
    firmware_release: str
    board_config_sha256: dict[str, str]
    board_config_files: dict[str, bytes]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


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
        raise CampaignError(f"{label} does not exist: {value}") from exc
    if not path.is_dir():
        raise CampaignError(f"{label} is not a directory: {value}")
    return path


def manifest_value(text: str, label: Path, key: str) -> str:
    matches = [
        line.split("=", 1)[1]
        for line in text.splitlines()
        if line.startswith(f"{key}=")
    ]
    if len(matches) != 1 or not matches[0]:
        raise CampaignError(f"{label} must contain exactly one nonempty {key} entry")
    return matches[0]


def validate_board_config(
    path: Path, board: str
) -> tuple[dict[str, str], dict[str, bytes], str]:
    missing = sorted(
        name for name in REQUIRED_BOARD_CONFIG_FILES if not (path / name).is_file()
    )
    if missing:
        raise CampaignError(
            f"board_config for {board} is missing: {', '.join(missing)}"
        )
    symlinks = sorted(
        str(candidate) for candidate in path.rglob("*") if candidate.is_symlink()
    )
    if symlinks:
        raise CampaignError(f"board_config for {board} contains symlinks")
    files = {
        name: (path / name).read_bytes()
        for name in sorted(REQUIRED_BOARD_CONFIG_FILES)
    }
    texts = {name: data.decode("utf-8") for name, data in files.items()}
    for name, text in texts.items():
        if FORBIDDEN_MAC_SETTER_RE.search(text):
            raise CampaignError(
                f"board_config for {board} contains a forbidden MAC setter in {name}"
            )

    manifest = path / "manifest.env"
    values = {
        key: manifest_value(texts["manifest.env"], manifest, key)
        for key in (
            "ASSET_ID",
            "HOSTNAME_FQDN",
            "EXPECTED_BOOT_MAC",
            "FIRMWARE_RELEASE",
        )
    }
    for key, value in values.items():
        if not MANIFEST_VALUE_RE.fullmatch(value):
            raise CampaignError(f"unsafe {key} value in {manifest}")
    asset_id = values["ASSET_ID"]
    if asset_id != board:
        raise CampaignError(
            f"board {board} does not match {manifest} ASSET_ID={asset_id}"
        )
    if not MAC_RE.fullmatch(values["EXPECTED_BOOT_MAC"]):
        raise CampaignError(f"invalid EXPECTED_BOOT_MAC in {manifest}")

    hostname_lines = texts["hostname"].splitlines()
    if hostname_lines != [values["HOSTNAME_FQDN"]]:
        raise CampaignError(
            f"hostname payload for {board} does not match manifest HOSTNAME_FQDN"
        )
    board_env = path / "daphne-board.env"
    if manifest_value(texts["daphne-board.env"], board_env, "BOARD_ID") != asset_id:
        raise CampaignError(f"BOARD_ID in {board_env} does not match manifest ASSET_ID")
    if (
        manifest_value(
            texts["daphne-board.env"], board_env, "HOSTNAME_FQDN"
        )
        != values["HOSTNAME_FQDN"]
    ):
        raise CampaignError(
            f"HOSTNAME_FQDN in {board_env} does not match manifest HOSTNAME_FQDN"
        )
    return (
        {
            name: hashlib.sha256(data).hexdigest()
            for name, data in files.items()
        },
        files,
        values["FIRMWARE_RELEASE"],
    )


def load_campaign(path: Path) -> tuple[list[BoardTarget], str, bytes]:
    try:
        csv_path = path.expanduser().resolve(strict=True)
    except (OSError, ValueError, RuntimeError) as exc:
        raise CampaignError(f"campaign CSV does not exist: {path}") from exc
    if not csv_path.is_file():
        raise CampaignError(f"campaign CSV is not a file: {csv_path}")

    try:
        csv_bytes = csv_path.read_bytes()
        csv_text = csv_bytes.decode("utf-8-sig")
    except OSError as exc:
        raise CampaignError(f"cannot read campaign CSV: {csv_path}") from exc

    with io.StringIO(csv_text, newline="") as source:
        reader = csv.DictReader(source, strict=True)
        try:
            headers = reader.fieldnames
            rows = [(reader.line_num, row) for row in reader]
        except csv.Error as exc:
            raise CampaignError(f"malformed campaign CSV: {exc}") from exc
        if not headers:
            raise CampaignError("campaign CSV has no header")
        if len(headers) != len(set(headers)):
            raise CampaignError("campaign CSV has duplicate columns")
        missing_columns = sorted(REQUIRED_COLUMNS - set(headers))
        unknown_columns = sorted(set(headers) - REQUIRED_COLUMNS - OPTIONAL_COLUMNS)
        if missing_columns:
            raise CampaignError(
                f"campaign CSV is missing columns: {', '.join(missing_columns)}"
            )
        if unknown_columns:
            raise CampaignError(
                f"campaign CSV has unknown columns: {', '.join(unknown_columns)}"
            )

        targets: list[BoardTarget] = []
        seen: dict[str, dict[str, int]] = {
            "board": {},
            "host": {},
            "board_config": {},
            "host_key_sha256": {},
        }
        for index, (line_number, row) in enumerate(rows, start=1):
            if None in row:
                raise CampaignError(
                    f"campaign CSV line {line_number} has too many fields"
                )
            values = {name: (row.get(name) or "").strip() for name in headers}
            empty = sorted(name for name in REQUIRED_COLUMNS if not values[name])
            if empty:
                raise CampaignError(
                    f"campaign CSV line {line_number} has empty fields: {', '.join(empty)}"
                )

            board = values["board"]
            host = values["host"]
            user = values.get("user", "") or "petalinux"
            control_host = values.get("control_host", "") or None
            fingerprint = values["host_key_sha256"]
            if not BOARD_RE.fullmatch(board):
                raise CampaignError(f"unsafe board on CSV line {line_number}: {board!r}")
            if not HOST_RE.fullmatch(host):
                raise CampaignError(f"unsafe host on CSV line {line_number}: {host!r}")
            if not USER_RE.fullmatch(user):
                raise CampaignError(f"unsafe user on CSV line {line_number}: {user!r}")
            if control_host and (
                control_host.startswith("-")
                or not CONTROL_HOST_RE.fullmatch(control_host)
            ):
                raise CampaignError(
                    f"unsafe control_host on CSV line {line_number}: {control_host!r}"
                )
            if not HOST_KEY_RE.fullmatch(fingerprint):
                raise CampaignError(
                    f"invalid host_key_sha256 on CSV line {line_number}"
                )

            board_config = resolve_directory(
                values["board_config"],
                csv_path.parent,
                f"board_config on CSV line {line_number}",
            )
            (
                board_config_sha256,
                board_config_files,
                firmware_release,
            ) = validate_board_config(board_config, board)

            unique_values = {
                "board": board.casefold(),
                "host": host.casefold(),
                "board_config": str(board_config),
                "host_key_sha256": fingerprint,
            }
            for label, unique_value in unique_values.items():
                previous = seen[label].get(unique_value)
                if previous is not None:
                    raise CampaignError(
                        f"duplicate {label} on CSV lines {previous} and {line_number}"
                    )
                seen[label][unique_value] = line_number

            targets.append(
                BoardTarget(
                    index=index,
                    source_line=line_number,
                    board=board,
                    host=host,
                    board_config=board_config,
                    host_key_sha256=fingerprint,
                    user=user,
                    control_host=control_host,
                    firmware_release=firmware_release,
                    board_config_sha256=board_config_sha256,
                    board_config_files=board_config_files,
                )
            )

    if not targets:
        raise CampaignError("campaign CSV has no board rows")
    firmware_releases = {target.firmware_release for target in targets}
    if len(firmware_releases) != 1:
        raise CampaignError(
            "campaign board configurations name different firmware releases: "
            + ", ".join(sorted(firmware_releases))
        )
    return targets, hashlib.sha256(csv_bytes).hexdigest(), csv_bytes


def normalize_manifest_path(raw_name: str, bundle: Path, line_number: int) -> tuple[str, Path]:
    relative = PurePosixPath(raw_name)
    if relative.is_absolute() or ".." in relative.parts or "\\" in raw_name:
        raise CampaignError(
            f"unsafe path in {bundle / 'SHA256SUMS'} line {line_number}: {raw_name!r}"
        )
    normalized = str(relative)
    if normalized in {"", "."}:
        raise CampaignError(
            f"empty path in {bundle / 'SHA256SUMS'} line {line_number}"
        )
    candidate = bundle.joinpath(*relative.parts)
    if candidate.is_symlink() or not candidate.is_file():
        raise CampaignError(f"missing regular bundle artifact: {candidate}")
    try:
        candidate.resolve(strict=True).relative_to(bundle)
    except (OSError, ValueError, RuntimeError) as exc:
        raise CampaignError(f"bundle manifest path escapes bundle: {raw_name}") from exc
    return normalized, candidate


def verify_bundle(bundle_arg: Path) -> tuple[Path, dict[str, object]]:
    bundle = resolve_directory(str(bundle_arg), Path.cwd(), "release bundle")
    manifest = bundle / "SHA256SUMS"
    if manifest.is_symlink() or not manifest.is_file():
        raise CampaignError(f"release bundle has no SHA256SUMS: {bundle}")

    manifest_bytes = manifest.read_bytes()
    manifest_text = manifest_bytes.decode("utf-8")
    verified: dict[str, str] = {}
    for line_number, line in enumerate(manifest_text.splitlines(), start=1):
        if not line:
            continue
        match = CHECKSUM_RE.fullmatch(line)
        if not match:
            raise CampaignError(
                f"malformed checksum record in {manifest} line {line_number}"
            )
        expected, _, raw_name = match.groups()
        normalized, artifact = normalize_manifest_path(
            raw_name, bundle, line_number
        )
        if normalized in verified:
            raise CampaignError(f"duplicate bundle checksum path: {normalized}")
        actual = sha256_file(artifact)
        if actual != expected.lower():
            raise CampaignError(f"bundle checksum mismatch: {normalized}")
        verified[normalized] = actual

    missing = sorted(REQUIRED_BUNDLE_PATHS - set(verified))
    if missing:
        raise CampaignError(
            f"bundle manifest does not cover required artifacts: {', '.join(missing)}"
        )
    return bundle, {
        "manifest": str(manifest),
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "verified_utc": utc_now(),
        "verified_entries": len(verified),
        "required_entries": sorted(REQUIRED_BUNDLE_PATHS),
        "artifacts_sha256": verified,
    }


def snapshot_file(path: Path, data: bytes, mode: int) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    path.chmod(mode)
    return hashlib.sha256(data).hexdigest()


def copy_verified_snapshot(source: Path, destination: Path, expected: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    if sha256_file(destination) != expected:
        raise CampaignError(f"input changed while snapshotting: {source}")
    destination.chmod(0o444)


def snapshot_inputs(
    evidence_dir: Path,
    campaign_source: Path,
    campaign_bytes: bytes,
    deploy_source: Path,
    deploy_bytes: bytes,
    bundle_source: Path,
    bundle_evidence: dict[str, object],
    targets: list[BoardTarget],
) -> tuple[Path, Path, dict[int, Path], dict[str, object]]:
    root = evidence_dir / "inputs"
    campaign_snapshot = root / "campaign.csv"
    campaign_sha256 = snapshot_file(campaign_snapshot, campaign_bytes, 0o444)
    deploy_snapshot = root / "daphne_deploy.sh"
    deploy_sha256 = snapshot_file(deploy_snapshot, deploy_bytes, 0o555)

    artifact_hashes = {
        str(name): str(digest)
        for name, digest in dict(bundle_evidence["artifacts_sha256"]).items()
        if str(name) in REQUIRED_BUNDLE_PATHS
    }
    bundle_snapshot = root / "bundle"
    for name in sorted(REQUIRED_BUNDLE_PATHS):
        copy_verified_snapshot(
            bundle_source / name, bundle_snapshot / name, artifact_hashes[name]
        )
    snapshot_manifest = "".join(
        f"{artifact_hashes[name]}  ./{name}\n"
        for name in sorted(REQUIRED_BUNDLE_PATHS)
    ).encode("utf-8")
    snapshot_manifest_sha256 = snapshot_file(
        bundle_snapshot / "SHA256SUMS", snapshot_manifest, 0o444
    )

    config_snapshots: dict[int, Path] = {}
    for target in targets:
        snapshot = root / "board-configs" / f"{target.index:03d}-{target.board}"
        for name, data in target.board_config_files.items():
            actual = snapshot_file(snapshot / name, data, 0o444)
            if actual != target.board_config_sha256[name]:
                raise CampaignError(
                    f"captured board_config hash mismatch for {target.board}: {name}"
                )
        config_snapshots[target.index] = snapshot

    for directory in sorted(
        (path for path in root.rglob("*") if path.is_dir()), reverse=True
    ):
        directory.chmod(0o555)
    root.chmod(0o555)
    return deploy_snapshot, bundle_snapshot, config_snapshots, {
        "root": str(root),
        "campaign_csv": {
            "source": str(campaign_source),
            "snapshot": str(campaign_snapshot),
            "sha256": campaign_sha256,
        },
        "deploy_script": {
            "source": str(deploy_source),
            "snapshot": str(deploy_snapshot),
            "sha256": deploy_sha256,
        },
        "bundle": {
            "source": str(bundle_source),
            "snapshot": str(bundle_snapshot),
            "source_manifest_sha256": bundle_evidence["manifest_sha256"],
            "snapshot_manifest_sha256": snapshot_manifest_sha256,
            "artifacts_sha256": artifact_hashes,
            "integrity_gate": (
                "The captured daphne_deploy.sh verifies snapshot SHA256SUMS "
                "before each board copy or write."
            ),
            "snapshot_bytes": sum(
                (bundle_snapshot / name).stat().st_size
                for name in REQUIRED_BUNDLE_PATHS
            ),
        },
    }


def deploy_command(
    deploy_script: Path,
    target: BoardTarget,
    bundle: Path,
    board_config: Path,
    execute: bool,
    reboot: bool,
) -> list[str]:
    command = [
        str(deploy_script),
        "--board",
        target.board,
        "--host",
        target.host,
        "--bundle",
        str(bundle),
        "--board-config",
        str(board_config),
        "--host-key-sha256",
        target.host_key_sha256,
    ]
    if target.user != "petalinux":
        command.extend(("--user", target.user))
    if target.control_host:
        command.extend(("--control-host", target.control_host))
    if reboot:
        command.append("--reboot")
    if not execute:
        command.append("--dry-run")
    return command


def console_write(message: str) -> None:
    """Write operator output without letting a closed pipe abandon a deployment."""
    try:
        sys.stdout.write(message)
        sys.stdout.flush()
    except BrokenPipeError:
        try:
            null_fd = os.open(os.devnull, os.O_WRONLY)
            try:
                os.dup2(null_fd, sys.stdout.fileno())
            finally:
                os.close(null_fd)
        except (OSError, ValueError):
            pass


def stop_process_group(process: subprocess.Popen[str]) -> None:
    """Terminate and reap the isolated deploy process group."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            break
        process.poll()
        time.sleep(0.05)
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def require_unchanged_file(path: Path, expected: str, label: str) -> None:
    if path.is_symlink() or not path.is_file() or sha256_file(path) != expected:
        raise CampaignError(f"{label} changed after campaign preflight: {path}")


def verify_launch_inputs(
    target: BoardTarget,
    board_config: Path,
    bundle_manifest: Path,
    bundle_manifest_sha256: str,
    deploy_script: Path,
    deploy_script_sha256: str,
) -> None:
    require_unchanged_file(
        bundle_manifest, bundle_manifest_sha256, "bundle manifest"
    )
    require_unchanged_file(deploy_script, deploy_script_sha256, "deploy script")
    for name, expected in target.board_config_sha256.items():
        require_unchanged_file(
            board_config / name, expected, f"board_config for {target.board}"
        )


def board_identity(target: BoardTarget, board_config: Path) -> dict[str, object]:
    return {
        "index": target.index,
        "source_line": target.source_line,
        "board": target.board,
        "host": target.host,
        "user": target.user,
        "control_host": target.control_host,
        "firmware_release": target.firmware_release,
        "board_config_source": str(target.board_config),
        "board_config": str(board_config),
        "board_config_sha256": target.board_config_sha256,
        "host_key_sha256": target.host_key_sha256,
        "qualification_status": "not_performed",
        "release_qualified": False,
    }


def run_board(
    command: list[str],
    target: BoardTarget,
    board_config: Path,
    log_path: Path,
    success_status: str,
) -> dict[str, object]:
    started = utc_now()
    started_monotonic = time.monotonic()
    return_code = 127
    was_interrupted = False
    process: subprocess.Popen[str] | None = None
    with log_path.open("w", encoding="utf-8") as log:
        log.write(f"started_utc={started}\n")
        log.write(f"command={shlex.join(command)}\n")
        log.flush()
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                start_new_session=True,
            )
        except OSError as exc:
            log.write(f"ERROR: could not start deploy command: {exc}\n")
        except (KeyboardInterrupt, CampaignSignal) as exc:
            was_interrupted = True
            return_code = (
                130 if isinstance(exc, KeyboardInterrupt) else 128 + exc.signum
            )
            if process is not None:
                stop_process_group(process)
            log.write("Campaign interrupted while this board was active.\n")
        else:
            try:
                assert process.stdout is not None
                for line in process.stdout:
                    log.write(line)
                    log.flush()
                    console_write(f"[{target.board}] {line}")
                return_code = process.wait()
            except (KeyboardInterrupt, CampaignSignal) as exc:
                was_interrupted = True
                return_code = (
                    130
                    if isinstance(exc, KeyboardInterrupt)
                    else 128 + exc.signum
                )
                stop_process_group(process)
                try:
                    log.write("Campaign interrupted while this board was active.\n")
                except OSError:
                    pass
            except BaseException:
                stop_process_group(process)
                raise
        completed = utc_now()
        duration = round(time.monotonic() - started_monotonic, 3)
        log.write(f"completed_utc={completed}\n")
        log.write(f"return_code={return_code}\n")

    return {
        **board_identity(target, board_config),
        "command": command,
        "log": log_path.name,
        "log_sha256": sha256_file(log_path),
        "started_utc": started,
        "completed_utc": completed,
        "duration_seconds": duration,
        "return_code": return_code,
        "status": (
            "interrupted"
            if was_interrupted
            else success_status
            if return_code == 0
            else "failed"
        ),
    }


def write_summary(path: Path, summary: dict[str, object]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def raise_campaign_signal(signum: int, _frame: object) -> None:
    raise CampaignSignal(signum)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("campaign_csv", type=Path)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        help="new directory for per-board logs and campaign-summary.json",
    )
    parser.add_argument(
        "--deploy-script",
        type=Path,
        default=Path(__file__).with_name("daphne_deploy.sh"),
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help=(
            "stage writes without reboot; success is staged, not qualified; "
            "without this flag every board uses --dry-run"
        ),
    )
    parser.add_argument(
        "--reboot",
        action="store_true",
        help="include reboot in a dry-run plan; rejected together with --execute",
    )
    parser.add_argument("--continue-on-error", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.execute and args.reboot:
            raise CampaignError(
                "--execute --reboot is unsupported without a post-reboot "
                "qualification gate; deploy without --reboot, then qualify manually"
            )
        csv_path = args.campaign_csv.expanduser().resolve(strict=True)
        targets, campaign_csv_sha256, campaign_bytes = load_campaign(csv_path)
        bundle_source, bundle_evidence = verify_bundle(args.bundle)
        deploy_source = args.deploy_script.expanduser().resolve(strict=True)
        if not deploy_source.is_file() or not os.access(deploy_source, os.X_OK):
            raise CampaignError(
                f"deploy script is not an executable file: {deploy_source}"
            )
        deploy_bytes = deploy_source.read_bytes()
        deploy_script_sha256 = hashlib.sha256(deploy_bytes).hexdigest()
        campaign_stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")
        evidence_dir = args.evidence_dir or Path.cwd() / (
            f"daphne-deploy-campaign-{campaign_stamp}"
        )
        evidence_dir = evidence_dir.expanduser().resolve(strict=False)
        if evidence_dir.exists():
            raise CampaignError(f"evidence directory already exists: {evidence_dir}")
        evidence_dir.mkdir(parents=True)
        (
            deploy_script,
            bundle,
            config_snapshots,
            input_snapshot,
        ) = snapshot_inputs(
            evidence_dir,
            csv_path,
            campaign_bytes,
            deploy_source,
            deploy_bytes,
            bundle_source,
            bundle_evidence,
            targets,
        )
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    summary: dict[str, object] = {
        "contract": "daphne.deploy-campaign",
        "version": 1,
        "campaign_csv": str(csv_path),
        "campaign_csv_sha256": campaign_csv_sha256,
        "bundle": str(bundle),
        "bundle_source": str(bundle_source),
        "bundle_verification": bundle_evidence,
        "deploy_script": str(deploy_script),
        "deploy_script_source": str(deploy_source),
        "deploy_script_sha256": deploy_script_sha256,
        "input_snapshot": input_snapshot,
        "firmware_release": targets[0].firmware_release,
        "mode": "execute" if args.execute else "dry-run",
        "reboot": args.reboot,
        "continue_on_error": args.continue_on_error,
        "started_utc": utc_now(),
        "completed_utc": None,
        "status": "running",
        "total_boards": len(targets),
        "attempted_boards": 0,
        "succeeded_boards": 0,
        "staged_boards": 0,
        "dry_run_passed_boards": 0,
        "failed_boards": 0,
        "interrupted_boards": 0,
        "not_attempted_boards": 0,
        "error": None,
        "evidence_scope": "deployment_only_not_qualification",
        "qualification": {
            "status": "not_performed",
            "required_for_release": True,
            "evidence": None,
            "note": (
                "A staged image is not release-qualified until the board is "
                "rebooted and post-boot health is recorded separately."
            ),
        },
        "boards": [],
    }
    summary_path = evidence_dir / "campaign-summary.json"
    console_write(
        f"Campaign mode: {summary['mode']}; boards: {len(targets)}; "
        f"evidence: {evidence_dir}\n"
    )
    console_write(
        "Bundle verification: "
        f"PASS ({bundle_evidence['verified_entries']} manifest entries)\n"
    )

    board_results: list[dict[str, object]] = []
    interrupted = False
    interrupted_exit_code = 130
    campaign_error: str | None = None
    success_status = "staged" if args.execute else "dry_run_passed"
    bundle_manifest = bundle / "SHA256SUMS"
    bundle_manifest_sha256 = str(
        dict(input_snapshot["bundle"])["snapshot_manifest_sha256"]
    )
    handled_signals = [signal.SIGTERM]
    if hasattr(signal, "SIGHUP"):
        handled_signals.append(signal.SIGHUP)
    previous_handlers = {
        signum: signal.signal(signum, raise_campaign_signal)
        for signum in handled_signals
    }
    try:
        for target in targets:
            board_config = config_snapshots[target.index]
            verify_launch_inputs(
                target,
                board_config,
                bundle_manifest,
                bundle_manifest_sha256,
                deploy_script,
                deploy_script_sha256,
            )
            command = deploy_command(
                deploy_script,
                target,
                bundle,
                board_config,
                args.execute,
                args.reboot,
            )
            log_path = evidence_dir / f"{target.index:03d}-{target.board}.log"
            board_results.append(
                {
                    **board_identity(target, board_config),
                    "command": command,
                    "log": log_path.name,
                    "log_sha256": None,
                    "started_utc": utc_now(),
                    "completed_utc": None,
                    "duration_seconds": None,
                    "return_code": None,
                    "status": "active",
                }
            )
            console_write(f"Starting {target.board} ({target.host})\n")
            result = run_board(
                command, target, board_config, log_path, success_status
            )
            board_results[-1] = result
            if result["status"] == "interrupted":
                interrupted = True
                interrupted_exit_code = int(result["return_code"])
                break
            if result["status"] == "failed" and not args.continue_on_error:
                break
    except KeyboardInterrupt:
        interrupted = True
        print("Campaign interrupted", file=sys.stderr)
    except CampaignSignal as exc:
        interrupted = True
        interrupted_exit_code = 128 + exc.signum
        print("Campaign interrupted", file=sys.stderr)
    except (CampaignError, OSError, UnicodeError, subprocess.SubprocessError) as exc:
        campaign_error = str(exc)
        print(f"ERROR: {exc}", file=sys.stderr)
    finally:
        for signum, previous_handler in previous_handlers.items():
            signal.signal(signum, previous_handler)

    if board_results and board_results[-1]["status"] == "active":
        active = board_results[-1]
        active_log = evidence_dir / str(active["log"])
        active.update(
            {
                "log_sha256": (
                    sha256_file(active_log) if active_log.is_file() else None
                ),
                "completed_utc": utc_now(),
                "return_code": interrupted_exit_code if interrupted else 1,
                "status": "interrupted" if interrupted else "failed",
            }
        )

    attempted = len(board_results)
    for target in targets[attempted:]:
        board_results.append(
            {
                **board_identity(target, config_snapshots[target.index]),
                "command": None,
                "log": None,
                "log_sha256": None,
                "started_utc": None,
                "completed_utc": None,
                "duration_seconds": None,
                "return_code": None,
                "status": "not_attempted",
            }
        )

    succeeded = sum(result["status"] == "succeeded" for result in board_results)
    staged = sum(result["status"] == "staged" for result in board_results)
    dry_run_passed = sum(
        result["status"] == "dry_run_passed" for result in board_results
    )
    failed = sum(result["status"] == "failed" for result in board_results)
    interrupted_count = sum(
        result["status"] == "interrupted" for result in board_results
    )
    not_attempted = sum(
        result["status"] == "not_attempted" for result in board_results
    )
    summary.update(
        {
            "completed_utc": utc_now(),
            "status": (
                "interrupted"
                if interrupted
                else "failed"
                if failed or campaign_error
                else success_status
            ),
            "attempted_boards": attempted,
            "succeeded_boards": succeeded,
            "staged_boards": staged,
            "dry_run_passed_boards": dry_run_passed,
            "failed_boards": failed,
            "interrupted_boards": interrupted_count,
            "not_attempted_boards": not_attempted,
            "error": campaign_error,
            "boards": board_results,
        }
    )
    write_summary(summary_path, summary)
    console_write(f"Campaign evidence: {summary_path}\n")

    if interrupted:
        return interrupted_exit_code
    return 1 if failed or campaign_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
