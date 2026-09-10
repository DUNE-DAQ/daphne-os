# Parser-error history: server deployed, new firmware still pending

2026-09-10. Small commits: `41aea4c` (reader/protobuf), `0962e7a`
(runtime admission/bracketing), `3f636f4` (independent client/wire tests).
The [firmware implementation](protocol-error-firmware-verification.md) still
needs supported synthesis, routed CDC checks and live qualification.

## What the operator gets

`ReadSystemStatus.endpoint.protocol_errors` reports a **history**, not a
current-health verdict. It counts RX-parser error episodes, not physical bit
errors, all protocol errors or network errors. Multiple reasons can describe
one episode. Zero is a valid measurement only when its optional field is present.

| Admitted platform ABI | Native timestamp | Parser history |
| --- | --- | --- |
| 2.0 | Unavailable; no extension reads | Unavailable; no diagnostic reads |
| 2.1 | Existing coherent snapshot | Unavailable; no diagnostic reads |
| 2.2 | Same timestamp contract | New coherent PS snapshot |
| Unknown ABI | Admission rejected | No speculative support |

The 32-bit history saturates; separate flags report saturation, lost further
episodes and receiver reset at capture. Five accumulated reasons cover async
checksum/length, sync length/comma and unavailable control buffer. History
survives parser recovery and clears on common platform reset. That reset epoch
is **not observed**: neither zero nor a nonzero count establishes since-boot
history or current health. The existing 15-check health assessment is unchanged.
Optical register 0x76 and the unimplemented command decoder remain separate.

## Collection and failure handling

After exact image admission, the reader validates feature `0x50450100`, then
reads sequence/request/sequence/status/count/detail/sequence. It requires one
modulo-32-bit sequence increment, matching status and complete raw words.
Only conflicting transactions are retried, at most three times. Timeout/busy
returns unavailable; malformed words, changing metadata or failed reads return
error. Raw evidence is retained, but failed observations have no usable count.
The 100 ms host budget is checked after calls return; it cannot interrupt stuck
MMIO. Firmware bounds its response only while the AXI clock/reset allow progress.

Complete firmware identity and programming checks surround collection. The
existing timing-context checks remain conservative; timestamp unavailability
alone does not invalidate good parser history. The server's single hardware
worker serializes requests; outside raw readers are not locked out. Matching
IDs cannot detect an identical-image reload. No MMIO writes, history clears,
network/bias changes or protection actions are introduced.

The Python client independently checks raw/decoded agreement, optional-field
presence, limits, order, scope, lifetime, freshness and outer context. Only
qualified counts appear in its redacted report; the protobuf retains raw failures.

## Verified scope

Clean detached source: `3f636f4acf3f795e96d1e20e89936c6a861ac58a`;
server tree: `afdcc5997d31d32232c23ba9bcd5a6d1dcf62353`.

- **26 native C++ suites pass**, including both firmware modes, ABI admission,
  no old-register probes, all low-byte status combinations, zero/saturation,
  sequence wrap/conflicts, partial failures, timing and invalidated observations.
- **119 Python tests pass** with each generated binding set: host Protobuf
  3.21.12 and ARM-build Protobuf 30.1. No untracked waveform test was included.
- **13 C++-to-Python wire cases pass** with each binding set. These use actual
  collector serialization with scripted MMIO and synthetic outer context.
- Server and all unit executables **cross-build for AArch64** with GCC 12.2.
  All **26 hardware-free ARM suites**, candidate `--help` and the same **13
  serialized wire cases now pass on DAPHNE-015**. This is native software
  execution with scripted MMIO, not live reads of the new firmware registers.

ARM server SHA-256:
`22989ec267179f7d53e1547ab794380a4d0d0b6b96d90cd09bacad37f62754fa`.
RUNPATH is `/usr/lib/daphne-server`; generated-message deprecation warnings
remain. Evidence directory: `firmware-health.W1CUQ3E7/protocol-server.Mh4iBcOB`,
including `qualification.json`, clean native logs, ARM build log and wire reports.
Changed Markdown passes its checks. Repository-wide documentation lint still
reports five pre-existing developer-path findings in unrelated files.

### Native ARM execution

Evidence: `protocol-server.Mh4iBcOB/arm-execution.x6LFuE0t`. The owner-only test
archive contains the exact 26 CTest unit executables, candidate binary, runner,
inventory/source records and checksums. It was staged in RAM-backed `/tmp` and
run as unprivileged `petalinux`, using the hash-checked installed libraries.
Archive SHA-256:
`45f2be2aac311faa62b547e387c52efb64fe7904de5b54603be21bca6b919963`.
`RESULTS.json` records completed tests and equal before/after guards: running
server/Hermes executable hashes, service instances/PIDs/restart counts, boot,
private identity and all eight protected configuration-file hashes.
The runner performs post-checks even on test failure. It never starts the server.

Native scripted wire bytes are retained in `protocol-wire.txt`; their SHA-256
matches both the board runner and the independent local Python verification:
`e09dcb969c7b7d6c204a506adf74d9171677bfb8253a67769424e5d891f44903`.
Only the outer observation context is synthetic in that wire test. Temporary
test files were retained; no installed application or board configuration changed.

## Reproduce the focused software checks

From the OS repository root, with the [build dependencies](../daphne-server/README.md)
and a Python environment compatible with the generated Protobuf:

```bash
daphne_build=build/protocol-native
cmake -S daphne-server -B "$daphne_build" \
  -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=ON \
  -DDAPHNE_BUILD_SERVER=OFF -DDAPHNE_BUILD_PROTOCOL_TESTS=ON \
  -DDAPHNE_BUILD_PY_PROTO=ON -DDAPHNE_ENABLE_HARDWARE_TESTS=OFF
cmake --build "$daphne_build" --parallel 4
ctest --test-dir "$daphne_build" --output-on-failure
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH="$daphne_build/srcs/protobuf:daphne-server/tests" \
  python3 -m unittest test_protocol_errors test_native_timestamp test_fpga_health
PYTHONDONTWRITEBYTECODE=1 python3 daphne-server/tests/check_protocol_error_wire.py \
  --probe "$daphne_build/protocol_error_tests" \
  --proto-dir "$daphne_build/srcs/protobuf"
```

Future live verification uses `scripts/verify_fpga_health.py` under
`daphne-server`, with explicit `--expected-abi 0x20002`, the **actual** firmware
build ID, selected mode, matching generated bindings and an approved tunnel.
Its default remains exact ABI 2.0. `verify_server_v05.py` remains the separate
ABI 2.0 regression tool; it has not been silently loosened for new firmware.

## Live self-trigger ABI 2.0 regression

Server `3f636f4` is now deployed on DAPHNE-015 with the exact binary hash above.
The normal runtime restart reloaded the same `3f17f1b` firmware; no flash,
partition, network or private-identity changes were made. The original full
zero-bias FE profile was restored before alignment and capture.

Evidence: `protocol-server.Mh4iBcOB/live-abi20.416CxtFF/qualification.json`,
SHA-256 `d3ec69409bb0a2087cd0ff0cce8f76b77e719e7048064fd60eae146408336807`.

- 153 aggregate exchanges: both five-AFE orders, alignment, fresh registers and
  all 40 spybuffer channels pass. Bookkeeping heartbeat, rejection before hardware,
  direct-write invalidation and canonical-hash restoration also pass.
- Six regression suites pass: v0.5 telemetry (17 exchanges), ADC (93, including
  80 CRC-checked samples), SFP (5), regulators (7), FPGA health (4), identity (5).
- The new parser-history field explicitly reports unavailable on ABI 2.0;
  its capability remains false. Neither native timestamp nor parser-history
  firmware measurements are claimed. Health remains 11 PASS / 1 external-timing
  FAIL / 3 UNKNOWN, not an overall healthy-board declaration.
- Same boot, protected/private-file hashes, reference FE hash and generator/
  current-selector policy; BIASCTRL and all five BIAS caches zero. No automatic
  server restarts occurred. Cache checks are not analog voltage measurements.

The complete runtime archive also passes a native-board loader/CLI smoke using
its packaged private libraries, with service/configuration guards unchanged.
Archive SHA-256: `1af9600acbfb8e557bedde23bde93e13270ccf7b5439d8a4b9f6803e335d0497`.
Known private MAC/IPv4 literal checks pass; this is not a general secret audit.

## Still required

The [ONL runtime handoff](qualified-server-runtime.md) is saved and checksum-
verified, with matching client bindings and privacy-filtered source exports.
[ABI 2.2 OS staging/guards](protocol-error-image-verification.md)
now pass 122 tests with the reviewed `3f636f4` pin, minors `0 1 2`.
The actual complete archive stages and passes the recipe decision for all nine
synthetic overlay-minor pairs. This is not a PetaLinux image build.
Then qualify supported-tool firmware builds, routed paths, both modes/sources
and live zero-bias readout/regression. The current Cooper probe still times out
at the FNAL bridge; **no synthesis job was launched**. The application deployment
above does not qualify new firmware or close the entire workbook.
