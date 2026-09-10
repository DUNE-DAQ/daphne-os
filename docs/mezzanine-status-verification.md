# Mezzanine status: coherent cache connected to server and client

Candidate **79f6e5d is native-tested, not deployed**. Server `97831dc` connects
the [cache driver](mezzanine-monitoring-cache.md); client `79f6e5d` validates and
renders its response. DAPHNE-015, its image pin and ONL runtime remain **fb82e0a**.
No mezzanines are fitted. SC-owned BiasEnable and BIASCTRL are unchanged.

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

## What passed

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

## Operator command after qualified deployment

Use matching generated bindings and an approved local SSH forward:

```bash
DAPHNE_BUILD_DIR="$BUILD_DIR" python daphne-server/client/hdmezz_control_v2.py \
  read-status --ip 127.0.0.1 --port 19876 --afe 0
```

Set `BUILD_DIR` explicitly. This command never enables/configures a block. With
the no-mezzanine startup policy, expect typed unavailable, no measurements and
exit 2—not zero readings and not a reason to enable nonexistent hardware.

Next: qualify the candidate's live no-mezzanine response and full SC-preserving
server-only regression, then package the exact runtime and matching client for
ONL. No deployment/runtime-pin advance has happened. Populated-hardware and
metrology, firmware/full-stream, missing authoritative assignments and other
v0.5 producer gaps remain in the [completion plan](server-v05-completion-plan.md).
