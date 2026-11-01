# Documentation guide

## Operators

- [PetaLinux profiles, staging and builds](kr260-petalinux-build-guide.md)
- [Dual-gateware deployment and QSPI environment](dual-gateware-deployment.md)
- [Board enrollment](daphne-board-enrollment-runbook.md)
- [SOM identity and production policy](kria-board-identity-and-production-deployment.md)
- [JTAG and eMMC recovery](uboot-jtag-emmc-flash.md)
- [Station power control](kontron-wiener-power-control.md)
- [Coldbox RS PRO IPS-3303S control](coldbox-rs-pro-ips3303s.md)
- [Coldbox DAPHNE serial console](coldbox-daphne-serial.md)

## Developers and maintainers

- [On-board server builds and client protobuf generation](server-development.md)
- [Server register/transport contract](server-contract.md)
- [Experimental raw DMA diagnostics and board qualification](raw-dma-diagnostics.md)
- [Persistent DMA session driver](raw-dma-persistent-driver.md)
- [Persistent DMA physical qualification and recovery](raw-dma-persistent-physical-results-2026-10-12.md)
- [DAPHNE10 manual DMA/default mode switch](raw-dma-manual-mode-switch.md)
- [DMA manual override flags and physical verification](raw-dma-manual-overrides-results-2026-10-12.md)
- [Repository ownership and preserved history](repository-split.md)
- [Credential audit and public upstream test fixtures](security-audit.md)
- [Frozen dual-gateware RC1 record](releases/dual-gateware-2026.08.31-rc1.md)
- [HDL and Vivado build documentation](https://github.com/DUNE-DAQ/daphne-firmware/blob/develop/docs/build-manual.md)

`pl-i2c-binding-blocker.md` is a historical incident record. The imported
`daphne-server/docs/` tree retains upstream documentation unchanged; use the
current OS runbooks above for deployment policy.

Earlier QSPI experiments and DAPHNE-015 observations are preserved in
[historical bring-up notes](history/kr260-bringup-2026-05.md), not current
installation instructions.
