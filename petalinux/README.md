# PetaLinux integration

This directory owns the DAPHNE Linux image, runtime packaging and build
configuration. FPGA HDL and artifact generation belong to
[daphne-firmware](https://github.com/DUNE-DAQ/daphne-firmware).

Start with the [PetaLinux build guide](../docs/kr260-petalinux-build-guide.md).
It is the source of truth for profiles, prerequisites, staging, build commands,
developer workspace sizing and artifact validation.

## Contents

- [meta-daphne/](meta-daphne/): device-tree policy, services, overlay/runtime
  recipes and image profiles;
- [config/kr260/](config/kr260/): project configuration fragments;
- [toolchains/](toolchains/): SDK cross-compilation toolchain;
- [daphne-server-deps.lock.cmake](daphne-server-deps.lock.cmake): pinned runtime
  dependency versions;
- [image tools](../scripts/petalinux/): setup, staging, builds and collection.

Projects own their staged inputs; the source layer is not a shared staging
area. Follow the build guide to migrate older symlinked projects.

For installation and service operation, use the
[deployment runbook](../docs/dual-gateware-deployment.md). For native compilation
inside DAPHNE, use [server development](../docs/server-development.md).
QSPI firmware updates remain a separately qualified workflow.
