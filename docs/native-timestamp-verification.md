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
- ARM64 server and test executables cross-build successfully. All **24 ARM
  software suites** now pass on DAPHNE-015, including the native timestamp,
  FPGA health, bookkeeping, identity, ADC, SFP and regulator fixtures. The clean
  candidate's `--help` also passes. These use scripted MMIO/fake sysfs/temporary
  files, not FPGA or analog accesses. This does **not** qualify a running new
  server or ABI 2.1 firmware on hardware.
- Tests cover both modes and admitted ABIs, zero/rollover/stalled/backward
  counters, all low-byte status patterns, reserved flags, partial reads,
  conflicts/retry limits, source/context changes, stale observations and
  identity/programming failures. ABI 2.0 tests assert zero extension reads.
- Firmware's earlier GHDL and Tcl mock tests pass; those are **not routed
  timing/CDC evidence**. See the firmware's `docs/native-timestamp-snapshot.md`.

Logs: firmware qualification workspace `firmware-health.W1CUQ3E7`, files
`native-timestamp-{native,arm,python}-qualification.txt`. Follow-up ARM log:
`native-arm.tJWJ9FOa/arm-onboard-tests-final.txt`. The test archive was staged
in private temporary directories and executed unprivileged. Before/after
guards confirm unchanged service PID/restart count, server executable, boot ID,
eight protected-file hashes and private identity. No server was installed or
restarted, and no hardware configuration or network settings were changed.

The image uses BusyBox checksum options (`sha256sum -c`, quiet check `-c -s`),
has no `timeout` utility, and needs `LD_LIBRARY_PATH=/usr/lib/daphne-server`
for protobuf's transitive libraries. Earlier attempts stopped at those
environment prerequisites; they were not passing test runs. The final runner
uses installed Python's `subprocess.run(..., timeout=30)` for each executable
and performs post-run guards even when a test fails. Test archive SHA-256:
`7534e1178a2534fc4508de2b7d9b2d130ee8b1a6b1aa71f2badc62d6836edbdb`.

### Complete clean-candidate ARM check

Source: OS commit `13bc7251b6a8dceedf4db3a8d6f91c4f4782c5e7`, server subtree
`da1945b6d108cd53cbcf38200e3a57c504175687`, isolated clean detached worktree.
The candidate was cross-built using GCC 12.2 and the existing hashed Protobuf
30.1/ZeroMQ dependencies, then relinked with install RUNPATH
`/usr/lib/daphne-server`. All 102 tracked Python tests also pass against its
generated bindings. No uncommitted source changes or user worktree edits were
included.

Candidate server SHA-256:
`281696155ed8c08aea5e7ef3976a0a4c47b56f5a9c8dfbfc19399d5d46df75d8`.
Final software-test archive SHA-256:
`e0aec445bbf134505713fe7615b9b1d0bac63f88e0a7176161ad2e1367df5f74`.
Evidence under `firmware-health.W1CUQ3E7/runtime-candidate.00FTH1Zj`:
`configure-install-rpath.txt`, `build-install-rpath.txt`, `python-tests.txt`,
`ctest-inventory.json`, `arm-onboard-tests-verified-libs.txt` and the archived
`run-tests.py`/`SHA256SUMS`/`SOURCE.txt`. The archive contains exactly the 24
registered unit executables plus the candidate/help check, not the opt-in
hardware diagnostic programs or private configuration.

The first preflight stopped before tests because installed library hashes
differed from the unstripped linker inputs. Read-only retrieval and comparison
proved that Protobuf, utf8-validity and ZeroMQ become **byte-identical** after
`objcopy --strip-unneeded --remove-section=.comment --remove-section=.gnu_debuglink`
on local comparison copies. The final runner checks the actual installed raw
hashes, not the normalized hashes; no libraries on the board were replaced.
`library-normalization-comparison.txt` records the comparison. The failed
preflight log/archive are retained separately and are not passing evidence.

The final run was unprivileged and checked the service PID/restart count and
invocation, boot ID, deployed binary, eight protected files, private identity
and three installed private libraries before/after. Only temporary test files
were added. No service restart, installation, live RPC, FPGA or analog access,
QEMU execution or PetaLinux image build occurred. This is a software candidate,
**not** a qualified runtime installation bundle; the release pin remains old
until the matching runtime and live regression are qualified.

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
   relabel old profiles or bypass admission. Both producers now retain the ABI
   evidence through OS overlay staging. The image's pinned server runtime still
   needs to be updated/qualified alongside the new overlay/profile contract.
2. Run qualified Cooper synthesis/routing, review mandatory CDC/path reports,
   and qualify both firmware variants. No synthesis job is running yet.
3. Complete guarded live ABI 2.0/2.1 regression (all ARM software suites now pass). Preserve CERN
   MAC/IP, private identity and zero BIAS/BIASCTRL; verify the complete FE
   configuration, alignment and all 40 spy waveforms separately.
4. Publish the qualified client/source/bundle and update the wiki with actual
   deployed versions and hardware evidence, not these source-only results.

## Full-stream source port

The separate full-stream repository now has branch `fix/health-timestamp-abi21`:
`8798471` adds the same native snapshot RTL/ABI and native-clock bindings;
`d52e420` adds mandatory routed payload checks and excludes the held payload
from the two legacy master-clock-to-PS blanket cuts. The A002 mux and acquisition
timestamp path remain unchanged. Eight ratio/phase simulations, four FuseSoC
smoke suites and 20 source/Tcl-mock tests pass. These do not qualify the actual
endpoint netlist, routing, CDC or live full-stream data. Cooper's latest route
check terminated with a bridge timeout; no build job was launched.

Full-stream build binding `6052164` and packaging `67510d0` now pass 37
source/Tcl/packaging tests and three shell gate tests. Cross-repository synthetic
integration runs both actual packagers and OS overlay staging with real dtc,
ZIP and checksums; ABI 2.1 survives into both profiles and recipe variables.
Invalid evidence preserves the previous staged tree. This does not stage or
qualify the matching server runtime, build an OS image or qualify hardware.
