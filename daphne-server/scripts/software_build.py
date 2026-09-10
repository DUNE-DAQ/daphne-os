"""Check compiled source/schema metadata; never treat hashes as authorization."""
import hashlib
from pathlib import Path
import re


def require(ok):
    if not ok:
        raise RuntimeError("Invalid or unexpected server build metadata; details suppressed")


def check_build(info, high, *, expected_commit=None, require_clean=False, source_root=None):
    require(info.metadata_format_version == 1 and info.component == "daphne-server")
    require(info.control_envelope_version == 2)
    digest = lambda value: bool(re.fullmatch(r"[0-9a-f]{64}", value))
    require(digest(info.high_level_schema_sha256) and digest(info.low_level_schema_sha256))
    require(info.high_level_schema_sha256 != info.low_level_schema_sha256)
    for field in ("compiler_id", "compiler_version", "target_architecture", "protobuf_compile_version"):
        require(bool(re.fullmatch(r"[A-Za-z0-9_.+\-]{1,80}", getattr(info, field))))
    require(info.source_quality in (high.MEASUREMENT_GOOD, high.MEASUREMENT_UNAVAILABLE))
    require(bool(info.source_detail) and len(info.source_detail) <= 256)
    available = info.source_quality == high.MEASUREMENT_GOOD
    for field in ("software_version", "source_git_commit", "committed_source_tree", "source_worktree_dirty"):
        require(info.HasField(field) == available)
    if available:
        require(bool(re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", info.source_git_commit)))
        require(len(info.committed_source_tree) == len(info.source_git_commit)
                and bool(re.fullmatch(r"[0-9a-f]+", info.committed_source_tree)))
        require(info.software_version == "git:" + info.source_git_commit +
                ("-dirty" if info.source_worktree_dirty else ""))
    if expected_commit is not None:
        require(bool(re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", expected_commit)))
        require(available and info.source_git_commit == expected_commit)
    if require_clean:
        require(available and not info.source_worktree_dirty)
    if source_root is not None:
        root = Path(source_root) / "srcs/protobuf"
        for level in ("high", "low"):
            actual = hashlib.sha256((root / f"daphneV3_{level}_level_confs.proto").read_bytes()).hexdigest()
            require(actual == getattr(info, f"{level}_level_schema_sha256"))
    return {
        "component": "daphne-server", "source_available": available,
        "software_version": info.software_version if available else None,
        "source_git_commit": info.source_git_commit if available else None,
        "committed_source_tree": info.committed_source_tree if available else None,
        "source_worktree_dirty": info.source_worktree_dirty if available else None,
        "high_level_schema_sha256": info.high_level_schema_sha256,
        "low_level_schema_sha256": info.low_level_schema_sha256,
        "control_envelope_version": 2, "compiler_id": info.compiler_id,
        "compiler_version": info.compiler_version,
        "target_architecture": info.target_architecture,
        "protobuf_compile_version": info.protobuf_compile_version,
        "schema_source_compared": source_root is not None,
        "scope": "Compiled metadata, not signature, installed-file hash, semantic compatibility or hardware health",
    }
