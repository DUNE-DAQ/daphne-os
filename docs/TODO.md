# DAPHNE OS follow-up work

## Complete FPGA health evidence across both ABI variants

The [sampled FPGA health checklist](server-fpga-health.md) distinguishes kernel
programming state, live configuration STAT, admitted gateware, clocks, resets,
external timing, FE execution evidence and management observations. Missing
evidence prevents an overall pass; this is not a run permit or safety interlock.

Next firmware work must be isolated and verified before synthesis/deployment:

- Add a coherent live timing snapshot with source/validity and bounded
  request/acknowledgement across clock domains. Expose local-bench and external
  timestamps distinctly. At deployed `3f17f1b`, `endpoint.vhd:387` explicitly
  warns about the existing endpoint-to-master-clock timestamp transfer, and
  `ep_axi` exports only four control/status words. This source-level hazard is
  not a reproduced on-board timestamp failure.
- Test rollover, resets during capture, clock-source changes and stopped source
  clocks; a timed-out snapshot must be unavailable, never a fresh zero value.
- Add meaningful decoder/protocol-error and Hermes data-path evidence. Do not
  reinterpret hardwired-zero/legacy offsets or SFP EEPROM access as measured
  error counters, PCS health, packet delivery, or link-to-stream assignment.
- Establish a reset/reload epoch that survives the events it is meant to detect.
  A counter reset by reloading the same image cannot by itself prove continuity.
- Reserve/version the new addresses and qualify both self-trigger and
  full-stream variants. Keep old control offsets and CERN-approved identities
  unchanged. No new synthesis was launched in the FPGA-health server step;
  Cooper's configured SSH route timed out.

## Finish schematic-backed onboard monitor bindings

The schematic-backed PS I2C1 binding now restores both ADS7138 voltage ADCs;
carrier U9 MCP9808 and three AMS die temperatures are deployed and tested.
See [the carrier/services qualification](carrier-telemetry-and-services-verification.md).
Supply values are plausible, not externally calibrated; zero-command VBIAS0/1
residual readings still need characterization without assuming physical zero.

Onboard U6 ADS1261 now has an identified kernel-owned SPI path, with all 40
carrier-mux channels read twice successfully. See the
[raw-readout qualification](ads1261-readout-verification.md). Current calibration
and known-stimulus analog mapping remain open; do not claim measured amperes.
Next bind the onboard sheet-11/12 regulators, currently hardcoded to absent
`/dev/i2c-2`, by verified PL-controller identity. Review initialization writes
before retargeting either driver. No mezzanines are fitted on DAPHNE-015, but
these onboard devices are not thereby absent. Do not use broad scans, infer
physical absence from Linux clients, or change CERN MAC/IP and clock/bias
policy. Observation-only temperature alarms are implemented with provisional
high thresholds; protection qualification and additional sensor coverage remain
separate work.

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
