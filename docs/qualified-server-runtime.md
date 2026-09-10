# Qualified server runtime: 13bc725

This userspace archive contains the server already tested on DAPHNE-015.
It is **not a new OS/firmware image** and contains no private identity,
MAC/IP, network, analogue or service configuration.

## What is pinned

- Source: `DUNE-DAQ/daphne-os@13bc7251b6a8dceedf4db3a8d6f91c4f4782c5e7`,
  directory `daphne-server/`, clean tree at build time.
- Server SHA-256:
  `281696155ed8c08aea5e7ef3976a0a4c47b56f5a9c8dfbfc19399d5d46df75d8`.
- Archive SHA-256:
  `a09d74ccaa9c0a3ce00818b93e73f7f7b7e2bd51d975610bcd3cd03a15613e1a`.
- Hermes and Protobuf/UTF-8/ZeroMQ libraries: exact installed board bytes,
  with hashes in `BUILD-METADATA.txt`. These remain legacy binary inputs;
  they were not rebuilt. Their normalized bytes match the earlier runtime inputs.
- Server RUNPATH: `/usr/lib/daphne-server`. Retain the existing service's
  private-library search path for transitive dependencies.

The archive includes nine executable/library entries, the required library
aliases, and redacted qualification evidence with an internal checksum manifest.
The source commit is an **OS-repository** revision, not a daphneZMQ commit.

## What passed—and what did not

All 24 hardware-free C++ suites and the exact server's `--help` passed on the
native AArch64 board. All 102 tracked Python tests passed against its generated
bindings. The same server then passed the [live self-trigger ABI 2.0
regression](native-timestamp-verification.md#live-self-trigger-abi-20-qualification),
including zero-bias configuration, alignment, spy buffers and register collectors.
The current board checks also identify the actual running Hermes payload,
not just its Bash launcher.

Staging accepts explicit `execution_validation_kind=native-aarch64` with a
passing `execution_validation` record; it no longer requires falsely labelling
this work as QEMU execution. Legacy QEMU metadata remains supported. Missing,
failed, duplicate or mixed execution records are rejected before staging changes.

The reviewed source contract admits ABI minors `0 1`. This is a **software
capability**, not qualification of new firmware. Both overlay minors are checked,
including the inactive variant; ABI 2.1 still requires sealed identity metadata.
The 101 PetaLinux tests and actual-runtime staging/recipe-guard check pass.
The latter uses synthetic overlay declarations: it is not a BitBake/image test.

Still pending: real ABI 2.1 routed firmware, full-stream and native-counter
hardware tests, and a complete PetaLinux image build. Current health remains
11 PASS / 1 external-timing FAIL / 3 UNKNOWN; no overall healthy-board claim.
Metadata and evidence hashes are not authenticated signatures.

## Inspect and stage

Keep the runtime tarball, `BUILD-METADATA.txt` and `SHA256SUMS` together.
In the received runtime directory:

```bash
sha256sum --check --strict SHA256SUMS
runtime_inspect_dir=$(mktemp -d)
tar -xzf daphne-server-runtime-minimal.tgz -C "$runtime_inspect_dir"
(cd "$runtime_inspect_dir" && sha256sum --check --strict qualification/PAYLOAD-SHA256SUMS)
```

From a current OS checkout with the updated source contract and native-aware
stager, use your **project-owned** layer, refreshed from the same checkout:

```bash
./scripts/petalinux/stage_runtime_into_project.sh \
  "$PETALINUX_PROJECT_DIR" "$RUNTIME_DIR/daphne-server-runtime-minimal.tgz"
```

The script validates declarations/digests/ELF identity; it does not run tests,
flash hardware or install the server. A stale project contract rejects the new
pin; refresh the layer instead of editing metadata to impersonate the old pin.
Only qualified real firmware bundles may be used for an eventual image build.
