# Protocol-error firmware: implemented source, not deployed

2026-09-10. This closes the missing **firmware source-to-PS path**, not the whole
workbook I281 requirement. The [typed server/client reader](protocol-error-server-verification.md)
is now source-tested and cross-built; ABI 2.2 OS integration and real FPGA
qualification still need work. No board, bias, network or service changes
were made during this step.

## Small commits

Both firmware repositories use isolated branch `fix/timing-protocol-diagnostics`.

| Variant | Parser-to-PS implementation | ABI 2.2 / CDC / producer packaging |
| --- | --- | --- |
| Self-trigger | `cc18e78` | `c5a8477` |
| Full-stream | `25c5798` | `3e39194` |

Timestamp-only ABI 2.1 branches remain at `83a868a` / `0d3072b`.
They were not rebased or modified.

## Meaning and interface

The existing receive parser produces one event when it enters ERRS from
ASYNC/SYNC. A 32-bit counter retains episodes across parser recovery; it
saturates and separately records overflow and accumulated reasons. It is not a
count of physical bit errors, control-transaction failures or TX/network errors.

The event/reasons/reset state now pass through the actual endpoint wrappers to
`ep_axi`. A separate 40-bit coherent mailbox exports count, five reasons,
saturated/overflowed and parser-reset observation. Only common AXI/platform
reset clears history; there is no software clear or observed reset epoch.

ABI 2.2 declares the PS feature at timing offsets 0x30–0x48:
identity, read-to-capture request, sequence, status, count, detail and timeout.
The feature ID is `0x50450100`. Failed attempts erase old shadow data and
carry timeout/busy status. Late replies drain without becoming new samples.
Timestamp readiness is not required for valid parser **history**.
The firmware's `docs/protocol-error-diagnostics.md` defines bit meanings,
concurrency and the complete transaction. Never probe old ABI aliases.

The optical 0x76 placeholder remains separate. Workbook I277's configurable
command decoder is still unimplemented.

## Verification scope

| Check | Self-trigger | Full-stream |
| --- | --- | --- |
| Counter/parser/parser-to-AXI GHDL runs | 8 pass | 8 pass |
| Existing timestamp CDC/AXI GHDL runs | 8 pass | 8 pass |
| Actual PDTS core elaboration | Pass | Pass |
| Existing FuseSoC RTL smoke suites | 11 pass | 4 pass |
| Timing/binding/identity/packaging Python tests | 36 pass | 50 pass |
| Tcl constraint model cases (included above) | 17 pass | 17 pass |

Both register-map and Markdown checks pass. Self-trigger's three timing-boundary
shell contracts and 63 mirrored PetaLinux regression tests also pass.
Those 63 tests retain old ABI 2.0/2.1 staging coverage; they do **not** prove
ABI 2.2 OS staging. Producer fixtures use synthetic FPGA artifacts.
Full-stream ABI 2.2 packaging/checking uses real device-tree/archive/hash tools
with mocked SDTGen. Source wiring tests are not complete CDR/PLL simulation.

Every one of the 170 held-data destination bits is required by the routed gate;
the new 40-bit path cannot be hidden by existing broad clock exceptions.
The producer requires exact per-ABI report populations and hashes: 130 for
2.1, 170 for 2.2. These model tests do not prove real Vivado bindings or timing.
The inherited sync-length reason is still not exercised as a first parser
failure; only the standalone counter fixture covers its accumulation.

Evidence: `completion-VEpMKkGG/firmware-health.W1CUQ3E7/protocol-axi.LzlwrhED`.
Final protocol/timestamp/timing logs supersede initial attempts. The initial
full-stream archive test correctly exposed an omitted ABI 2.2 report rule;
that rule was fixed and all 50 tests passed. A wrong full-stream smoke CLI
attempt was followed by its correct four-suite run.

## Still required

1. Native ARM execution and live qualification of the now-implemented typed
   server/client history and exact ABI 2.2 admission. Software fixtures do not
   prove new register behavior on hardware.
2. ABI 2.2 OS report validation and compatible, qualified server/runtime/image
   pairing. Do not manually widen a profile to bypass admission.
3. Supported-tool synthesis/routing, actual CDC checks, both variants/timing
   sources and live zero-bias regression. The latest Cooper route probe timed
   out at the FNAL bridge; **no job was launched**.
4. Keep broader health gaps explicit: current calibration, unavailable installed
   SFP routes/link mapping, authoritative timing/management-MAC assignments,
   Hermes delivery and external reset/epoch evidence.

No live readout of the new registers, overall-healthy verdict or completed
workbook coverage is claimed.
