# Timesync service: source and standalone ARM qualification

**Not deployed.** Collector `dcd6bc6`, client/checker `702155b`.
DAPHNE-015 still runs server `eecff61`, firmware `3f17f1b`, self-trigger ABI 2.0.
No clock correction, NTP configuration change or service restart was performed.

## What the fields mean

`SystemStatusSnapshot.host_time.timesync` adds read-only timesyncd evidence to
the [local clock and kernel observations](host-clock-verification.md).
Independent bookkeeping is unchanged. This is not a UTC-accuracy verdict.

| Workbook item | New evidence | Still not established |
| --- | --- | --- |
| I098 `Host.NtpSynchronized` | Successful local service observation, processed-response counter and separately reported kernel synchronization state | Synchronization to an **approved** source; service availability alone does not prove it |
| I099 `Host.NtpOffsetMilliseconds` | Historical four-timestamp offset in signed nanoseconds; divide by 1,000,000 for milliseconds | A fresh offset from an approved source; no sample means unavailable, not zero |
| I100 `Host.TimeSource` | Selected server name/address, each with explicit presence and private-detail opt-in | Selected peer need not be the origin of the retained historical sample |

The daemon retains processed responses, including ignored spikes and responses
whose clock-adjustment attempt failed. The `ignored_spike` flag is preserved;
false does not prove successful adjustment. Counter integers never pass through
floating point. Reference IDs and unrelated server lists are not exported.
See the [systemd v255 service properties](https://raw.githubusercontent.com/systemd/systemd/v255/src/timesync/timesyncd-bus.c)
and [sample retention behavior](https://raw.githubusercontent.com/systemd/systemd/v255/src/timesync/timesyncd-manager.c).

The first historical sample has **unknown age**. When its counter increases
between non-overlapping reads with the same bus/owner/selected peer, the prior
query start gives a conservative monotonic age bound. An unchanged sample does
not become fresh just because it was queried again. Owner/peer changes,
counter regression, inconsistent data and query failures discard that bound.
No age is derived by subtracting a pre-adjustment wall timestamp from the
corrected wall clock. GOOD sample quality means valid decoded history only.

## Read-only and privacy boundaries

The collector uses `libsystemd` on the fixed local system-bus socket. Its four
application requests read bus ID, service owner, that owner's properties, and
owner again. Reply identity must match. Service auto-start and interactive
authorization are disabled; there are no time-setting or remote NTP requests.
An unavailable service is reported without starting it.

Each method wait is at most 500 ms within a two-second acquisition deadline.
Selected strings, property count and typed values are bounded/validated. These
are not hard limits on all memory allocated inside D-Bus or OS scheduling.
Clients reject successful observations older than five seconds.

`ReadSystemStatusRequest.include_time_source_details=true` explicitly requests
the private selected name/address. The default omits both. This switch is not
authorization: preserve the existing restricted transport. The verification
CLI never requests or prints peer addresses, service free text or bus IDs.

## Build and check

Server/protocol-test builds now require Linux `libsystemd` headers and the
**target-architecture** library. Python clients do not. On a Debian-like Linux
build host, add `libsystemd-dev` to the existing prerequisites; do not install
workstation libraries onto the board. For a cross build, add these options to
the [existing build commands](https://github.com/DUNE-DAQ/daphne-os/wiki/Building-daphne-server-and-clients):

```bash
cmake -S "$SERVER_SOURCE" -B "$ARM_BUILD" \
  -DDAPHNE_SYSTEMD_INCLUDE_DIR="$SYSTEMD_HEADERS" \
  -DDAPHNE_SYSTEMD_LIBRARY="$SYSTEMD_TARGET_LIB/libsystemd.so.0" \
  -DCMAKE_INSTALL_RPATH=/usr/lib/daphne-server \
  -DCMAKE_BUILD_WITH_INSTALL_RPATH=ON \
  -DCMAKE_EXE_LINKER_FLAGS="-Wl,-rpath-link,$ARM_DEPS/target/lib:$SYSTEMD_TARGET_LIB:$SYSTEMD_EXTRA_LIB"
# Continue only after successful configuration.
cmake --build "$ARM_BUILD" -j4
```

`SYSTEMD_HEADERS` contains `systemd/sd-bus.h`; the two target library directories
also provide transitive link dependencies when using this extracted-dependency
layout. A matching PetaLinux SDK can supply these instead. The image recipe
declares the `systemd` provider and `libsystemd` runtime package; OE splits this
library dynamically. The existing image manifest names its installed package
`libsystemd0` 255.21. This does not mean a new image has been built.
[OE package split](https://raw.githubusercontent.com/openembedded/openembedded-core/scarthgap/meta/recipes-core/systemd/systemd_255.22.bb).

The standalone `timesync_probe` reads only local clocks and the local service,
needs no root privilege and does not access the FPGA. After a separately
qualified server deployment, verify the RPC through the approved SSH tunnel:

```bash
python daphne-server/scripts/verify_host_clock.py \
  --endpoint tcp://127.0.0.1:19876 \
  --proto-dir "$MATCHING_PROTO_DIR" \
  --server-source "$SERVER_SOURCE" \
  --expected-server-commit "$EXPECTED_FULL_COMMIT" \
  --require-timesync-service
```

Omit the final option to accept correctly reported service unavailability.
Neither mode requires or proves synchronized UTC. Installed `eecff61` lacks
these fields and is expected to fail this new verifier.

## Evidence and remaining gates

Clean candidate source `702155b8068823118fd7dbecd2f4a982ec031785`, server subtree
`78625e81be99c8eee4c826bc682226d40745b426`:

- **31 host C++ suites, 31 actual ARM suites and 185 Python tests per binding
  set pass.** Private socket-pair tests exercise actual sd-bus messages,
  read-only flags, timeout, owner change, malformed/duplicate/missing values,
  oversized selected data and default/opt-in privacy. They do not contact NTP.
- Native candidate loader/help and both clock/service probes pass on the board.
  It loads the existing `/usr/lib/libsystemd.so.0.38.0`, not a bundled replacement.
  Cross-link inputs used 252.39 headers/library; this exact 255.21 native run
  checks that combination, not arbitrary distro compatibility.
- Actual timesync service queries are GOOD, selected name/address are present
  but redacted, processed packet count is **0**, sample/offset/age unavailable.
  Kernel remains `TIME_ERROR=5`, `STA_UNSYNC=64`; reported wall date is May 2025,
  not this September 2026 qualification date.
- Before/after guards match boot, server/Hermes/timesyncd instances, PIDs,
  restart counts, executables/libraries, protected network/SSH/firmware/identity
  files and timesync configuration. The existing FE configuration was untouched.
- **127 OS packaging tests pass**, including the new recipe-source dependency
  assertion. These are not BitBake parsing, package resolution or image tests.

Candidate SHA-256:
`065cbd159a5391588e33a02cfa6ac33ae5e06deb1cd8e0eaa579ce01377b7476`.
Timesync probe SHA-256:
`f0c8c7078c68af4028a4129dab5ca80dafc001781da48caf47cd5d536a964a56`.
Native proof SHA-256:
`de2d5339cb8823e6139a9f404a369c5d38dedb502b866d24a1cc65d4abaaef80`.

Evidence: `server-v05-fixes-20260909/timesync.16nLdZFs`, especially
`native-audit-{host,arm}-bindings.json`. Owner-only native test payload:
`/tmp/daphne-timesync-native.XXCeQymN`. It is not a deploy bundle.

Next: candidate live RPC/zero-BIAS regression, complete runtime and image pin,
ONL handoff/wiki update. Approved time-source identity and fresh physical NTP
samples remain unverified; no time or network configuration change is implied.
New firmware, full-stream and full-image qualification remain separate gates.
