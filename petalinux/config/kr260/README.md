# KR260 project configuration

These fragments are applied by
[bootstrap_kr260_project.sh](../../../scripts/petalinux/bootstrap_kr260_project.sh).
Use the [PetaLinux build guide](../../../docs/kr260-petalinux-build-guide.md) for
commands, profiles, staged-input preservation and migration from shared layers.

## Owned configuration

- `bblayers.conf.append` attaches the project's `meta-daphne` copy.
- `local.conf.append` selects runtime packages, the WIC layout and the
  developer filesystem-space budget.
- `project-spec/meta-user/` carries the U-Boot configuration overlay.
- Bootstrap pins `xilinx-k26-kr` with the `daphne-k26c-xsa` include and
  UART1 at 115200 across the boot chain. It disables the XSA-flow Image Selector.

Generated configuration uses managed blocks. Repeated setup updates those
blocks without duplicating them; malformed markers are rejected. Keep local
operator settings outside managed blocks and use `petalinuxbsp.conf` for
project-specific build overrides.

The XSA/eMMC build does not qualify QSPI firmware. See the separate
[deployment and QSPI environment procedure](../../../docs/dual-gateware-deployment.md).
