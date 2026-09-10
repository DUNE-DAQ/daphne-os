# Qualified server runtime

Current server: **eecff61**, deployed with full self-trigger ABI 2.0 regression;
see [server/schema identity qualification](software-build-verification.md).

On `np04-onl-004`:

```bash
cd "$HOME/daphne015-server-runtime-eecff61"
sha256sum --check --strict SHA256SUMS
```

Owner-only directory, **22 payload files** plus the checksum manifest. Runtime
archive SHA-256:
`a0d8f6cc6fdda60b46e2dedf7bc95eb1d565a9a8e82b7a5d343f24a65f48bbea`.
Handoff `SHA256SUMS` digest:
`e41bc5087db7d4fb4688fbb89dd95d1d1d7b449f8766e5540d2b9a2dc0d41def`.
The bundle supplies the exact server/Hermes/private libraries, matching Python
bindings, native/live/busy-Configure evidence and privacy-filtered source exports.
No private network/identity/service/FE configuration or new OS/firmware image.

Server source base **eecff61**, OS integration base **3052e65** (pin and tests).
File-by-file source audit: 1,197 / 1,363 unchanged regular files, 19 / 22 redacted
text files, one omitted serialized request per export; all 13 changed Python/
shell examples per export pass syntax checks. Production server/build and .proto
files are unchanged. These modified exports exclude uncommitted work and are
not exact Git snapshots or a general secret-audit guarantee. Rebuilding without
Git leaves compiled source revision unavailable, not falsely labelled canonical.
Read `README.md`, source metadata and both redaction manifests before reuse.

Verified: 28 host/28 actual ARM suites, 162 Python tests per binding, live metadata
through both RPC paths and 32 observations during Configure, full zero-BIAS/
all-channel and six-suite regression. Native packaged-library loader/CLI smoke,
actual staging and **126 packaging tests** pass. The image pin names eecff61;
ABI 0/1/2 minor support is not routed-firmware/full-stream/image qualification.
Firmware remains 3f17f1b; CERN settings are unchanged. Final health is still
11 PASS / 1 external-timing FAIL / 3 UNKNOWN. Earlier handoffs are retained.

## Previous handoff: bffea24

Previous server: **bffea24**, deployed on DAPHNE-015 with full live self-trigger
ABI 2.0 regression; see [management-link qualification](management-link-verification.md).
The matching image pin and complete userspace runtime retain ABI 0/1/2 minor
capabilities, without claiming newer firmware or image qualification.

On `np04-onl-004`:

```bash
cd "$HOME/daphne015-server-runtime-bffea24"
sha256sum --check --strict SHA256SUMS
```

Owner-only directory, 20 payload files plus their checksum manifest. Runtime
archive SHA-256:
`ff956a4fc41dec8035c6a0cb8a857b4aa2256d01321a639548214458cb8c1dad`.
Handoff `SHA256SUMS` digest:
`aab55661b64181cb3a6ee29b27ab336a0e4858c08dd7f48142e5ac097a41b0d3`.
It supplies the exact server/Hermes/private libraries, matching protoc-30.1
Python bindings, redacted native/live evidence and privacy-filtered source
exports. No private network/identity configuration or OS/firmware image.

Server export base **bffea24**, OS integration base **214b676** (pin and tests).
The file-by-file audit finds 1,185 / 1,350 unchanged regular files, 19 / 22
redacted text files and one omitted serialized seed request per export; all
13 changed Python/shell examples per export pass syntax checks. Production
server/build sources remain unchanged. These modified exports exclude
uncommitted work and are not exact Git snapshots or a general secret audit.
Read `README.md`, `SOURCE-METADATA.txt` and the redaction manifests first.

Verified: 27 host and 27 actual ARM suites, 144 Python tests with each binding,
all 14 management-link observations, full zero-BIAS/all-channel regression,
bookkeeping and six telemetry suites. The archive's native packaged-library
loader/CLI smoke, actual staging and all **124 packaging tests** pass.
Firmware stays **3f17f1b**, self-trigger ABI 2.0; private/network settings match.
The initial post-reload/pre-FE policy guard failed, then passed unchanged after
full zero-BIAS Configure. See the qualification report for the retained caveat.
Health remains 11 PASS / 1 external-timing FAIL / 3 UNKNOWN, not overall OK.
Routed newer firmware, full-stream, Hermes delivery, metrology and a full image
remain unqualified. Previous handoffs below are retained with historical pins.

## Previous handoff: 3f636f4

Previous server: **3f636f4**, deployed on DAPHNE-015 with full live self-trigger
ABI 2.0 regression; [qualification and current image contract](protocol-error-server-verification.md).
Its complete runtime SHA-256 is
`1af9600acbfb8e557bedde23bde93e13270ccf7b5439d8a4b9f6803e335d0497`;
native packaged-library smoke and 122 packaging tests pass.

The owner-only ONL home directory is **`daphne015-server-runtime-3f636f4`**.
All 19 handoff file checksums pass; its `SHA256SUMS` digest is
`b49f0967b4ea02afba6e967f24a4ab670a5108d518dec3ef2515d17c02e4f56c`.
It includes the matching protoc-30.1 Python bindings, native/live evidence and
privacy-filtered server/OS exports based on `3f636f4` / `3ff916b`.
File-by-file source audit finds 1,178 / 1,340 unchanged regular files, 19 / 22
redacted text files and one omitted serialized request per export; all 13
changed Python/shell examples per export pass syntax checks. Production server/
build sources are unchanged, but these modified exports are not exact Git snapshots
or a general secret-audit guarantee. Uncommitted work is excluded.

For that historical handoff on ONL:

```bash
cd "$HOME/daphne015-server-runtime-3f636f4"
sha256sum --check --strict SHA256SUMS
```

Read its `README.md` and source/redaction manifests before reuse.
`ASSEMBLY-METADATA.txt` and the archive's internal scope record the earlier
software-only assembly phase. Adjacent `BUILD-METADATA.txt` and
`LIVE-QUALIFICATION.json` add the subsequent live ABI 2.0 evidence without
changing archive bytes. The final handoff also passes actual runtime staging.
No private network/identity configuration or new OS/firmware image is supplied.
Previous handoffs below are retained and require their matching historical pins.

## Previous handoff: 3556811

The historical userspace archive below contains the previous qualified server.
It is **not a new OS/firmware image**. No private identity, MAC/IP, network,
analogue or service configuration is included.

## Pinned bytes and source

- Server source: `DUNE-DAQ/daphne-os@3556811fbe5bf01b7c66c862a8a6e1821a4f6246`,
  directory `daphne-server/`, clean tree at build time.
- Server source tree: `9d50e75e12a24721cb29deb9ded3c1b05d84abb4`.
- Server SHA-256:
  `727b9187ec239f65d7e93740553be89acba606ef11a8a67ff2f068b8c64fa993`.
- Runtime archive SHA-256:
  `38f9a18f716e32b2c3d48b37ee2c1b6d65953ee411a45e56e26387f6a56a0b56`.
- Its matching historical image contract: server `3556811`, ABI minors **0 and 1**.
  Pin update `e01af89`; source capability is not firmware qualification.
- Hermes and Protobuf/UTF-8/ZeroMQ libraries: exact hash-verified copies of
  the installed board bytes. These legacy binary dependencies were not rebuilt.
- Server RUNPATH: `/usr/lib/daphne-server`. Retain the existing service's
  private-library search path for transitive dependencies.

The archive has five regular runtime binaries/libraries, four library aliases
and redacted qualification records with a checksum manifest. OS-provided
libraries such as libc, libstdc++, OpenMP and libi2c remain prerequisites;
this is not a self-contained root filesystem.

## Verified scope

All **25 hardware-free ARM C++ suites**, exact candidate `--help` and **109
Python tests** passed. Subsequent [live self-trigger ABI 2.0 qualification](host-resource-verification.md)
covers the new host-resource fields, full zero-bias configuration/bookkeeping,
five-AFE alignment, all 40 spybuffer channels, ADS1261, SFP, regulator,
temperature/service, identity and FPGA-health reporting.

The complete archive then passed a fresh unprivileged native-board loader/CLI
check. Loader tracing verifies that all three private dependencies resolve
inside the extracted archive, rather than the installed library directory.
Service instances/PIDs/restarts, boot, installed binaries/libraries, private
identity and protected settings match before and after; no restart or hardware
configuration is performed by that check.

All **101 PetaLinux tests** pass. The actual runtime also stages successfully
and passes the actual recipe decision with both real-packager synthetic ABI 2.1
overlay declarations. This fixture is **not deployable firmware or a BitBake/image
test**. No private configuration is imported into it.

Remaining: real ABI 2.1 routed firmware/native-counter tests, full-stream hardware,
Hermes delivery, analog calibration and a complete PetaLinux image build.
The board remains at firmware `3f17f1b`, self-trigger ABI 2.0.
FPGA health remains 11 PASS / 1 external-timing FAIL / 3 UNKNOWN.
Evidence hashes are not authenticated signatures.

## ONL handoff

The updated handoff directory is `daphne015-server-runtime-3556811` in the
operator's home on `np04-onl-004`, owner-only. It contains the archive, metadata,
checksums, packaging/native-check scripts, native smoke result and privacy-filtered
source exports. Read its `README.md`, `SOURCE-METADATA.txt` and per-export
redaction manifests before reuse.

All 16 handoff file checksums passed on ONL, with mode 0700 verified for the
directory. Handoff `SHA256SUMS` digest:
`aaa0623030aa8bd7b279dcdd9f554dc5a53f5a85d1ab7f86875bde6df62bc03e`.
The OS integration export is based on `6dcd12a`; source-export audit confirms
1,172 / 1,329 unchanged regular files in the server / OS exports, respectively.
There are 19 / 22 redacted text files and one omitted serialized request per
export; all 13 affected Python/shell examples per export pass syntax checks.
The known-address scan passes after filtering. Unfiltered local source exports
were retained outside the handoff, not uploaded as part of this bundle.

The server-source export starts from `3556811`. The newer OS integration export
includes the matching image contract and documentation, plus the probe-only
TextFormat fix `b4e50b8`. Known private MAC/IPv4 literals in legacy client examples,
remote scripts and documentation are replaced with explicit placeholders; the
serialized seed request is omitted. Production server/build sources are unchanged.
These are **modified source exports**, not byte-identical Git snapshots or a
relabeling of the deployed binary's build source. Manifests retain original and
exported hashes for each changed/omitted file. Uncommitted user work, the external
toolchain and Git database are excluded. The check targets known board address
literals, not all possible secrets.

The previous `daphne015-server-runtime-13bc725` handoff is retained unchanged.
Its runtime SHA-256 is
`a09d74ccaa9c0a3ce00818b93e73f7f7b7e2bd51d975610bcd3cd03a15613e1a`;
it supplies the previous server but lacks host-resource observations. Its older
source snapshot was not privacy-filtered; do not redistribute that snapshot
as address-free. The runtime tarball and source snapshot are separate artifacts.
The current image contract intentionally rejects that older source pin.

## Inspect and stage

On ONL:

```bash
cd "$HOME/daphne015-server-runtime-3556811"
sha256sum --check --strict SHA256SUMS
runtime_inspect_dir=$(mktemp -d)
tar -xzf daphne-server-runtime-minimal.tgz -C "$runtime_inspect_dir"
(cd "$runtime_inspect_dir" && sha256sum --check --strict qualification/PAYLOAD-SHA256SUMS)
```

From the matching OS checkout, with its refreshed **project-owned** layer:

```bash
./scripts/petalinux/stage_runtime_into_project.sh \
  "$PETALINUX_PROJECT_DIR" "$RUNTIME_DIR/daphne-server-runtime-minimal.tgz"
```

The stager validates declarations, digests, ELF identity and explicit native
execution evidence; it does not run tests, install, flash or authenticate a
bundle. Old/missing/mixed execution metadata and stale source pins fail closed.
Do not alter hashes or source metadata to impersonate the required pin.
