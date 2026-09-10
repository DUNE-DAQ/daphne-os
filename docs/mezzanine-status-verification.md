# Mezzanine status: coherent cache connected to server and client

Server **79f6e5d is deployed and live-tested** on DAPHNE-015. Server `97831dc` connects
the [cache driver](mezzanine-monitoring-cache.md); client `79f6e5d` validates and
renders its response. Image pin **cb8958c** and the verified **46-file ONL handoff**
now contain this exact server. No mezzanines are fitted. SC-owned BiasEnable
remains 1; BIAS and BIASCTRL remain zero. Firmware was not reloaded.

## Response contract

| Data | Meaning and availability |
| --- | --- |
| Original fields 4–11 | TCA output requests and six V/mA/mW readings; present only with GOOD quality and success |
| Original alert fields 12/13 | Optional historical software latches, not current voltage/power |
| Quality, start/end/cache times, last-good, attempt | Complete sequential acquisition; monotonic process/host time, not UTC or simultaneous ADC conversions |
| Driver state | Explicit software access selection and programming history, not physical population |
| `active_configuration_verified` | GOOD cycle's checked configuration/calibration/limit/status/direction words match requested settings; not physical protection/metrology proof |
| Alert histories | Last actual Mask/Enable observation and raw word; retained timestamp is never refreshed by a status RPC |

Original field numbers/types are preserved; fields 4–13 now have explicit
presence, so valid zero/false is distinguishable from missing. Legacy clients
must honor `success=false`. New clients reject legacy-unqualified responses.
The server status handler takes one cache snapshot and performs **no bus I/O**.

Background monitoring now publishes complete per-block cycles instead of ten
independent atomics. Failed/partial/invalid samples suppress numbers and power
claims; samples older than five seconds are stale. Control attempts invalidate
before mutation. Calibration mismatch cannot leave cached current scaling valid.
Alert evidence survives failed protective writes and numerical failure. Existing
alert-driven removal is retained; no new shutdown on generic I/O/configuration errors.
Runtime configuration is invalidated when an alert is observed, without claiming
that removing requests necessarily succeeded.

The CLI validates presence, state, timestamps, flags, units/sign and consistency
before printing values. Unavailable/rejected/legacy responses exit nonzero.
Request duration conservatively increases sample age. GUI logic blanks invalid
measurements/requests, labels alerts as history, avoids re-plotting one cached
sample, expires local displays and preserves pending control choices. Qt timers
are not hard-real-time; the existing synchronous request path can block the UI.
Actual Qt visual/event-loop testing remains open—Qt is not installed on this host.

## Native qualification

Clean source `79f6e5d94ea23260a624d3b8b752d15ea475bda8`, server subtree
`27c600141e529177e8bc7a1f7a080688a1c88de4`:

- **34 host and 34 actual Kria C++ suites**, including 33 fake-bus driver cases
  and executed protobuf mapping/presence/failure tests.
- **240 Python tests per independently generated binding set**, no skips:
  wire faults, actual CLI against a private localhost responder, no fallback
  writes, timeout and GUI methods executed with recording widgets.
- Complete ARM build, native metadata probe and candidate `--help`; no installed
  service replacement. Two independent binding sets verify the native proof.
- Native tests ran from private RAM. Before/after board guards are identical:
  same installed fb82e0a process, boot, firmware/runtime/Hermes, protected settings,
  enable1 and selectors0/0. No Configure, real mezzanine I2C, network/time/SC write,
  service restart or FPGA load was issued by this phase.

Candidate binary SHA-256:
`4d1b9ed74e895fac1fdf6688c6e26d66da09380d498e32c39ef73c7e105efbaa`.
Native proof SHA-256:
`ecdf3fee9824c290dd923dcb1eb1e964aeb9674c75becf4c601b49d6b2a2f104`.
Evidence: `server-v05-fixes-20260909/mezzanine-status.9rUhbWps`.
The first focused Python attempt lacked generated bindings; after generating
them, focused and full runs pass. The failed setup log is retained.

Source guards verify actual handler/monitor wiring but do not execute the full
hardware-constructing Daphne handler. Native fake-bus tests do not establish real
mezzanine identity, measurements, alert circuitry, latency or physical power.

## Live qualification

The exact native-tested executable replaced fb82e0a through the previously
qualified, administrator-only `--job-mode=ignore-requirements` stop/start of
`daphne.service`. Normal stop hooks and firmware admission stayed enabled.
Eight guard snapshots preserved firmware/runtime/Hermes, boot, protected CERN
settings, SC enable1 and ADC selectors0/0. Only the server invocation changed;
the prior executable remains in private RAM. No rollback or deployment retry.
An ordinary service restart is not equivalent: it can propagate to the firmware.

- No-mezzanine checks before Configure and after the full regression each pass
  **24 exchanges**: all five status/calibration pairs, typed invalid status-block
  rejections and ten actual CLI calls. Every valid block reports unavailable,
  with no fabricated measurements, requests, alert history or driver state.
  The CLI returns exit 2. Process/build/boot/configuration evidence and SC enable
  bracket each read-only run. This tests the configured absence policy, not
  physical population detection; no mezzanine bus access is enabled.
- Initial and final aggregate runs each pass **158 exchanges**, both AFE orders,
  alignment, fresh AFE registers and all 40 spybuffer channels. Configure and
  capture preserve enable1; normal AFE reset pulses remain. Equal samples are
  not a physical glitch or reset-pin test.
- Bookkeeping passes **48 observations, 32 during Configure**, maximum **288.6 ms**.
  Rejected requests retain evidence; the existing offset rewrite invalidates it;
  full Configure restores the same FE v2 hash.
- ADC supplies **80 CRC-checked raw samples**, not calibrated current. Existing
  platform/temperature, SFP, regulator, identity and FPGA-health regressions pass,
  plus five build/host/clock/privacy clients. Health remains **12 PASS / 1 external
  timing FAIL / 3 UNKNOWN**, not an overall healthy-board verdict.

The first no-mezzanine verifier incorrectly required an idle executor during its
own system-status read. It stopped after that one read. The corrected verifier
requires its exact read type/task/message IDs; six fault-test cases pass. The
failed result and original verifier are retained. No server change was needed.

Live evidence: `mezzanine-status.9rUhbWps/live-abi20.n3FkGAaa`, with **83 sealed
files**, including maintenance scripts, response payloads, captures and checks.
Live `qualification.json` SHA-256:
`4a6a4606a5c341d074721b3da3e278b35b9efb812b0e241db0b32161d2446d25`.
Final policy: BIAS/BIASCTRL0, offset2200/x1, trim0, VGAIN1700, enable1, selectors0/0.
Final FE hash: `a7c843ddbb3014bc15e5bcb26d528899078b98a6948f034c6c5e487733404bea`.

## Operator read-only command

Use matching generated bindings and an approved local SSH forward:

```bash
DAPHNE_BUILD_DIR="$BUILD_DIR" python daphne-server/client/hdmezz_control_v2.py \
  read-status --ip 127.0.0.1 --port 19876 --afe 0
```

Set `BUILD_DIR` explicitly. This command never enables/configures a block. With
the no-mezzanine startup policy, expect typed unavailable, no measurements and
exit 2—not zero readings and not a reason to enable nonexistent hardware.

## Runtime and ONL handoff

The exact deployed executable and unchanged Hermes/Protobuf/UTF-8/ZeroMQ bytes
are packaged together. Native Kria loader/help checks resolve bundled libraries
inside the archive and retain OS libsystemd 255.21. Hermes was not executed.
All **142 packaging tests** and actual staging pass; the old fb82e0a runtime is
rejected without replacing staged files. The fail-closed unstaged sentinel is
retained. This is not a BitBake/image build or firmware qualification.

On `np04-onl-004`:

```bash
cd "$HOME/daphne015-server-runtime-79f6e5d"
sha256sum --check --strict SHA256SUMS
```

Owner-only directory: **46 payload files plus SHA256SUMS**, verified remotely.
Runtime SHA-256: `efdb5159075852e31f2ef333e64f8a20071534bef876466713fdd0b027f39c1c`.
Manifest SHA-256: `060fb8484a47870f6955e61e25d47a41f433b99bff16b18c95db4226dd1cf32e`.
Six exported clients pass **42 read-only exchanges**, including all five
no-mezzanine blocks and actual CLI calls. Before/after bookkeeping matches the
qualified process, boot and FE hash. Existing ONL Python 3.9.16/protobuf 6.33.5/
pyzmq 25.1.2 were used; nothing installed. See the bundle README for commands.

Server source export base 79f6e5d and OS integration base cb8958c differ only in
the already reviewed server documentation page. Production/build sources and
schemas are unchanged; uncommitted work is excluded. Known MAC/IP examples are
placeholders and one serialized request is omitted per export. File-by-file Git
comparisons and all 13 changed Python/shell examples per export pass. Modified
exports are not exact Git snapshots or a general secret audit.

Packaging evidence: `mezzanine-status.9rUhbWps/runtime-handoff.C31Gb0ID`.
Board guards preserve the server process, SC state, firmware/runtime/Hermes and
protected settings. No Configure, service restart, FPGA load or network/time
write occurred during packaging. Earlier fb82e0a and 4e74f10 handoff hashes are
unchanged. Populated-hardware and
metrology, firmware/full-stream, missing authoritative assignments and other
v0.5 producer gaps remain in the [completion plan](server-v05-completion-plan.md).
