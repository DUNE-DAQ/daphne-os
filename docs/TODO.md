# DAPHNE OS follow-up work

## Finish schematic-backed onboard monitor bindings

The schematic-backed PS I2C1 binding now restores both ADS7138 voltage ADCs;
carrier U9 MCP9808 and three AMS die temperatures are deployed and tested.
See [the carrier/services qualification](carrier-telemetry-and-services-verification.md).
Supply values are plausible, not externally calibrated; zero-command VBIAS0/1
residual readings still need characterization without assuming physical zero.

Next, reconcile onboard U6 ADS1261 (schematic sheet 7) with the legacy
ADS1260-labelled current-monitor driver and its absent `/dev/spidev3.0` path.
Also bind the onboard sheet-11/12 regulators, currently hardcoded to absent
`/dev/i2c-2`, by verified PL-controller identity. Review initialization writes
before retargeting either driver. No mezzanines are fitted on DAPHNE-015, but
these onboard devices are not thereby absent. Do not use broad scans, infer
physical absence from Linux clients, or change CERN MAC/IP and clock/bias
policy. Temperature alarm thresholds and additional sensor coverage remain
separate qualification work.

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
