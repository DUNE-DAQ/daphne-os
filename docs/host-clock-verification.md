# Host clock: source and standalone ARM qualification

**Not deployed.** Server collector `d143c0d`, client/checker `ebf3988`.
DAPHNE-015 still runs `eecff61` with firmware `3f17f1b` / self-trigger ABI 2.0.
The complete runtime archive, image pin and ONL home handoff are unchanged.
The follow-up [timesync service collector](timesync-verification.md), candidate
`702155b`, now passes clean builds and standalone ARM service checks. This page
retains the earlier host-clock qualification's exact source and evidence.

## What is reported

Additive `SystemStatusSnapshot.host_time` (field 30) contains two independently
qualified observations. The ordinary system-status request collects them;
independent bookkeeping remains free of new system calls or subprocesses.

| Workbook field | Observation | Qualification boundary |
| --- | --- | --- |
| I086 `Host.CurrentUtc` | ISO-8601 UTC representation, nine fractional digits | Board wall clock, not verified UTC |
| I087 `Host.UnixTimeNs` | Signed Unix nanoseconds from the same `CLOCK_REALTIME` sample | No separate reads or rounding through floating point |
| I090 `Host.BootTime` | Bracketed realtime midpoint minus `CLOCK_BOOTTIME` | Estimate including suspended time, not a persisted boot event; changes when wall time is corrected |
| I098 synchronization evidence | Kernel `adjtimex` return state and raw status bits | Supporting observation, not proof of a current accepted NTP exchange or a complete timesync-service contract |
| I099/I100 peer offset/time source | Added separately in the [timesync candidate](timesync-verification.md), not deployed | Historical sample and selected peer, not verified current offset from an approved source; kernel adjustment offset is not substituted |

Legacy `ps_local_time` and `ps_local_unix_ns` are aliases of that exact clock
observation. Each new group carries quality, fixed source and monotonic
start/completion times; failed groups contain no value or success timestamp.
Zero and false retain presence. A valid unsynchronized reading has GOOD
measurement quality with `reports_synchronized=false`.

The collector rejects unsupported ranges, negative wall time, overflow,
non-normalized nanoseconds, observed backward/large forward wall-clock steps,
invalid monotonic brackets and collections longer than 250 ms. Wall/boot values
are one group: an invalid derived boot estimate invalidates that group. Samples
span at most the monotonic interval plus a 1 ms discontinuity tolerance; this
is not a clock-accuracy bound, and small/compensating steps can evade detection.
Clients separately reject readings older than five seconds.

Kernel offset units follow `STA_NANO`; maximum/estimated error units are always
microseconds and are converted without overflow. These are kernel discipline
parameters, not fresh peer measurements or certified error bounds.
[Linux adjtimex contract](https://man7.org/linux/man-pages/man2/adjtimex.2.html).
The boot estimate uses suspend-inclusive `CLOCK_BOOTTIME`, not process uptime
or suspend-exclusive monotonic time.
[Linux clock definitions](https://man7.org/linux/man-pages/man2/clock_gettime.2.html).

No time-setting, service activation, file/network access or FPGA access is added
by this collector. Its single `adjtimex` request has every field initialized to
zero, including `modes`; a syscall-seam test checks the actual argument fields.
This does not change the other existing collectors in a system-status request.

## Tests and actual board observations

Clean source: `ebf3988e6a7331bd10c4b9deee0e522a0bb22a5f`.
Server subtree: `d1fc4acb5327ddaadaa24a295067c585b32ab61d`.

- All **29 host C++ suites** and **174 Python tests with each binding set** pass.
  New cases cover UTC conversion, epoch/maximum signed range, leap-day formatting,
  overflow, clock discontinuities, source errors, explicit false/zero, kernel
  units/states, privacy, wire round-trips and the actual CLI on synthetic ZMQ.
- Clean full AArch64 build passes. The exact **29 ARM unit executables**, two
  build-metadata samples, candidate `--help` and two read-only host-clock probe
  executions pass on DAPHNE-015. Independent parsing with both binding sets
  checks the recorded native results and binary/source hashes.
- The board samples report **2025-05-30**, kernel `TIME_ERROR=5`, `STA_UNSYNC=64`
  and `reports_synchronized=false`. This is unverified board time, not the date
  of this September 2026 qualification. A separate read-only service query found
  timesyncd active but `NTPSynchronized=no`. The clock was **not corrected**.
- Before/after guards match server/Hermes executables, private libraries,
  protected network/SSH/firmware and identity files, boot, service instances,
  PIDs and zero automatic restarts. No server deployment or FE configuration was
  performed; existing zero-BIAS settings were not touched.

Candidate binary SHA-256:
`33ec51de8f0697bad973d0dab672df9db95d9872f46fbff958848d4e7af77de0`.
Clock probe SHA-256:
`44389783938055f5ca96004099c5ad9a3b51f81af9107639a1a27f391b8d2434`.
Native proof SHA-256:
`37a6bfef5ce7b21792ebcada21d9a34f662e6be35ff4c74e6096be17d5eec857`.

Evidence: `server-v05-fixes-20260909/host-clock.vpYfqden`, including
`native-audit-{host,arm}-bindings.json`. Owner-only board test files remain in
`/tmp/daphne-clock-native.XXMmFhvk`; this is a test payload, not a deploy bundle.
Initial failure logs are retained: the capability-count test needed its new
entry; one build was attempted before CMake finished; the first ARM link lacked
the dependency `-rpath-link`, and a retry overlapped reconfiguration. A fresh
build after terminal configuration completion passed. No server-source change
or guard relaxation was needed for those build-command errors.

## Commands

Build using the [server/client build guide](https://github.com/DUNE-DAQ/daphne-os/wiki/Building-daphne-server-and-clients).
For this existing cross-build dependency layout retain both runtime-path flags
and the link-time dependency search path:

```bash
cmake -S "$SERVER_SOURCE" -B "$ARM_BUILD" \
  -DCMAKE_INSTALL_RPATH=/usr/lib/daphne-server \
  -DCMAKE_BUILD_WITH_INSTALL_RPATH=ON \
  -DCMAKE_EXE_LINKER_FLAGS="-Wl,-rpath-link,$ARM_DEPS/target/lib"
# Wait for successful configuration before starting the build.
cmake --build "$ARM_BUILD" -j4
```

The standalone `host_clock_probe` only reads OS clock state and requires no
root privilege. It exits zero for successful reporting, including unsynchronized
state. To verify the RPC **after a separately qualified deployment**:

```bash
python daphne-server/scripts/verify_host_clock.py \
  --endpoint tcp://127.0.0.1:19876 \
  --proto-dir "$MATCHING_PROTO_DIR" \
  --server-source "$SERVER_SOURCE" \
  --expected-server-commit "$EXPECTED_FULL_COMMIT"
```

Use the approved SSH transport. The CLI performs one bookkeeping read followed
by two default system-status reads, checks source/schema and stable process/boot
identity, and only prints whitelisted clock data. The deployed `eecff61` does
not have this field and is expected to fail that new check. Candidate RPC/live
regression, complete runtime/pin/ONL handoff and new-firmware/full-stream/image
qualification remain pending. The timesync follow-up supplies service/history
observations, but approved-source and fresh physical NTP evidence remain open.
