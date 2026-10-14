#!/usr/bin/env python3
"""Recover boot payloads and Linux readback references from pinned artifacts.

This is an offline operation. It never opens serial, JTAG, or a block device.
The partition offsets are specific to the checksummed September 17 image.
"""
import gzip
import hashlib
import json
import struct
import zlib
from pathlib import Path


def elf(segments, entry, machine=183, bits=64):
    """Wrap flattened BOOT.BIN payloads in loadable ELF program headers."""
    if bits == 64:
        header_size, ph_size = 64, 56
        body = bytearray(header_size + ph_size * len(segments))
        body[:16] = b'\x7fELF\x02\x01\x01' + bytes(9)
        struct.pack_into('<HHIQQQIHHHHHH', body, 16, 2, machine, 1, entry,
                         header_size, 0, 0, header_size, ph_size, len(segments), 0, 0, 0)
    else:
        header_size, ph_size = 52, 32
        body = bytearray(header_size + ph_size * len(segments))
        body[:16] = b'\x7fELF\x01\x01\x01' + bytes(9)
        struct.pack_into('<HHIIIIIHHHHHH', body, 16, 2, machine, 1, entry,
                         header_size, 0, 0, header_size, ph_size, len(segments), 0, 0, 0)
    for index, (address, payload) in enumerate(segments):
        offset = len(body)
        if bits == 64:
            struct.pack_into('<IIQQQQQQ', body, header_size + index * ph_size,
                             1, 7, offset, address, address, len(payload), len(payload), 1)
        else:
            struct.pack_into('<IIIIIIII', body, header_size + index * ph_size,
                             1, offset, address, address, len(payload), len(payload), 7, 1)
        body.extend(payload)
    return bytes(body)


def fat_boot_files(image):
    start = struct.unpack_from('<I', image, 446 + 8)[0] * 512
    boot = image[start:start + 512]
    sector_size = struct.unpack_from('<H', boot, 11)[0]
    sectors_per_cluster = boot[13]
    reserved = struct.unpack_from('<H', boot, 14)[0]
    fats = boot[16]
    root_entries = struct.unpack_from('<H', boot, 17)[0]
    fat_sectors = struct.unpack_from('<H', boot, 22)[0]
    if not sector_size or not sectors_per_cluster:
        raise ValueError('Invalid FAT boot partition')
    fat32 = fat_sectors == 0
    if fat32:
        fat_sectors = struct.unpack_from('<I', boot, 36)[0]
    fat_start = start + reserved * sector_size
    root_size = ((root_entries * 32 + sector_size - 1) // sector_size) * sector_size
    root_start = fat_start + fats * fat_sectors * sector_size
    data_start = root_start + root_size
    cluster_bytes = sector_size * sectors_per_cluster

    def chain(cluster):
        content = bytearray()
        visited = set()
        while 2 <= cluster < (0xffffff8 if fat32 else 0xfff8):
            if cluster in visited:
                raise ValueError('FAT cluster loop')
            visited.add(cluster)
            pos = data_start + (cluster - 2) * cluster_bytes
            if pos + cluster_bytes > len(image):
                raise ValueError('FAT cluster outside image')
            content.extend(image[pos:pos + cluster_bytes])
            fmt, width = ('<I', 4) if fat32 else ('<H', 2)
            cluster = struct.unpack_from(fmt, image, fat_start + cluster * width)[0]
            if fat32:
                cluster &= 0xfffffff
        return bytes(content)

    directory = chain(struct.unpack_from('<I', boot, 44)[0]) if fat32 else image[root_start:root_start + root_size]
    result = {}
    for pos in range(0, len(directory), 32):
        entry = directory[pos:pos + 32]
        if entry[0] == 0:
            break
        if entry[0] == 0xe5 or entry[11] & 0x18 or entry[11] == 0xf:
            continue
        name = entry[:8].decode('ascii').strip()
        suffix = entry[8:11].decode('ascii').strip()
        filename = name + ('.' + suffix if suffix else '')
        if filename.upper() in ('IMAGE', 'SYSTEM.DTB'):
            cluster = struct.unpack_from('<H', entry, 26)[0]
            if fat32:
                cluster |= struct.unpack_from('<H', entry, 20)[0] << 16
            size = struct.unpack_from('<I', entry, 28)[0]
            result['Image' if filename.upper() == 'IMAGE' else 'system.dtb'] = chain(cluster)[:size]
    if set(result) != {'Image', 'system.dtb'}:
        raise ValueError('Boot partition lacks Image or system.dtb')
    return result


def prepare(artifacts, destination, release):
    artifacts, destination = Path(artifacts), Path(destination)
    inputs = {}
    for name, expected in release['artifacts'].items():
        value = (artifacts / name).read_bytes()
        if len(value) != expected['size'] or hashlib.sha256(value).hexdigest() != expected['sha256']:
            raise ValueError(f'Release artifact checksum/size mismatch: {name}')
        inputs[name] = value
    boot = inputs['BOOT.BIN']
    # Offsets/lengths from bootgen 2026.1 -read on the pinned BOOT.BIN.
    pmu = boot[0x2800:0x2800 + 0x1fae0]
    fsbl = boot[0x2800 + 0x1fae0:0x2800 + 0x1fae0 + 0x19d48]
    uboot = boot[0x7c1100:0x7c1100 + 0x175c84]
    dtb_size = struct.unpack_from('>I', boot, 0x7b8104)[0]
    if not 40 <= dtb_size <= 0x8fcc:
        raise ValueError('Invalid U-Boot DTB size')
    dtb = boot[0x7b8100:0x7b8100 + dtb_size]
    # The original U-Boot hash excludes zero padding at the end of its partition.
    wanted = release['recovered_payload_sha256']['qualified-uboot.bin']
    candidates = [uboot, uboot.rstrip(b'\0')]
    uboot = next((p for p in candidates if hashlib.sha256(p).hexdigest() == wanted), None)
    if uboot is None:
        raise ValueError('Recovered U-Boot does not match the original campaign hash')
    if hashlib.sha256(dtb).hexdigest() != release['recovered_payload_sha256']['BOOT-BIN-fdt-7b8100.dtb']:
        raise ValueError('Recovered U-Boot DTB hash mismatch')
    payloads = {
        'qualified-ram/qualified-uboot.bin': uboot,
        'qualified-ram/BOOT-BIN-fdt-7b8100.dtb': dtb,
        'kit/boot/zynqmp_fsbl.elf': elf([(0xfffc0000, fsbl)], 0xfffc0000),
        'kit/boot/pmufw.elf': elf([(0xffdc0000, pmu)], 0xffdc0000, 189, 32),
        'kit/boot/bl31.elf': elf([(0xfffea000, boot[0x7abc00:0x7abc00 + 0x9000]),
                               (0xffff3000, boot[0x7b4c00:0x7b4c00 + 0x34e0])], 0xfffea000),
        'kit/boot/system.bin': boot[0x3c040:0x3c040 + 0x76fbbc],
        'kit/boot/BOOT.BIN': boot,
        'kit/image/rootfs.wic.gz': inputs['rootfs.wic.gz'],
    }
    raw = gzip.decompress(inputs['rootfs.wic.gz'])
    if len(raw) != 377346048:
        raise ValueError('Unexpected WIC uncompressed size')
    for name, value in fat_boot_files(raw).items():
        payloads['kit/image/verify-' + name] = value
    manifest = {
        'sha256': release['artifacts']['rootfs.wic.gz']['sha256'],
        'compressed_size': len(inputs['rootfs.wic.gz']), 'uncompressed_size': len(raw),
        'crc32': f"{zlib.crc32(inputs['rootfs.wic.gz']):08x}",
    }
    payloads['kit/image/manifest.json'] = (json.dumps(manifest, indent=2) + '\n').encode()
    for name, value in payloads.items():
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
    return {name: hashlib.sha256(value).hexdigest() for name, value in payloads.items()}
