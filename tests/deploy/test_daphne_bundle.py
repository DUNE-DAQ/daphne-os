from __future__ import annotations

import hashlib
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "scripts/deploy"
SPEC = importlib.util.spec_from_file_location("bundle_under_test", TOOLS / "daphne_bundle.py")
BUNDLE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUNDLE)
REQUIRED = ("boot/Image", "boot/system.dtb", "boot/ramdisk.cpio.gz.u-boot", "rootfs/rootfs.ext4")


class BundleValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.bundle = self.base / "bundle"
        for name in REQUIRED:
            path = self.bundle / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture:" + name)
        self.manifest = self.bundle / "SHA256SUMS"
        self.manifest.write_text("".join(self.record(name) for name in REQUIRED))
        self.config = self.base / "config"
        self.config.mkdir()
        (self.config / "manifest.env").write_text(
            "ASSET_ID=TEST-001\nHOSTNAME_FQDN=test.invalid\nEXPECTED_BOOT_MAC=02:00:00:00:00:01\n"
        )
        for name in ("hostname", "daphne-board.env", "20-daphne-mgmt.network", "21-daphne-unused.network"):
            (self.config / name).write_text("fixture\n")
        stubs = self.base / "stubs"
        stubs.mkdir()
        for name in ("ssh", "scp", "ssh-keyscan", "ssh-keygen"):
            stub = stubs / name
            stub.write_text("#!/bin/sh\necho NETWORK_STUB >&2\nexit 91\n")
            stub.chmod(0o755)
        self.env = {**os.environ, "PATH": f"{stubs}:{os.environ['PATH']}"}

    def record(self, name: str, *, spelling: str | None = None) -> str:
        return hashlib.sha256((self.bundle / name).read_bytes()).hexdigest() + "  " + (spelling or name) + "\n"

    def deploy(self, script: Path | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run([
            str(script or TOOLS / "daphne_deploy.sh"), "--board", "TEST-001",
            "--host", "test.invalid", "--bundle", str(self.bundle),
            "--board-config", str(self.config), "--host-key-sha256", "SHA256:" + "A" * 43,
            "--dry-run",
        ], cwd=self.base, env=self.env, capture_output=True, text=True)

    def assert_rejected(self, message: str) -> None:
        with self.assertRaisesRegex(BUNDLE.BundleError, message):
            BUNDLE.verify_bundle(self.bundle)
        result = self.deploy()
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn(message, result.stderr)
        self.assertNotIn("NETWORK_STUB", result.stderr)

    def test_valid_bundle_passes_shared_and_single_board_preflight(self) -> None:
        _, evidence = BUNDLE.verify_bundle(self.bundle)
        self.assertEqual(evidence["required_entries"], sorted(REQUIRED))
        self.assertEqual(self.deploy().returncode, 91)  # stopped at the fake SSH boundary

    def test_manifest_must_cover_every_required_image(self) -> None:
        self.manifest.write_text(self.record("boot/Image"))
        self.assert_rejected("does not cover required artifacts")

    def test_empty_manifest_is_rejected(self) -> None:
        self.manifest.write_text("")
        self.assert_rejected("does not cover required artifacts")

    def test_modified_image_is_rejected(self) -> None:
        (self.bundle / "rootfs/rootfs.ext4").write_text("changed")
        self.assert_rejected("bundle checksum mismatch")

    def test_normalized_duplicate_path_is_rejected(self) -> None:
        self.manifest.write_text(self.manifest.read_text() + self.record("boot/Image", spelling="./boot/Image"))
        self.assert_rejected("duplicate bundle checksum path")

    def test_parent_traversal_is_rejected(self) -> None:
        self.manifest.write_text(self.manifest.read_text() + "0" * 64 + "  ../outside\n")
        self.assert_rejected("unsafe path")

    def test_symlinked_artifact_is_rejected(self) -> None:
        original = self.bundle / "boot/Image"
        original.rename(self.base / "saved-image")
        original.symlink_to(self.base / "saved-image")
        self.assert_rejected("missing regular bundle artifact")

    def test_symlinked_parent_directory_is_rejected(self) -> None:
        original = self.bundle / "boot"
        original.rename(self.base / "saved-boot")
        original.symlink_to(self.base / "saved-boot", target_is_directory=True)
        self.assert_rejected("missing regular bundle artifact")

    def test_malformed_manifest_is_rejected(self) -> None:
        self.manifest.write_text("not a checksum\n")
        self.assert_rejected("malformed checksum record")

    def test_whole_emmc_collection_also_requires_checksummed_wic(self) -> None:
        with self.assertRaisesRegex(BUNDLE.BundleError, "rootfs/rootfs.wic.gz"):
            BUNDLE.verify_bundle(self.bundle, require_wic=True)
        (self.bundle / "rootfs/rootfs.wic.gz").write_text("wic fixture")
        with self.assertRaises(BUNDLE.BundleError):
            BUNDLE.verify_bundle(self.bundle, require_wic=True)
        self.manifest.write_text(self.manifest.read_text() + self.record("rootfs/rootfs.wic.gz"))
        BUNDLE.verify_bundle(self.bundle, require_wic=True)

    def test_snapshot_deployer_uses_validator_beside_it_without_repository(self) -> None:
        captured = self.base / "captured"
        captured.mkdir()
        for name in ("daphne_deploy.sh", "daphne_bundle.py"):
            shutil.copy2(TOOLS / name, captured / name)
        self.assertEqual(self.deploy(captured / "daphne_deploy.sh").returncode, 91)
        (captured / "daphne_bundle.py").rename(captured / "not-available.py")
        result = self.deploy(captured / "daphne_deploy.sh")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("NETWORK_STUB", result.stderr)
