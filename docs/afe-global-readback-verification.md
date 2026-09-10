# AFE global status: SC ownership and hardware readback

Server implementation **0e5f48b**, client verification **78504f1**.
Server **78504f1 is deployed and live-qualified on DAPHNE-015**. Firmware
remains self-trigger **3f17f1b / ABI 2.0**. The complete runtime and native
loader pass; image pin **fb53223** and 140 packaging/audit tests pass.
The refreshed ONL home/source/client handoff is verified; see the handoff
section below and the [SC ownership wiki page](https://github.com/DUNE-DAQ/daphne-os/wiki/DAPHNE-015-AFE-global-and-SC-ownership).

## What the fields mean

**Ownership follow-up:** [server fb82e0a](sc-bias-enable-ownership.md) removes
the implicit enable write from aggregate Configure. It is deployed and live-tested
without a firmware reload; the historical read-only qualification below did not
change write policy. Its new runtime/image-pin/ONL handoff remains pending.

The v0.5 workbook assigns ordinary energization authority to **SC**;
`daphne-server` executes local operations and reports observed state.
`SystemStatusSnapshot.afe_global` is read-only. No write policy, Configure
behavior, default enable state, interlock or automatic power action changed.

Specifically, **SC003 `SC.BiasEnableRequested`** belongs to the workbook's
SC Gateway tab. **I288 `AFE Global.BiasEnable`** belongs to Server Platform
because it is device readback consumed by SC, not authority to choose the
requested state. SC003 is still a proposed SC-interface contract, not a new
wire command implemented by this read-only collector. Keep both roles distinct;
do not remove I288 or turn telemetry into an automatic bias decision.

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

The deployed server's matching client checks three ordinary RPCs without
private opt-ins or writes:

```bash
python3 daphne-server/scripts/verify_afe_global.py \
  --endpoint "$DAPHNE_ENDPOINT" --proto-dir "$PROTO_DIR" \
  --server-source "$SERVER_SOURCE" --expected-server-commit "$SERVER_COMMIT" \
  --expected-build-id 0x3f17f1b --expected-abi 0x20000 --mode self-trigger
```

## Deployed regression and complete runtime

Deployment one-shot `daphne-deploy-78504f1.service` exited successfully. Only
the server executable was replaced after the old process exited; the normal
runtime restart reloaded the same installed FPGA. The old executable remains
in RAM at `/run/daphne-candidate-78504f1/previous-server`, not in a recovery
image. No partition, library, identity, network, time or bias-policy changes.

Initial and final full zero-BIAS passes each completed **153 exchanges**:
both AFE orders, all five alignments and all 40 usable spybuffer channels.
The new AFE client passed three RPCs with fresh raw words **0x2 / 0x1**, matching
quality, identity brackets, source/schema and unchanged configuration evidence.

Bookkeeping passed 46 metadata-checked observations, 31 during Configure;
maximum round trip **322.311 ms**. Rejections preserved applied state, a direct
rewrite of the existing channel-0 offset invalidated it, and full Configure
restored the reference hash. The six inherited regressions passed: v0.5 (17
exchanges), ADC (93, including 80 CRC-checked samples), SFP (5), regulator (7),
FPGA health (4) and private identity/link reporting (5). Kernel/OS, clock and
build clients passed three exchanges each; timesync privacy passed five.

Final FE hash:
`c858989d7e847a98146c39ad50ec1f053c67acc78ea3c268d6a880341ad8d503`.
Policy remains BIAS/BIASCTRL=0, offset=2200/x1, trim=0, VGAIN=1700,
generator=1 and current selectors=0/0. These are command/register observations,
not physical zero-voltage or calibration evidence. Health remains **11 PASS /
1 external-timing FAIL / 3 UNKNOWN**. No automatic restart or error-or-higher
journal entry was observed for the new invocation; private messages were not
exported. Protected-file, boot, service and final policy guards pass.

Live proof `live-abi20.gFlLwtK4/qualification.json` SHA-256:
`ca90374e49749db0558f4b0e6dd68cb9ea9177adee908fdca89a9549bbc085f9`.
Complete runtime `runtime-78504f1/daphne-server-runtime-minimal.tgz` SHA-256:
`38e691b37ee80b5a5dd5a1d97157347eaf270d05269c01181d2712b81b3ad61a`.
Its 20 regular files and four aliases include the exact server and unchanged
qualified Hermes/protobuf/utf8/ZeroMQ dependencies. The archive's payload checks
and native loader/help pass with all three private libraries resolved inside
the extracted bundle; OS-provided libsystemd is not bundled or replaced.

Actual runtime staging and all nine synthetic overlay-minor combinations pass.
The source `daphne-server-version.inc` remains fail-closed until a real project
stages the matching archive. This is not BitBake or a complete image build.

## ONL home handoff

`$HOME/daphne015-server-runtime-78504f1` on `np04-onl-004` contains 32 payload
files plus `SHA256SUMS`, in owner-only storage. Runtime and both source exports,
matching Python bindings, redaction manifests and native/live/client proofs
are included. Server export base is 78504f1; OS integration base is 6457a68.
Production/build sources match Git; known private literals in legacy examples
are replaced and one serialized seed request is omitted per export. These
are modified exports, not exact Git snapshots or a general secret guarantee.

ONL's existing Python 3.9.16/protobuf 6.33.5/pyzmq 25.1.2 ran the four exported
AFE, kernel/OS, clock and build clients: three read-only RPCs each. One extra
bookkeeping read confirmed the qualified process/boot and unchanged valid FE
hash. No packages were installed. All handoff and internal runtime payload
hashes pass; the previous 75972de handoff remains unchanged and was reverified.
Manifest SHA-256:
`02d71b5c65344ee03d733d68537849b283f273172ced18930b929d0b6465e30a`.

Remaining: real busy/reset transitions;
full-stream and newer routed firmware qualification. Do not toggle SC-owned
energization or reset merely to make a diagnostic pass.
