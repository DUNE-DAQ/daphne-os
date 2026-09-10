# Host resource observations

Source `a9cac7d`, client/compatibility checks `3556811`, probe serialization
`b4e50b8`. **Not deployed yet**;
DAPHNE-015 and the qualified image-runtime pin remain at `13bc725`.

The v0.5 workbook SHA-256 is
`7c58f7f469523b7dd69ff3836f43d1a59bffdae49e2925bb328ac182122d8fd8`.
All 251 Server Platform rows × 30 displayed columns were compared directly
with the exported CSV and match. That verifies the audit input, **not full
implementation of those rows**. This patch addresses:

| Workbook ID / Excel row | Export in `SystemStatusSnapshot.host_resources` |
| --- | --- |
| I088 / 58 | Host uptime, seconds; not server-process uptime |
| I101 / 71 | One-minute load average; not CPU utilization percent |
| I102 / 72 | Linux `MemAvailable` estimate, converted from kB to bytes |
| I103 / 73 | Root free bytes, including reserved space |
| Additional disambiguation | Root bytes available to unprivileged processes |
| I104 / 74 | Root `ST_RDONLY` mount state, without inferring whether it is unexpected |

The source semantics follow the [Linux proc documentation](https://docs.kernel.org/filesystems/proc.html)
and [Linux statvfs manual](https://man7.org/linux/man-pages/man3/statvfs.3.html).
Available memory is not `MemFree`; free and unprivileged-available filesystem
space use `f_bfree` and `f_bavail`, respectively, multiplied by `f_frsize`.

## Contract and limits

Six typed records in additive field **28**, with value presence, units, source,
quality and monotonic acquisition/completion times. Host wall time is explicitly
unverified. Root measurements share one `statvfs` call; separate proc files are
not a simultaneous snapshot. GOOD means a valid observation, not sufficient
memory/disk capacity or overall server/FPGA health.

The collector reads only `/proc/uptime`, `/proc/loadavg`, `/proc/meminfo` and
`statvfs("/")`, with bounded input sizes and no cached fallback. Missing sources
or `MemAvailable` are unavailable. Malformed/overflowing data, failed reads or
invalid acquisition clocks are errors; no value or successful observation time
is supplied. Zero and `false` remain genuine present values when read correctly.
No subprocess, hardware access, network configuration, mount change, threshold
or protection action is introduced. Byte limits are not a hard syscall deadline.

`HostResources` is appended to the capability list, preserving prior ordering.
Old field numbers and request IDs remain unchanged. The independent Python
validator checks identities/types/units, presence, clock ordering, a five-second
QA freshness limit and shared-root observation consistency.

## Checks

All **25 native C++ suites** and **109 tracked Python tests** pass. Fixtures cover
zero values, missing/invalid inputs, unit/byte overflow, clock reversal, root
consistency and protobuf round trips. An older capability-list test initially
failed after insertion; the final implementation appends the new entry and the
complete suite passes. The clean ARM server at `3556811` builds, and all 25
hardware-free suites plus candidate `--help` pass on DAPHNE-015. All 109 Python
tests also pass against the ARM build's generated bindings.

The first standalone probe collected valid native measurements, but its
`DebugString` output was unsuitable for parsing with Protobuf 30. Probe-only
commit `b4e50b8` uses explicit TextFormat serialization of its non-private host
metrics. It was rebuilt and run twice on the board; independent Python checks
accept all six fields and advancing acquisition times. This follows the
[Protobuf diagnostic-format guidance](https://protobuf.dev/programming-guides/deserialize-debug/),
without stripping or parsing the debug-only prefix.

The last probe observed approximately 3.28 GiB available RAM, load average 0.13,
and root free/available space of 40,101,888 / 23,751,680 bytes (about 38 / 23 MiB).
The root filesystem was writable. This is a sampled capacity observation, not
a calibrated alarm threshold. No cleanup, resizing or mount change was made.
Service instances/PIDs/restarts, installed binaries/libraries, boot, private
identity and protected settings matched before/after both qualification stages.

Evidence under `firmware-health.W1CUQ3E7/host-resources.SKeWnt4N`:
`arm-onboard-checks.txt`, `native-readable-probe-guards.txt` and
`native-readable-probe-verification.json`. The latter SHA-256 is
`08fb7519f92c36d35bb20fce41985e926955aef042804860f3541eba046acca5`.
The uninstalled server candidate SHA-256 is
`727b9187ec239f65d7e93740553be89acba606ef11a8a67ff2f068b8c64fa993`.

The board probes execute the actual collector, **not the running server's RPC
handler**. Deployment, live RPC regression and updating the qualified runtime
bundle/source pin remain pending. The current `13bc725` service was not restarted.

Once a matching server is deployed, add `--require-host-resources` to
`verify_server_v05.py` with the intended endpoint and exact firmware build ID.
That option adds only status reads and checks advancing acquisition times.
It must fail against the current `13bc725` server; do not treat optional empty
results as qualification of the new fields.
