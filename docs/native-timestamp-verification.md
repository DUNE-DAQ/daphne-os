# Native timestamp health: source ready, not deployed

This addresses workbook **I273/TI001**. Firmware branch
`fix/health-timestamp-abi21` provides the native-clock snapshot export. Server
commits `a8adaec` and `ef2ffe9` collect it and assess progress. OS admission
`7139e28` accepts known platform ABIs 2.0 and 2.1 but still requires the exact
installed profile to match the loaded FPGA. Unknown minors are rejected.

**DAPHNE-015 is unchanged:** deployed server `a729c2b`, firmware `3f17f1b`,
ABI 2.0. These new sources have not been installed or hardware-qualified.

## What changes

`ReadSystemStatus` automatically collects two diagnostic samples on admitted
ABI **2.1**. It maps no snapshot window on ABI **2.0**. Reading REQUEST triggers
only a diagnostic capture; the collector performs no MMIO writes, clock/reset
changes, spy captures or network configuration changes.

The additive `EndpointStatus.live_timestamp` field includes optional raw words,
attempt sequences, source, host monotonic times, quality and a progress result.
Each sample uses sequence-before / request / sequence-first / status / low /
high / sequence-after. Conflicts are discarded and retried, at most three times
per sample. Feature identity and the firmware timeout budget must agree before
and after the pair. Complete FPGA identity, programming state and timing
controls are also checked around collection.

| Evidence | `live_timestamp_progress` |
| --- | --- |
| Two qualified, same-source samples with forward modulo-64-bit difference | PASS |
| Qualified pair is stationary or has a backward/discontinuous difference | FAIL |
| Unsupported, timeout, busy/quarantined, invalid, stale or unbracketed evidence | UNKNOWN |

Measured zero is valid only when `timestamp_ticks` is present. Failed pairs
retain diagnostic raw words but clear usable ticks/delta/progress. Legacy
timestamp fields 7/8 remain unpopulated. Source, raw decoding, attempt order,
presence, host intervals and progress arithmetic are checked independently by
the Python client; it does not simply trust the server's PASS label.

The 100 ms host budget is checked after reads return: **it cannot interrupt a
stuck MMIO transaction**. Firmware supplies its own bounded AXI response while
the AXI clock runs. Matching image IDs cannot detect a reload of the same image.

Local-counter progress is not external timing readiness. Neither source proves
clock frequency, epoch continuity or waveform/acquisition timestamp alignment.
Hermes delivery and external-reset epoch remain UNKNOWN; no overall healthy
board or run-permit claim is possible from this addition alone.

## Verification completed

- All **24 native C++ suites** and **102 Python tests** pass.
- ARM64 server and test executables cross-build successfully. These new ARM
  executables have **not** yet been run on the board.
- Tests cover both modes and admitted ABIs, zero/rollover/stalled/backward
  counters, all low-byte status patterns, reserved flags, partial reads,
  conflicts/retry limits, source/context changes, stale observations and
  identity/programming failures. ABI 2.0 tests assert zero extension reads.
- Firmware's earlier GHDL and Tcl mock tests pass; those are **not routed
  timing/CDC evidence**. See the firmware's `docs/native-timestamp-snapshot.md`.

Logs: firmware qualification workspace `firmware-health.W1CUQ3E7`, files
`native-timestamp-{native,arm,python}-qualification.txt`. No board contact,
runtime restart, remote write or private identity change was needed for this
server/client work.

## Client command — only after qualifying/deploying the matching firmware

Use matching generated protobufs and the existing approved SSH forward. Set
`qualified_build_id` to the build ID from the qualified release manifest:

```bash
python daphne-server/scripts/verify_fpga_health.py \
  --endpoint tcp://127.0.0.1:44015 \
  --proto-dir /path/to/arm-build/srcs/protobuf \
  --expected-build-id "$qualified_build_id" \
  --expected-abi 0x20001 --mode self-trigger \
  --require-bench-profile
```

On the current deployed image, retain ABI `0x20000` (the client's default) and
its actual build ID. The ABI 2.1 bench check requires native local progress,
external timing FAIL, and Hermes/reset-epoch UNKNOWN. Exit zero verifies the
report, **not full FPGA health**. Output contains no private network values.

## Before deployment

1. Qualify the new [bundle identity and staging path](gateware-bundle-identity.md)
   with actual build outputs. Local positive/negative tests pass; do not
   relabel old profiles or bypass admission.
2. Run qualified Cooper synthesis/routing, review mandatory CDC/path reports,
   and qualify both firmware variants. No synthesis job is running yet.
3. Run ARM executables and guarded live ABI 2.0/2.1 regression. Preserve CERN
   MAC/IP, private identity and zero BIAS/BIASCTRL; verify the complete FE
   configuration, alignment and all 40 spy waveforms separately.
4. Publish the qualified client/source/bundle and update the wiki with actual
   deployed versions and hardware evidence, not these source-only results.
