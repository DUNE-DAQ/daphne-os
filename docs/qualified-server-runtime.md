# Qualified server runtime: 3556811

This userspace archive contains the exact server now running on DAPHNE-015.
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
- Image contract: server `3556811`, supported ABI minors **0 and 1**.
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
