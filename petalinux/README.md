# PetaLinux Integration Notes

`daphne-os` owns the PetaLinux system, services, and deployment contract that
host `daphne-server`. FPGA HDL and artifact generation live in
[daphne-firmware](https://github.com/DUNE-DAQ/daphne-firmware).

Current contents:

- `toolchains/aarch64-petalinux.cmake` for cross-compiling user-space support
  against a Petalinux SDK/sysroot.
- `daphne-server-deps.lock.cmake` copied from the current `daphne-server`
  checkout so the OS repo records the expected pinned runtime bundle.
- `meta-daphne/` as the repo-owned DT, firmware, userspace, and service
  packaging layer.
- `config/kr260/` and `scripts/petalinux/bootstrap_kr260_project.sh` for
  attaching that layer to an initialized KR260 PetaLinux project.
- `scripts/petalinux/init_kr260_project.sh` for terminal-driven project
  creation/import plus hardware-handoff application.
- `scripts/petalinux/build_kr260_image.sh` and
  `scripts/petalinux/collect_project_artifacts.sh` for repo-owned
  `petalinux-build`, boot packaging, and image artifact collection into a
  stable bundle.
- `docs/kr260-petalinux-build-guide.md` for the current written build and
  staging procedure, updated against the proven `015` findings.
- an optional `packagegroup-daphne-server-build` that stages the target-side
  development dependencies needed by `daphne-server` / `daphneZMQ`

The build wrappers now connect the firmware handoff, repo-owned layer, overlay,
optional runtime bundle, PetaLinux build, boot packaging, and artifact
collection. Current release candidates still require target-board
qualification, and the 2026.1 `daphne-server` dependency bundle must be pinned
and checked as part of each release. QSPI boot firmware remains a separate,
explicitly gated update path.

## Current default package policy

When `scripts/petalinux/bootstrap_kr260_project.sh` attaches `meta-daphne`, the
project-local config now records a `DAPHNE_IMAGE_PROFILE`. The supported
profiles are:

- `provisioning`
  - no `daphne-overlay`, `daphne-server`, or auto-start runtime services
  - intended for JTAG RAM boot and first eMMC installation on a virgin SOM
  - emits `rootfs.wic.gz` with a 128 MiB boot partition to reduce the raw JTAG
    write size compared with AMD's generic 512 MiB boot layout

- `developer`
  - `daphne-overlay`
  - `daphne-server`
  - `daphne-services`
  - `packagegroup-daphne-server-build`
  - `dev-pkgs` and `tools-sdk`
- `minimal`
  - `daphne-overlay`
  - `daphne-server`
  - `daphne-services`

The `developer` packagegroup is meant to make on-target `daphne-server` /
`daphneZMQ` builds practical when explicitly requested. It pulls in the core toolchain plus
the upstream dependency families called out by `daphneZMQ`: ZeroMQ / cppzmq,
protobuf, abseil, CLI11, Python 3, and the Python client packages.

The repo now defaults fresh KR260 projects to `minimal`. That keeps the
current `petalinux-initramfs-image` build under the initramfs size limit. Use
`provisioning` when no qualified FPGA overlay is available, and use
`developer` only when you intentionally want the extra on-target build stack.

All XSA-based image profiles disable the optional QSPI Image Selector. The
2026.1 QSPI A/B firmware is a separate SDT build and qualification stream;
rootfs package selection does not implicitly change boot firmware.

To select the smaller profile during project setup:

```bash
./scripts/petalinux/init_kr260_project.sh \
  /path/to/petalinux-project \
  /path/to/hw-handoff-dir \
  --image-profile minimal
```

or change it later in the project `build/conf/local.conf`:

```conf
DAPHNE_IMAGE_PROFILE = "minimal"
```

## Current bootstrap point

For a full terminal-driven setup from a hardware handoff directory:

```bash
./scripts/petalinux/init_kr260_project.sh \
  /path/to/petalinux-project \
  /path/to/hw-handoff-dir \
  --self-trigger-output-dir /path/to/selftrigger/output-<self-sha7> \
  --self-trigger-sha <self-sha7> \
  --full-stream-output-dir /path/to/fullstream/output-<full-sha7> \
  --full-stream-sha <full-sha7>
```

That wrapper:

- creates the project if needed,
- runs `petalinux-config --get-hw-description`,
- pins the project to the KR260 machine (`xilinx-k26-kr` / `k26-smk-kr`) plus `petalinux-initramfs-image`, then reruns `petalinux-config --silentconfig`,
- attaches `meta-daphne`,
- optionally stages the generated overlay artifacts.

## Boot model status

The current repo build flow is still experimenting with an `initramfs-root`
style image, but that is not the long-term fleet contract.

The target remote-operations contract is documented in:

- `docs/remote-boot-deployment-plan.md`

In short:

- QSPI should own first-stage boot and rescue
- eMMC should own the normal runtime OS
- U-Boot should own slot selection, MAC identity, and fallback state
- Linux should own board services and boot-health confirmation

The current repo-built image should therefore be treated as an experimental
bring-up path until it reproduces the intended eMMC-root remote-boot contract.

## Current full build wrapper

To drive the repo-owned flow through `petalinux-build`, boot packaging, and
bundle collection:

```bash
./scripts/petalinux/build_kr260_image.sh \
  /path/to/petalinux-project \
  /path/to/hw-handoff-dir \
  --self-trigger-output-dir /path/to/selftrigger/output-<self-sha7> \
  --self-trigger-sha <self-sha7> \
  --full-stream-output-dir /path/to/fullstream/output-<full-sha7> \
  --full-stream-sha <full-sha7>
```

That wrapper:

- creates or reuses the project,
- runs `petalinux-config --get-hw-description`,
- attaches `meta-daphne`,
- optionally stages the overlay bundle,
- runs `petalinux-build`,
- runs `petalinux-package --boot --u-boot --force`,
- preserves explicit QSPI-primary boot candidates under `boot/qspi-primary/`,
- validates `BOOT.primary.BIN` with `bootgen -read` when `bootgen` is available,
- emits `PRIMARY-BOOT-BANKS.txt` so the remote staging helper can target the
  right QSPI image bank deterministically,
- collects the resulting artifacts into:

```text
petalinux/output/<project-name>/
```

If you already have an initialized project and only want to attach the layer,
use the lower-level bootstrap script:

To attach the repo-owned layer to an existing PetaLinux project:

```bash
./scripts/petalinux/bootstrap_kr260_project.sh /path/to/petalinux-project
```

That step does not create the project for you and does not yet produce a full
bootable image. It only makes the DAPHNE layer, DT append points, and package
set visible to the project in a reproducible way.

## Current firmware staging point

After qualified builds have produced both overlay bundles, stage the exact
seven-character build IDs. The two output directories may belong to separate
firmware worktrees:

```bash
./scripts/petalinux/stage_overlay_into_project.sh \
  /path/to/petalinux-project \
  --self-trigger-output /path/to/selftrigger/xilinx/output-<self-sha7> \
  --self-trigger-sha <self-sha7> \
  --full-stream-output /path/to/fullstream/xilinx/output-<full-sha7> \
  --full-stream-sha <full-sha7>
```

That copies the two explicitly selected overlay payloads into:

```text
project-spec/meta-daphne/recipes-firmware/daphne-overlay/files/staged/
```

so the `daphne-overlay` recipe has a repo-owned place to install both qualified
firmware artifacts from. Staging validates both source manifests and both DTBO
`firmware-name` properties before replacing anything. Each name is the
immutable xmutil app payload (`<app>.bin`), and the packaging step requires it
to live on the `&fpga_full` fragment while PL peripherals live on `&amba`. If
one variant is missing or ambiguous, the prior staging state is left unchanged.

The installed xmutil app names are immutable:

```text
daphne_selftrigger_ol_<self-sha7>
daphne_fullstream_ol_<full-sha7>
```

The staging transaction rewrites each runtime profile's `APP` field to the
corresponding exact name along with the payload and recipe variables. The
recipe creates no mutable `daphne` alias.

Each completed build should carry an app-scoped manifest beside its archive:

```text
daphne_selftrigger_ol_<self-sha7>.SHA256SUMS
daphne_fullstream_ol_<full-sha7>.SHA256SUMS
```

Those names make `--output-dir /path/to/shared-output` safe even though a
second independent packager may overwrite the compatibility `SHA256SUMS` at
the root. An aggregate root manifest covering both apps is also accepted. If
only legacy root manifests are available, keep the builds in separate output
directories and use `--self-trigger-output` plus `--full-stream-output`.

## Current userspace runtime staging point

After cross-building the pinned server commit, validating it for AArch64, and
placing its generated `BUILD-METADATA.txt` beside the qualified runtime bundle:

```bash
./scripts/petalinux/stage_runtime_into_project.sh \
  /path/to/petalinux-project \
  /path/to/daphne-server-runtime-minimal.tgz
```

That copies the bundle into:

```text
project-spec/meta-daphne/recipes-apps/daphne-server/files/staged/
```

so the `daphne-server` recipe can install:

- `daphneServer`
- `hermes_udp_srv`
- the private runtime libraries needed by `daphneServer`

## Collected bundle layout

After `build_kr260_image.sh` succeeds, the repo-owned bundle directory contains
the collected output shape:

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
      daphne_selftrigger_ol_<sha7>.bin
      daphne_selftrigger_ol_<sha7>.dtbo
      shell.json
      BUILD-METADATA.txt
      SHA256SUMS
    full-stream/
      daphne_fullstream_ol_<sha7>.bin
      daphne_fullstream_ol_<sha7>.dtbo
      shell.json
      BUILD-METADATA.txt
      SHA256SUMS
  meta/
  MANIFEST.txt
  SHA256SUMS
```

This does not guarantee that the build matches the golden image yet, but it
gives the repo a stable place to compare against `~/golden/`.
