"""Locate generated Python protobuf modules without assuming a build folder."""

import importlib
import os
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]


def load_protobuf_modules(require_trigger_source=False, require_synthetic_sipm=False, require_dma=False):
    candidates = []
    configured = os.environ.get("DAPHNE_PROTO_PYTHON_DIR")
    if configured:
        candidates.append(Path(configured))
    configured_build = os.environ.get("DAPHNE_BUILD_DIR")
    if configured_build:
        candidates.append(Path(configured_build) / "srcs" / "protobuf")
    for build_name in ("build-petalinux", "build-client", "build-test", "build"):
        candidates.append(REPO_ROOT / build_name / "srcs" / "protobuf")
    candidates.append(REPO_ROOT / "srcs" / "protobuf")

    visited = set()
    errors = []
    required_tokens = []
    if require_dma:
        required_tokens.extend(("DmaAcquireRequest", "DmaReadResponse", "AcquisitionCapabilitiesResponse", "MT2_DMA_SCAN_REQ"))
    if require_trigger_source:
        required_tokens.extend((
            "SPY_TRIGGER_SOURCE_LEGACY_ALL",
            "WriteSpyBufferTriggerSourceRequest",
            "ReadSpyBufferTriggerSourceRequest",
            "MT2_WRITE_SPYBUFFER_TRIGGER_SOURCE_REQ",
            "MT2_READ_SPYBUFFER_TRIGGER_SOURCE_REQ",
        ))
    if require_synthetic_sipm:
        required_tokens.extend((
            "SYNTHETIC_SIPM_FBK",
            "SYNTHETIC_SIPM_HPK",
            "ConfigureSyntheticSipmRequest",
            "ReadSyntheticSipmConfigRequest",
            "SyntheticSipmConfigResponse",
            "MT2_CONFIGURE_SYNTHETIC_SIPM_REQ",
            "MT2_CONFIGURE_SYNTHETIC_SIPM_RESP",
            "MT2_READ_SYNTHETIC_SIPM_CONFIG_REQ",
            "MT2_READ_SYNTHETIC_SIPM_CONFIG_RESP",
        ))
    for candidate in candidates:
        candidate = candidate.expanduser().resolve()
        if candidate in visited:
            continue
        visited.add(candidate)
        if not all(
            (candidate / filename).is_file()
            for filename in (
                "daphneV3_high_level_confs_pb2.py",
                "daphneV3_low_level_confs_pb2.py",
            )
        ):
            continue

        # Reject a stale generated module before importing it. Importing an
        # incompatible candidate registers its proto filename in protobuf's
        # process-wide descriptor pool, which prevents a later compatible
        # candidate with the same filename from being loaded.
        if required_tokens:
            high_source = (
                candidate / "daphneV3_high_level_confs_pb2.py"
            ).read_text(encoding="utf-8", errors="ignore")
            # protoc may escape a message's first byte in the descriptor
            # literal; generated descriptor metadata also uses uppercase names.
            if not all(
                token in high_source or token.upper() in high_source
                for token in required_tokens
            ):
                errors.append(f"{candidate}: requested RPC schema is out of date")
                continue

        high_name = "daphneV3_high_level_confs_pb2"
        low_name = "daphneV3_low_level_confs_pb2"
        sys.modules.pop(high_name, None)
        sys.modules.pop(low_name, None)
        sys.path.insert(0, str(candidate))
        try:
            high = importlib.import_module(high_name)
            low = importlib.import_module(low_name)
        except Exception as exc:
            errors.append(f"{candidate}: {exc}")
            continue
        finally:
            sys.path.pop(0)

        if not all(hasattr(high, name) for name in required_tokens):
            errors.append(f"{candidate}: requested RPC schema is out of date")
            continue
        return high, low

    detail = "; ".join(errors)
    if detail:
        detail = " Checked: " + detail
    raise RuntimeError(
        "Compatible Python protobuf bindings were not found. Rebuild the "
        "project or set DAPHNE_PROTO_PYTHON_DIR." + detail
    )
