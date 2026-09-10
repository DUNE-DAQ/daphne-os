# v0.5 register corrections and qualification

Development branch: `fix/server-v05-register-coverage`. This is not a newly
qualified dual-gateware release. The source workbook is
`DAPHNE_Operations_Variable_Ownership_Draft_v0.5.xlsx`, SHA-256
`7c58f7f469523b7dd69ff3836f43d1a59bffdae49e2925bb328ac182122d8fd8`.

Current DAPHNE-015 server: `1dc613e`, including
[opt-in SFP inventory and diagnostics](sfp-diagnostics-verification.md),
[CRC-checked 40-channel ADS1261 raw readout](ads1261-readout-verification.md),
[responsive bookkeeping](server-bookkeeping-verification.md),
[observation-only temperature alarms](temperature-alarm-verification.md),
[schematic-backed voltage/carrier telemetry and services](carrier-telemetry-and-services-verification.md),
[named AMS temperatures and the voltage scan-count fix](telemetry-ams-verification.md)
and the [aggregate zero-BIAS correction](aggregate-bias-verification.md). Prior
offset-gain measurements below retain their original server provenance.

## Scope and provenance

The Server Platform tab contains 251 entries, including proposed interfaces
and verification-pending inventory. This patch does not claim all 251 are
implemented or hardware-qualified.

All 25 advertised branches of `ecristal/daphneZMQ` were checked against the
preserved history. Relevant prior work:

- `marroyav/ps-system-status-protobuf` at `6c8b044`: system-status schema;
  preserve its message names, fields and request/response IDs 324/325.
- `feature/slow-control-emulator` at `c262397`: monitor quality/timestamps,
  register telemetry and high/low/high counter reads. Adapt selectively:
  its exhausted-retry counter fallback, live-timestamp interpretation and
  old identity offsets are not valid for this deployment.
- `server` at `4be8e3a`: `writeChannelOffset()` already forwards the boolean
  `offsetGain` to `Dac::setDacOffset()`. Commit `bc5b1e9` encodes that flag in
  AD5327 bit 13. The aggregate path still hardcoded `false`, ignoring
  `ChannelConfig.gain`. The operator confirmed this field means offset DAC
  gain; the AD5327 datasheet establishes the 1/2 mapping below.

## Corrections

| Workbook issue / path | Implemented behavior | Remaining qualification |
| --- | --- | --- |
| I306/C022, PGA gain | Aggregate configuration writes `PGA_GAIN_CONTROL`, register 51 bit 13, and checks returned readback | Register-level tests; not an analog amplitude calibration |
| I315/C013, offset DAC gain | `ChannelConfig.gain` 1/2 selects AD5327 bit 13 = 0/1; 0 retains legacy x1. Explicit x1/x2 offset limits are 2700/1500 | Deployed; full Configure exercised on all 40 channels. Local sweep: x2/x1 slope ratios 1.934–2.062; 36/40 within 164 counts at all five points. Analog calibration unqualified |
| Aggregate per-AFE BIAS | Every present AFE entry applies its BIAS code, including zero; order resolved by AFE ID | Two direct zero-only hardware configurations pass, without low-level workaround. Nonzero/mixed values tested with mocks; analog voltage unqualified |
| Analog configuration validation | Reject bad IDs, duplicates, DAC ranges, LPF/LNA codes and invalid gain before reset/quiesce/writes | Full zero-bias configuration tested. Nonzero-bias operation unqualified |
| Counter reads, request 320 | ABI-2 address only; reject invalid channels; volatile ordered high/low/high reads; clear partial response on retry exhaustion | Not a common-time latch across counters or protection against concurrent external resets |
| I293, bias and rail telemetry | One complete scan per ADC; coherent cache, quality, names/units and times; schematic-backed PS I2C1 binding | Real acquisition/freshness tested; five supply rails near nominal. Bias residuals and external calibration remain unqualified |
| I316/I317, raw/calibrated current | Identified kernel-owned ADS1261, explicit physical channel 0..39, differential mux mapping/restoration, CRC/status checks and signed raw/nominal volts; calibrated amperes explicitly unavailable | All 40 raw paths read twice on zero-BIAS DAPHNE-015. No mezzanines; current calibration, analog mapping and full-stream live qualification remain open |
| I227–I248, SFP inventory/diagnostics | Six physical routes, checked EEPROM/DOM, optional identity/status/measurements, module calibration/thresholds/flags, OUI/rate/wavelength, host acquisition times and mux restoration | GTH0/TMG/GTR identified; GTH1/GTH2/GTH3 presence unknown. I231 provides raw rate bits, not proven wiring. I238 is explicitly MBd signaling rate, not payload Mbps. Hermes LinkId association and suspected wiring fault remain unresolved |
| I200–I202, named temperatures | Three AMS die sensors plus identified carrier U9 MCP9808; Celsius, quality and host observation times | Four readings deployed and tested. Not all possible sensors or ADC conversion timestamps |
| Temperature-alarm follow-up | Active startup thresholds and Good/Warning/High/Critical/Missing/Invalid/Stale evaluation on each temperature | Deployed with provisional 85/95/105 C thresholds; boundary/fault tests synthetic. Monitoring only, not protection or safe ratings |
| M009, GeneralInfo temperature | Bound to identified carrier U9; additive source/time metadata; failures NaN with quality | Real carrier readout tested; not calibrated ambient temperature |
| Service observations / proposed SV017 instance | Eight allow-listed systemd unit observations, available PID/restart/exit data; same-PID invocation ID and uptime | Deployed; service state is not hardware readiness, heartbeat or authentication. Configured app name is not live xmutil inventory |
| SV016–SV021, server bookkeeping | Responsive request 326, heartbeat/process/boot identity, in-progress execution, canonical successful configuration hash/validity and correlated last result | Deployed and observed during full Configure. Known local invalidations only; no claim to detect all external resets or prove analog readback |
| I264, timing usable | Endpoint source + both MMCM locks + FSM 8 + timestamp-valid + no reset requests | Sampled observation only; not a continuous lock guarantee |
| I273/TI001, live timestamp | Explicit unsupported capability; never interpret spy-capture words as a live timestamp | Requires a firmware-supported coherent export |
| I058/I059/I061, legacy identity offsets | Explicit unsupported crate/slot/detector readback; expose common ABI identity instead | Do not read self-trigger controls under old identity names |
| I277/I281, decoder/error counter | Explicit unsupported capabilities with reasons | Firmware does not supply these as meaningful measurements |
| Low-level AFE writes | Reject narrowing and readback mismatch; return the board AFE index | Readback does not prove analog signal-chain behavior |
| Low-level AFE register read | Fresh SPI read with explicit hardware-readback flag and monotonic acquisition time, not the command cache | SPI reads themselves require controller writes; they are opt-in in the read-only QA client |
| Python counter client | Timeout/failure gives a nonzero exit and no fabricated zero-counter table | Unit-tested against a silent local TCP listener |

The PGA mapping follows the existing register dictionary and the
[TI AFE5808A datasheet](https://www.ti.com/lit/ds/symlink/afe5808a.pdf):
0 = 24 dB, 1 = 30 dB. Timing bits were checked against the deployed self-trigger
firmware's `ep_axi.vhd` at `3f17f1b`, including clock-control bit 0 (MMCM0 reset).

### Offset DAC gain follow-up (`b631271`)

This is the offset/pedestal DAC multiplier, **not PGA gain**. The
[AD5327 datasheet, p. 17](https://www.analog.com/media/en/technical-documentation/data-sheets/ad5307_5317_5327.pdf)
specifies per-output GAIN bit 13: clear for x1, set for x2. The deployed
firmware identifies AD5327 devices in `spim_afe.vhd`; `spim_dac2.vhd` sends
the packed words unchanged. No firmware modification is needed for this field.

The aggregate handler now uses the existing low-level DAC path. Low-level
`offsetGain` stays a boolean hardware bit; high-level `ChannelConfig.gain`
stays a multiplier. Do not cast 1/2 directly to bool (both would become true).
An omitted/zero high-level field retains x1 and its legacy 0..4095 code range.
Explicit gains use the existing `daphnemodules` client limits: x1 <=2700,
x2 <=1500. Invalid requests fail in preflight; trim, PGA, LNA and HV gain
handling are unchanged. Protobuf field numbers and types are unchanged.

Verification: all six host C++ tests pass, including 240 channel/gain/boundary
protobuf round trips and 32,768 x1/x2 encoder comparisons. The complete ARM64
server builds with runtime path `/usr/lib/daphne-server`; the Python counter
failure test passes. Candidate SHA-256:
`ad15adf71cb02e62a83911f946f3ae2f95d98ae41ebd14f49733c3c4d5cee1c5`.
This aggregate-handler follow-up is now installed. The
[full-configuration verification](offset-gain-full-configuration-verification.md)
exercised Configure on all 40 channels with BIAS/BIASCTRL=0. All five AFEs align
after full initialization; no alignment patch was needed. The final offset-only
A/B/A comparison passes the 164-count criterion on 37/40 channels, with a
maximum difference of 236 counts and repeat drift no larger than 5.5 counts.
The earlier 32-channel result lacked the full FE setup and is superseded.
The previous deployment and its qualification below remain separate.

The subsequent [unsaturated local sweep](offset-gain-sweep-verification.md)
(`877caa7`) confirms approximately doubled slopes on all 40 channels, without
changing the server or FE profile. It retains the baseline criterion: 36/40
pass across all five points; channels 15/19/36/38 have remaining analog
differences. No calibration correction or further gain/alignment patch was
applied. This distinguishes working gain selection from calibrated equivalence.

Use the updated `verify_server_v05.py`: its invalid-gain probe now uses **3**.
Do not run the previous script against the corrected server: its gain=1 probe
is now valid, and a valid aggregate Configure request can enable HV.

The DAC's final SDO is not connected, so a cached code or FPGA command register
cannot prove analog gain. The subsequent waveform comparison provides bounded
analog evidence; full-range DAC calibration and the residual A/B differences
remain unqualified. See that report for the final offset and zero-bias settings.

## Protocol compatibility

`53b6566` intentionally changes zero-BIAS semantics without changing the wire
schema: a present AFE entry with zero/default `v_bias` now sends code zero,
instead of retaining the previous code. No BIAS command is planned for an
absent AFE entry. BIASCTRL and generator-enable behavior are unchanged.

Existing field numbers and request IDs are retained. Additive fields carry
measurement quality, source/acquisition metadata, hardware readback and
capabilities. The original system-status schema is retained, but empty
inventory fields are not claims that absent devices or values were measured.
Only level 0 is supported. `include_ps_values` is accepted for the bounded host
metadata already included at level 0; I2C scans and xmutil probes are rejected.
`include_sfp_diagnostics=true` now enables the bounded, restoring SFP collector;
ordinary status requests do not touch it. Optional fields and quality distinguish
unknown from false/zero. A successful status response does not mean the links
are healthy; confirmed factory warning flags remain visible.

Current-monitor request 244 now requires explicit `physical_channel` field 3,
including presence for channel zero. Legacy ambiguous ADC-input-only requests
are rejected; regenerate clients. See the raw-readout report for response
quality, signed-code and unavailable-current handling.

Legacy GeneralInfo voltage doubles are NaN when invalid, stale or unavailable.
Its `power_*` fields keep their old voltage mappings; named voltages state the
physical rail explicitly. The board wall clock is unverified, so acquisition
wall-clock fields must not be treated as timing-endpoint timestamps or verified
UTC. Freshness uses the monotonic clock.

No credentials, SSH keys, MAC/IP configuration or arbitrary diagnostic probes
were added to the protocol. Authentication changes require a separately agreed
contract; a ZeroMQ routing identity is not authentication.

## Reproduce software checks

From the OS repository root, with native libi2c, protobuf headers and protoc:

```bash
cmake -S daphne-server -B build/server-host-tests \
  -DDAPHNE_BUILD_SERVER=OFF -DDAPHNE_BUILD_PROTOCOL_TESTS=ON \
  -DBUILD_TESTING=ON -DDAPHNE_ENABLE_HARDWARE_TESTS=OFF
cmake --build build/server-host-tests --parallel 6
ctest --test-dir build/server-host-tests --output-on-failure -L unit
python3 -m unittest discover -s tests/petalinux
```

Six C++ test executables cover telemetry, configuration/AFE protocol, counter
reads, timing, gateware mode and HD mezzanine driver logic. Timing tests include
2,048 combinations. The PetaLinux suite has 79 tests. Hardware tests are not
enabled by these commands.

See the wiki's [server/client build guide](https://github.com/DUNE-DAQ/daphne-os/wiki/Building-daphne-server-and-clients)
for the ARM64 cross-build and Python environment. Build and install are separate:
check the ELF architecture, dynamic libraries, final runtime path and SHA-256
before transferring a binary. The current service dependencies can stop the
whole runtime and reload the same FPGA application during an update. Verify
the server has actually stopped, then restart `daphne-runtime.target`.

## Previous hardware checks and exclusions (`c267a6c`)

On DAPHNE-015, the six ARM64 test executables run successfully without hardware
access. The protocol checks exercise the self-trigger ABI identity, four timing
registers, all 40 counter channels, unavailable telemetry, unsupported optional
probes and deliberately invalid configuration requests.

The first gain-only test exposed that the existing AFE read handler served a
software cache: an apparently successful all-zero read was not hardware proof.
That failure motivated the live SPI readback correction. Do not cite the earlier
cached reads as hardware qualification.

After that correction, **44 protocol exchanges passed** on server source
`c267a6c`: both PGA gain codes on each of five AFEs, fresh register-51 readback,
unchanged non-gain bits, and restoration verified through fresh reads on every
AFE. Register 51 was `0x0000` at the start and end of this final test on all
five AFEs. This proves register handling, not analog gain calibration.

The final server binary SHA-256 is
`dfe43a0b1f78c667f2e699fd264de5cbfd994ffc4c89aa8ef43d4bdaa8b788e9`.
The runtime target is active with no automatic server restarts. Timing raw
words were `0, 3, 0, 6`: both locks set, local clock selected, FSM 6 and no
valid timestamp. `ready=false` is therefore expected, not a test failure.

No valid aggregate Configure request, HV/DAC write, clock reset, timing setup,
SFP/HD-mezzanine scan, DAQ acquisition, cold boot or new full-stream hardware
qualification is included. The deployed self-trigger firmware remains
`0x03F17F1B`; no replacement OS or firmware image was flashed. Network files,
SSH host public key and firmware/board environment file checksums are preserved.

The board has named Xilinx AMS IIO temperatures (`Temp_LPD`, `Temp_FPD`,
`Temp_PL`), but no chosen GeneralInfo temperature binding yet. Missing I2C/SPI
drivers must be traced to the device tree and physical bus topology; do not
guess new device numbers or probe all addresses on powered hardware.
