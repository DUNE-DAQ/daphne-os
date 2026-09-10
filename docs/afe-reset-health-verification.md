# AFE reset as an FPGA-health prerequisite

Server change **a01d95e**, client checks **4e74f10**. Server **4e74f10 is deployed
and live-qualified** on DAPHNE-015 with unchanged self-trigger
**3f17f1b / ABI 2.0** firmware and a 16-check RPC assessment. Complete runtime,
native loader, image pin **ecff25e** and 140 packaging/audit tests pass.
The refreshed ONL home/source/client handoff is verified; see below and the
[wiki instructions](https://github.com/DUNE-DAQ/daphne-os/wiki/DAPHNE-015-AFE-global-and-SC-ownership).

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

The native-phase probe deliberately did not collect the full status inputs: network,
temperature and applied-configuration checks remained UNKNOWN. These probes
alone did not qualify the RPC checklist. No physical reset was stimulated.
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
Use the matching 4e74f10 health client with the installed server. It expects
16 checks; the old 78504f1 health client expects 15 and is not interchangeable.

## Deployed regression and complete runtime

One-shot `daphne-deploy-4e74f10.service` completed successfully. The old process
exited before the executable was replaced. Normal runtime startup reloaded the
same installed FPGA, invalidating the previous process's applied-state record
as expected. No board reboot, library, partition, identity, network or time change.

Initial and final full zero-BIAS passes each completed **153 exchanges**:
both AFE orders, five-AFE alignment and all 40 usable spybuffer channels.
The existing Configure path issued its normal AFE reset pulse; no held-reset
fault was injected and the physical pin was not measured. The live health check
was verified in the released state afterward, not during the pulse.
Bookkeeping checked **48 observations**, 32 during Configure; maximum round trip
**282.021 ms**. Rejections preserved applied state, a rewrite of the existing
channel-0 offset invalidated it, and full Configure restored the reference hash.

All six inherited regression suites pass: v0.5 (17 exchanges), ADC (93, including
80 CRC-checked samples), SFP (5), regulator (7), FPGA health (4), and identity/link
reporting (5). The AFE, kernel/OS, clock and build clients pass three RPCs each;
timesync default/opt-in/default privacy passes five. Independent health checks
confirm `afe_reset_released=PASS` at its exact source observation time.
Final health: **12 PASS / 1 external-timing FAIL / 3 UNKNOWN**, not overall OK.

Final FE hash:
`c858989d7e847a98146c39ad50ec1f053c67acc78ea3c268d6a880341ad8d503`.
BIAS/BIASCTRL=0, offset=2200/x1, trim=0, VGAIN=1700, generator=1 and current
selectors=0/0. Existing bias-enable readback remains 1. These command/register
observations do not prove physical voltage or analog calibration. Final protected
file, boot, process and policy guards pass; no automatic restarts or error-level
journal entries were observed for this invocation. Private messages were not exported.

Live proof `live-abi20.PfrVGkis/qualification.json` SHA-256:
`ab11336bbc5ec59b582b4c7e8f5fcfa6113d6af23f44e2d91b7cb58b2fafac83`.
Complete runtime SHA-256:
`bc1b0d60179d7d116f5cedc39b784772505e7cf9a00f0c410a6a6927478824e6`.
Its 22 regular files and four aliases include the exact server, unchanged
qualified Hermes/protobuf/utf8/ZeroMQ dependencies and qualification evidence.
Native payload checks and loader/help pass with the private libraries resolved
inside the extracted bundle; OS libsystemd is not bundled or replaced.
Actual staging and all nine synthetic overlay-minor combinations pass.
The source version include remains fail-closed until an actual project stages
the matching runtime. This is not BitBake, a complete image build or new firmware.

## ONL home handoff

`$HOME/daphne015-server-runtime-4e74f10` on `np04-onl-004` holds 35 payload files
plus `SHA256SUMS` in owner-only storage. Server export base is 4e74f10; OS
integration base is 4c5273e, with an identical server subtree. Production/build
files match Git. Known private literals in legacy examples become placeholders;
one serialized seed request is omitted per export. These are modified exports,
not exact Git snapshots or a general secret-audit guarantee.

ONL's existing Python 3.9.16/protobuf 6.33.5/pyzmq 25.1.2 passed all five exported
clients: AFE, kernel/OS, clock and build (three RPCs each), and FPGA health (four).
One bookkeeping read confirmed the same process/boot and unchanged valid FE hash.
No packages were installed. All handoff and internal runtime payload hashes pass;
the previous 78504f1 payload and manifest were reverified unchanged.
Handoff manifest SHA-256:
`0923e685a297f45208f7519418768d12e8c8bb8655509d8d5bc4c6ec765dbd9d`.

Next: physical transitions
and full-stream/new-firmware qualification. Do not toggle SC-owned state merely
to make a diagnostic pass. See the [remaining objective](server-v05-completion-plan.md).
