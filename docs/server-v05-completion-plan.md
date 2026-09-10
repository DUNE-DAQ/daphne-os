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
| Server software/schema identity / I143–I144 | Compiled source/version, explicit dirty/unavailable provenance, exact schema hashes and admitted envelope version; same metadata through independent bookkeeping and system status | Deployed eecff61: 28 host/28 actual ARM suites and 162 Python tests per binding pass. Live system/bookkeeping metadata, 32 observations during Configure, full zero-bias/all-channel and six-suite regression pass. Complete runtime native smoke, 126 packaging tests, pin and ONL handoff pass. Other service versions and semantic schema compatibility policy remain open. See software-build-verification.md |
| Database identity | Authoritative crate/slot/detector, management IP, timing address and per-Hermes MAC/IP; typed provenance/revision and unavailable handling; distinguish assigned from observed, never change network identity implicitly | Private artifact and protocol reporting deployed/tested: placement, management IPv4 and one Hermes assignment; separate live management comparison and timing-control address readback. Approved timing/management-MAC assignments, physical-link mapping and actual FPGA placement readback remain pending |
| Temperature alarms | Configurable high initial thresholds, Good/Warning/High/Critical/Missing/Invalid/Stale distinction, boundary/stale tests; observation only, no new shutdown policy | Implemented; 14 native/ARM suites and live normal-temperature/all-channel checks passed. High/fault cases synthetic, not physical trips |
| Host resources / workbook I088 and I101–I104 | Host uptime, CPU load, available memory and root filesystem free/available/read-only values; typed quality and observation times, no inferred operational-health verdict | Deployed as 3556811; 25 native/ARM suites, 109 Python tests, native probes and live RPC freshness checks pass. Full zero-bias/alignment/all-channel capture and existing-collector regression passed. Complete runtime native smoke, matching image pin and 101 packaging tests pass. Approximately 23 MiB root space available; no cleanup/resizing. See host-resource-verification.md |
| Host clock / workbook I086/I087/I090 and I098–I100 | Local clock/derived boot observations, kernel synchronization evidence, actual timesync-service source/sample/offset reporting with explicit freshness and privacy | Source ebf3988 adds wall/boot and kernel observations: 29 host/29 actual ARM suites and 174 Python tests per binding pass; standalone board probe reports May 2025 and unsynchronized. No clock correction or deployment. Actual timesyncd peer/sample/offset collector, candidate live regression and runtime handoff remain pending; see host-clock-verification.md |
| Management Ethernet / workbook I071–I084 | Read-only state/carrier/speed/duplex/MTU, traffic/error/drop and carrier-change counters; conservative health semantics | Deployed bffea24: 27 host/27 native ARM suites and 144 Python tests pass; standalone and live RPC checks validate all 14 fields. Full zero-bias/all-channel and six-suite regression pass. Complete runtime native smoke, actual staging, 124 packaging tests and ONL handoff pass; image pin updated. No network changes. See management-link-verification.md |
| SFP diagnostics | Resolve all connector/mux wiring, especially the possibly unwired port; targeted EEPROM/DDM reads and calibration/status decoding, explicit unsupported/absent/error; no TX-disable changes | Implemented/deployed; 18 native/ARM suites and 53 Python tests pass. GTH0/TMG/GTR identified; 14 diagnostic values per acquisition. Three unanswered cages and installed PCB/wiring caveat remain unresolved; factory RX warnings retained |
| FPGA health | Actual loaded/admitted FPGA identity, configuration state, clocks/reset/timing, transport/link observations and clear degraded/unknown reasons; no service-active shortcut | Sampled programming STAT and 15-check assessment deployed/tested; see server-fpga-health.md. Coherent live timestamp, Hermes delivery and external-reset epoch remain unknown; no overall health/run-permit claim |
| Firmware-dependent gaps | Review live timestamp/decoder/error export needs against both ABIs; isolated Cooper build only for an evidenced necessary firmware change | ABI 2.1 timestamp and ABI 2.2 parser-history RTL/producer gates are source-tested in both firmware repositories. Server 3f636f4, complete runtime/pin and ONL handoff pass native and live self-trigger ABI 2.0 qualification; 122 OS tooling tests pass. Actual firmware synthesis/routing, new-register readout and image/full-stream qualification remain pending |
| Qualification and handoff | Native/ARM tests, negative/stale/concurrency cases, live zero-BIAS/all-channel regression, both-ABI scope recorded, protocol clients/docs/wiki and ONL bundle | Server eecff61 native/live ABI 2.0 regression, matching client bindings and privacy-filtered ONL runtime/source handoff are complete. New-firmware/full-stream/image qualification and remaining hardware/database evidence are still pending |

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
  Read-only re-extraction after the NP02/VST location reminder matched the same
  source revision and target; it supplies no new timing/management-MAC assignment.
- [Hardware-database identity import](hardware-database-identity-import.md),
  commit `0c9d1b7`, fills timing/MAC assignments from an explicitly selected,
  hash-pinned authorized v1 export that matches the preserved network baseline.
  All 137 Python tests and synthetic native C++ artifact checks pass. The tool
  is saved on ONL; no approved DAPHNE-015 export or new assignment is installed.
  The matching CERN release schema itself has no such board attributes.
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
job was launched. The firmware work initially left server `a729c2b` and firmware
`3f17f1b` unchanged. A subsequent five-suite ARM run
used hardware-free fixtures on the board; all passed with service, executable,
boot and protected/private-file guards unchanged. That old server accepted
ABI 2.0 exactly. New source admission `7139e28` explicitly admits known ABI 2.1
while requiring exact installed-profile agreement. The collector `a8adaec`,
health integration `ef2ffe9` and independent client checks pass 24 native C++
suites and 102 Python tests; ARM cross-build also passes. See
[source verification and remaining gates](native-timestamp-verification.md).
Bundle identity capture/sealing and ABI-aware staging are now implemented and
locally tested; see [bundle provenance and remaining build gates](gateware-bundle-identity.md).
Actual Vivado bindings, routed artifacts and an image build remain unqualified.
Do not relabel old artifacts or bypass identity checks. Firmware
`docs/native-timestamp-snapshot.md` defines the complete transaction and
physical qualification gates. The separate full-stream repository now contains
the source port `8798471` and routed-check gates `d52e420`, with eight simulation
ratios/phases, four smoke suites and 20 source/Tcl-mock tests passing. Its
build-bound identity/packaging producer port is now implemented in `6052164` /
`67510d0`, with 37 source/Tcl/packaging tests, three shell tests and cross-repository
synthetic OS-overlay staging passing. The image runtime contract now pins
server `3556811` with a complete native-tested runtime archive; a full image
must still be built and qualified. Both repositories' actual
netlist/routing and live qualification remain open. Legacy full-stream ABI 2.0
remains supported without a native timestamp claim.

The server image recipe now explicitly cross-checks its staged supported minor
set against **both** overlays. The pinned server supports 2.0 and 2.1; its
capabilities do not prove firmware or image qualification. Old RC1-runtime
pairings with ABI 2.1 remain rejected by the legacy contract's regression tests.

Clean candidate `13bc725` now cross-builds with the install runtime-library
path; all 24 hardware-free ARM suites and candidate `--help` pass on DAPHNE-015,
with all 102 Python tests passing against its generated bindings. Installed
library/link-input differences were verified as debug/metadata stripping, and
the final guard checks the actual installed hashes. During that software-only
phase, the running service and protected configuration remained unchanged. See
[candidate qualification](native-timestamp-verification.md#complete-clean-candidate-arm-check).
The candidate is now deployed and passes live self-trigger ABI 2.0 bookkeeping,
full zero-bias configuration/alignment/all-channel spy capture, ADC, telemetry,
identity, SFP/regulator and FPGA-health regression. The original valid FE hash,
private identity and approved network settings are preserved; no automatic
server restarts occurred. See [live qualification](native-timestamp-verification.md#live-self-trigger-abi-20-qualification).
The [complete runtime archive and updated source/minor contract](qualified-server-runtime.md)
are now prepared, with explicit native execution provenance and no private
configuration. The handoff is saved in the ONL home directory and the complete
archive passes a native-board loader check using its packaged libraries.
Current firmware still cannot supply ABI 2.1 snapshot evidence;
full-stream live qualification and the full PetaLinux image build remain pending.

## Protocol-error firmware path — source-tested, not deployed

The workbook's I277/I281 entries belong to **Timing Interface**, not the 251-row
Server Platform tab. The deployed server correctly advertises them unavailable.
The latest Cooper probe still times out at the FNAL bridge; no job was launched.

Separate firmware branch `fix/timing-protocol-diagnostics` now contains
self-trigger `cc18e78` / `c5a8477` and full-stream `25c5798` / `3e39194`.
The parser event reaches a common-reset 32-bit saturating counter and a coherent
40-bit mailbox with bounded PS register reads. Source platform ABI is 2.2.
Both producer/packaging paths require all 170 routed diagnostic payload bits.
Actual parser and AXI simulations, source wiring, Tcl-model and synthetic
packaging tests pass. See [scope and evidence](protocol-error-firmware-verification.md).

The new firmware is **not deployed or hardware-qualified**. Server `3f636f4`
is now deployed and passes full zero-bias self-trigger ABI 2.0 regression;
ProtocolErrorCount correctly remains unavailable on that firmware. The reviewed
image contract now pins `3f636f4` and admits ABI 2.0/2.1/2.2. Server/client source
`41aea4c` / `0962e7a` / `3f636f4` implements
typed history, exact ABI 2.2 admission and independent client checks. All 26
native C++ suites, 119 Python tests with each binding set and 13 serialized-wire
cases pass; the clean AArch64 cross-build passes. All 26 native ARM software
suites, candidate help and 13 native wire cases now pass with unchanged service/
boot/protected-file guards. See [server evidence](protocol-error-server-verification.md).
OS commits `38f0547` / `d9dc40c` implement complete ABI 2.2 report validation,
staging/loader and runtime pairing guards; all 121 clean-checkout tests pass.
The reviewed image pin is now 3f636f4/minors `0 1 2`; all 122 packaging tests
and staging/recipe checks of the complete runtime pass. See
[image tooling scope](protocol-error-image-verification.md). The complete runtime
passes native packaged-library smoke; the ONL handoff, matching client bindings
and privacy-filtered source exports are saved and checksum-verified. Next are
supported synthesis/routing and image/live tests.
Optical 0x76 remains a separate placeholder; the new PS interface is not an
optical bridge. No command decoder or board change is claimed.
The ready ABI 2.1 worktrees remain untouched.
