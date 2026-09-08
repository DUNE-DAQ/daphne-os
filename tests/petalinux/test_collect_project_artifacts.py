from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COLLECT = ROOT / "scripts" / "petalinux" / "collect_project_artifacts.sh"


class CollectProjectArtifactsTests(unittest.TestCase):
    def test_collects_xsdb_ram_boot_inputs_wic_and_both_gatewares(self) -> None:
        with tempfile.TemporaryDirectory() as root_text:
            root = Path(root_text)
            project = root / "daphne-petalinux"
            images = project / "images" / "linux"
            overlay = (
                project
                / "project-spec"
                / "meta-daphne"
                / "recipes-firmware"
                / "daphne-overlay"
                / "files"
                / "staged"
            )
            server_recipe = (
                project
                / "project-spec"
                / "meta-daphne"
                / "recipes-apps"
                / "daphne-server"
            )
            server_staged = server_recipe / "files" / "staged"
            (project / "project-spec").mkdir(parents=True)
            (project / "build" / "conf").mkdir(parents=True)
            (project / "build" / "conf" / "local.conf").write_text(
                'DAPHNE_IMAGE_PROFILE = "minimal"\n', encoding="utf-8"
            )
            images.mkdir(parents=True)
            overlay.mkdir(parents=True)
            server_staged.mkdir(parents=True)

            for name in (
                "BOOT.BIN",
                "zynqmp_fsbl.elf",
                "pmufw.elf",
                "bl31.elf",
                "u-boot-dtb.elf",
                "Image",
                "system.dtb",
                "rootfs.wic.gz",
            ):
                (images / name).write_text(f"{name}\n", encoding="utf-8")
            for mode, app in (
                ("self-trigger", "daphne_selftrigger_ol_abcdef1"),
                ("full-stream", "daphne_fullstream_ol_1234abc"),
            ):
                mode_dir = overlay / mode
                mode_dir.mkdir()
                for name in (
                    f"{app}.bin",
                    f"{app}.dtbo",
                    "shell.json",
                    "BUILD-METADATA.txt",
                    "SHA256SUMS",
                ):
                    (mode_dir / name).write_text(f"{mode}:{name}\n", encoding="utf-8")
            version_inc = overlay.parent.parent / "daphne-overlay-version.inc"
            version_inc.write_text('DAPHNE_DUAL_OVERLAY_STAGED = "1"\n')
            (server_staged / "BUILD-METADATA.txt").write_text(
                "server_git_commit=e17515b\n", encoding="utf-8"
            )
            (server_staged / "SHA256SUMS").write_text(
                "0" * 64 + "  daphne-server-runtime-minimal.tgz\n",
                encoding="utf-8",
            )
            (server_recipe / "daphne-server-contract.inc").write_text(
                'DAPHNE_SERVER_REQUIRED_GATEWARE_ABI_MAJOR = "2"\n',
                encoding="utf-8",
            )
            (server_recipe / "daphne-server-version.inc").write_text(
                'DAPHNE_SERVER_RUNTIME_QUALIFIED = "1"\n', encoding="utf-8"
            )
            bundle = root / "bundle"

            subprocess.run([str(COLLECT), str(project), str(bundle)], check=True, text=True)

            for relative in (
                "boot/BOOT.BIN",
                "boot/zynqmp_fsbl.elf",
                "boot/pmufw.elf",
                "boot/bl31.elf",
                "boot/u-boot-dtb.elf",
                "boot/Image",
                "boot/system.dtb",
                "rootfs/rootfs.wic.gz",
                "overlay/daphne-overlay-version.inc",
                "overlay/self-trigger/daphne_selftrigger_ol_abcdef1.bin",
                "overlay/self-trigger/daphne_selftrigger_ol_abcdef1.dtbo",
                "overlay/self-trigger/shell.json",
                "overlay/self-trigger/BUILD-METADATA.txt",
                "overlay/self-trigger/SHA256SUMS",
                "overlay/full-stream/daphne_fullstream_ol_1234abc.bin",
                "overlay/full-stream/daphne_fullstream_ol_1234abc.dtbo",
                "overlay/full-stream/shell.json",
                "overlay/full-stream/BUILD-METADATA.txt",
                "overlay/full-stream/SHA256SUMS",
                "meta/DAPHNE-SERVER-BUILD-METADATA.txt",
                "meta/DAPHNE-SERVER-STAGED-SHA256SUMS",
                "meta/daphne-server-contract.inc",
                "meta/daphne-server-version.inc",
                "MANIFEST.txt",
                "SHA256SUMS",
            ):
                self.assertTrue((bundle / relative).is_file(), relative)

            metadata = (bundle / "meta" / "COLLECT-METADATA.txt").read_text(
                encoding="utf-8"
            )
            self.assertIn("image_profile=minimal", metadata)
            os_commit = subprocess.check_output(
                ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True
            ).strip()
            self.assertIn(f"os_git_commit={os_commit}\n", metadata)
            self.assertRegex(metadata, r"os_git_dirty=(true|false)\n")
            self.assertNotIn("firmware_git_", metadata)
            self.assertIn("deployment_scope=whole-emmc-and-inactive-slot", metadata)
            self.assertIn(
                "overlay_policy=included-from-staged-dual-artifacts", metadata
            )
            checksums = (bundle / "SHA256SUMS").read_text(encoding="utf-8")
            self.assertIn(
                "  ./overlay/self-trigger/SHA256SUMS\n", checksums
            )
            self.assertIn(
                "  ./overlay/full-stream/SHA256SUMS\n", checksums
            )
            self.assertNotIn("  ./SHA256SUMS\n", checksums)

    def test_provisioning_bundle_excludes_stale_staged_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as root_text:
            root = Path(root_text)
            project = root / "daphne-petalinux"
            images = project / "images" / "linux"
            overlay = (
                project
                / "project-spec"
                / "meta-daphne"
                / "recipes-firmware"
                / "daphne-overlay"
                / "files"
                / "staged"
            )
            (project / "project-spec").mkdir(parents=True)
            (project / "build" / "conf").mkdir(parents=True)
            (project / "build" / "conf" / "local.conf").write_text(
                'DAPHNE_IMAGE_PROFILE ?= "minimal"\n'
                'DAPHNE_IMAGE_PROFILE = "provisioning"\n',
                encoding="utf-8",
            )
            images.mkdir(parents=True)
            overlay.mkdir(parents=True)
            (images / "rootfs.wic.gz").write_text("wic\n", encoding="utf-8")
            for mode in ("self-trigger", "full-stream"):
                (overlay / mode).mkdir()
                (overlay / mode / "stale.dtbo").write_text(
                    "stale\n", encoding="utf-8"
                )
            bundle = root / "bundle"

            subprocess.run([str(COLLECT), str(project), str(bundle)], check=True, text=True)

            self.assertTrue((bundle / "rootfs" / "rootfs.wic.gz").is_file())
            self.assertFalse((bundle / "overlay" / "self-trigger").exists())
            self.assertFalse((bundle / "overlay" / "full-stream").exists())
            metadata = (bundle / "meta" / "COLLECT-METADATA.txt").read_text(
                encoding="utf-8"
            )
            self.assertIn("image_profile=provisioning", metadata)
            self.assertIn("deployment_scope=virgin-som-whole-emmc", metadata)
            self.assertIn("overlay_policy=excluded-for-provisioning", metadata)


if __name__ == "__main__":
    unittest.main()
