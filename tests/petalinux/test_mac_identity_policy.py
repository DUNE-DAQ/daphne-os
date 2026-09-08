#!/usr/bin/env python3
"""Regression tests for the K26 SOM EEPROM MAC ownership policy."""

from __future__ import annotations

import re
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
META = ROOT / "petalinux" / "meta-daphne"
NETWORK_DTSI = (
    META / "recipes-bsp" / "device-tree" / "files" / "daphne-k26c-network.dtsi"
)
UBOOT_CFG = (
    ROOT
    / "petalinux"
    / "config"
    / "kr260"
    / "project-spec"
    / "meta-user"
    / "recipes-bsp"
    / "u-boot"
    / "files"
    / "bsp.cfg"
)


class MacIdentityPolicyTests(unittest.TestCase):
    def test_source_has_no_board_stamped_mac_or_identity_path(self) -> None:
        roots = [META, ROOT / "scripts" / "petalinux"]
        forbidden = {
            "MACAddress=": "Linux .link MAC setter",
            "ethaddr=": "U-Boot MAC setter",
            "eth1addr=": "secondary U-Boot MAC setter",
            "DAPHNE_BOARD_ID": "build-time board selector",
            "ff0b_board_inventory": "image-local board inventory",
            "daphne-board-identity": "image-local identity service",
            "02:00:00:00:00:20": "placeholder MAC",
            "ba:be:ba:": "legacy DAPHNE MAC prefix",
        }
        findings: list[str] = []
        for root in roots:
            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                try:
                    text = path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    continue
                for token, description in forbidden.items():
                    if token in text:
                        findings.append(f"{path.relative_to(ROOT)}: {description}")
        self.assertEqual([], findings)

    def test_device_tree_has_standard_alias_and_no_compiled_mac(self) -> None:
        text = NETWORK_DTSI.read_text(encoding="utf-8")
        self.assertIn("ethernet0 = &gem0;", text)
        self.assertIn("serial0 = &uart0;", text)
        self.assertIn("serial1 = &uart1;", text)
        self.assertIn('stdout-path = "serial1:115200n8";', text)
        self.assertIn("/delete-property/ mac-address;", text)
        self.assertIn("/delete-property/ local-mac-address;", text)
        self.assertNotRegex(text, r"(?m)^\s*(?:local-)?mac-address\s*=\s*\[")

    def test_compiled_device_tree_removes_inherited_mac(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            source = tmpdir / "test.dts"
            output = tmpdir / "test.dtb"
            source.write_text(
                "/dts-v1/;\n"
                "/ {\n"
                "  aliases {};\n"
                "  uart0: serial@0 {};\n"
                "  uart1: serial@1 {};\n"
                "  gem0: ethernet@0 {\n"
                "    mac-address = [02 00 00 00 00 20];\n"
                "    local-mac-address = [02 00 00 00 00 20];\n"
                "  };\n"
                "};\n"
                f'/include/ "{NETWORK_DTSI}"\n',
                encoding="utf-8",
            )
            subprocess.run(
                ["dtc", "-I", "dts", "-O", "dtb", "-o", output, source],
                check=True,
                capture_output=True,
                text=True,
            )
            alias = subprocess.run(
                ["fdtget", "-t", "s", output, "/aliases", "ethernet0"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            self.assertEqual("/ethernet@0", alias)
            for prop in ("mac-address", "local-mac-address"):
                result = subprocess.run(
                    ["fdtget", output, "/ethernet@0", prop],
                    capture_output=True,
                    text=True,
                )
                self.assertNotEqual(0, result.returncode, prop)

            for prop, expected in (
                ("serial0", "/serial@0"),
                ("serial1", "/serial@1"),
            ):
                result = subprocess.run(
                    ["fdtget", "-t", "s", output, "/aliases", prop],
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.strip()
                self.assertEqual(expected, result)
            stdout_path = subprocess.run(
                ["fdtget", "-t", "s", output, "/chosen", "stdout-path"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            self.assertEqual("serial1:115200n8", stdout_path)

    def test_random_fallback_is_disabled(self) -> None:
        text = UBOOT_CFG.read_text(encoding="utf-8")
        self.assertRegex(
            text,
            re.compile(r"^# CONFIG_NET_RANDOM_ETHADDR is not set$", re.MULTILINE),
        )

    def test_new_recipes_reference_existing_local_files(self) -> None:
        recipes = [
            META / "recipes-core" / "daphne-boot-state" / "daphne-boot-state.bb",
            META / "recipes-core" / "daphne-services" / "daphne-services.bb",
        ]
        missing: list[str] = []
        for recipe in recipes:
            text = recipe.read_text(encoding="utf-8")
            for relative in re.findall(r"file://([^\s\\\"]+)", text):
                if relative.startswith("${"):
                    continue
                candidate = recipe.parent / "files" / relative
                if not candidate.exists():
                    missing.append(str(candidate.relative_to(ROOT)))
        self.assertEqual([], missing)


if __name__ == "__main__":
    unittest.main()
