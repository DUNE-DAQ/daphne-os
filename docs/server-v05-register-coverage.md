# v0.5 register corrections and qualification

Development branch: `fix/server-v05-register-coverage`. This is not a newly
qualified dual-gateware release. The source workbook is
`DAPHNE_Operations_Variable_Ownership_Draft_v0.5.xlsx`, SHA-256
`7c58f7f469523b7dd69ff3836f43d1a59bffdae49e2925bb328ac182122d8fd8`.

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
- No aggregate `ChannelConfig.gain` hardware implementation was found in the
  advertised branch tips. A boolean DAC gain bit exists at low level, but
  that does not establish the DAQ field's 1/2 mapping or polarity.

## Corrections

| Workbook issue / path | Implemented behavior | Remaining qualification |
| --- | --- | --- |
| I306/C022, PGA gain | Aggregate configuration writes `PGA_GAIN_CONTROL`, register 51 bit 13, and checks returned readback | Register-level tests; not an analog amplitude calibration |
| I315/C013, channel gain | Nonzero values fail explicitly before configuration writes; 0 retains unspecified/legacy DAC-bit behavior | Confirm mapping before implementing gain 1/2. Do not silently clear client requests |
| Analog configuration validation | Reject bad IDs, duplicates, DAC ranges, LPF/LNA codes and unsupported gain before reset/quiesce/writes | No valid aggregate HV/configuration campaign performed |
| Counter reads, request 320 | ABI-2 address only; reject invalid channels; volatile ordered high/low/high reads; clear partial response on retry exhaustion | Not a common-time latch across counters or protection against concurrent external resets |
| I293, bias and rail telemetry | One mutex-protected cache generation, quality, names/units, source and acquisition times | ADS7138 devices unavailable on the test board; real voltage acquisition unqualified |
| M009, GeneralInfo temperature | Explicit unavailable quality and NaN, not default zero | Bind a specifically identified sensor before publishing temperature |
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

## Protocol compatibility

Existing field numbers and request IDs are retained. Additive fields carry
measurement quality, source/acquisition metadata, hardware readback and
capabilities. The original system-status schema is retained, but empty
inventory fields are not claims that absent devices or values were measured.
Only level 0 with optional probes disabled is supported; I2C scans are rejected.

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

## Hardware checks and exclusions

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
