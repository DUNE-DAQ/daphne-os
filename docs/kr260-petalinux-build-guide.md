# DAPHNE PetaLinux build guide

This is the current image-build procedure for `daphne-os`. HDL, Vivado builds,
and FPGA artifact generation belong to
[daphne-firmware](https://github.com/DUNE-DAQ/daphne-firmware).
Building an image does not flash a board or qualify a release.

## Choose an image profile

| Profile | Contents | Intended use |
| --- | --- | --- |
| `minimal` (default) | Both gateware apps, qualified server, runtime services | Runtime installation |
| `developer` | Minimal plus native compiler, CMake, Protobuf, ZeroMQ and Python development dependencies | Compile your own server on the board |
| `provisioning` | No DAPHNE overlay, server or auto-start runtime services | Bootstrap a virgin SOM before qualified runtime inputs are available |

All profiles produce a whole-eMMC `rootfs.wic.gz` with a 128 MiB FAT `boot`
partition and an ext4 `root` partition. The WIC is a two-partition factory
layout, not an A/B layout. `rootfs.ext4` and the separate boot files also
support updates to an existing inactive A/B slot.

### Developer build workspace

The `developer` profile reserves an extra-space budget of `2097152` KiB
(2 GiB), scoped to `petalinux-image-minimal`. Both the standalone ext4 and
WIC root filesystem receive it. Minimal and provisioning keep their compact
layout; RAM-boot/initramfs helper images do not receive this reservation.

To override the budget, set this in the project's
`project-spec/meta-user/conf/petalinuxbsp.conf`:

```bitbake
IMAGE_ROOTFS_EXTRA_SPACE:pn-petalinux-image-minimal = "2097152"
```

Wic rebuilds its root filesystem rather than copying `rootfs.ext4`. The
`daphne-emmc-developer.wks.in` template therefore explicitly passes
`--extra-space ${IMAGE_ROOTFS_EXTRA_SPACE}K`. Keep the option and value as
separate tokens: the PetaLinux 2026.1 parser resets the equals form to its
10 MiB default.

Filesystem overhead and reserved blocks affect actual available space. Check
`df -h .` in the intended build directory before compiling, and follow
[server development](server-development.md). Larger images need more target
capacity and transfer time; check project rootfs/initramfs limits and existing
A/B slot sizes. Rebuilding does not resize an installed image or an A/B slot.

## Build prerequisites

Use a Linux host with PetaLinux 2026.1 and its matching tools. The staging and
collection scripts also need Python 3, `dtc`/`fdtget`, `unzip`, `readelf`,
`strings`, `tar`, and `sha256sum`. Source the site's PetaLinux settings; on
Cooper the installation is:

```bash
source /tools/petalinux/settings.sh
```

Use a short checkout path in your assigned workspace. For minimal/developer
builds, obtain these inputs before starting:

- self-trigger hardware output, including its XSA and qualified overlay bundle;
- full-stream output with its qualified overlay bundle;
- the exact seven-character build ID for each gateware;
- `daphne-server-runtime-minimal.tgz` with adjacent `BUILD-METADATA.txt` and
  `SHA256SUMS` from the qualified server build.

The output directories can come from separate firmware worktrees. Generate
hardware artifacts in the firmware repository; never use an OS commit as a
hardware build ID. The [server contract](server-contract.md) describes the
pinned runtime requirements. Compiling an edited server does not automatically
qualify it for image staging.

## Build and collect

Run from the OS checkout, replacing the input paths and build IDs:

```bash
cd /path/to/daphne-os

./scripts/petalinux/build_kr260_image.sh \
  /path/to/petalinux-project \
  /path/to/self-trigger/xilinx/output-<self-sha7> \
  --image-profile minimal \
  --self-trigger-output-dir /path/to/self-trigger/xilinx/output-<self-sha7> \
  --self-trigger-sha <self-sha7> \
  --full-stream-output-dir /path/to/full-stream/xilinx/output-<full-sha7> \
  --full-stream-sha <full-sha7> \
  --runtime-bundle /path/to/runtime/daphne-server-runtime-minimal.tgz \
  --bundle-dir /path/to/collected-bundle
```

Choose `--image-profile developer` for an on-board development image. For
`provisioning`, supply the hardware handoff but omit the gateware/runtime
staging arguments. Use `--bsp` to initialize from a BSP instead of the generic
ZynqMP template; see the wrapper's `--help` for all options.

The wrapper creates or reuses the project, imports the hardware handoff,
applies the KR260 machine/console settings, refreshes the project-owned layer,
stages supplied inputs, builds, and collects the result. It preserves the
existing staged inputs when none are supplied. `--skip-stage-overlay` and
`--skip-stage-runtime` skip replacement; they do not remove prior inputs.

`--package-boot` additionally runs `petalinux-package --boot --u-boot --force`.
It is optional, and the resulting `BOOT.BIN` is not a qualified QSPI update.
The wrapper does not produce the historical QSPI-primary/SOM bundles.

## Refresh a project or stage different inputs

Setup and build are separate entry points: `init_kr260_project.sh` performs
project setup without building. To refresh only the layer/configuration in an
already initialized project:

```bash
./scripts/petalinux/bootstrap_kr260_project.sh \
  /path/to/petalinux-project --image-profile developer
```

Each project owns a physical `project-spec/meta-daphne` copy. Refresh replaces
layer code while preserving staged payload directories, generated version
includes, and selected app names. Other profile settings come from the updated
layer. Changes to compatibility contracts may require freshly qualified inputs.

Old layer symlinks are detached into a project-owned copy by bootstrap without
changing the linked source. Unset an old `DAPHNE_META_LAYER_MODE=symlink`
setting first; staging refuses shared layer symlinks. `--copy-layer` remains
accepted by the init/build wrappers for compatibility but is no longer needed.

To deliberately replace the staged release inputs:

```bash
./scripts/petalinux/stage_overlay_into_project.sh \
  /path/to/petalinux-project \
  --self-trigger-output /path/to/self-trigger/xilinx/output-<self-sha7> \
  --self-trigger-sha <self-sha7> \
  --full-stream-output /path/to/full-stream/xilinx/output-<full-sha7> \
  --full-stream-sha <full-sha7>

./scripts/petalinux/stage_runtime_into_project.sh \
  /path/to/petalinux-project \
  /path/to/runtime/daphne-server-runtime-minimal.tgz
```

Staging verifies checksums and compatibility before replacing the previous
payload. The layer fails closed for unqualified runtime or missing dual-app
inputs. After standalone bootstrap, run `petalinux-config --silentconfig`
inside the project before building; the init/build wrappers do this for you.
Do not run concurrent setup/staging/build operations on the same project.

## Collected artifacts and validation

By default the bundle is `petalinux/output/<project-name>/`. It contains:

- `boot/`: kernel, DTB, ramdisk and any available boot/recovery artifacts;
- `rootfs/`: ext4, compressed WIC, package manifest and available archive formats;
- `overlay/`: staged self-trigger/full-stream payloads for runtime profiles;
- `meta/`: collection provenance and applicable runtime contracts;
- `MANIFEST.txt` and `SHA256SUMS`.

The collector requires the kernel, DTB, ramdisk, ext4 and compressed WIC, then
checks the complete checksum manifest before publishing. Missing or invalid
inputs leave the prior bundle intact. Publication failures restore the previous
output; if restoration itself fails, the tool prints the retained backup path.
It refuses to replace unrelated directories or symlinked bundle destinations.

The collector, single-board deployer and campaign wrapper use the same validator:

```bash
python3 scripts/deploy/daphne_bundle.py /path/to/collected-bundle --require-wic
```

The deployment path requires checksums for every image it transfers, and rejects
duplicate, malformed, escaping or symlinked manifest paths. Campaign evidence
captures the validator beside the deployer and checks both before each board.

## Installation and qualification

Use the [dual-gateware runbook](dual-gateware-deployment.md) for deployment,
service checks, gateware switching and the separate QSPI environment step.
Use [JTAG/eMMC recovery](uboot-jtag-emmc-flash.md) for whole-device provisioning.
Do not apply a two-partition boot command to an existing A/B installation.

Shared images remain board-neutral. Enrollment supplies approved board/site
configuration; the SOM EEPROM supplies MAC identity. See
[board enrollment](daphne-board-enrollment-runbook.md). Base device-tree policy
is in [meta-daphne](../petalinux/meta-daphne/recipes-bsp/device-tree/files/);
overlay normalization belongs to the firmware repository.

Software tests and successful builds do not replace per-board post-boot
qualification. Earlier hardware observations and failed QSPI experiments are
preserved in [historical bring-up notes](history/kr260-bringup-2026-05.md), not
used as instructions for the current release.
