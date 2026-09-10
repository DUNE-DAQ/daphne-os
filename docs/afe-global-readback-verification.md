# AFE global status: SC ownership and hardware readback

Server implementation **0e5f48b**, client verification **78504f1**.
The candidate is compiled and its collector is tested on DAPHNE-015, but it
has **not replaced the installed 75972de server**. Firmware remains
self-trigger **3f17f1b / ABI 2.0**.

## What the fields mean

The v0.5 workbook assigns ordinary energization authority to **SC**;
`daphne-server` executes local operations and reports observed state.
`SystemStatusSnapshot.afe_global` is read-only. No write policy, Configure
behavior, default enable state, interlock or automatic power action changed.

| Workbook row | New field | Exact FPGA readback |
| --- | --- | --- |
| I283 PowerState | `power_state_bit` | `0x80000000`, bit 1; raw legacy POWERSTATE value |
| I284 ResetAsserted | `reset_asserted` | Same word, bit 0 |
| I285 BusyAfe0 | `busy_afe0` | Same word, bit 2 |
| I286 BusyAfe12 | `busy_afe12` | Same word, bit 3 |
| I287 BusyAfe34 | `busy_afe34` | Same word, bit 4 |
| I288 BiasEnable | `bias_enabled` | `0x9400000C`, bit 0 |

**BiasEnable is not BIASCTRL.** BIASCTRL is a 0–4095 DAC setpoint; the legacy
`readVbiasControl()` response returns its software cache. BiasEnable is a
different FPGA register. Neither establishes actual bias voltage. POWERSTATE
is deliberately reported as a raw bit, not a measured powered/unpowered state;
the RTL drives `afe_pdn = !POWERSTATE`. Busy combines the AFE, trim and offset
SPI engines for each named firmware group, not the server executor or historical
work. Group numbers follow the FPGA register names, not an inferred remapping
through channel/API board-to-PL indices.

Mapping evidence: deployed `3f17f1b`,
`ip_repo/daphne_ip/rtl/afe/spim_afe.vhd` and `rtl/config/stuff.vhd`, with bases
in `boards/k26c/bd_shell.tcl`. Matching full-stream source was checked at
`3e39194`, under `ip_repo/daphne3_ip/rtl/` and
`xilinx/daphne_fullstream_bd_gen.tcl`. Source agreement is not full-stream
hardware qualification.

## Safeguards and tests

- The AFE collector adds only two aligned 32-bit read-only mappings; no SPI,
  I2C or MMIO writes. The surrounding status path also reads its usual FPGA
  programming, identity and timing observations.
- Existing fresh programming/startup checks and admitted ABI/mode/build checks
  precede mapping. Matching complete identities bracket collection.
- Raw words, optional decoded flags, monotonic start/end times and quality are
  explicit. Zero/false retains presence; failures remove decoded values.
- Reserved-bit violations and read/clock errors fail. Acquisition exceeding
  100 ms is stale; the client also rejects observations older than 5 seconds.
  These checks do not interrupt a hung bus transaction.
- The two registers are sequential samples, not a common latch. Identity
  bracketing cannot detect every identical-image reload. No health/run permit,
  physical power/bias, busy-history or verified UTC claim is made.

Clean source **78504f11dec0ebc5971bd0bbc9ba8b3f76ca89cd**: 33 host and
33 actual AArch64 unit suites pass; all 203 Python tests pass independently
with host and ARM-generated bindings. The new decoder tests cover all
384 ABI/variant/bit combinations and injected failures; the client has six
additional wire/quality/bracketing tests. These are software tests, not
physical stimulation of every register state.

Two standalone native probes on DAPHNE-015 both observed global word **0x2**
and bias-enable word **0x1**: POWERSTATE=1, reset clear, all busy flags clear,
BiasEnable=1. The enable bit was already set before the probe. Installed
executables, protected configuration, boot, service PIDs/invocations and
generator/ADC-selector guards matched before and after. No service restarted.
Only test binaries were staged in private root-owned RAM storage.

Evidence directory: `afe-global.ouGmbzdZ` in the qualification deliverables.
Native proof SHA-256:
`31da762bdb2dd9a8566328550fe66e4698ee697bba618d911c68c13f506dfede`.
Probe SHA-256:
`617dc876e534faf83a4cf8fbbbfff7730d8786a9fe09be57fa8e14defa89743b`.

## Commands

Build using the existing [server/client build guide](https://github.com/DUNE-DAQ/daphne-os/wiki/Building-daphne-server-and-clients),
then run the hardware-free suites:

```bash
ctest --test-dir "$BUILD_HOST" -L unit --output-on-failure
PYTHONPATH="$BUILD_HOST/srcs/protobuf" python3 -m unittest discover \
  -s daphne-server/tests -p test_afe_global.py -v
```

The standalone probe uses the server's admission path without constructing
the hardware-control application. Run only on an identified, operating board
with exact expected firmware values and the compiled runtime dependencies:

```bash
sudo env LD_LIBRARY_PATH=/usr/lib/daphne-server \
  "$PROBE_STAGE/afe_global_probe" self-trigger 0x20000 0x3f17f1b
```

After a candidate server is separately deployed and qualified, its matching
client can check three ordinary RPCs without private opt-ins or writes:

```bash
python3 daphne-server/scripts/verify_afe_global.py \
  --endpoint "$DAPHNE_ENDPOINT" --proto-dir "$PROTO_DIR" \
  --server-source "$SERVER_SOURCE" --expected-server-commit "$SERVER_COMMIT" \
  --expected-build-id 0x3f17f1b --expected-abi 0x20000 --mode self-trigger
```

Remaining: candidate server RPC/full regression and runtime handoff; real
busy/reset transitions; full-stream and newer routed firmware qualification.
Do not toggle SC-owned energization or reset merely to make a diagnostic pass.
