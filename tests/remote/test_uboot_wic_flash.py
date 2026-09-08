from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from pathlib import Path

from scripts.remote.prepare_uboot_wic_chunks import prepare_chunks
from scripts.remote.uboot_flash_wic import (
    FlashOptions,
    _crc32_value,
    _filesize_matches,
    build_command_plan,
    load_manifest,
)


class UBootWicFlashTests(unittest.TestCase):
    def test_prepare_chunks_creates_block_aligned_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as root_text:
            root = Path(root_text)
            image = root / "image.wic"
            image.write_bytes(bytes(range(251)) * 11)
            out = root / "tftp"

            manifest = prepare_chunks(
                image,
                out,
                name="pilot",
                chunk_size=1024,
                manifest_name="manifest.json",
                force=False,
            )

            chunks = manifest["chunks"]
            self.assertEqual(len(chunks), 3)
            self.assertEqual(chunks[0]["emmc_start_block"], 0)
            self.assertEqual(chunks[1]["emmc_start_block"], 2)
            self.assertEqual(chunks[2]["padded_size_bytes"], 1024)
            self.assertTrue((out / "pilot.part0000").is_file())
            self.assertEqual((out / "pilot.part0002").stat().st_size, 1024)
            self.assertEqual(manifest["image"]["raw_size_bytes"], 2761)
            self.assertEqual(manifest["image"]["padded_block_count"], 6)

    def test_prepare_chunks_accepts_gzip_input(self) -> None:
        with tempfile.TemporaryDirectory() as root_text:
            root = Path(root_text)
            image = root / "image.wic.gz"
            with gzip.open(image, "wb") as handle:
                handle.write(b"abcd" * 300)

            manifest = prepare_chunks(
                image,
                root / "tftp",
                name="pilot",
                chunk_size=1024,
                manifest_name="manifest.json",
                force=False,
            )

            self.assertEqual(manifest["image"]["raw_size_bytes"], 1200)
            self.assertEqual(manifest["image"]["padded_block_count"], 3)

    def test_build_command_plan_includes_crc_and_mmc_writes(self) -> None:
        with tempfile.TemporaryDirectory() as root_text:
            root = Path(root_text)
            image = root / "image.wic"
            image.write_bytes(b"a" * 1500)
            manifest = prepare_chunks(
                image,
                root / "tftp",
                name="pilot",
                chunk_size=1024,
                manifest_name="manifest.json",
                force=False,
            )
            manifest_path = root / "tftp" / "manifest.json"
            loaded = load_manifest(manifest_path)
            self.assertEqual(loaded["image"], manifest["image"])

            plan = build_command_plan(
                loaded,
                FlashOptions(
                    manifest=manifest_path,
                    tftp_prefix="daphne/pilot",
                    loadaddr="0x10000000",
                    verifyaddr="0x18000000",
                    mmc_dev=0,
                    mmc_hwpart=0,
                    serverip="192.0.2.1",
                    ipaddr="192.0.2.101",
                    netmask="255.255.255.0",
                    gatewayip=None,
                    ethaddr=None,
                    use_dhcp=False,
                    erase=True,
                    verify_readback=True,
                    reset_after=True,
                    tftp_dst_port=1069,
                    tftp_blocksize=1468,
                    tftp_windowsize=4,
                ),
            )

        commands = [step["command"] for step in plan]
        self.assertIn("setenv serverip 192.0.2.1", commands)
        self.assertIn("setenv ipaddr 192.0.2.101", commands)
        self.assertIn("setenv tftpdstp 1069", commands)
        self.assertIn("setenv tftpblocksize 1468", commands)
        self.assertIn("setenv tftpwindowsize 4", commands)
        self.assertIn("mmc erase 0x0 0x3", commands)
        self.assertIn("tftpboot 0x10000000 daphne/pilot/pilot.part0000", commands)
        self.assertIn("mmc write 0x10000000 0x0 0x2", commands)
        self.assertIn("mmc read 0x18000000 0x0 0x2", commands)
        self.assertEqual(commands[-1], "reset")

    def test_manifest_validation_rejects_noncontiguous_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as root_text:
            root = Path(root_text)
            manifest_path = root / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "contract": "daphne.uboot-wic-flash-manifest",
                        "version": 1,
                        "block_size_bytes": 512,
                        "image": {"padded_block_count": 4},
                        "chunks": [
                            {
                                "index": 0,
                                "filename": "x.part0000",
                                "emmc_start_block": 1,
                                "block_count": 1,
                                "padded_size_bytes": 512,
                                "crc32": "00000000",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "not contiguous"):
                load_manifest(manifest_path)

    def test_uboot_output_checks_match_expected_values(self) -> None:
        self.assertTrue(_filesize_matches("Bytes transferred = 1024 (400 hex)", "0x400"))
        self.assertTrue(_filesize_matches("filesize=400\nZynqMP>", "0x400"))
        self.assertFalse(_filesize_matches("Bytes transferred = 1025 (401 hex)", "0x400"))
        self.assertEqual(_crc32_value("crc32 for 10000000 ... ==> 89abcdef"), "89abcdef")
        self.assertEqual(_crc32_value("CRC32 for 10000000 ... 01234567\nZynqMP>"), "01234567")


if __name__ == "__main__":
    unittest.main()
