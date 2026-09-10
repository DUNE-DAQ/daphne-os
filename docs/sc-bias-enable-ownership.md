# SC BiasEnable: remove the implicit Configure write

Server **fb82e0a is deployed and live-tested** on DAPHNE-015. Aggregate Configure
now leaves SC-owned BiasEnable untouched. The FPGA was not reloaded. The complete
runtime bundle, image pin **1039f46** and **41-file ONL handoff** are verified.
The previous 4e74f10 bundle is retained unchanged and lacks this correction.

## Contract and correction

- **SC003** is SC's requested enable state; its dedicated interface and caller
  authorization remain pending. **I288** stays server-produced FPGA readback.
- Commit **bd47682** removes `setBiasEnable(true)` from aggregate Configure.
  DAQ still programs BIASCTRL and the per-AFE numerical BIAS targets. It neither
  writes nor reads/restores the enable register. Normal AFE reset/alignment is
  otherwise unchanged.
- The existing explicit `writeVbiasControl(..., enable)` path remains unchanged.
  Keeping that command is not proof of SC-only authorization or a new interlock.
- Canonical command evidence becomes `daphne-executed-configuration-v2` with
  `bias_enable_command=none`. Expect a different applied hash after the next
  successful Configure; do not compare it with the old v1 hash as if settings
  were lost. Protocol field numbers and schema files are unchanged.
- Commit **fb82e0a** makes the aggregate client check fresh admitted enable
  observations before/after Configure and after capture. Both sampled states
  must agree, with the same process, boot, firmware and successful execution.
  The client sends no enable command. Equal samples are not a physical glitch
  test and do not measure voltage.

On a fresh FPGA load the enable register resets to zero; this Configure change
deliberately does not turn it back on. Do not use a firmware/runtime reload as
an application-update shortcut when preserving the current SC state is required.

## Verification so far

Clean detached source `fb82e0a6f6607e9486a98ed6fc1a26b07b0b0665`:

- All **33 host C++ suites** and **33 actual ARM suites** pass.
- **216 Python tests per independently generated binding set**, no skips.
- Synthetic checks accept unchanged 0 and unchanged 1; reject either transition,
  missing/failed/stale readback, mismatched raw bits, changed identity, unrelated
  or failed Configure evidence, and the old implicit-enable acknowledgement.
- Source-wiring guards verify the actual handler has no direct enable access;
  these are explicitly not a simulated execution of the complete hardware handler.
- Native candidate `--help` and build-metadata probe pass. Installed service,
  runtime/Hermes invocations, boot, enable=1, ADC selectors=0/0 and protected
  settings are unchanged. No Configure, bias command or service restart was
  performed during this qualification.
- The existing ONL readback client also passes three read-only RPCs against
  installed **4e74f10**, confirming fresh enable=1 observations and unchanged
  process/boot/configuration evidence within that check. This is not a live test
  of the new candidate's Configure behavior.

Evidence: `server-v05-fixes-20260909/sc-bias-ownership.STn69mL3`, including
`native-manifest.json`, `native-proof.json`, both independently decoded
`native-audit-*.json`, build/test logs and before/after board guards.
Candidate executable SHA-256:
`67c6c470dc61f8b54a1c0058b0d80b678169209133aa74619a28fb61dcfe685c`.

## Live qualification

The board's systemd 255.21 was tested with three temporary dummy services
reproducing the Requires/PartOf relationships. Ordinary restart propagated to
the dummy runtime/firmware; scoped stop/start did not. All dummy services were
stopped and unloaded. The first probe's cleanup returned an error for an already
unloaded unit; the corrected cleanup and complete rerun passed.

The actual deployment used an explicit administrator-only
`--job-mode=ignore-requirements` stop/start of `daphne.service`. This retains
ordering but does not pull requirement jobs into that transaction; it is not an
application restart API or a general shortcut. See the
[systemd 255 job-mode documentation](https://raw.githubusercontent.com/systemd/systemd/v255/man/systemctl.xml).
All dependencies were required to be active first. Normal stop hooks, including
quiesce, and server firmware-admission checks stayed enabled. No unit files,
dependencies, network configuration or enable registers were changed.

Eight guarded snapshots (before, stopped, replaced and five after-start)
confirmed the same runtime, firmware, clock, endpoint and Hermes invocations,
boot, FPGA identity and enable=1. The old server executable was retained in RAM;
rollback was not used. Only the server invocation changed.

- Initial and final aggregate regressions each pass **158 exchanges**, both AFE
  orders, fresh AFE readback, alignment and all 40 spybuffer channels. Enable=1
  was retained after Configure and capture. Normal AFE reset pulses remain;
  no held-reset fault or physical glitch/pin test was performed.
- Bookkeeping: **48 observations, 32 during Configure**, maximum **288.4 ms**.
  Rejections preserve evidence; the existing channel-0 offset rewrite invalidates
  it; full Configure restores the same v2 hash.
- ADC, SFP, regulator, identity, platform and FPGA-health regressions pass.
  ADC supplied 80 CRC-checked samples, not calibrated current measurements.
  All five metadata/privacy client checks pass. No new-invocation error-level
  journal messages were found.
- Compatible read-only AFE/health clients from the prior ONL source export also
  pass against fb82e0a (3 + 4 exchanges); those client/schema files are unchanged.
  This does not qualify the old runtime bundle as containing the new fix.

Final BIAS/BIASCTRL=0, offset2200/x1, trim0, VGAIN1700, enable1, selectors0/0.
Health remains **12 PASS / 1 external-timing FAIL / 3 UNKNOWN**, not a healthy-board
or run-permit assertion. New applied hash:
`a7c843ddbb3014bc15e5bcb26d528899078b98a6948f034c6c5e487733404bea`.

Live evidence: `sc-bias-ownership.STn69mL3/live-abi20.XylKSa3Q`.
Sealed `qualification.json` SHA-256:
`22e544c93df846c2dc71e4a4310db77ac818ce0d1f771dde01d1c1e3a94f5c08`.
The native-phase qualification above remains historical and unchanged.

## Repeat the maintenance verification

With the exact deployed source/client and an approved SSH forward:

```bash
python daphne-server/scripts/verify_aggregate_zero_bias.py \
  --endpoint tcp://127.0.0.1:19876 \
  --proto-dir /path/to/clean-arm-build/srcs/protobuf \
  --server-source /path/to/clean-source/daphne-server \
  --expected-server-commit fb82e0a6f6607e9486a98ed6fc1a26b07b0b0665 \
  --expected-build-id 0x3f17f1b \
  --output-dir /path/to/new-empty-evidence-directory \
  --apply-zero-bias-configuration
```

This is a maintenance command, not a read-only check. It applies the full FE
profile twice, aligns five AFEs and captures all 40 channels. Do not run it
against the old server. This qualification does not establish physical enable
transitions, full-stream or newly routed firmware.

## Runtime and ONL handoff

The exact deployed executable and unchanged Hermes/Protobuf/UTF-8/ZeroMQ
dependencies are packaged together. Native ARM loader/help checks validate the
packaged libraries and existing OS libsystemd 255.21; Hermes was not executed.
All **140 packaging/audit tests** and actual runtime staging pass. The immediate
previous 4e74f10 archive is rejected without replacing staged files. Synthetic
ABI-minor combinations are packaging checks, not routed-firmware qualification.

On `np04-onl-004`:

```bash
cd "$HOME/daphne015-server-runtime-fb82e0a"
sha256sum --check --strict SHA256SUMS
```

The owner-only directory contains 41 payload files plus the manifest. Runtime
SHA-256: `932106f611ee2b5fdd274cd6956678e804a99d4ebb9b7dd1d2b1e50cd5866644`.
Manifest SHA-256: `88dd42bd333778aa4ef546da10e9412ffeb130eef52e5a2731a0ba49865732b5`.
All new and previous-handoff payload hashes were verified remotely. The first
comparison helper rejected the old manifest's conventional `./` prefix; the
corrected basename-only parser passed without changing either handoff.

Server source export base fb82e0a and OS integration base 1039f46 have identical
server subtrees. Production/build files and both schemas are unchanged. Known
private MAC/IP literals in examples/docs are placeholders, and one serialized
seed request is omitted per export. File-by-file Git comparisons and all 13
changed Python/shell example syntax checks per export pass. Modified exports
are not exact Git snapshots or a general secret-audit guarantee; Git-less
rebuilds must report revision unavailable. Uncommitted user work is excluded.

Five matching exported clients passed on ONL using existing Python 3.9.16,
protobuf 6.33.5 and pyzmq 25.1.2: **18 read-only exchanges**, including a
before/after bookkeeping bracket. The qualified process, boot and valid v2
configuration hash agree; board guards before/after packaging and clients are
identical. No service restart, FPGA reload, configuration or network/time write
occurred during packaging. Read the bundle README for commands and scope.

Packaging evidence is beside the frozen native/live phases: `runtime-assembly.json`,
`runtime-native-smoke.json`, `actual-runtime-staging-with-old-rejection.txt`,
`packaging-tests.txt`, `handoff-seal.json` and `onl-final-handoff-check-v2.json`.
This is a userspace archive, not a newly built PetaLinux image. Dedicated SC
request/authorization, physical transitions and remaining register producers
stay open.
