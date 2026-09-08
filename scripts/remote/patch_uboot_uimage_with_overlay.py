#!/usr/bin/env python3
"""Append a gzip/cpio overlay to a legacy U-Boot ramdisk image and fix checksums."""

import argparse
import binascii
import os
import struct
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base", help="Path to the existing legacy uImage")
    parser.add_argument("overlay", help="Path to the gzip/cpio overlay to append")
    parser.add_argument(
        "--backup",
        help="Optional backup copy path for the original image",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    base_path = Path(args.base)
    overlay_path = Path(args.overlay)

    base = base_path.read_bytes()
    overlay = overlay_path.read_bytes()

    if len(base) < 64:
        raise SystemExit("base image is too small to be a legacy uImage")

    fields = struct.unpack(">7I4B32s", base[:64])
    magic, _, timestamp, _, load, ep, _, os_id, arch_id, type_id, comp_id, name = fields
    if magic != 0x27051956:
        raise SystemExit("base image does not look like a legacy uImage")

    payload = base[64:] + overlay
    data_crc = binascii.crc32(payload) & 0xFFFFFFFF
    header_wo_crc = struct.pack(
        ">7I4B32s",
        magic,
        0,
        timestamp,
        len(payload),
        load,
        ep,
        data_crc,
        os_id,
        arch_id,
        type_id,
        comp_id,
        name,
    )
    header_crc = binascii.crc32(header_wo_crc) & 0xFFFFFFFF
    header = struct.pack(
        ">7I4B32s",
        magic,
        header_crc,
        timestamp,
        len(payload),
        load,
        ep,
        data_crc,
        os_id,
        arch_id,
        type_id,
        comp_id,
        name,
    )

    if args.backup:
        backup_path = Path(args.backup)
        backup_path.write_bytes(base)

    tmp_path = base_path.with_name(base_path.name + ".codex-new")
    tmp_path.write_bytes(header + payload)
    os.replace(tmp_path, base_path)
    os.sync()

    print(str(base_path))
    print("new_bytes={}".format(len(header) + len(payload)))
    print("overlay_bytes={}".format(len(overlay)))


if __name__ == "__main__":
    main()
