# AFE reset as an FPGA-health prerequisite

Server change **a01d95e**, client checks **4e74f10**. Candidate **4e74f10** is
clean-built and native-qualified, **not deployed**. DAPHNE-015 still runs
**78504f1** with unchanged self-trigger **3f17f1b / ABI 2.0** firmware and its
15-check RPC assessment. The existing ONL runtime/image pin remains 78504f1.

## What changed

The candidate adds a sixteenth named check, `afe_reset_released`, using the
existing I284 readback. The deployed RTL says bit 0 at `0x80000000` drives the
common active-high AFE hard-reset output. No new register or protocol field
is needed. This checks the sampled request bit, not the physical output pin.

- Fresh, consistent, admitted reset-clear observation: PASS.
- Equally qualified reset-asserted observation: FAIL / NOT_READY.
- Missing, stale, inconsistent or unqualified observation: UNKNOWN.

The assessor requires exact supported ABI/variant/magic/build format, matching
admission, operating/startup programming evidence, decoded/raw agreement and
complete acquisition/identity timestamp ordering. Maximum acquisition is 100 ms;
maximum observation age is five seconds. The check retains the sample time,
not the later assessment time. Source diagnostics/private strings are not echoed.

SC003 still owns the bias request; I288 remains hardware readback. Neither
BiasEnable nor POWERSTATE becomes a health-policy decision. A single SPI busy
sample is not enough to identify a stall, so busy flags are not fault checks.
No automatic reset, reconfiguration, power/bias action or runtime invalidation
was added. Reset history, actual analog readiness and identical-image reload
detection remain unproved. The assessment is not a run permit or interlock.

## Verification

Clean source: `4e74f1071d09e16a15db597204c22debead2592c`.
Server subtree: `932cdc9dd0d0b4c26a6b6d766807bad2a4d2979c`.

- All 33 host and 33 actual AArch64 software suites pass.
- All 208 Python tests pass independently with host and ARM-generated bindings.
- C++ and independent Python tests cover all 384 ABI/variant/control/bias
  combinations. C++ has 40 missing/corrupt/admission/order mutations plus
  acquisition/age boundaries. Client tests reject false PASS and wrong sample time.
- The exact candidate's native `--help` and compiled-source metadata pass.
- Two standalone probes use the actual collector and assessor on DAPHNE-015.
  Both saw global/bias words **0x2 / 0x1**, and `afe_reset_released=PASS`.
  Both independently generated bindings reproduce the result.

The probe deliberately does not collect the full status inputs: network,
temperature and applied-configuration checks remain UNKNOWN. This is not live
qualification of the candidate's RPC checklist. No physical reset was stimulated.
Protected executable/configuration hashes, boot, service PIDs/invocations and
generator/current-selector guards match before and after. No service restart.
Only test/candidate binaries were placed in owner-only root RAM storage.

Candidate executable SHA-256:
`76afabb25827fc8499abea8d058ea78d6bbb868de96fc3dd2edc8f1ba7c240e2`.
Native proof SHA-256:
`9ea4b278e8bec4531cf13e1bc1806d394e159d54cc3d40fc43b0d3f08c8769c1`.
Matching independent audits SHA-256:
`a0c37583c04d3911abda59000629920b02278b9e00ba4791b0957c4e9aca86a4`.
Evidence directory: `afe-reset-health.B0qg7HuL` in the qualification deliverables.

## Commands and remaining qualification

```bash
ctest --test-dir "$BUILD_HOST" -L unit --output-on-failure
PYTHONPATH="$BUILD_HOST/srcs/protobuf" python3 -m unittest discover \
  -s daphne-server/tests -p 'test_*.py'
sudo env LD_LIBRARY_PATH=/usr/lib/daphne-server \
  "$PROBE_STAGE/afe_global_probe" self-trigger 0x20000 0x3f17f1b
```

Set the build/probe paths explicitly; use the matching dependencies and an
identified operating board. The probe is not an automatic hardware-free test.
Use the existing 78504f1 client with the installed 78504f1 server: the new strict
health client expects 16 checks and is intentionally not interchangeable.

Next: candidate deployment and full zero-BIAS Configure/alignment/40-channel
and RPC regression, complete runtime/pin/ONL handoff, then physical transitions
and full-stream/new-firmware qualification. Do not toggle SC-owned state merely
to make a diagnostic pass. See the [remaining objective](server-v05-completion-plan.md).
