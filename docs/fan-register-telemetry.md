# Fan register telemetry

Server **a23e5a9 is deployed and live-tested on DAPHNE-015**, adding read-only
fan reporting. Server-only maintenance preserved firmware/runtime/Hermes,
approved CERN settings and SC BiasEnable=1. See the [v0.6 checkpoint](releases/v0.6/README.md).

## What is reported

`SystemStatusSnapshot.fans` contains `fan0` and `fan1`. A single admitted
acquisition reads the common command, both tach words, then the command again.
Matching FPGA identity and programming-state observations bracket those reads.

| Workbook field | Producer | Limit |
| --- | --- | --- |
| I250 PwmCommand | `pwm_command`, raw words before/after | Shared 8-bit applied register, not measured duty |
| I251 TachometerRaw | `tachometer_raw` | Unmodified register word; inspect quality |
| I257 LastUpdate | Host monotonic acquisition start/end | Partial: **no FPGA sample timestamp** |
| I249 / I252–I256 | Presence / RPM / running / stall / count / control mode | Remain unavailable; no invented physical observation or policy |

GOOD qualifies register reporting, **not fan health or the age of the last FPGA
measurement window**. Decoded pulse count is `raw >> 7`; `tach_at_counter_limit`
means 31 pulses or more, not proven saturation. Zero does not prove an absent or
stopped fan. Raw words survive errors as unqualified evidence; decoded values
are removed. Acquisitions over 100 ms are stale. The independent client rejects
host observations older than five seconds, contradictory shared records and
unknown profiles. Neither time limit establishes physical sample freshness.

Existing protobuf field numbers/types 1–8 are preserved. Fields 2–5 now have
explicit presence: unknown is absent, not `false` or zero. New fields 9–24 carry
quality, raw/decoded register evidence and explicit unknown physical status.
Old clients cannot distinguish absent scalar values: use the matching decoder.

## Firmware and schematic evidence

- Deployed self-trigger `3f17f1b`: `ip_repo/daphne_ip/rtl/config/{stuff,fanmon}.vhd`.
  Matching full-stream source: `3e39194`, `ip_repo/daphne3_ip/rtl/config/`.
  ABI 2.0/2.1/2.2 source profiles have the same fan register semantics; other
  profiles are rejected before mapping. Source agreement is not routed or
  full-stream hardware qualification.
- Addresses: command `0x94000000`, fan0 `0x94000004`, fan1 `0x94000008`.
  The read-only mapping exposes 12 bytes; the adjacent BiasEnable word is not
  accessible through that mapping's read API.
- The default window is 23,437,500 AXI cycles. The design requests approximately
  100 MHz PL0 and connects it to STUFF AXI in both variants. Firmware assumes
  two pulses/revolution and exports a five-bit saturating count shifted left
  seven bits. Nominal conversion is 128 RPM/count, maximum code 3968.
  Installed fan identity/pulses per revolution and physical timing remain
  unqualified; `tach_rpm` is deliberately absent.
- Carrier drawing **177020 rev 0**, dated **2026-05-22**, sheet **11**:
  J13/J4 have separate tach signals and share FPWM through Q2. It recommends
  **Noctua NF-A8 5V PWM**, not proof of the installed population. PDF SHA-256:
  `d9750668c02f5af5024301bf820f3e248858cd4ffd93af05db637a2165b78794`.
- Two RTL caveats need separate simulation/firmware review: a tach edge on the
  window-publication cycle is discarded by the `if/elsif` priority; steady
  PWM endpoints are not exact off/full. The source produces one high cycle
  per 4096 for command zero and `16*command` high cycles for commands 1–255
  before/after the two inversions. Do not turn `code/255` into measured duty
  or change PWM to diagnose either issue.

## Verification and next checks

Clean builds: **35 host and 35 actual ARM C++ suites** and **246 Python tests
per independently generated binding** pass, including six fan Python tests.
The C++ fan suite exercises all 49,152 mode/ABI/PWM/tach combinations, plus
reserved bits, capped counts, read/clock failures, shared-command changes,
wire presence, acquisition limits and no-write assertions. Status integration
tests cover lazy admission, invalidation, snapshot reuse and malformed pairs.
These are software tests, not a physical fan experiment.

Two native read-only fan probes and six deployed fan RPC exchanges pass.
Both channels reported changing capped counts (17/18 pulses), with command
255; this is not calibrated RPM. The 158-exchange zero-BIAS/BIASCTRL test
passed both AFE orders, all five alignments and all 40 channels. Six collector
regressions, bookkeeping during Configure, five metadata clients and the
24-exchange no-mezzanine RPC/CLI test pass. The 16-check health report remains
12 PASS / one external-timing FAIL / three UNKNOWN; no overall-health claim.

The first final-check wrapper lacked its client-scripts import path; the
corrected wrapper passed without a server change. Both results are retained.
Exact evidence is in [deployment.json](releases/v0.6/deployment.json). No PWM
command, SC-enable command, firmware reload or network/time change was made.

After building the candidate, the explicit standalone probe is:

```bash
sudo ./fan_register_probe self-trigger 0x20000 0x03f17f1b
```

Run it only against the matching admitted image, with programming/identity and
protected board-state checks. It does not instantiate or restart the server.
To verify the eventual deployed RPC producer with the matching build/source:

```bash
python3 daphne-server/scripts/verify_fan_status.py \
  --endpoint "$DAPHNE_ENDPOINT" --proto-dir "$DAPHNE_PROTO_DIR" \
  --server-source "$DAPHNE_SERVER_SOURCE" \
  --expected-server-commit "$DAPHNE_SERVER_COMMIT" \
  --expected-build-id 0x03f17f1b --expected-abi 0x20000 --mode self-trigger
```

The endpoint and source/build paths are supplied locally; no private network
values are embedded. Success verifies three read-only RPC exchanges and a
stable server process/boot/configuration record, **not a healthy fan**.
