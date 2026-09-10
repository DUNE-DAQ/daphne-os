# Bundle ABI metadata: what changed

Source implementation only. No new image, FPGA application or network settings
have been installed on DAPHNE-015.

Source revisions: firmware build binding `a5f93a2`, staging fixes through
`0281c82`; OS staging/refresh `c08eb05`.

Previously, staging wrote `identity_abi_minor=0` and changed only the runtime
profile's app name. That would incorrectly label a new ABI 2.1 payload and make
the live admission check reject it.

## New path

1. The firmware's default board-complete Vivado flow captures the unique
   effective `stuff.vhd` synthesis input and its literal magic/ABI/variant.
   The BD's configured build word must match the selected seven-digit stamp.
2. Before synthesis, it writes `<build>.identity-input.json`. After successful
   routed snapshot checks and bit/bin/XSA export, it checks the source again
   and writes `<build>.identity.json`, binding the declaration to source,
   binary, XSA and timestamp-report SHA-256 digests. Changed sources, missing
   checks and unsupported ABI/tool values fail the build.
3. Packaging verifies that record; it does **not** create it retrospectively
   from an arbitrary XSA/bin pair. The app archive and checksum manifests retain
   `GATEWARE-IDENTITY.json` and, for ABI 2.1, the complete 130-bit
   `post_route_timestamp_snapshot.rpt`.
4. OS staging verifies the selected app/variant/build, binary digest, report
   and manifest coverage. It renders the corresponding `IDENTITY_ABI_MINOR` into the
   runtime profile and preserves the evidence through the image recipe.
   Either app may have a different supported minor. Existing transaction
   rollback still covers payloads, version variables and both profiles.
   OS layer refresh preserves the app and ABI bindings together.
5. Startup still compares actual FPGA magic/ABI/variant/build against the
   selected profile. Packaging metadata cannot replace live admission.

“Sealed” means **hash-bound, not signed or authenticated**. This is build
provenance, not bitstream decoding or proof of the complete source tree's
revision. Inputs/output directories must remain private to the isolated build.
Real routed timing, CDC and board qualification are still required.

## Existing bundles

An old-format bundle without the new record remains **ABI 2.0**. Staging never
upgrades it by inference from a branch/app name. A timestamp report without a
record is rejected. Bare old handoffs cannot be relabelled/repackaged as new
qualified builds; retain their existing qualified archives.

Only the firmware's default board-complete implementation lane currently
produces the captured/sealed evidence. The compatibility/native export lane
does not, so its standalone exports do not satisfy the new packaging gate.
The separate full-stream firmware has not yet received the timestamp RTL port;
legacy full-stream ABI 2.0 can coexist with a qualified self-trigger ABI 2.1.

Staging commands are unchanged. For example, use the existing
`scripts/petalinux/stage_overlay_into_project.sh` with both exact bundle paths
and SHA selections. **Do not manually edit `IDENTITY_ABI_MINOR` to force admission.**

## Tests and remaining verification

- **85 OS PetaLinux tests**, **63 mirrored firmware PetaLinux tests**, and
  **23 firmware timing/build-identity tests** pass locally.
- The real packager is exercised with synthetic binary/XSA and fake device-tree
  tools; archive contents and actual checksum verification are checked.
- Negative tests cover source/artifact mismatch, unknown ABI, bad build stamp,
  missing/duplicate evidence, incomplete/failing timing rows, wrong profiles,
  mixed ABI staging and rollback. Tcl uses mocks, not a Vivado netlist.
- Remote-wrapper commit `96abace` also fixes failure propagation through `tee`.
  Its three local tests exercise failed preflight/build/package stages, failed
  logging and successful completion; no Vivado process is launched by them.

Evidence is under `completion-VEpMKkGG/firmware-health.W1CUQ3E7/bundle-identity-*`.
No full PetaLinux image build, real Vivado source-object binding, routed build,
ARM/live regression or deployment has been qualified for these changes yet.

The synthesis-source query follows
[AMD's documented compile-order query](https://docs.amd.com/r/2024.1-English/ug896-vivado-ip/Querying-IP-Customization-Files).
That documents the API, not this board's actual object bindings.
