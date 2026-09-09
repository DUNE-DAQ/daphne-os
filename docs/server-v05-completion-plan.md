# Remaining v0.5 server implementation

Active scope requested after server 56b390f. This checklist is not a declaration
of completion; retain every item until implementation and relevant verification
are evidenced. Preserve CERN MAC/IP, installed network settings, zero BIAS and
BIASCTRL, and the existing generator-enable policy. Commit in small steps.

| Requirement | Implementation / evidence needed | State |
| --- | --- | --- |
| ADS1261 current readout | Reuse/reconcile legacy current handler; stable controller ownership, schematic mux mapping, device/status/timeout checks, signed/scaled values and quality; mocks and board readings | Investigating |
| Onboard regulators | Schematic-backed PL bus binding and read-only telemetry; do not introduce regulator configuration writes | Pending |
| Server bookkeeping | Independent heartbeat; observable configuration-in-progress; successful canonical applied-config hash, validity/invalidation, correlated last result; restart and failure tests | Implementing |
| Database identity | Authoritative crate/slot/detector, management IP, timing address and per-Hermes MAC/IP; typed provenance/revision and unavailable handling; distinguish assigned from observed, never change network identity implicitly | Authoritative placement/Hermes record requested |
| Temperature alarms | Configurable high initial thresholds, Good/Warning/High/Critical/Missing/Invalid distinction, boundary/stale tests; observation only, no new shutdown policy | Pending |
| SFP diagnostics | Resolve all connector/mux wiring, especially the possibly unwired port; targeted EEPROM/DDM reads and calibration/status decoding, explicit unsupported/absent/error; no TX-disable changes | Pending |
| FPGA health | Actual loaded/admitted FPGA identity, configuration state, clocks/reset/timing, transport/link observations and clear degraded/unknown reasons; no service-active shortcut | Pending |
| Firmware-dependent gaps | Review live timestamp/decoder/error export needs against both ABIs; isolated Cooper build only for an evidenced necessary firmware change | Pending |
| Qualification and handoff | Native/ARM tests, negative/stale/concurrency cases, live zero-BIAS/all-channel regression, both-ABI scope recorded, protocol clients/docs/wiki and ONL bundle | Pending |

Evidence found so far:

- daphneZMQ commit `a4e19e1` implements `read_current_monitor_raw` through AXI
  Quad SPI at `0x9c020000`; it is present on `main`, `feature/BIAS_voltage_controller`
  and other branches, and is already inherited by this OS server. It is separate
  from the ADS1260-labelled constructor using `/dev/spidev3.0`. Do not run raw
  MMIO against a controller simultaneously owned by the kernel SPI driver.
- The companion `hardware-database` board-config v1 schema contains management
  network and timing assignments, but no crate/slot/detector or Hermes-link fields.
  No example or observed seed is accepted as an approved DAPHNE-015 assignment.
- The existing router executes hardware requests synchronously. Merely adding
  a configuration-in-progress field would not make it observable during a long
  Configure. Keep hardware execution serialized while providing a responsive
  bookkeeping-only request on the existing endpoint.
