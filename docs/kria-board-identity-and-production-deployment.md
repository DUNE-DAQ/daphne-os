# DAPHNE K26 board identity and MAC boot chain

Status: source and hardware audit completed 2026-07-14. The eMMC deployment
path is implemented; the final MAC change on `NP04-DAPHNE-015` is gated on the
LANDB update.

## Production decision

For the existing hardware, use this policy:

1. Read the K26 SOM EEPROM at I2C address `0x50` during enrollment.
2. Store its UUID, serial number and factory MAC ID 0 in the hardware database.
3. Register that factory MAC with the network authority.
4. Provision the same approved value as U-Boot `ethaddr` and verify it on every
   production boot.
5. Let U-Boot copy `ethaddr` into the working device tree.
6. Do not set a MAC in the compiled device tree, FPGA overlay, systemd `.link`
   files, application configuration or image build.
7. Treat a missing or different MAC as an enrollment failure. Do not continue
   with a random address.

This uses the AMD-programmed MAC value, but the hardware database and the
U-Boot environment are the production control points. Explicitly pinning the
approved EEPROM value in `ethaddr` also makes the result independent of
differences between EEPROM parsers and boot-firmware versions.

The source sets `CONFIG_NET_RANDOM_ETHADDR=n`. This takes effect only when a
future U-Boot/boot-firmware image containing that configuration is qualified
and installed. The supported deployment script in this repository writes only
the inactive eMMC slot; it does not update QSPI or change `ethaddr`.

## Physical EEPROM path

AMD defines the K26 identity EEPROM at `0x50`; a carrier-card EEPROM, when
fitted, uses `0x51`. The EEPROM identification-page addresses are `0x58` and
`0x59`, respectively. AMD defines the SOM OEM MAC record's MAC ID 0 as the
primary PS Ethernet address.

The reviewed DAPHNE drawing is `DAPHNE_Mezz_V2_Schematic.pdf`, drawing 177020,
revision 0, sheet 13 of 15, dated 2026-05-22. It shows:

```text
K26 connector C26  MIO24_I2C_SCK
K26 connector C27  MIO25_I2C_SDA
        -> U35 PCA9306 level shifter, 1.8 V to 3.3 V
        -> PS_SCL / PS_SDA
        -> U9 MCP9808 temperature sensor
```

No carrier FRU EEPROM is fitted on `PS_SCL/PS_SDA`. Therefore:

- `0x50` is inside the K26 SOM and remains available;
- `0x51` has no DAPHNE hardware device behind it;
- DAPHNE carrier asset ID/revision cannot be discovered from a carrier FRU;
- carrier identity must come from the physical asset label plus the hardware
  database.

This cannot be changed without a hardware revision, which is outside this
project's constraints.

## AMD flow compared with the DAPHNE flow

| Stage | AMD/Xilinx intended behavior | DAPHNE production behavior |
|---|---|---|
| Manufacturing identity | SOM `0x50`, and carrier `0x51` when present, hold IPMI FRU identity. | Read SOM `0x50`; bind it to the scanned DAPHNE asset. No carrier FRU exists. |
| Board selection | U-Boot can use decoded SOM/carrier names and revisions to select a board configuration or FIT configuration. | Use the fixed `k26c` hardware profile; carrier revision comes from the database and release record. |
| MAC discovery | Xilinx U-Boot parses valid OEM MAC records and initializes Ethernet environment variables. | Enrollment independently decodes MAC ID 0 and records evidence. The approved value is explicitly verified/provisioned as `ethaddr`. |
| Device-tree handoff | U-Boot's Ethernet fix-up follows `ethernetN` aliases and writes the environment MAC into the working FDT. | `ethernet0 = &gem0`; the compiled DT has no MAC property, so the U-Boot value is authoritative. |
| Linux network policy | Site-specific and outside the EEPROM definition. | Render IP, prefix, gateway and DNS from the database. Do not render `MACAddress=`. |
| Network admission | Outside the Kria boot specification. | LANDB/network automation consumes the approved MAC/IP pair from the database. |

AMD documents the UUID as suitable for customer enrollment. DAPHNE follows
that recommendation: the UUID identifies the replaceable SOM; the DAPHNE asset
ID identifies the carrier assembly.

## Exact MAC chain

### EEPROM

Read `/sys/bus/i2c/devices/1-0050/eeprom` and preserve the raw 8192-byte dump
and SHA-256 digest. Decode the board-information UUID/serial and OEM MAC ID 0.

On `NP04-DAPHNE-015`, read-only inspection found:

```text
product       SM-K26-XCL2GC-ED
serial        XFL1YQLNWT4C
UUID          70c5439d-de29-4263-8066-99627ad4ae5e
MAC ID 0      00:0a:35:0e:9b:63
```

FreeIPMI prints that MAC and then reports `multirecord area checksum invalid`.
The OEM MAC record at offset `0x7a` has valid header and payload checksums; the
error occurs when traversal reaches `0xff` padding before a later record. Do
not reinterpret the decoded MAC as `ff:ff:ff:ff:ff:ff`, and do not claim the
whole EEPROM parses without warnings. Production QA records both facts.

### U-Boot

Xilinx `board_late_init_xilinx()` exports decoded board fields and valid MAC
records to environment variables. U-Boot's Ethernet device initialization
prefers a valid environment address over an address obtained from the device
tree or ROM. If no valid address exists, `CONFIG_NET_RANDOM_ETHADDR` controls
whether U-Boot invents one.

DAPHNE therefore requires:

```text
database production_mac == U-Boot ethaddr
```

After LANDB accepts `00:0a:35:0e:9b:63`, provision it once and read it back:

```bash
sudo fw_setenv ethaddr 00:0a:35:0e:9b:63
sudo fw_printenv ethaddr
```

Do not run this before LANDB is ready. Do not merely delete `ethaddr` on a
remote production board: automatic recovery from EEPROM must first be proven
with the exact installed boot firmware and a serial recovery path.

### Base device tree

The source fragment
`petalinux/meta-daphne/recipes-bsp/device-tree/files/daphne-k26c-network.dtsi`
defines `ethernet0 = &gem0` and deletes inherited `mac-address` and
`local-mac-address` properties. This makes the image board-neutral while
retaining the alias that U-Boot requires for its Ethernet fix-up.

### FPGA overlay

The DAPHNE FPGA overlay describes PL devices and names its bitstream. It must
not define GEM aliases or MAC properties. Loading an overlay must not change
the management interface identity.

### PetaLinux runtime configuration

The per-board renderer creates hostname, IP, gateway, DNS and DAPHNE endpoint
files. It includes the factory MAC as informational identity data but never
emits `MACAddress=`, `ethaddr=` or `eth1addr=`. Linux therefore keeps the MAC
that U-Boot placed in the working FDT.

## Current and expected DAPHNE-15 states

The 2026-07-14 read-only observation is intentionally not production-clean:

| Layer | Current value |
|---|---|
| SOM EEPROM MAC ID 0 | `00:0a:35:0e:9b:63` |
| saved U-Boot `ethaddr` | `ba:be:ba:d1:cc:ff` |
| compiled/driver permanent address | `02:00:00:00:00:20` |
| systemd `.link` setter | `ba:be:ba:d1:cc:ff` |
| active Linux address | `ba:be:ba:d1:cc:ff` |

The first eMMC trial deliberately retains the admitted legacy U-Boot address:

```text
ethaddr ba:be:ba:d1:cc:ff
  -> working FDT ba:be:ba:d1:cc:ff
  -> Linux ba:be:ba:d1:cc:ff
```

After LANDB approval, the final state is:

```text
EEPROM record 00:0a:35:0e:9b:63
  == database production_mac
  == U-Boot ethaddr
  == working FDT mac-address/local-mac-address
  == Linux eth0 address
  == LANDB/network admission record
```

## FIT and the rest of the board information

FIT means **Flattened Image Tree**. It is U-Boot's container/manifest for boot
components and configurations: kernel, ramdisk, device tree, firmware or FPGA
payloads, plus hashes and optional signatures.

Do not put the DAPHNE IP address, timing endpoint, hostname or current SOM UUID
in FIT. Those values are mutable, site-specific per-board assignments. Putting
them in a signed boot artifact would require one image and signature per board
and would mix operational configuration with immutable boot content.

| Information | Authoritative location | Runtime copy |
|---|---|---|
| SOM UUID, serial, factory MAC | SOM EEPROM evidence and hardware database | `/etc/daphne-board.env` for diagnostics |
| Carrier asset ID and revision | asset label and hardware database | hostname/board environment |
| Approved MAC | hardware database/network authority | U-Boot `ethaddr`, then working FDT |
| IP, prefix, gateway, DNS | network database | systemd-networkd `.network` file |
| Timing endpoint/profile | DAPHNE hardware database | `/etc/daphne-board.env` |
| Kernel, DTB, ramdisk, FPGA payload | release artifact/FIT or boot bundle | boot storage |

## References

- [AMD K26 SOM EEPROM (DS987)](https://docs.amd.com/r/en-US/ds987-k26-som/EEPROM)
- [AMD Kria SOM EEPROM Design Guide](https://xilinx.github.io/kria-apps-docs/ipmi_eeprom.html)
- [AMD Kria EEPROM mapping](https://xilinx.github.io/kria-apps-docs/creating_applications/2022.1/build/html/docs/EEPROM_mapping_for_Kria_products.html)
- [AMD K26 connector mapping, including C26/C27](https://docs.amd.com/r/en-US/ds1012-xrf4-card/Kria-SOM-K26-SM-K26-XCL2GC-Connector-Specifications)
- [Xilinx U-Boot 2026.01 board EEPROM handling](https://github.com/Xilinx/u-boot-xlnx/blob/xlnx_rebase_v2026.01/board/xilinx/common/board.c)
- [Xilinx U-Boot Ethernet address precedence](https://github.com/Xilinx/u-boot-xlnx/blob/xlnx_rebase_v2026.01/net/eth-uclass.c)
- [U-Boot Ethernet FDT fix-up](https://github.com/Xilinx/u-boot-xlnx/blob/xlnx_rebase_v2026.01/boot/fdt_support.c)
- [U-Boot FIT format](https://docs.u-boot.org/en/v2023.10/usage/fit/source_file_format.html)
