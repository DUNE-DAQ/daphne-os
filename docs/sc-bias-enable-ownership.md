# SC BiasEnable: remove the implicit Configure write

Candidate **fb82e0a** is built and native-tested, **not deployed**. DAPHNE-015
still runs **4e74f10**, whose aggregate Configure unconditionally enables bias.

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

## Pending live gate

First qualify a server-only restart path against the actual systemd dependency
graph; preserve SC enable and the approved CERN network identity. Then run the
full zero-BIAS/BIASCTRL regression against the pinned candidate:

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
against the old installed server. Live preservation, packaging/image pin and
the updated ONL runtime bundle remain pending. Native tests do not qualify
physical enable transitions, full-stream or newly routed firmware.
