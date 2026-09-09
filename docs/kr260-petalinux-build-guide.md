# DAPHNE KR260 PetaLinux build guide

This guide turns the older screenshot-based bring-up notes into a repo-owned
written procedure for building and staging a DAPHNE PetaLinux image from
`daphne-os`. Build HDL and generate hardware handoffs in the separate
`daphne-firmware` repository.

It is based on the older `DAPHNE SYSTEM DEV (1).docx` flow, but updated to
match the current repo state and the May 9, 2026 bring-up findings on
`NP04-DAPHNE-015`.

## Scope and current status

Current 2026.1 handover target:

- board family: KR260 / ZynqMP
- PetaLinux release: `2026.1`
- Yocto codename: `scarthgap`
- image policy: board-neutral common image
- deployment scope: whole-eMMC provisioning for virgin SOMs, then inactive
  eMMC slot updates for enrolled boards
- board inventory and assignment authority: companion `hardware-database`
  branch `marroyav/daphne-production-qa`

Important current status:

- the repo owns whole-eMMC JTAG provisioning, overlay, service, board-config
  rendering, runtime packaging, and inactive-slot update paths
- the PetaLinux 2026.1 XSA-flow provisioning image builds successfully with
  UART1 at 115200 through PMUFW, FSBL, TF-A, U-Boot, and Linux
- the build emits and checksums `BOOT.BIN`, the JTAG boot ELFs, `Image`,
  `system.dtb`, the ramdisk, `rootfs.ext4`, and a compact `rootfs.wic.gz`
- the WIC layout has a 128 MiB FAT `boot` partition and an ext4 `root`
  partition; both labels have been verified from the generated image
- hardware qualification is still pending the first JTAG/UART/eMMC pilot on
  the DAPHNE carrier
- QSPI A/B firmware is a separate 2026.1 SDT deliverable; it is deliberately
  excluded from the XSA/eMMC image build
- the minimal image stages the exact self-trigger and full-stream applications;
  both generate complete bitstreams, while inherited CDC/methodology findings
  and the four-link target test remain release-qualification gates
- Vivado still reports XXV Ethernet feature-key warnings, but they do not block
  synthesis, implementation, DRC, or bitstream generation under the current
  2026.1/`2026.07` entitlement
- the staged `daphneServer` comes from a qualified, source-identified AArch64
  build; its private protobuf/ZeroMQ libraries and Hermes helper remain legacy
  binary inputs with recorded hashes

Historical bring-up on `DAPHNE-015` proved the older flow with:

  - repo-built `Image`
  - repo-built `system.dtb`
  - repo-built `rootfs.ext4`
  - repo-built tiny switch-root ramdisk
  - full repo-owned runtime service chain

Those observations prove hardware feasibility. The current 2026.1 build is
software-validated but has not yet completed the first-board pilot.
The longer-term boot contract is documented separately in:

- `docs/remote-boot-deployment-plan.md`

The production-oriented plan is:

- use PetaLinux to reproducibly build repo-owned artifacts;
- deploy runtime Linux to the inactive eMMC slot;
- verify boot health before marking a slot good.
- keep QSPI firmware changes outside the production campaign until separately
  qualified.

## Host requirements

Use a Linux-capable build host for the real PetaLinux build.

Required tools:

```bash
petalinux-create
petalinux-config
petalinux-build
petalinux-package
sdtgen
dtc
zip
sha256sum
```

On this workspace, the active PetaLinux settings file is:

```bash
source /tools/petalinux/settings.sh
```

Keep the checkout path short. On Cooper, keep all task data below the assigned
workspace:

```text
/tmp/REPLACE_WITH_FNAL_USER/work/current
```

## Build the firmware handoff

This section runs in the separate `daphne-firmware` checkout. Do not use an
OS commit hash as a hardware build ID.

```bash
cd /path/to/daphne-firmware

export DAPHNE_BOARD=k26c
export DAPHNE_ETH_MODE=create_ip
export DAPHNE_GIT_SHA="$(git rev-parse --short=7 HEAD)"
export DAPHNE_OUTPUT_DIR="./output-$DAPHNE_GIT_SHA"

./scripts/fusesoc/run_vivado_batch.sh
./scripts/package/complete_dtbo_bundle.sh ./xilinx/output-$DAPHNE_GIT_SHA
```

Expected products:

```text
xilinx/output-<gitsha>/
  daphne_selftrigger_<gitsha>.bit
  daphne_selftrigger_<gitsha>.bin
  daphne_selftrigger_<gitsha>.xsa
  daphne_selftrigger_<gitsha>.dtbo
  daphne_selftrigger_ol_<gitsha>/
  daphne_selftrigger_ol_<gitsha>.zip
  daphne_selftrigger_ol_<gitsha>.SHA256SUMS
  SHA256SUMS
```

If implementation finished but DT overlay packaging did not:

```bash
./scripts/package/complete_dtbo_bundle.sh ./xilinx/output-$DAPHNE_GIT_SHA
```

## Vivado PS sanity checks

If you regenerate or edit the block design, confirm the PS-side settings
before exporting hardware. Legacy notes still broadly match the intended KR260
shape:

- GEM0 enabled for management
  - explicitly `sgmii` on the PS GT path with a `fixed-link`
- SD0 / eMMC enabled
- UART1 on MIO 36..37
- I2C1 on MIO 24..25

The current source of truth is the generated `.xsa` plus the repo-owned build
scripts, not the old screenshots.

## Create or reuse the PetaLinux project

Preferred wrapper:

```bash
cd /path/to/daphne-os

PROJECT_DIR=/path/to/daphne-petalinux
HW_HANDOFF_DIR=/path/to/selftrigger/xilinx/output-<self-sha7>

./scripts/petalinux/init_kr260_project.sh \
  "$PROJECT_DIR" \
  "$HW_HANDOFF_DIR" \
  --self-trigger-output-dir /path/to/selftrigger/xilinx/output-<self-sha7> \
  --self-trigger-sha <self-sha7> \
  --full-stream-output-dir /path/to/fullstream/xilinx/output-<full-sha7> \
  --full-stream-sha <full-sha7>
```

This wrapper:

- creates the project if needed
- runs `petalinux-config --get-hw-description`
- attaches `petalinux/meta-daphne`
- stages overlay payload
- applies the repo-owned image profile and board-config hooks

Current default:

- fresh KR260 projects now default to `--image-profile minimal`
- use `--image-profile provisioning` for virgin-SOM JTAG/eMMC bootstrap when
  no qualified FPGA overlay has been staged; this profile omits the overlay
  and DAPHNE runtime services
- use `--image-profile developer` only when you explicitly want the on-target
  build stack and are prepared to carry a larger image footprint

### Developer build workspace

The `developer` profile defaults `IMAGE_ROOTFS_EXTRA_SPACE` to `2097152` KiB
(2 GiB), scoped to `petalinux-image-minimal`. Both `rootfs.ext4` and the root
filesystem inside `rootfs.wic.gz` receive this extra-space budget. The developer
WIC uses `daphne-emmc-developer.wks.in`: Wic's `rootfs` source rebuilds the
filesystem instead of copying the already-sized `rootfs.ext4`, so the template
explicitly passes `--extra-space ${IMAGE_ROOTFS_EXTRA_SPACE}K`. Keep the option
and value as separate tokens: PetaLinux 2026.1's Wic parser silently resets the
equals form to its 10 MiB default.

To change that budget, set the recipe-scoped value in the project's
`project-spec/meta-user/conf/petalinuxbsp.conf`, for example:

```bitbake
IMAGE_ROOTFS_EXTRA_SPACE:pn-petalinux-image-minimal = "2097152"
```

Wic's normal overhead factor still applies; the budget is not an exact free
space guarantee after filesystem metadata and reserved blocks. Check `df -h .`
in the intended build directory on the board before compiling. Larger developer
images require more destination capacity and take longer to transfer over JTAG.
Do not apply the extra-space setting globally to RAM-boot/initramfs images.

The `minimal` and `provisioning` profiles retain `daphne-emmc.wks` and their
compact layout. All profiles retain the 128 MiB FAT `boot` partition, ext4
`root` label, and partition start alignment. This whole-eMMC packaging setting
does not change QSPI firmware, U-Boot environment, runtime services, or the
capacity of existing A/B slots; verify slot size before an inactive-slot update.
Re-run bootstrap with `--image-profile developer` and rebuild an existing project
to pick up the corrected template. Previously published images are unchanged.

### Attach the layer to an existing project

If you already have a project and only need to attach the repo-owned layer:

```bash
./scripts/petalinux/bootstrap_kr260_project.sh "$PROJECT_DIR"
./scripts/petalinux/stage_overlay_into_project.sh \
  "$PROJECT_DIR" \
  --self-trigger-output /path/to/selftrigger/xilinx/output-<self-sha7> \
  --self-trigger-sha <self-sha7> \
  --full-stream-output /path/to/fullstream/xilinx/output-<full-sha7> \
  --full-stream-sha <full-sha7>
```

If you also have a harvested runtime bundle:

```bash
./scripts/petalinux/stage_runtime_into_project.sh \
  "$PROJECT_DIR" \
  /path/to/daphne-server-runtime-minimal.tgz
```

## Manual equivalent of the older screenshot flow

Use the wrappers above unless you are debugging PetaLinux directly.

Create the project:

```bash
petalinux-create project -t zynqMP -n daphne-petalinux
cd daphne-petalinux
petalinux-config --get-hw-description /path/to/handoff-dir
```

Then configure U-Boot if needed:

```bash
petalinux-config -c u-boot
```

Build:

```bash
petalinux-build -c u-boot
petalinux-build
petalinux-package --boot --u-boot --force
```

## Preferred full build wrapper

Use the repo-owned wrapper for the full image path:

```bash
cd /path/to/daphne-os

PROJECT_DIR=/path/to/daphne-petalinux
HW_HANDOFF_DIR=/path/to/selftrigger/xilinx/output-<self-sha7>

./scripts/petalinux/build_kr260_image.sh \
  "$PROJECT_DIR" \
  "$HW_HANDOFF_DIR" \
  --self-trigger-output-dir /path/to/selftrigger/xilinx/output-<self-sha7> \
  --self-trigger-sha <self-sha7> \
  --full-stream-output-dir /path/to/fullstream/xilinx/output-<full-sha7> \
  --full-stream-sha <full-sha7>
```

Collected output lands in:

```text
petalinux/output/<project-name>/
  boot/
    BOOT.BIN
    zynqmp_fsbl.elf
    pmufw.elf
    bl31.elf
    u-boot.elf
    u-boot-dtb.elf
    Image
    system.dtb
    ramdisk.cpio.gz.u-boot
  rootfs/
    rootfs.ext4
    rootfs.wic.gz
  overlay/
    daphne-overlay-version.inc
    self-trigger/
      daphne_selftrigger_ol_<self-sha7>.dtbo
      daphne_selftrigger_ol_<self-sha7>.bin
      shell.json
      BUILD-METADATA.txt
      SHA256SUMS
    full-stream/
      daphne_fullstream_ol_<full-sha7>.dtbo
      daphne_fullstream_ol_<full-sha7>.bin
      shell.json
      BUILD-METADATA.txt
      SHA256SUMS
  meta/
  MANIFEST.txt
  SHA256SUMS
```

At minimum, check for:

```text
boot/Image
boot/system.dtb
boot/zynqmp_fsbl.elf
boot/pmufw.elf
boot/bl31.elf
boot/u-boot-dtb.elf
boot/ramdisk.cpio.gz.u-boot
rootfs/rootfs.ext4
rootfs/rootfs.wic.gz
overlay/daphne-overlay-version.inc
overlay/self-trigger/daphne_selftrigger_ol_<self-sha7>.dtbo
overlay/self-trigger/daphne_selftrigger_ol_<self-sha7>.bin
overlay/full-stream/daphne_fullstream_ol_<full-sha7>.dtbo
overlay/full-stream/daphne_fullstream_ol_<full-sha7>.bin
```

`BOOT.BIN` is collected only when `build_kr260_image.sh --package-boot` is
explicitly requested. It is not a qualified QSPI campaign artifact.

## Historical QSPI development notes

The remaining QSPI material in this document records the earlier 2024.1
bring-up and recovery experiments. It is not an instruction to generate or
write QSPI from the current 2026.1 source candidate. The 2026.1 custom machine
removes `kria-qspi` from `EXTRA_IMAGEDEPENDS`, and the current collector emits
the whole-eMMC provisioning image plus the inactive-slot update payload.

Historically, the collected boot artifacts were split into three tiers:

- `boot/BOOT.BIN`
  the stock PetaLinux package output
- `boot/qspi-primary/BOOT.primary.BIN`
  the narrower repo-owned primary-bank payload used for focused bank-level
  boot-chain experiments
- `boot/qspi-som/kria-qspi.bin`
  the AMD/KR260 full-SOM QSPI image wrapper that includes Image Selector,
  persistent registers, dual BOOT.BIN banks, and the recovery image

That distinction matters. `BOOT.primary.BIN` is still useful for bank-level
debug on an already-partitioned live QSPI layout, but the long-term
AMD-compatible whole-flash artifact is `boot/qspi-som/kria-qspi.bin`.

When `bootgen` is available, the build still validates that
`boot/qspi-primary/BOOT.primary.BIN` resolves to the expected primary image
headers and records that result in
`boot/qspi-primary/PRIMARY-BOOT-VALIDATION.txt`.

All three XSA-based image profiles pin:

- `# CONFIG_SUBSYSTEM_COMPONENT_IMG_SEL is not set`
- `CONFIG_SUBSYSTEM_UBOOT_EXT_DTB=y`

Image Selector is not part of the JTAG-to-U-Boot/eMMC staging path, and the
legacy XSCT application template is unavailable in the installed 2026.1
tools. The separate U-Boot DTB remains explicit. Treat the complete QSPI A/B
image as a separate SDT-based, qualified boot-firmware deliverable; do not
make it a prerequisite for recovering or provisioning a virgin SOM.

Do not run `petalinux-build -c kria-qspi` in this XSA project. The equivalent
`kria-qspi` target belongs in the separate K26 SDT boot-firmware project; that
workstream must emit and qualify the complete `kria-qspi.bin` SOM image around
Image Selector, recovery, and the duplicated boot banks.

## Deployment host topologies

The normal documented setup is general: a Linux/Vivado/PetaLinux host connected
directly to a DAPHNE board. That host owns the build workspace, can reach the
board's management SSH address, and has serial/JTAG access when recovery is
needed.

For a directly connected host, deploy the collected bundle with:

```bash
./scripts/deploy/daphne_deploy.sh \
  --board daphne-15 \
  --host 10.73.137.16 \
  --bundle petalinux/output/<project-name> \
  --board-config /path/to/rendered/daphne-15 \
  --host-key-sha256 SHA256:<ed25519-fingerprint> \
  --emmc inactive-slot \
  --dry-run
```

Remove `--dry-run` only after the preflight reports the expected active and
target slots.

The deploy helper stages transient files on the target under
`/tmp/daphne-deploy` by default, not under the small root filesystem. If the
active runtime provides `resize2fs`, the helper grows the inactive ext4 rootfs
after writing the compact `rootfs.ext4` payload.

Running from ONL is the same direct-host workflow if the repo and bundle are on
ONL:

```bash
./scripts/deploy/daphne_deploy.sh \
  --board daphne-15 \
  --host 10.73.137.16 \
  --bundle /path/to/petalinux/output/<project-name> \
  --board-config /path/to/rendered/daphne-15 \
  --host-key-sha256 SHA256:<ed25519-fingerprint> \
  --emmc inactive-slot
```

The workstation-to-ONL-to-DAPHNE arrangement used during the May 2026 recovery
is a relay topology, not a separate deployment architecture. Use
`--control-host` only when the bundle is local to the workstation but the board
is reachable/trusted from ONL:

```bash
./scripts/deploy/daphne_deploy.sh \
  --board daphne-15 \
  --host 10.73.137.16 \
  --bundle petalinux/output/<project-name> \
  --board-config /path/to/rendered/daphne-15 \
  --host-key-sha256 SHA256:<ed25519-fingerprint> \
  --emmc inactive-slot \
  --control-host marroyav@np04-onl-004.cern.ch
```

For a healthy board, the preferred QSPI boot-firmware update helper is:

```bash
./scripts/remote/stage_bootfw_update_over_ssh.sh \
  <board-host> \
  /path/to/petalinux/output/<project-name> \
  --dry-run
```

That helper copies the repo-built boot-firmware image to the board as
`BOOT.BIN`, runs `xmutil bootfw_update -i`, records `xmutil bootfw_status`, and
expects a reboot or power-cycle followed immediately by:

```bash
./scripts/remote/stage_bootfw_update_over_ssh.sh \
  <board-host> \
  --verify-only
```

The install step is intentionally gated. After the dry-run and recovery
preflight are complete, pass `--force-install` for a real install/update.

Current DAPHNE-specific caveat:

- some K26 SOM FRUs report product names such as `SM-K26-XCL2GC-ED`;
- the Xilinx `image_update` backend in the 2024.1 stack truncates this to
  `SM-K26-`;
- the stock whitelist only accepted the older `SMK-K26` spelling, causing
  `xmutil bootfw_update -i` to reject the board;
- `petalinux/meta-daphne/recipes-apps/image-update` patches the whitelist so
  repo-built images accept the current `SM-K26-*` FRU prefix.

Historical recovery caveat: during the May 12 recovery, the temporary slot-B
rootfs did not have `xmutil` installed directly, so boot-firmware status was
checked through the p2-mounted backend:

```bash
sudo -n /run/media/root-mmcblk0p2/usr/bin/image_update -p
```

That is no longer the normal `DAPHNE-15` state after the May 13 rebuilt runtime
deployment. Both runtime slots now contain `xmutil`; use normal
`xmutil bootfw_status` checks unless the board has regressed into the older
recovery image.

Relevant AMD references:

- [KR260 Boot Devices and Firmware Overview (UG1092)](https://docs.amd.com/r/en-US/ug1092-kr260-starter-kit/Boot-Devices-and-Firmware-Overview)
- [KR260 Board Reset, Firmware Update, and Recovery (UG1092)](https://docs.amd.com/r/en-US/ug1092-kr260-starter-kit/Board-Reset-Firmware-Update-and-Recovery)
- [Kria SOM Boot Firmware Update](https://xilinx-wiki.atlassian.net/wiki/spaces/A/pages/3020685316/Kria%2BSOM%2BBoot%2BFirmware%2BUpdate)
- [Moving from AMD Software Stacks to Production Deployment](https://xilinx-wiki.atlassian.net/wiki/spaces/A/pages/2741928025/Moving%2Bfrom%2BAMD%2BSoftware%2BStacks%2Bto%2BProduction%2BDeployment)
- [PetaLinux Image Selector (UG1144)](https://docs.amd.com/r/en-US/ug1144-petalinux-tools-reference-guide/Image-Selector)
- [Building a Separate U-Boot DTB (UG1144)](https://docs.amd.com/r/2021.2-English/ug1144-petalinux-tools-reference-guide/Building-a-Separate-U-Boot-DTB)

The repo-owned full-SOM staging helper is a factory/recovery helper:

```bash
./scripts/remote/stage_kria_qspi_som_over_ssh.sh \
  <board-host> \
  /path/to/petalinux/output/<project-name>
```

That helper uses `boot/qspi-som/QSPI-SOM-LAYOUT.txt` to flash KR260 boot
firmware partitions from `kria-qspi.bin` while deliberately leaving:

- `U-Boot storage variables`
- `U-Boot storage variables backup`
- `Secure OS Storage`
- `User`

untouched on the live board.

The repo-owned direct bank helper for controlled diagnostics is:

```bash
./scripts/remote/stage_qspi_primary_over_ssh.sh \
  <board-host> \
  /path/to/petalinux/output/<project-name> \
  --bank b
```

That helper uses `boot/qspi-primary/PRIMARY-BOOT-BANKS.txt`, copies
`BOOT.primary.BIN` to the board, flashes the selected QSPI image bank with
`flashcp`, verifies the readback prefix hash, and prints the matching temporary
MultiBoot value for the later serial boot test.

The matching serial-side bank test is:

```bash
./scripts/remote/test_qspi_primary_multiboot.sh \
  /path/to/petalinux/output/<project-name> \
  --bank b \
  --device /dev/ttyUSB2
```

After a bank passes that temporary MultiBoot boot test, promotion may be a
second run of `stage_qspi_primary_over_ssh.sh` against the other bank, but only
as a deliberate lab/factory action. Normal remote updates should use
`stage_bootfw_update_over_ssh.sh`.

## Overlay generation notes

The manual `xsct` / `createdts` flow from the older notes is still useful for
debugging. Generate the overlay in the `daphne-firmware` checkout:

```bash
./scripts/package/complete_dtbo_bundle.sh ./xilinx/output-$DAPHNE_GIT_SHA
```

Each overlay runtime also needs the firmware-name alias expected by its DTBO.
The dual-app recipe derives and validates both names from the immutable app
IDs, then installs aliases such as:

```text
/lib/firmware/daphne_selftrigger_ol_<self-sha7>.bin
/lib/firmware/daphne_fullstream_ol_<full-sha7>.bin
```

Both aliases are owned by the repo overlay packaging. A PetaLinux image build
fails closed until both variants have been staged; it never substitutes the
checked-in historical self-trigger payload for a missing release artifact.

## Device-tree policy

Do not hand-edit generated `pl.dtsi` files in the project workspace as the
long-term solution.

The OS base-tree policy lives in:

- `petalinux/meta-daphne/recipes-bsp/device-tree/files/system-user.dtsi`
- `petalinux/meta-daphne/recipes-bsp/device-tree/files/daphne-k26c-network.dtsi`

Hardware overlay normalization remains in
[daphne-firmware/scripts/package/normalize_pl_overlay.py](https://github.com/DUNE-DAQ/daphne-firmware/blob/develop/scripts/package/normalize_pl_overlay.py).

The overlay normalizer emits two fragments. FPGA programming properties,
clocks, AFI configuration, resets, and ZOCL target `&fpga_full`; PL peripheral
nodes target `&amba`. In particular, `firmware-name` must never be placed on
the AXI bus node: `xmutil` can apply such a device-tree fragment without ever
programming the FPGA. The normalizer also rewrites the generated interrupt
parent to the base-tree `gic` symbol and repairs the AXI interrupt and SPI
bindings before `dtc` runs.

Important current finding:

- the generated base `pl.dtsi` on `015` originally injected `pl-bus`,
  `axi_iic_0`, `axi_intc_0`, and `axi_quad_spi_0` into the non-overlay DT
- that caused the early `rcu_sched` boot failure
- the repo fix is to delete the generated base `amba_pl` node in
  `system-user.dtsi`, so those PL timing nodes arrive only through the overlay

That fix is now part of the repo-owned DAPHNE DT policy.

## Network configuration notes

The older static `ifconfig` / `rc.local` approach should not be treated as the
fleet contract.

Current DAPHNE policy is:

- one shared image
- repo-owned board inventory
- board-specific identity generated from:
  - MAC addresses
  - hostname
  - management IP
  - endpoint address
  - firmware app
  - timing profile

So board identity is no longer “MAC only”.

## Boot and board validation

After booting the image:

```bash
ssh petalinux@<board-ip>
uname -a
cat /etc/os-release
ip addr show eth0
```

Then validate runtime state:

```bash
systemctl is-active firmware
systemctl is-active clockchip
systemctl is-active endpoint
systemctl is-active hermes
systemctl is-active daphne
```

Validate the overlay/runtime expectations:

```bash
xmutil listapps
ls -l /lib/firmware/xilinx
ls -l /dev/i2c-*
ss -ltnp | grep 40001
```

For `015`, a successful runtime bring-up now means:

- the expected eMMC slot mounted as `/`
- FPGA state `operating`
- PL timing path present
- service chain active

After the May 13 runtime redeployment, the active autonomous boot is QSPI Image
B into eMMC slot B (`/dev/mmcblk0p4`). QSPI persistent state reports Image B as
both requested and last booted.

## Proven DAPHNE-15 flash workflow

The currently proven offline rootfs flash path on `015` is:

1. stage `rootfs.ext4` on `mmcblk0p1`
2. boot a maintenance shell from a known-good kernel/DT/ramdisk
3. `dd` the staged `rootfs.ext4` onto `mmcblk0p2`
4. `e2fsck`
5. reboot normally

Maintenance-shell example:

```bash
setenv bootargs 'console=ttyPS1,115200 earlycon rdinit=/bin/sh'
fatload mmc 0:1 0x18000000 Image
fatload mmc 0:1 0x40000000 system.dtb
fatload mmc 0:1 0x02100000 ramdisk.cpio.gz.u-boot
booti 0x18000000 0x02100000 0x40000000
```

In the shell:

```bash
mkdir -p /proc /sys /dev /mnt
mount -t devtmpfs devtmpfs /dev
mount -t proc proc /proc
mount -t sysfs sysfs /sys
mount /dev/mmcblk0p1 /mnt
dd if=/mnt/deploy-20260509-repo/rootfs.ext4 of=/dev/mmcblk0p2 bs=16M
sync
e2fsck -fy /dev/mmcblk0p2
reboot -f
```

## What was actually proven on 2026-05-09

On `NP04-DAPHNE-015`:

- the rebuilt repo-owned `rootfs.ext4` was flashed successfully
- the board came back with `/dev/mmcblk0p2` as the real `/`
- the repo-owned service chain came up without live rootfs patching
- the fixed repo-owned DTB was first proven in one-shot serial/U-Boot boot
  testing, and is now the persistent default `/boot/system.dtb` on `015`
- the repo-built `Image` is now also the top-level boot image on
  `mmcblk0p1`, and `015` comes back through the normal U-Boot `bootcmd`
  path with the repo-built `Image + system.dtb + ramdisk`
- after a plain reboot, `015` comes back on `10.73.137.16` with the full
  `firmware`, `clockchip`, `endpoint`, `hermes`, and `daphne` chain active
- the early DT-related `rcu_sched` stall is gone

2026-05-12 update:

- the remote-only eMMC A/B deployment path is now proven through
  `scripts/deploy/daphne_deploy.sh` from this workstation via
  `np04-onl-004`;
- the corrected repo-built image was written to inactive slot A, booted,
  marked healthy by `daphne-boot-ok.service`, and survived a plain reboot with
  `/dev/mmcblk0p2` as `/`;
- `dfx-mgr`, `firmware`, `clockchip`, `endpoint`, `hermes`, and `daphne`
  services were active, FPGA manager state was `operating`, and
  `daphneServer` was reachable on `10.73.137.16:40001`.

2026-05-13 update:

- the runtime image was rebuilt with unused NFS/rpcbind runtime packages
  removed so non-DAPHNE service failures do not hide the real board state;
- `e2fsprogs-resize2fs` is included in the runtime image;
- `scripts/deploy/daphne_deploy.sh` now stages through `/tmp/daphne-deploy`
  by default and grows the inactive ext4 rootfs when `resize2fs` is available;
- the cleaned runtime generation was deployed to both slot A
  (`/dev/mmcblk0p2`) and slot B (`/dev/mmcblk0p4`);
- both rootfs filesystems are grown to the full rootfs partition size;
- the final accepted boot is slot B with `active_slot=b`, `last_good_slot=b`,
  `upgrade_available=0`, and `bootcount=0`;
- `dfx-mgr`, `firmware`, `clockchip`, `endpoint`, `hermes`, and `daphne`
  are active, `daphne-boot-ok.service` completed successfully, FPGA manager is
  `operating`, `systemctl --failed` reports no failed units, and
  `daphneServer` is reachable on `10.73.137.16:40001`.

What is still not fully proven:

- the repo-built QSPI boot-firmware update path through
  `xmutil bootfw_update` / `stage_bootfw_update_over_ssh.sh`; on May 13 the
  helper's current `BOOT.primary.BIN` payload was accepted by `xmutil` and
  written to Image A, but `015` did not boot it and did not recover with a
  normal cold cycle;
- the confirmed QSPI recovery path for that failed install was legacy XSCT
  `boot.tcl`, followed by U-Boot `sf` restore of pre-attempt QSPI backups for
  Image Selector, persistent registers, Image A, and the SHA256 region;
- fully unattended rollback after a genuinely broken boot attempt with the
  rebuilt U-Boot payload.

## Where this guide differs from the older notes

The older notes and screenshots are still useful, but these parts are now
outdated:

- `meta-daphne` is no longer only a placeholder layer
- board identity is no longer just MAC provisioning
- the `015` DTB failure is now understood and fixed
- the current repo has a real runtime staging path:
  `scripts/petalinux/stage_runtime_into_project.sh`
- the current missing piece is not “can we build any image at all”, but
  “can we complete the repo-owned persistent boot contract”
