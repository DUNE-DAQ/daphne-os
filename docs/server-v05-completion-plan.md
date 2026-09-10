# Remaining v0.5 server implementation

Active scope requested after server 56b390f. This checklist is not a declaration
of completion; retain every item until implementation and relevant verification
are evidenced. Preserve CERN MAC/IP, installed network settings, zero BIAS and
BIASCTRL, and the existing generator-enable policy. Commit in small steps.

| Requirement | Implementation / evidence needed | State |
| --- | --- | --- |
| ADS1261 current readout | Reuse/reconcile legacy current handler; stable controller ownership, schematic mux mapping, device/status/timeout checks, signed/scaled values and quality; mocks and board readings | Raw 40-channel path deployed: 17 native/ARM suites, 45 tracked Python tests and 80 live CRC-checked acquisitions passed. Calibrated amperes and analog channel mapping remain unqualified |
| Onboard regulators | Schematic-backed PL bus binding and read-only telemetry; do not introduce regulator configuration writes | Deployed as a729c2b: four identified modules, PEC-checked raw/decoded voltage/current/temperature, status flags and alarms; see regulator qualification. Manufacturer status/VIN and metrology remain unqualified |
| Server bookkeeping | Independent heartbeat; observable configuration-in-progress; successful canonical applied-config hash, validity/invalidation, correlated last result; restart and failure tests | Implemented, native/ARM and live configuration tests passed; see bookkeeping qualification |
| Database identity | Authoritative crate/slot/detector, management IP, timing address and per-Hermes MAC/IP; typed provenance/revision and unavailable handling; distinguish assigned from observed, never change network identity implicitly | Private artifact and protocol reporting deployed/tested: placement, management IPv4 and one Hermes assignment; separate live management comparison and timing-control address readback. Approved timing/management-MAC assignments, physical-link mapping and actual FPGA placement readback remain pending |
| Temperature alarms | Configurable high initial thresholds, Good/Warning/High/Critical/Missing/Invalid/Stale distinction, boundary/stale tests; observation only, no new shutdown policy | Implemented; 14 native/ARM suites and live normal-temperature/all-channel checks passed. High/fault cases synthetic, not physical trips |
| SFP diagnostics | Resolve all connector/mux wiring, especially the possibly unwired port; targeted EEPROM/DDM reads and calibration/status decoding, explicit unsupported/absent/error; no TX-disable changes | Implemented/deployed; 18 native/ARM suites and 53 Python tests pass. GTH0/TMG/GTR identified; 14 diagnostic values per acquisition. Three unanswered cages and installed PCB/wiring caveat remain unresolved; factory RX warnings retained |
| FPGA health | Actual loaded/admitted FPGA identity, configuration state, clocks/reset/timing, transport/link observations and clear degraded/unknown reasons; no service-active shortcut | Sampled programming STAT and 15-check assessment deployed/tested; see server-fpga-health.md. Coherent live timestamp, Hermes delivery and external-reset epoch remain unknown; no overall health/run-permit claim |
| Firmware-dependent gaps | Review live timestamp/decoder/error export needs against both ABIs; isolated Cooper build only for an evidenced necessary firmware change | Native timestamp RTL/ABI 2.1 and physical-check scripts committed on firmware branch fix/health-timestamp-abi21. Server/OS admission, snapshot collector, protocol, health and client source tests now pass. No synthesis/deployment yet; bundle ABI staging, routed/live qualification and decoder/error exports remain pending |
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
- The router now provides a responsive bookkeeping-only request while a single
  worker serializes hardware execution. See
  [implementation and live qualification](server-bookkeeping-verification.md).
- ONL's `ehn1-vst-daphne15` OKS configuration contains matching board and stream
  placement records plus a Hermes network-interface assignment. No timing
  endpoint assignment was found there yet. Separate VST JSON files inspected
  identify board 61, not 15; do not apply their settings to DAPHNE-015.
- [ADC and SFP schematic details](server-remaining-hardware-evidence.md): U6
  has five differential DA/DB pairs, not the legacy default ten single-ended
  selections. All six SFP I2C routes are drawn; the installed-board wiring caveat
  still needs qualification. [Current ADC reads are now qualified](ads1261-readout-verification.md)
  within the raw-readout scope. [SFP collection is implemented](sfp-diagnostics-verification.md);
  unresponsive-cage population/wiring and approved Hermes associations remain open.
- [Temperature alarm qualification](temperature-alarm-verification.md):
  provisional 85/95/105 C monitoring thresholds, configurable at startup and
  returned with each evaluation. No automatic protection action was added.

## Native timestamp firmware progress — not deployed

Firmware branch `fix/health-timestamp-abi21`, based on the dual-release tree,
now contains `65de6d0` (native-clock mailbox), `ab61fb7` (local reset release),
`ab08082` (AXI snapshot registers and platform ABI 2.1), and `1bb3765` (bounded
payload constraints and mandatory routed checks). Its parent has the same timing
RTL as deployed firmware `3f17f1b`; no waveform/acquisition timestamp mux change
was made. The source-side monitoring capture is separate from that still
unqualified acquisition crossing.

The feature adds coherent 64-bit observations, source/validity/failure flags,
an attempt sequence, bounded AXI response, and quarantine/discard of late replies
after stopped clocks resume. It also fixes the timing AXI slave's dropped-read
risk under backpressure and rejects formerly aliased high-offset accesses.

Evidence in the firmware qualification workspace: eight GHDL CDC/AXI simulation
runs, all eleven local FuseSoC smoke tests, and twelve Tcl mock-model tests pass.
Register-map, documentation and timing-boundary/constraint contracts pass. The
Tcl tests check selectors and rejection paths, **not real FPGA timing or CDC**.
Actual netlist bindings, both variants and both timing-source cases still need
the qualified synthesis/routing toolchain and hardware regression.

The configured route to Cooper still times out at the FNAL bridge; no synthesis
job is running. DAPHNE-015 remains on server `a729c2b` and firmware `3f17f1b`;
this work did not connect to or change the board. The deployed server accepts
ABI 2.0 exactly. New source admission `7139e28` explicitly admits known ABI 2.1
while requiring exact installed-profile agreement. The collector `a8adaec`,
health integration `ef2ffe9` and independent client checks pass 24 native C++
suites and 102 Python tests; ARM cross-build also passes. See
[source verification and remaining gates](native-timestamp-verification.md).
Bundle profile staging still hardcodes minor 0 and needs provenance-backed
support before packaging ABI 2.1. Do not relabel old artifacts or bypass
identity checks. Firmware `docs/native-timestamp-snapshot.md` defines the
complete transaction and physical qualification gates.
