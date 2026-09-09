# DAPHNE OS follow-up work

## Resolve monitor/service device identities before retargeting buses

DAPHNE-015 voltage acquisition remains unqualified. The scan-count software
bug is fixed, but ADS7138 initialization still fails and legacy I2C/SPI node
numbers do not match live enumeration. Establish the deployed controller/mux
routes against board wiring, then use stable identities and narrowly targeted
validation. Do not infer missing hardware from missing Linux clients or repair
this through blind bus scans/renumbering. Preserve CERN MAC/IP and clock/bias
policy. See [the telemetry audit](telemetry-ams-verification.md).

## Qualify unattended boot redundancy for underground deployment

Do not adopt an A/B eMMC layout merely because both slots can be written and
selected manually. Underground boards will expose only the management GbE
interface; JTAG and serial recovery will not be available.

An A/B design is acceptable only after a destructive fault-injection campaign
demonstrates recovery when a boot-critical file or filesystem in the selected
slot is corrupted. The implementation must provide at least one of these
qualified recovery paths:

- U-Boot brings up the approved management MAC and static IP, and offers a
  documented authenticated remote recovery/update path over Ethernet; or
- boot firmware detects the failed slot, selects the other complete slot
  automatically, and persists a bounded boot-attempt/last-known-good state.

Acceptance evidence must cover:

- corrupted kernel, device tree, root filesystem, and FPGA application or
  manifest, tested separately;
- automatic boot from the surviving image without JTAG, serial input, or a
  local power-cycle operator;
- preservation of the CERN-approved MAC and static IP in normal and recovery
  boots, with no DHCP or random-MAC dependency;
- restored management-network reachability and SSH after failover;
- a remote procedure for repairing the failed image and returning to a known
  active/last-known-good state;
- repeated cold-boot and power-interruption tests using the production QSPI,
  eMMC, and U-Boot versions.

Until this evidence exists, the supported whole-eMMC installation is the
two-partition WIC layout (FAT boot plus ext4 root). Treat loss of either
partition as requiring physical recovery and record that operational risk in
deployment qualification.

### DAPHNE-015 observation, 2026-09-09

The installed U-Boot 2024.01 retained the approved MAC, static address and
gateway (private site values omitted). A serial-driven ping to the control
host through `ethernet@ff0b0000` nevertheless failed with
`ARP Retry count exceeded`. The boot log also reported `PHY reset timed out`.
Linux management networking worked with this same registered identity.

This is a failed test of the existing U-Boot network setup, not evidence
that Ethernet recovery is impossible. Qualify PHY/SGMII initialization and
an actual remote command/update path before relying on it underground.

The PetaLinux 2026.1 RC1-derived image subsequently booted from the new
two-partition eMMC layout and restored SSH after a cold power cycle, but
exposes no Linux MTD devices. Qualify QSPI driver/device-tree exposure and
the `fw_env.config` mapping before depending on Linux-side boot-environment
updates; `fw_printenv` currently reports `Cannot initialize environment`.
