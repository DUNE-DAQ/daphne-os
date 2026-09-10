# Server build and protobuf identity

Candidate **eecff61**, native-software qualified, **not deployed**. DAPHNE-015
still runs **bffea24** with self-trigger firmware **3f17f1b / ABI 2.0**.
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

After a separately qualified candidate installation, with matching Python
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
This client deliberately rejects the currently deployed bffea24's missing field.
Fingerprint checks are not authentication; retain approved transport controls.

## Qualification

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

Still pending: guarded installation, actual candidate RPC/full zero-BIAS
regression, complete runtime packaging, image pin and ONL-home handoff. Versions
for the other services, a semantic schema compatibility policy, newer routed
firmware, full-stream/image qualification and the broader
[hardware/database gaps](server-v05-completion-plan.md) remain open.
