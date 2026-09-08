# daphne-os

The DAPHNE Linux image, userspace server, runtime services, and deployment tools.
HDL, Vivado/FuseSoC builds, and FPGA artifact generation belong to
[daphne-firmware](https://github.com/DUNE-DAQ/daphne-firmware).

## Repository layout

| Path | Owns |
| --- | --- |
| `daphne-server/` | C++ server, protobuf schemas, clients, and server tests imported from daphneZMQ with full history |
| `petalinux/` | PetaLinux layer, profiles, boot configuration, service recipes, and SDK toolchain |
| `scripts/petalinux/` | Image setup, staging, builds, and artifact collection |
| `scripts/deploy/` | Board configuration, deployment campaigns, and qualification records |
| `scripts/remote/` | Serial/JTAG recovery, QSPI/eMMC provisioning, and station support |
| `scripts/server/` | Native on-board developer build helper |
| `tests/` | OS, deployment, recovery, and repository-boundary regressions |

The repositories exchange qualified XSA, bitstream, DTBO, and checksum-manifest
artifacts, not private source-directory layouts. OS wrappers locate this
repository themselves; `DAPHNE_OS_ROOT` overrides that location.
`DAPHNE_FIRMWARE_ROOT` remains a firmware-build setting and is not an OS root.

## Build and deploy

Start with the [PetaLinux build guide](docs/kr260-petalinux-build-guide.md) and
[image profiles](petalinux/README.md). Supply hardware output from the selected
firmware releases, plus a qualified userspace runtime bundle. The checked-in
staging sentinels deliberately reject unqualified runtime or overlay inputs.

Use the [dual-gateware deployment runbook](docs/dual-gateware-deployment.md) for
campaigns, service checks, application switching, and the separate QSPI U-Boot
environment step. Flashing, rebooting, service replacement, and qualification
remain explicit operator actions; a successful build is not qualification.

## Compile your own server inside DAPHNE

Boot the `developer` image profile, clone this repository on the board, then:

```bash
./scripts/server/build_native.sh ./daphne-server ./build/server-native
```

The helper builds the server and Python protobuf modules, runs hardware-free
unit tests, and checks the command-line interface. It does not install the
binary, change services, or access FPGA registers. See
[server development](docs/server-development.md) for incremental builds,
client protobuf generation, and installation boundaries.

## History and releases

The active imported server is the dual-gateware-compatible `77b39b7` revision.
Its original commits are retained, without squashing or rewriting. All 25
source branches and 15 source tags are retained under `archive/daphneZMQ/`;
they are historical references, not supported deployment branches.

See [the repository split and provenance](docs/repository-split.md) and
[the credential audit](docs/security-audit.md). The original repositories and
the published dual-gateware RC1 tag/assets are unchanged. Historical release
manifests intentionally retain their original repositories, hashes, and paths.

The [documentation guide](docs/README.md) lists operator and developer entry points.
