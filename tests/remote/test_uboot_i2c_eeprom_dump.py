from __future__ import annotations

import unittest
from pathlib import Path

from scripts.remote.uboot_dump_i2c_eeprom import (
    DumpOptions,
    build_command_plan,
    parse_i2c_md_bytes,
)


class UBootI2CEepromDumpTests(unittest.TestCase):
    def test_build_command_plan_reads_full_eeprom_in_chunks(self) -> None:
        plan = build_command_plan(
            DumpOptions(
                i2c_bus=1,
                chip="0x50",
                offset_width=2,
                size=768,
                chunk_size=256,
                output=Path("eeprom.bin"),
                probe=True,
            )
        )

        commands = [step["command"] for step in plan]
        self.assertEqual(commands[:3], ["version", "i2c dev 1", "i2c probe"])
        self.assertEqual(commands[3], "i2c md 0x50 0x0.2 0x100")
        self.assertEqual(commands[4], "i2c md 0x50 0x100.2 0x100")
        self.assertEqual(commands[5], "i2c md 0x50 0x200.2 0x100")

    def test_parse_i2c_md_bytes_ignores_echo_and_prompt(self) -> None:
        text = """
ZynqMP> i2c md 0x50 0x0.2 0x20
0000: 01 00 00 01 00 05 00 f9  01 02 03 04 05 06 07 08    ................
0010: 10 11 12 13 14 15 16 17  18 19 1a 1b 1c 1d 1e 1f    ................
ZynqMP>
"""

        self.assertEqual(
            parse_i2c_md_bytes(text),
            bytes(
                [
                    0x01,
                    0x00,
                    0x00,
                    0x01,
                    0x00,
                    0x05,
                    0x00,
                    0xF9,
                    0x01,
                    0x02,
                    0x03,
                    0x04,
                    0x05,
                    0x06,
                    0x07,
                    0x08,
                    0x10,
                    0x11,
                    0x12,
                    0x13,
                    0x14,
                    0x15,
                    0x16,
                    0x17,
                    0x18,
                    0x19,
                    0x1A,
                    0x1B,
                    0x1C,
                    0x1D,
                    0x1E,
                    0x1F,
                ]
            ),
        )


if __name__ == "__main__":
    unittest.main()
