# Server build and protobuf identity

Server **eecff61**, deployed and live-qualified on DAPHNE-015 with unchanged
self-trigger firmware **3f17f1b / ABI 2.0**.
Implementation `4a20887`; independent client/tests `eecff61`.

## What it reports

Workbook I143/I144 now have explicit server software/build and schema identity:
`SystemStatusSnapshot.server_build` field **29** and the independent
`ServerState.server_build` field **19**, sharing `ServerBuildInfo`.
Existing fields, request IDs and envelope version remain unchanged.

- Software version `git:<full HEAD>[-dirty]`, full revision, committed server
  directory tree and a present clean/dirty flag. GOOD means metadata was
  collected, not that the source is clean, approved or authenticated.
- Exact high/low `.proto` source SHA-256 hashes and **ControlEnvelopeV2 version 2**.
  Router admission and metadata use the same constant. Hash differences do not
  themselves establish incompatibility: even a comment changes the source hash.
- Compiler ID/version, target architecture and build-time Protobuf version.
  These are not runtime-library readback or firmware/OS/Hermes versions.

Metadata is compiled in: no Git, file read or subprocess is added to runtime
bookkeeping. It remains available while Configure occupies the hardware worker.
The parent reply supplies process identity and observation time; no build UTC,
paths, remote URLs, credentials or private network identity are exported.

Git-less exports leave revision/version/tree/dirty fields absent with UNAVAILABLE
quality. An untracked export inside an unrelated Git repository cannot borrow
the parent revision. Dirty source retains its base commit but does not pretend
the committed tree describes its modified bytes. Ignored files/build flags and
external dependencies are not a source-tree attestation. Build from a stable
checkout; sequential Git/hash collection is not an atomic source snapshot.

## Build and inspect

Follow [the server/client build guide](https://github.com/DUNE-DAQ/daphne-os/wiki/Building-daphne-server-and-clients)
using a pinned clean Git checkout. For the target build, retain the qualified
dependency paths and set **both** `CMAKE_INSTALL_RPATH=/usr/lib/daphne-server`
and `CMAKE_BUILD_WITH_INSTALL_RPATH=ON`; check the actual ELF RUNPATH before reuse.

The [CMake custom target](https://cmake.org/cmake/help/latest/command/add_custom_target.html)
checks metadata on every build, not only configuration. Its generated header
uses [configure_file](https://cmake.org/cmake/help/latest/command/configure_file.html),
which preserves the timestamp if contents do not change. Actual Make and Ninja
fixtures confirm that source edits and new commits refresh the compiled result.
Run `software_build_probe` on the matching architecture: it prints only compiled
metadata as protobuf hex in JSON and does not initialize the runtime or hardware.

With the deployed server, matching Python
bindings and an approved SSH forward:

```bash
python daphne-server/scripts/verify_server_build.py \
  --endpoint tcp://127.0.0.1:44015 \
  --proto-dir /path/to/matching/protobuf \
  --server-source /path/to/pinned/daphne-server \
  --expected-server-commit eecff616ea6841732e9422c7af6afaa2b06c4ce9
```

Default: two software-only bookkeeping requests, exact source/schema comparison,
same process/boot, advancing heartbeat and clean-source requirement. Optional
`--include-system-status` adds ordinary hardware-status collection and compares
both metadata paths. No identity-details opt-in, setters or service changes.
This client deliberately rejects the historical bffea24's missing field.
Fingerprint checks are not authentication; retain approved transport controls.

## Standalone native qualification before deployment

- Clean detached source: `eecff616ea6841732e9422c7af6afaa2b06c4ce9`;
  server tree `90192962c5a293bc885b72cec90f45a27236d285`.
- **28 host C++ suites**, **28 actual ARM software suites**, and **162 Python
  tests with each binding set** (protoc 3.21.12 and 30.1) pass.
- Tests cover Git-less/dirty/staged/untracked sources, unrelated parent repos,
  explicit false presence, Make/Ninja incremental rebuilds, source-hash mismatch,
  old replies, dirty builds, correlation errors, stalled heartbeat, process
  replacement and unrequested private details. CLI responder tests are synthetic.
- Two native compiled-metadata samples agree; independent Python checks with
  both bindings match the clean Git source/tree, both schema hashes, AArch64 and
  compile-time Protobuf 6.30.1. Exact candidate `--help` passes with installed libs.
- Before/after guards preserve running bffea24/Hermes binaries, libraries,
  service instances/PIDs/restarts, boot, protected files and private identity.
  No restart, firmware reload, network/FE write or hardware collector was run.

Candidate SHA-256:
`2d0333f7e486afa25cfffc4eb23dd56eccce2e90489d6e341fe8748140f9755f`.
Native qualification SHA-256:
`e811eeda2cd22f497a0909b8127a6ed3eb38aa17d5bf5c87a4e46603a7dbec8d`.
Evidence directory `software-build.zd1nH7Oj`; owner-only board test directory
`/tmp/daphne-build-native.XXP6gSO0` is retained. This test archive is not a complete
runtime or deployment image. An initial host configure lacked the local I2C
dependency path; the first ARM build had a build-machine RUNPATH. Corrected
clean builds and final ELF inspection preceded native qualification. The first
Ninja fixture lacked Ninja; a task-local tool supplied it for the passing run.

## Live qualification and handoff

Only the stopped server binary was replaced. The normal runtime restart reloaded
the same installed firmware. Both 153-exchange aggregate runs passed, bracketing
bookkeeping maintenance: both AFE orders, all five alignments and all 40 channels.
All 48 bookkeeping replies retained matching metadata, including 32 during
Configure; heartbeat progressed, invalid requests were rejected before writes,
and direct-write invalidation/canonical-hash restoration passed.

The independent three-exchange build client passed through both RPC paths.
Six further suites passed: v0.5 (17 exchanges), ADC (93; 80 CRC acquisitions),
SFP (5), regulators (7), FPGA health (4) and identity/link status (5).
Final FE is offset 2200/x1, trim 0, VGAIN 1700, BIAS/BIASCTRL zero; generator
enable 1 and current selectors 0/0 were checked after full Configure.
Protected/private files, firmware and dependencies match. Server PID 28860,
instance `35692266d8f84438b0a9471ae5db3ce8`, zero automatic restarts.
Root remains writable with 23,592,960 bytes available; no cleanup/resizing.
Health remains **11 PASS / 1 external-timing FAIL / 3 UNKNOWN**, not overall OK.

The first staging attempt lacked permission to create its new /run directory;
it failed before service changes. A supplemental metadata-check wrapper used a
C++ serialization method name in Python and failed on its initial read, before
Configure. Both were corrected without changing the server or weakening guards;
failed records are retained. Previous executable remains in RAM at
`/run/daphne-candidate-eecff61/previous-server`.

Live evidence: `software-build.zd1nH7Oj/live-abi20.sL5T0IL6`; qualification SHA-256
`e59f9d2696e7196fd6e791c25bbc1d5a6e58f4a9b0441138e40d08e12df84d7b`.
The complete runtime passes native packaged-library loader/CLI smoke, actual
staging and **126 packaging tests**. Image pin `3052e65` names eecff61; its
0/1/2 minor capabilities do not qualify newer firmware or an image.
The owner-only ONL handoff is `daphne015-server-runtime-eecff61`; see
[contents, source filtering and checksums](qualified-server-runtime.md).

Other service versions, semantic schema compatibility policy, newer routed
firmware, full-stream/image qualification and the broader
[hardware/database gaps](server-v05-completion-plan.md) remain open. Cooper's
latest connection attempt timed out at the FNAL bridge; no synthesis job started.
