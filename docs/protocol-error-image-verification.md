# ABI 2.2 image plumbing: implemented, not a built image

2026-09-10. Commits `38f0547` (sealed-report validation) and `d9dc40c`
(overlay staging, loader and runtime compatibility). These changes do not
flash DAPHNE-015 or replace its running server.

## What changed

- The OS identity helper now accepts exact platform ABI 2.2 and requires all
  **170** diagnostic payload bits: 65 local timestamp, 65 external timestamp,
  40 parser-history bits. ABI 2.1 still requires its original **130** bits.
  The two report headers/populations cannot qualify each other. The helper is
  byte-identical to the producer helper in both firmware ABI 2.2 branches.
- Overlay staging retains the sealed identity and complete report in the
  per-app checksum manifest, records minor 2 and updates only matching profiles.
  Restaging an existing minor-2 profile is supported. Invalid inputs leave
  previously staged payloads, version variables and profiles intact.
- Image recipes fetch the report for minors 1 **and** 2, require sealed
  declarations for both, and explicitly track both variants' guard inputs.
  Empty/malformed declarations no longer silently become legacy minor zero;
  only omitted old-stager declarations retain that compatibility default.
- The board loader understands exact minor 2 but still verifies the complete
  live magic/ABI/variant/build against its selected profile. Unknown minors
  are rejected before hardware access.
- Runtime staging/recipe guards understand an explicit `0 1 2` source contract,
  still require the matching source/archive/execution record, and check both
  overlays. Tool support does not widen the release contract automatically.

The **actual image runtime pin remains `3556811`, minors `0 1`**. Therefore an
ABI 2.2 overlay is still rejected with that old runtime, including when the
other overlay is legacy. New-contract tests explicitly substitute candidate
`3f636f4` in isolated fixtures; they do not make a release or qualify a bundle.

## Evidence

All **121 PetaLinux tooling tests pass** from clean detached source `d9dc40c`.
Coverage includes all nine self-trigger/full-stream minor pairs, both-mode
exact loader identity checks, each missing bit of the 170-bit report, wrong
headers/widths/parents, non-finite or failing timing, hashes, missing/unsealed
metadata, stale runtime capabilities and failure-state preservation.

The tests invoke the staging scripts, actual checksum tools and recipe guard/
URI expressions. FPGA artifacts and some device-tree tools are synthetic;
recipe tests use a datastore double. This is **not** a real BitBake parse,
image build, Vivado run, physical CDC/timing or live firmware qualification.
The initial suite found a test-fixture quoting typo; it was corrected before
the final clean-checkout 121-test run. Its failed log is retained separately.

Evidence: `firmware-health.W1CUQ3E7/protocol-server.Mh4iBcOB`, especially
`os-abi22-clean-all.txt`, `os-identity-abi22.txt`, `os-overlays-abi22.txt` and
`os-loader-abi22.txt`. Both staging shell scripts pass `bash -n`.

From the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/petalinux -v
bash -n scripts/petalinux/stage_overlay_into_project.sh \
        scripts/petalinux/stage_runtime_into_project.sh
```

## Remaining handoff

[The new ARM candidate passes software tests](protocol-error-server-verification.md),
but still needs running-server regression and its complete private-safe runtime
archive/native loader check before the reviewed release pin changes. Then
stage actual qualified firmware outputs, build the complete image and verify
both modes/sources on hardware. The Cooper route remains unavailable; no
synthesis job or new flash is claimed. Preserve approved MAC/IP and zero bias.
