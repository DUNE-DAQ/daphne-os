from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.remote.prepare_uboot_wic_chunks import prepare_chunks
from scripts.remote.uboot_flash_wic import load_manifest
from scripts.remote.uboot_flash_wic_jtag import (
    JtagFlashOptions,
    build_command_plan,
    build_xsdb_command,
    validate_chunk_files,
)


class UBootWicJtagFlashTests(unittest.TestCase):
    def make_manifest(self, root: Path) -> tuple[Path, dict[str, object]]:
        image = root / "image.wic"
        image.write_bytes(b"jtag-wic" * 300)
        chunk_dir = root / "chunks"
        prepare_chunks(
            image,
            chunk_dir,
            name="pilot",
            chunk_size=1024,
            manifest_name="manifest.json",
            force=False,
        )
        manifest_path = chunk_dir / "manifest.json"
        return manifest_path, load_manifest(manifest_path)

    def test_plan_loads_each_chunk_over_jtag_before_mmc_write(self) -> None:
        with tempfile.TemporaryDirectory() as root_text:
            root = Path(root_text)
            manifest_path, manifest = self.make_manifest(root)
            options = JtagFlashOptions(
                manifest=manifest_path,
                chunk_dir=manifest_path.parent,
                loadaddr="0x10000000",
                verifyaddr="0x18000000",
                mmc_dev=0,
                mmc_hwpart=0,
                erase=True,
                verify_readback=True,
                reset_after=True,
            )
            validate_chunk_files(manifest, options.chunk_dir)
            plan = build_command_plan(manifest, options)

        host_loads = [step for step in plan if "host_load" in step]
        commands = [step["command"] for step in plan if "command" in step]
        self.assertEqual(len(host_loads), len(manifest["chunks"]))
        self.assertEqual(host_loads[0]["address"], "0x10000000")
        self.assertTrue(host_loads[0]["host_load"].endswith("pilot.part0000"))
        self.assertIn("mmc erase 0x0 0x5", commands)
        self.assertIn("crc32 0x10000000 0x400", commands)
        self.assertIn("mmc write 0x10000000 0x0 0x2", commands)
        self.assertIn("mmc read 0x18000000 0x0 0x2", commands)
        self.assertFalse(any("tftp" in command for command in commands))
        self.assertEqual(commands[-1], "reset")

    def test_chunk_validation_rejects_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as root_text:
            root = Path(root_text)
            manifest_path, manifest = self.make_manifest(root)
            chunk = manifest_path.parent / str(manifest["chunks"][0]["filename"])
            chunk.write_bytes(b"x" * chunk.stat().st_size)

            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                validate_chunk_files(manifest, manifest_path.parent)

    def test_xsdb_command_carries_target_and_optional_server(self) -> None:
        command = build_xsdb_command(
            xsdb="/tools/2026.1/Vivado/bin/xsdb",
            script=Path("xsdb_load_data.tcl"),
            data_file=Path("pilot.part0000"),
            address="0x10000000",
            a53_target="*Cortex-A53*#0*",
            hw_server="tcp:localhost:3121",
        )

        self.assertEqual(command[0], "/tools/2026.1/Vivado/bin/xsdb")
        self.assertIn("-file", command)
        self.assertIn("pilot.part0000", command)
        self.assertIn("-hw-server", command)
        self.assertEqual(command[-1], "tcp:localhost:3121")


if __name__ == "__main__":
    unittest.main()
