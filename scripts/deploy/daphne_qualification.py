#!/usr/bin/env python3
"""Create and verify per-board DAPHNE hardware qualification records.

The record is deliberately separate from deployment evidence: staging an image is
not hardware qualification.  ``init`` binds one staged board to the exact
deployment campaign and release compatibility files.  Operators then fill the
site acceptance values, gate observations, evidence references, and review.
``check`` verifies those source bindings and every referenced evidence file.

Exit status:
  0  input is valid and the board is release-qualified
  1  input is valid, but qualification is incomplete or has failed
  2  invalid input, broken binding, bad evidence, or another operational error
"""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import math
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CONTRACT = "daphne.hardware-qualification"
CONTRACT_VERSION = 1
SCHEMA_REFERENCE = "schemas/daphne-hardware-qualification-v1.schema.json"
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
BUILD_ID_RE = re.compile(r"^0x[0-9A-Fa-f]{8}$")
HOST_FINGERPRINT_RE = re.compile(r"^SHA256:[A-Za-z0-9+/]{43}$")
UTC_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]+)?Z$"
)
PROFILE_SEQUENCE = ("self-trigger", "full-stream", "self-trigger")
GATE_IDS = (
    "postboot_identity",
    "switch_cycle_1_self_full_self",
    "switch_cycle_2_self_full_self",
    "failed_load_rollback",
    "self_trigger_data",
    "full_stream_data_channel_mapping",
    "four_link_ethernet",
)
GATE_STATUSES = {"NOT_RUN", "PASS", "FAIL"}
QUALIFICATION_STATUSES = {"NOT_RUN", "IN_PROGRESS", "FAIL", "PASS"}
REQUIRED_RELEASE_ARTIFACTS = {
    "petalinux_image",
    "self_trigger_build",
    "full_stream_build",
    "server_runtime",
    "client_install",
}


class QualificationError(ValueError):
    """A cleanly reportable contract or input error."""


class DuplicateKeyError(QualificationError):
    """JSON objects may not silently replace a duplicate member."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> Any:
    raise QualificationError(f"non-finite JSON number is forbidden: {value}")


def load_json(path: Path, label: str) -> tuple[dict[str, Any], str]:
    try:
        resolved = path.expanduser().resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise QualificationError(f"cannot open {label}: {path}: {exc}") from exc
    if resolved.is_symlink() or not resolved.is_file():
        raise QualificationError(f"{label} is not a regular file: {resolved}")
    try:
        value = json.loads(
            resolved.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, DuplicateKeyError) as exc:
        raise QualificationError(f"invalid {label}: {resolved}: {exc}") from exc
    if not isinstance(value, dict):
        raise QualificationError(f"{label} must contain a JSON object: {resolved}")
    return value, sha256_file(resolved)


def require_dict(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise QualificationError(f"{label} must be an object")
    return value


def require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise QualificationError(f"{label} must be an array")
    return value


def require_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise QualificationError(f"{label} must be a non-empty string")
    return value


def require_hash(value: Any, label: str) -> str:
    if not isinstance(value, str) or HASH_RE.fullmatch(value) is None:
        raise QualificationError(f"{label} must be a lowercase SHA-256")
    return value


def require_host_fingerprint(value: Any, label: str) -> str:
    if not isinstance(value, str) or HOST_FINGERPRINT_RE.fullmatch(value) is None:
        raise QualificationError(
            f"{label} must use OpenSSH SHA256:<43-base64-characters> format"
        )
    return value


def require_exact_integer(value: Any, expected: int, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value != expected:
        raise QualificationError(f"{label} must be integer {expected}")
    return value


def require_build_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or BUILD_ID_RE.fullmatch(value) is None:
        raise QualificationError(f"{label} must be an eight-digit hexadecimal build ID")
    return value


def require_utc(value: Any, label: str) -> str:
    text = require_string(value, label)
    if UTC_RE.fullmatch(text) is None:
        raise QualificationError(
            f"{label} must use YYYY-MM-DDTHH:MM:SS[.fraction]Z UTC format"
        )
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as exc:
        raise QualificationError(
            f"{label} must use YYYY-MM-DDTHH:MM:SS[.fraction]Z UTC format"
        ) from exc
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise QualificationError(
            f"{label} must use YYYY-MM-DDTHH:MM:SS[.fraction]Z UTC format"
        )
    return text


def utc_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value[:-1] + "+00:00")


def _artifact_hashes(compatibility: dict[str, Any]) -> dict[str, str]:
    artifacts = require_dict(compatibility.get("artifacts"), "release.artifacts")
    missing = sorted(REQUIRED_RELEASE_ARTIFACTS - artifacts.keys())
    if missing:
        raise QualificationError(
            "release.artifacts is missing required entries: " + ", ".join(missing)
        )
    hashes: dict[str, str] = {}
    for name, raw in sorted(artifacts.items()):
        artifact = require_dict(raw, f"release.artifacts.{name}")
        hashes[name] = require_hash(
            artifact.get("sha256"), f"release.artifacts.{name}.sha256"
        )
    return hashes


def release_binding(
    compatibility: dict[str, Any], source_path: Path, source_sha256: str
) -> dict[str, Any]:
    if compatibility.get("contract") != "daphne.dual-gateware-release":
        raise QualificationError(
            "release compatibility contract must be daphne.dual-gateware-release"
        )
    require_exact_integer(
        compatibility.get("contract_version"),
        1,
        "release compatibility contract_version",
    )
    profiles = require_dict(compatibility.get("profiles"), "release.profiles")
    self_profile = require_dict(profiles.get("self-trigger"), "self-trigger profile")
    full_profile = require_dict(profiles.get("full-stream"), "full-stream profile")
    artifacts = require_dict(compatibility.get("artifacts"), "release.artifacts")
    petalinux_image = require_dict(
        artifacts.get("petalinux_image"), "release.artifacts.petalinux_image"
    )
    return {
        "path": str(source_path.expanduser().resolve(strict=True)),
        "sha256": source_sha256,
        "contract": compatibility["contract"],
        "contract_version": 1,
        "release_id": require_string(compatibility.get("release_id"), "release_id"),
        "lifecycle": require_string(compatibility.get("lifecycle"), "lifecycle"),
        "self_trigger_build_id": require_build_id(
            self_profile.get("build_id"), "profiles.self-trigger.build_id"
        ),
        "full_stream_build_id": require_build_id(
            full_profile.get("build_id"), "profiles.full-stream.build_id"
        ),
        "petalinux_rootfs_ext4_sha256": require_hash(
            petalinux_image.get("rootfs_ext4_sha256"),
            "release.artifacts.petalinux_image.rootfs_ext4_sha256",
        ),
        "petalinux_bundle_manifest_sha256": require_hash(
            petalinux_image.get("bundle_manifest_sha256"),
            "release.artifacts.petalinux_image.bundle_manifest_sha256",
        ),
        "artifact_sha256": _artifact_hashes(compatibility),
    }


def _verify_deployment_log(summary_path: Path, board: dict[str, Any]) -> None:
    log_name = require_string(board.get("log"), "deployment.log")
    log_path = Path(log_name)
    if log_path.is_absolute() or ".." in log_path.parts:
        raise QualificationError("deployment.log must be relative to campaign-summary.json")
    campaign_root = summary_path.expanduser().resolve(strict=True).parent
    candidate = campaign_root / log_path
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(campaign_root)
    except ValueError as exc:
        raise QualificationError(
            f"deployment log escapes the campaign-summary directory: {log_name}"
        ) from exc
    except (OSError, RuntimeError) as exc:
        raise QualificationError(
            f"deployment log is missing or inaccessible: {candidate}: {exc}"
        ) from exc
    if candidate.is_symlink() or not resolved.is_file():
        raise QualificationError(
            f"deployment log is a symlink or not regular: {candidate}"
        )
    expected = require_hash(board.get("log_sha256"), "deployment.log_sha256")
    actual = sha256_file(resolved)
    if actual != expected:
        raise QualificationError(
            f"deployment log SHA-256 mismatch: expected {expected}, got {actual}"
        )


def campaign_binding(
    summary: dict[str, Any], source_path: Path, source_sha256: str, board_id: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    if summary.get("contract") != "daphne.deploy-campaign":
        raise QualificationError("campaign contract must be daphne.deploy-campaign")
    require_exact_integer(summary.get("version"), 1, "campaign version")
    if summary.get("mode") != "execute" or summary.get("status") != "staged":
        raise QualificationError(
            "campaign must be completed execute-mode staging (mode=execute, status=staged)"
        )
    if summary.get("reboot") is not False:
        raise QualificationError("a staged qualification campaign must record reboot=false")
    campaign_release = require_string(
        summary.get("firmware_release"), "campaign.firmware_release"
    )
    completed_utc = require_utc(summary.get("completed_utc"), "campaign.completed_utc")
    boards = require_list(summary.get("boards"), "campaign.boards")
    matching = [board for board in boards if isinstance(board, dict) and board.get("board") == board_id]
    if len(matching) != 1:
        raise QualificationError(
            f"campaign must contain exactly one board entry named {board_id!r}; found {len(matching)}"
        )
    deployment = matching[0]
    if deployment.get("status") != "staged" or deployment.get("return_code") != 0:
        raise QualificationError(f"board {board_id!r} was not staged successfully")
    if deployment.get("release_qualified") is not False:
        raise QualificationError("deployment entry must not claim release qualification")
    deployment_release = require_string(
        deployment.get("firmware_release"), "deployment.firmware_release"
    )
    if deployment_release != campaign_release:
        raise QualificationError(
            "deployment.firmware_release does not match campaign.firmware_release"
        )
    require_string(deployment.get("host"), "deployment.host")
    require_host_fingerprint(
        deployment.get("host_key_sha256"), "deployment.host_key_sha256"
    )
    require_dict(deployment.get("board_config_sha256"), "deployment.board_config_sha256")
    for name, digest in deployment["board_config_sha256"].items():
        require_string(name, "deployment.board_config_sha256 key")
        require_hash(digest, f"deployment.board_config_sha256.{name}")
    _verify_deployment_log(source_path, deployment)

    verification = require_dict(
        summary.get("bundle_verification"), "campaign.bundle_verification"
    )
    bundle_hashes_raw = require_dict(
        verification.get("artifacts_sha256"),
        "campaign.bundle_verification.artifacts_sha256",
    )
    bundle_hashes = {
        require_string(name, "bundle artifact name"): require_hash(
            digest, f"bundle artifact {name}"
        )
        for name, digest in sorted(bundle_hashes_raw.items())
    }
    if not bundle_hashes:
        raise QualificationError("campaign bundle artifact hash set must not be empty")
    binding = {
        "path": str(source_path.expanduser().resolve(strict=True)),
        "sha256": source_sha256,
        "contract": summary["contract"],
        "version": 1,
        "mode": summary["mode"],
        "status": summary["status"],
        "firmware_release": campaign_release,
        "completed_utc": completed_utc,
        "campaign_csv_sha256": require_hash(
            summary.get("campaign_csv_sha256"), "campaign.campaign_csv_sha256"
        ),
        "deploy_script_sha256": require_hash(
            summary.get("deploy_script_sha256"), "campaign.deploy_script_sha256"
        ),
        "bundle_manifest_sha256": require_hash(
            verification.get("manifest_sha256"),
            "campaign.bundle_verification.manifest_sha256",
        ),
        "bundle_artifact_sha256": bundle_hashes,
    }
    return binding, json.loads(json.dumps(deployment))


def require_release_alignment(
    campaign: dict[str, Any], deployment: dict[str, Any], release: dict[str, Any]
) -> None:
    release_id = require_string(release.get("release_id"), "release.release_id")
    campaign_release = require_string(
        campaign.get("firmware_release"), "campaign.firmware_release"
    )
    deployment_release = require_string(
        deployment.get("firmware_release"), "deployment.firmware_release"
    )
    if campaign_release != release_id:
        raise QualificationError(
            "campaign.firmware_release does not match release.release_id"
        )
    if deployment_release != release_id:
        raise QualificationError(
            "deployment.firmware_release does not match release.release_id"
        )
    bundle_hashes = require_dict(
        campaign.get("bundle_artifact_sha256"),
        "campaign.bundle_artifact_sha256",
    )
    staged_rootfs = require_hash(
        bundle_hashes.get("rootfs/rootfs.ext4"),
        "campaign.bundle_artifact_sha256.rootfs/rootfs.ext4",
    )
    release_rootfs = require_hash(
        release.get("petalinux_rootfs_ext4_sha256"),
        "release.petalinux_rootfs_ext4_sha256",
    )
    if staged_rootfs != release_rootfs:
        raise QualificationError(
            "staged rootfs/rootfs.ext4 SHA-256 does not match the release "
            "PetaLinux rootfs_ext4_sha256"
        )
    campaign_manifest = require_hash(
        campaign.get("bundle_manifest_sha256"),
        "campaign.bundle_manifest_sha256",
    )
    release_manifest = require_hash(
        release.get("petalinux_bundle_manifest_sha256"),
        "release.petalinux_bundle_manifest_sha256",
    )
    if campaign_manifest != release_manifest:
        raise QualificationError(
            "staged bundle manifest SHA-256 does not match the release "
            "PetaLinux bundle_manifest_sha256"
        )


def initial_gate(gate_id: str) -> dict[str, Any]:
    return {
        "id": gate_id,
        "status": "NOT_RUN",
        "evidence": [],
        "observed": None,
        "notes": None,
    }


def build_initial_record(
    summary: dict[str, Any],
    summary_path: Path,
    summary_sha256: str,
    board_id: str,
    compatibility: dict[str, Any],
    compatibility_path: Path,
    compatibility_sha256: str,
) -> dict[str, Any]:
    campaign, deployment = campaign_binding(
        summary, summary_path, summary_sha256, board_id
    )
    release = release_binding(
        compatibility, compatibility_path, compatibility_sha256
    )
    require_release_alignment(campaign, deployment, release)
    return {
        "$schema": SCHEMA_REFERENCE,
        "contract": CONTRACT,
        "version": CONTRACT_VERSION,
        "created_utc": utc_now(),
        "qualification_status": "NOT_RUN",
        "release_qualified": False,
        "binding": {
            "campaign": campaign,
            "deployment": deployment,
            "release": release,
        },
        "acceptance": {
            "daq": {
                "command_argv": None,
                "config": {"path": None, "sha256": None},
            },
            "ethernet": {
                "minimum_duration_seconds": None,
                "minimum_counter_deltas": None,
                "maximum_error_deltas": None,
            },
        },
        "gates": [initial_gate(gate_id) for gate_id in GATE_IDS],
        "review": {
            "status": "NOT_RUN",
            "reviewer": None,
            "approved_utc": None,
            "evidence": [],
            "notes": None,
        },
    }


def atomic_create_json(path: Path, value: dict[str, Any]) -> None:
    lexical = path.expanduser()
    if lexical.name in {"", ".", ".."}:
        raise QualificationError(f"output must name a new regular file: {path}")
    try:
        parent = lexical.parent.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise QualificationError(
            f"output parent directory is unavailable: {lexical.parent}: {exc}"
        ) from exc
    if not parent.is_dir():
        raise QualificationError(f"output parent directory does not exist: {parent}")
    target = parent / lexical.name
    if os.path.lexists(target):
        raise QualificationError(f"refusing to overwrite existing output: {target}")
    payload = (json.dumps(value, indent=2, sort_keys=False) + "\n").encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o644)
        try:
            os.link(temporary, target)
        except OSError as exc:
            if exc.errno == errno.EEXIST:
                raise QualificationError(f"refusing to overwrite existing output: {target}") from exc
            raise QualificationError(f"cannot create output {target}: {exc}") from exc
        directory_fd = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _error(errors: list[str], message: str) -> None:
    errors.append(message)


def _valid_hash(value: Any) -> bool:
    return isinstance(value, str) and HASH_RE.fullmatch(value) is not None


def _valid_build_id(value: Any) -> bool:
    return isinstance(value, str) and BUILD_ID_RE.fullmatch(value) is not None


def _is_nonnegative_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return value >= 0
    return isinstance(value, float) and math.isfinite(value) and value >= 0


def _is_positive_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return value > 0
    return isinstance(value, float) and math.isfinite(value) and value > 0


def _safe_evidence_path(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    path = Path(value)
    return not path.is_absolute() and ".." not in path.parts and path != Path(".")


def _verify_evidence_reference(
    reference: Any, record_dir: Path, label: str, errors: list[str]
) -> None:
    if not isinstance(reference, dict) or set(reference) != {"path", "sha256"}:
        _error(errors, f"{label} must contain exactly path and sha256")
        return
    path_text = reference.get("path")
    expected = reference.get("sha256")
    if not _safe_evidence_path(path_text):
        _error(errors, f"{label}.path must be a safe relative evidence path")
        return
    if not _valid_hash(expected):
        _error(errors, f"{label}.sha256 must be a lowercase SHA-256")
        return
    candidate = record_dir / str(path_text)
    try:
        resolved_root = record_dir.resolve(strict=True)
        resolved_candidate = candidate.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        _error(errors, f"{label}.path is missing or inaccessible: {path_text}: {exc}")
        return
    try:
        resolved_candidate.relative_to(resolved_root)
    except ValueError:
        _error(errors, f"{label}.path escapes the qualification record directory: {path_text}")
        return
    if candidate.is_symlink() or not resolved_candidate.is_file():
        _error(errors, f"{label}.path is a symlink or not a regular file: {path_text}")
        return
    try:
        actual = sha256_file(resolved_candidate)
    except OSError as exc:
        _error(errors, f"cannot hash {label}.path {path_text}: {exc}")
        return
    if actual != expected:
        _error(
            errors,
            f"SHA-256 mismatch at {label} for {path_text}: expected {expected}, got {actual}",
        )


def _validate_evidence(
    value: Any,
    performed: bool,
    record_dir: Path,
    label: str,
    errors: list[str],
) -> None:
    if not isinstance(value, list):
        _error(errors, f"{label} must be an array")
        return
    if performed and not value:
        _error(errors, f"{label} must contain evidence for a performed gate")
    if not performed and value:
        _error(errors, f"{label} must be empty while status is NOT_RUN")
    seen: set[str] = set()
    for index, reference in enumerate(value):
        _verify_evidence_reference(reference, record_dir, f"{label}[{index}]", errors)
        if isinstance(reference, dict) and isinstance(reference.get("path"), str):
            path = reference["path"]
            if path in seen:
                _error(errors, f"{label} contains duplicate evidence path: {path}")
            seen.add(path)


def _validate_command(value: Any, label: str, errors: list[str]) -> bool:
    if not isinstance(value, list) or not value:
        _error(errors, f"{label} must be a non-empty argv array")
        return False
    valid = True
    for index, token in enumerate(value):
        if not isinstance(token, str) or not token or "\x00" in token:
            _error(errors, f"{label}[{index}] must be a non-empty string without NUL")
            valid = False
    return valid


def _validate_profile_identity(
    entry: Any,
    profile: str,
    expected_build_id: str,
    label: str,
    errors: list[str],
    switch_step: bool = False,
) -> None:
    if not isinstance(entry, dict):
        _error(errors, f"{label} must be an object")
        return
    required = {"profile", "build_id", "server_mode", "service_active"}
    if switch_step:
        required.add("switch_exit_code")
    missing = sorted(required - entry.keys())
    if missing:
        _error(errors, f"{label} missing: {', '.join(missing)}")
        return
    if entry.get("profile") != profile:
        _error(errors, f"{label}.profile must be {profile}")
    if entry.get("build_id") != expected_build_id:
        _error(errors, f"{label}.build_id does not match the bound {profile} build")
    if entry.get("server_mode") != profile:
        _error(errors, f"{label}.server_mode must be {profile}")
    if entry.get("service_active") is not True:
        _error(errors, f"{label}.service_active must be true")
    if switch_step and entry.get("switch_exit_code") != 0:
        _error(errors, f"{label}.switch_exit_code must be zero")


def _validate_postboot(
    observed: Any, self_id: str, full_id: str, errors: list[str]
) -> None:
    if not isinstance(observed, dict) or set(observed) != {"profiles"}:
        _error(errors, "postboot_identity.observed must contain exactly profiles")
        return
    profiles = observed.get("profiles")
    if not isinstance(profiles, list) or len(profiles) != 2:
        _error(errors, "postboot_identity.observed.profiles must contain two profiles")
        return
    by_profile: dict[str, Any] = {}
    for entry in profiles:
        if isinstance(entry, dict) and isinstance(entry.get("profile"), str):
            if entry["profile"] in by_profile:
                _error(errors, f"postboot_identity has duplicate profile {entry['profile']}")
            by_profile[entry["profile"]] = entry
    for profile, build_id in (("self-trigger", self_id), ("full-stream", full_id)):
        _validate_profile_identity(
            by_profile.get(profile),
            profile,
            build_id,
            f"postboot_identity.{profile}",
            errors,
        )


def _validate_switch_cycle(
    gate_id: str, observed: Any, self_id: str, full_id: str, errors: list[str]
) -> None:
    if not isinstance(observed, dict) or set(observed) != {"sequence"}:
        _error(errors, f"{gate_id}.observed must contain exactly sequence")
        return
    sequence = observed.get("sequence")
    if not isinstance(sequence, list) or len(sequence) != 3:
        _error(errors, f"{gate_id}.sequence must contain exactly three steps")
        return
    build_ids = (self_id, full_id, self_id)
    for index, (profile, build_id) in enumerate(zip(PROFILE_SEQUENCE, build_ids)):
        _validate_profile_identity(
            sequence[index],
            profile,
            build_id,
            f"{gate_id}.sequence[{index}]",
            errors,
            switch_step=True,
        )


def _validate_rollback(
    observed: Any, self_id: str, errors: list[str]
) -> None:
    required = {
        "attempted_profile",
        "failure_observed",
        "switch_exit_code",
        "restored_profile",
        "restored_build_id",
        "server_mode",
        "service_active",
    }
    if not isinstance(observed, dict) or set(observed) != required:
        _error(
            errors,
            "failed_load_rollback.observed must contain exactly " + ", ".join(sorted(required)),
        )
        return
    if observed.get("attempted_profile") != "full-stream":
        _error(errors, "failed_load_rollback.attempted_profile must be full-stream")
    if observed.get("failure_observed") is not True:
        _error(errors, "failed_load_rollback.failure_observed must be true")
    code = observed.get("switch_exit_code")
    if not isinstance(code, int) or isinstance(code, bool) or code == 0:
        _error(errors, "failed_load_rollback.switch_exit_code must be a nonzero integer")
    if observed.get("restored_profile") != "self-trigger":
        _error(errors, "failed_load_rollback.restored_profile must be self-trigger")
    if observed.get("restored_build_id") != self_id:
        _error(errors, "failed_load_rollback.restored_build_id does not match the bound self-trigger build")
    if observed.get("server_mode") != "self-trigger":
        _error(errors, "failed_load_rollback.server_mode must be self-trigger")
    if observed.get("service_active") is not True:
        _error(errors, "failed_load_rollback.service_active must be true")


def _validate_daq_common(
    observed: Any,
    acceptance_daq: dict[str, Any],
    gate_id: str,
    errors: list[str],
) -> bool:
    if not isinstance(observed, dict):
        _error(errors, f"{gate_id}.observed must be an object")
        return False
    if observed.get("daq_command_argv") != acceptance_daq.get("command_argv"):
        _error(errors, f"{gate_id}.daq_command_argv does not match acceptance.daq")
    if observed.get("daq_config") != acceptance_daq.get("config"):
        _error(errors, f"{gate_id}.daq_config does not match acceptance.daq")
    if not _is_positive_number(observed.get("data_units")):
        _error(errors, f"{gate_id}.data_units must be positive")
    errors_seen = observed.get("errors")
    if not isinstance(errors_seen, int) or isinstance(errors_seen, bool) or errors_seen != 0:
        _error(errors, f"{gate_id}.errors must be integer zero")
    return True


def _validate_self_data(
    observed: Any, acceptance_daq: dict[str, Any], errors: list[str]
) -> None:
    required = {"daq_command_argv", "daq_config", "data_units", "errors"}
    if isinstance(observed, dict) and set(observed) != required:
        _error(errors, "self_trigger_data.observed has missing or unknown fields")
    _validate_daq_common(observed, acceptance_daq, "self_trigger_data", errors)


def _valid_channel_list(value: Any) -> bool:
    return (
        isinstance(value, list)
        and 1 <= len(value) <= 32
        and all(isinstance(item, int) and not isinstance(item, bool) and 0 <= item <= 39 for item in value)
        and len(set(value)) == len(value)
    )


def _validate_full_data(
    observed: Any, acceptance_daq: dict[str, Any], errors: list[str]
) -> None:
    required = {
        "daq_command_argv",
        "daq_config",
        "data_units",
        "errors",
        "configured_channels",
        "observed_channels",
        "mapping_errors",
    }
    if isinstance(observed, dict) and set(observed) != required:
        _error(errors, "full_stream_data_channel_mapping.observed has missing or unknown fields")
    if not _validate_daq_common(
        observed, acceptance_daq, "full_stream_data_channel_mapping", errors
    ):
        return
    configured = observed.get("configured_channels")
    observed_channels = observed.get("observed_channels")
    if not _valid_channel_list(configured):
        _error(errors, "full_stream_data_channel_mapping.configured_channels must contain 1-32 unique channels 0-39")
    if not _valid_channel_list(observed_channels):
        _error(errors, "full_stream_data_channel_mapping.observed_channels must contain 1-32 unique channels 0-39")
    if _valid_channel_list(configured) and _valid_channel_list(observed_channels):
        if configured != observed_channels:
            _error(
                errors,
                "full_stream_data_channel_mapping observed channels do not "
                "match configured channels in order",
            )
    mapping_errors = observed.get("mapping_errors")
    if not isinstance(mapping_errors, int) or isinstance(mapping_errors, bool) or mapping_errors != 0:
        _error(errors, "full_stream_data_channel_mapping.mapping_errors must be integer zero")


def _validate_threshold_map(
    value: Any, label: str, errors: list[str]
) -> dict[str, int | float] | None:
    if value is None:
        return None
    if not isinstance(value, dict) or not value:
        _error(errors, f"{label} must be null or a non-empty object")
        return None
    result: dict[str, int | float] = {}
    for key, threshold in value.items():
        if not isinstance(key, str) or not key:
            _error(errors, f"{label} names must be non-empty strings")
            continue
        if not _is_nonnegative_number(threshold):
            _error(errors, f"{label}.{key} must be nonnegative")
            continue
        result[key] = threshold
    return result


def _validate_ethernet(
    observed: Any, acceptance: dict[str, Any], errors: list[str]
) -> None:
    if not isinstance(observed, dict) or set(observed) != {"links"}:
        _error(errors, "four_link_ethernet.observed must contain exactly links")
        return
    links = observed.get("links")
    if not isinstance(links, list) or len(links) != 4:
        _error(errors, "four_link_ethernet.links must contain exactly four links")
        return
    minimum_duration = acceptance.get("minimum_duration_seconds")
    minimum_counters = acceptance.get("minimum_counter_deltas")
    maximum_errors = acceptance.get("maximum_error_deltas")
    seen: set[str] = set()
    required = {"link_id", "link_up", "duration_seconds", "counter_deltas", "error_deltas"}
    for index, link in enumerate(links):
        label = f"four_link_ethernet.links[{index}]"
        if not isinstance(link, dict) or set(link) != required:
            _error(errors, f"{label} has missing or unknown fields")
            continue
        link_id = link.get("link_id")
        if not isinstance(link_id, str) or not link_id:
            _error(errors, f"{label}.link_id must be a non-empty string")
        elif link_id in seen:
            _error(errors, f"four_link_ethernet has duplicate link_id {link_id}")
        else:
            seen.add(link_id)
        if link.get("link_up") is not True:
            _error(errors, f"{label}.link_up must be true")
        duration = link.get("duration_seconds")
        if not _is_positive_number(duration):
            _error(errors, f"{label}.duration_seconds must be positive")
        elif _is_positive_number(minimum_duration) and duration < minimum_duration:
            _error(errors, f"{label}.duration_seconds is below the accepted minimum")
        for member, thresholds, comparator in (
            ("counter_deltas", minimum_counters, "minimum"),
            ("error_deltas", maximum_errors, "maximum"),
        ):
            values = link.get(member)
            if not isinstance(values, dict):
                _error(errors, f"{label}.{member} must be an object")
                continue
            for name, value in values.items():
                if not isinstance(name, str) or not name or not _is_nonnegative_number(value):
                    _error(errors, f"{label}.{member} must map names to nonnegative values")
            if isinstance(thresholds, dict):
                if set(values) != set(thresholds):
                    _error(errors, f"{label}.{member} names must exactly match acceptance thresholds")
                    continue
                for name, threshold in thresholds.items():
                    value = values.get(name)
                    if not _is_nonnegative_number(value) or not _is_nonnegative_number(
                        threshold
                    ):
                        continue
                    if comparator == "minimum" and value < threshold:
                        _error(errors, f"{label}.{member}.{name} is below its accepted minimum")
                    if comparator == "maximum" and value > threshold:
                        _error(errors, f"{label}.{member}.{name} exceeds its accepted maximum")


def validate_record_shape(
    record: dict[str, Any], record_path: Path
) -> tuple[list[str], list[str], str, bool]:
    """Validate intrinsic structure/evidence and derive qualification state.

    Returns ``(errors, reasons, derived_status, qualified)``.  Source-file
    binding checks are intentionally performed separately by ``check``.
    """

    errors: list[str] = []
    reasons: list[str] = []
    record_dir = record_path.expanduser().resolve(strict=False).parent
    allowed_top = {
        "$schema",
        "contract",
        "version",
        "created_utc",
        "qualification_status",
        "release_qualified",
        "binding",
        "acceptance",
        "gates",
        "review",
    }
    if set(record) != allowed_top:
        _error(errors, "record has missing or unknown top-level fields")
    if record.get("$schema") != SCHEMA_REFERENCE:
        _error(errors, f"$schema must be {SCHEMA_REFERENCE}")
    if record.get("contract") != CONTRACT:
        _error(errors, f"contract must be {CONTRACT}")
    if (
        not isinstance(record.get("version"), int)
        or isinstance(record.get("version"), bool)
        or record.get("version") != CONTRACT_VERSION
    ):
        _error(errors, f"version must be integer {CONTRACT_VERSION}")
    created_datetime: datetime | None = None
    try:
        created_utc = require_utc(record.get("created_utc"), "created_utc")
        created_datetime = utc_datetime(created_utc)
    except QualificationError as exc:
        _error(errors, str(exc))
    if (
        not isinstance(record.get("qualification_status"), str)
        or record.get("qualification_status") not in QUALIFICATION_STATUSES
    ):
        _error(errors, "qualification_status is invalid")
    if not isinstance(record.get("release_qualified"), bool):
        _error(errors, "release_qualified must be boolean")

    binding = record.get("binding")
    if not isinstance(binding, dict) or set(binding) != {"campaign", "deployment", "release"}:
        _error(errors, "binding must contain exactly campaign, deployment, and release")
        binding = {}
    campaign = binding.get("campaign") if isinstance(binding.get("campaign"), dict) else {}
    deployment = binding.get("deployment") if isinstance(binding.get("deployment"), dict) else {}
    release = binding.get("release") if isinstance(binding.get("release"), dict) else {}
    if not campaign:
        _error(errors, "binding.campaign must be an object")
    if not deployment:
        _error(errors, "binding.deployment must be an object")
    if not release:
        _error(errors, "binding.release must be an object")
    for source, label in ((campaign, "binding.campaign"), (release, "binding.release")):
        if not _valid_hash(source.get("sha256")):
            _error(errors, f"{label}.sha256 must be a lowercase SHA-256")
        if not isinstance(source.get("path"), str) or not source.get("path"):
            _error(errors, f"{label}.path must be a non-empty string")
    if campaign.get("contract") != "daphne.deploy-campaign":
        _error(errors, "binding.campaign.contract is invalid")
    if (
        not isinstance(campaign.get("version"), int)
        or isinstance(campaign.get("version"), bool)
        or campaign.get("version") != 1
    ):
        _error(errors, "binding.campaign.version must be integer 1")
    if release.get("contract") != "daphne.dual-gateware-release":
        _error(errors, "binding.release.contract is invalid")
    if (
        not isinstance(release.get("contract_version"), int)
        or isinstance(release.get("contract_version"), bool)
        or release.get("contract_version") != 1
    ):
        _error(errors, "binding.release.contract_version must be integer 1")
    if not isinstance(deployment.get("host_key_sha256"), str) or HOST_FINGERPRINT_RE.fullmatch(
        deployment.get("host_key_sha256", "")
    ) is None:
        _error(
            errors,
            "binding.deployment.host_key_sha256 must use "
            "SHA256:<43-base64-characters> format",
        )
    self_id = release.get("self_trigger_build_id")
    full_id = release.get("full_stream_build_id")
    if not _valid_build_id(self_id):
        _error(errors, "binding.release.self_trigger_build_id is invalid")
        self_id = ""
    if not _valid_build_id(full_id):
        _error(errors, "binding.release.full_stream_build_id is invalid")
        full_id = ""
    if not _valid_hash(release.get("petalinux_rootfs_ext4_sha256")):
        _error(
            errors,
            "binding.release.petalinux_rootfs_ext4_sha256 must be a lowercase SHA-256",
        )
    if not _valid_hash(release.get("petalinux_bundle_manifest_sha256")):
        _error(
            errors,
            "binding.release.petalinux_bundle_manifest_sha256 must be a lowercase SHA-256",
        )
    artifact_hashes = release.get("artifact_sha256")
    if not isinstance(artifact_hashes, dict) or not artifact_hashes:
        _error(errors, "binding.release.artifact_sha256 must be a non-empty object")
    else:
        missing = REQUIRED_RELEASE_ARTIFACTS - artifact_hashes.keys()
        if missing:
            _error(errors, "binding.release.artifact_sha256 missing: " + ", ".join(sorted(missing)))
        for name, digest in artifact_hashes.items():
            if not isinstance(name, str) or not name or not _valid_hash(digest):
                _error(errors, f"binding.release.artifact_sha256.{name} is invalid")
    try:
        require_release_alignment(campaign, deployment, release)
    except QualificationError as exc:
        _error(errors, str(exc))

    acceptance = record.get("acceptance")
    if not isinstance(acceptance, dict) or set(acceptance) != {"daq", "ethernet"}:
        _error(errors, "acceptance must contain exactly daq and ethernet")
        acceptance = {}
    daq = acceptance.get("daq") if isinstance(acceptance.get("daq"), dict) else {}
    ethernet = acceptance.get("ethernet") if isinstance(acceptance.get("ethernet"), dict) else {}
    if set(daq) != {"command_argv", "config"}:
        _error(errors, "acceptance.daq must contain exactly command_argv and config")
    command = daq.get("command_argv")
    command_resolved = command is not None
    if command is None:
        reasons.append("acceptance.daq.command_argv is unresolved")
    else:
        _validate_command(command, "acceptance.daq.command_argv", errors)
    config = daq.get("config")
    config_resolved = False
    if not isinstance(config, dict) or set(config) != {"path", "sha256"}:
        _error(errors, "acceptance.daq.config must contain exactly path and sha256")
        config = {}
    config_path, config_hash = config.get("path"), config.get("sha256")
    if config_path is None and config_hash is None:
        reasons.append("acceptance.daq.config is unresolved")
    elif config_path is None or config_hash is None:
        _error(errors, "acceptance.daq.config path and sha256 must both be null or both be set")
    else:
        config_resolved = True
        _verify_evidence_reference(config, record_dir, "acceptance.daq.config", errors)

    if set(ethernet) != {
        "minimum_duration_seconds",
        "minimum_counter_deltas",
        "maximum_error_deltas",
    }:
        _error(errors, "acceptance.ethernet has missing or unknown fields")
    minimum_duration = ethernet.get("minimum_duration_seconds")
    if minimum_duration is None:
        reasons.append("acceptance.ethernet.minimum_duration_seconds is unresolved")
    elif not _is_positive_number(minimum_duration):
        _error(errors, "acceptance.ethernet.minimum_duration_seconds must be positive or null")
    minimum_counters = _validate_threshold_map(
        ethernet.get("minimum_counter_deltas"),
        "acceptance.ethernet.minimum_counter_deltas",
        errors,
    )
    if ethernet.get("minimum_counter_deltas") is None:
        reasons.append("acceptance.ethernet.minimum_counter_deltas is unresolved")
    maximum_errors = _validate_threshold_map(
        ethernet.get("maximum_error_deltas"),
        "acceptance.ethernet.maximum_error_deltas",
        errors,
    )
    if ethernet.get("maximum_error_deltas") is None:
        reasons.append("acceptance.ethernet.maximum_error_deltas is unresolved")

    gates = record.get("gates")
    gate_by_id: dict[str, dict[str, Any]] = {}
    if not isinstance(gates, list):
        _error(errors, "gates must be an array")
        gates = []
    for index, gate in enumerate(gates):
        if not isinstance(gate, dict):
            _error(errors, f"gates[{index}] must be an object")
            continue
        if set(gate) != {"id", "status", "evidence", "observed", "notes"}:
            _error(errors, f"gates[{index}] has missing or unknown fields")
        gate_id = gate.get("id")
        if gate_id not in GATE_IDS:
            _error(errors, f"gates[{index}].id is not a defined hardware gate")
            continue
        if gate_id in gate_by_id:
            _error(errors, f"duplicate hardware gate id: {gate_id}")
        else:
            gate_by_id[gate_id] = gate
        status = gate.get("status")
        if not isinstance(status, str) or status not in GATE_STATUSES:
            _error(errors, f"{gate_id}.status must be NOT_RUN, PASS, or FAIL")
            status = "NOT_RUN"
        if gate.get("notes") is not None and not isinstance(gate.get("notes"), str):
            _error(errors, f"{gate_id}.notes must be a string or null")
        if gate.get("observed") is not None and not isinstance(
            gate.get("observed"), dict
        ):
            _error(errors, f"{gate_id}.observed must be an object or null")
        _validate_evidence(
            gate.get("evidence"), status in {"PASS", "FAIL"}, record_dir, f"{gate_id}.evidence", errors
        )
        if status == "NOT_RUN":
            if gate.get("observed") is not None:
                _error(errors, f"{gate_id}.observed must be null while NOT_RUN")
            reasons.append(f"gate {gate_id} is NOT_RUN")
        elif status == "FAIL":
            reasons.append(f"gate {gate_id} is FAIL")

    missing_gates = [gate_id for gate_id in GATE_IDS if gate_id not in gate_by_id]
    if missing_gates:
        _error(errors, "missing hardware gates: " + ", ".join(missing_gates))
    if len(gates) != len(GATE_IDS):
        _error(errors, f"gates must contain exactly {len(GATE_IDS)} entries")

    if gate_by_id.get("postboot_identity", {}).get("status") == "PASS":
        _validate_postboot(gate_by_id["postboot_identity"].get("observed"), self_id, full_id, errors)
    for gate_id in (
        "switch_cycle_1_self_full_self",
        "switch_cycle_2_self_full_self",
    ):
        if gate_by_id.get(gate_id, {}).get("status") == "PASS":
            _validate_switch_cycle(gate_id, gate_by_id[gate_id].get("observed"), self_id, full_id, errors)
    if gate_by_id.get("failed_load_rollback", {}).get("status") == "PASS":
        _validate_rollback(gate_by_id["failed_load_rollback"].get("observed"), self_id, errors)
    if gate_by_id.get("self_trigger_data", {}).get("status") == "PASS":
        _validate_self_data(gate_by_id["self_trigger_data"].get("observed"), daq, errors)
    if gate_by_id.get("full_stream_data_channel_mapping", {}).get("status") == "PASS":
        _validate_full_data(
            gate_by_id["full_stream_data_channel_mapping"].get("observed"), daq, errors
        )
    if gate_by_id.get("four_link_ethernet", {}).get("status") == "PASS":
        _validate_ethernet(gate_by_id["four_link_ethernet"].get("observed"), ethernet, errors)

    review = record.get("review")
    if not isinstance(review, dict) or set(review) != {
        "status",
        "reviewer",
        "approved_utc",
        "evidence",
        "notes",
    }:
        _error(errors, "review has missing or unknown fields")
        review = {}
    review_status = review.get("status")
    if not isinstance(review_status, str) or review_status not in GATE_STATUSES:
        _error(errors, "review.status must be NOT_RUN, PASS, or FAIL")
        review_status = "NOT_RUN"
    if review.get("notes") is not None and not isinstance(review.get("notes"), str):
        _error(errors, "review.notes must be a string or null")
    _validate_evidence(
        review.get("evidence"), review_status in {"PASS", "FAIL"}, record_dir, "review.evidence", errors
    )
    if review_status == "PASS":
        if not isinstance(review.get("reviewer"), str) or not review.get("reviewer", "").strip():
            _error(errors, "review.reviewer is required for approval")
        try:
            approved_utc = require_utc(
                review.get("approved_utc"), "review.approved_utc"
            )
            approved_datetime = utc_datetime(approved_utc)
            if (
                created_datetime is not None
                and approved_datetime < created_datetime
            ):
                _error(
                    errors,
                    "review.approved_utc must not be earlier than created_utc",
                )
        except QualificationError as exc:
            _error(errors, str(exc))
    elif review_status == "FAIL":
        reasons.append("reviewer approval is FAIL")
    else:
        reasons.append("reviewer approval is NOT_RUN")
        if review.get("reviewer") is not None or review.get("approved_utc") is not None:
            _error(errors, "reviewer and approved_utc must be null while review is NOT_RUN")

    all_gates_pass = len(gate_by_id) == len(GATE_IDS) and all(
        gate_by_id[gate_id].get("status") == "PASS" for gate_id in GATE_IDS
    )
    acceptance_resolved = (
        command_resolved
        and config_resolved
        and _is_positive_number(minimum_duration)
        and isinstance(minimum_counters, dict)
        and bool(minimum_counters)
        and isinstance(maximum_errors, dict)
        and bool(maximum_errors)
    )
    qualified = not errors and acceptance_resolved and all_gates_pass and review_status == "PASS"
    statuses = [gate.get("status") for gate in gate_by_id.values()]
    if qualified:
        derived_status = "PASS"
    elif "FAIL" in statuses or review_status == "FAIL":
        derived_status = "FAIL"
    elif statuses and all(status == "NOT_RUN" for status in statuses) and review_status == "NOT_RUN":
        derived_status = "NOT_RUN"
    else:
        derived_status = "IN_PROGRESS"

    if record.get("qualification_status") != derived_status:
        _error(
            errors,
            f"qualification_status must be {derived_status} for the recorded results",
        )
    if record.get("release_qualified") is not qualified:
        _error(errors, f"release_qualified must be {str(qualified).lower()} for the recorded results")
    qualified = qualified and not errors
    return errors, reasons, derived_status, qualified


def _without_path(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key != "path"}


def validate_source_bindings(
    record: dict[str, Any],
    campaign: dict[str, Any],
    campaign_path: Path,
    campaign_sha256: str,
    compatibility: dict[str, Any],
    compatibility_path: Path,
    compatibility_sha256: str,
) -> list[str]:
    errors: list[str] = []
    binding = record.get("binding")
    if not isinstance(binding, dict):
        return ["binding is unavailable for source verification"]
    bound_campaign = binding.get("campaign")
    deployment = binding.get("deployment")
    bound_release = binding.get("release")
    if not isinstance(bound_campaign, dict) or not isinstance(deployment, dict) or not isinstance(bound_release, dict):
        return ["binding campaign, deployment, and release must be objects"]
    board_id = deployment.get("board")
    if not isinstance(board_id, str) or not board_id:
        return ["binding.deployment.board must be a non-empty string"]
    try:
        expected_campaign, expected_deployment = campaign_binding(
            campaign, campaign_path, campaign_sha256, board_id
        )
        expected_release = release_binding(
            compatibility, compatibility_path, compatibility_sha256
        )
        require_release_alignment(
            expected_campaign, expected_deployment, expected_release
        )
    except QualificationError as exc:
        return [str(exc)]
    if bound_campaign.get("sha256") != campaign_sha256:
        errors.append("campaign-summary SHA-256 does not match the bound input")
    if _without_path(bound_campaign) != _without_path(expected_campaign):
        errors.append("campaign binding does not exactly match campaign-summary.json")
    if deployment != expected_deployment:
        errors.append("deployment identity does not exactly match the selected campaign board")
    if bound_release.get("sha256") != compatibility_sha256:
        errors.append("release COMPATIBILITY SHA-256 does not match the bound input")
    if _without_path(bound_release) != _without_path(expected_release):
        errors.append("release binding does not exactly match COMPATIBILITY.json")
    return errors


def init_command(args: argparse.Namespace) -> int:
    try:
        campaign_path = args.campaign_summary.expanduser().resolve(strict=True)
        compatibility_path = args.compatibility.expanduser().resolve(strict=True)
        campaign, campaign_sha = load_json(campaign_path, "campaign summary")
        compatibility, compatibility_sha = load_json(
            compatibility_path, "release COMPATIBILITY"
        )
        record = build_initial_record(
            campaign,
            campaign_path,
            campaign_sha,
            args.board,
            compatibility,
            compatibility_path,
            compatibility_sha,
        )
        atomic_create_json(args.output, record)
    except (QualificationError, OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(f"Created unqualified hardware record: {args.output}")
    print("Qualification status: NOT_RUN (release_qualified=false)")
    return 0


def check_command(args: argparse.Namespace) -> int:
    try:
        record_path = args.record.expanduser().resolve(strict=True)
        campaign_path = args.campaign_summary.expanduser().resolve(strict=True)
        compatibility_path = args.compatibility.expanduser().resolve(strict=True)
        record, _record_sha = load_json(record_path, "qualification record")
        campaign, campaign_sha = load_json(campaign_path, "campaign summary")
        compatibility, compatibility_sha = load_json(
            compatibility_path, "release COMPATIBILITY"
        )
        errors, reasons, _status, qualified = validate_record_shape(record, record_path)
        errors.extend(
            validate_source_bindings(
                record,
                campaign,
                campaign_path,
                campaign_sha,
                compatibility,
                compatibility_path,
                compatibility_sha,
            )
        )
    except (QualificationError, OSError, RuntimeError, ValueError) as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 2
    if errors:
        print("INVALID: hardware qualification record failed validation", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 2
    board = record["binding"]["deployment"]["board"]
    release_id = record["binding"]["release"]["release_id"]
    print(f"VALID: {board} is bound to release {release_id}")
    if qualified:
        print("QUALIFIED: all hardware gates and reviewer approval PASS")
        return 0
    print("NOT QUALIFIED: the record is valid but does not pass release qualification")
    for reason in dict.fromkeys(reasons):
        print(f"  - {reason}")
    return 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "exit status: 0 = valid and qualified (or init succeeded); "
            "1 = valid but not qualified; 2 = invalid/error\n\n"
            "check always requires the original frozen campaign-summary and "
            "COMPATIBILITY files and verifies every recorded evidence SHA-256."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    init_parser = subparsers.add_parser(
        "init",
        help="atomically create a NOT_RUN record for one successfully staged board",
    )
    init_parser.add_argument("--campaign-summary", type=Path, required=True)
    init_parser.add_argument("--board", required=True, help="exact campaign board ID")
    init_parser.add_argument(
        "--compatibility", type=Path, required=True, help="frozen release COMPATIBILITY.json"
    )
    init_parser.add_argument("--output", type=Path, required=True)
    init_parser.set_defaults(handler=init_command)

    check_parser = subparsers.add_parser(
        "check", help="validate bindings/evidence and report qualification"
    )
    check_parser.add_argument("record", type=Path)
    check_parser.add_argument("--campaign-summary", type=Path, required=True)
    check_parser.add_argument("--compatibility", type=Path, required=True)
    check_parser.set_defaults(handler=check_command)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
