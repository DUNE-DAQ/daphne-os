# Timesync service: implemented and live-qualified

**Deployed as `702155b`.** Collector `dcd6bc6`, client/checker `702155b`.
DAPHNE-015 retains firmware `3f17f1b`, self-trigger ABI 2.0. Native/live regression,
complete runtime loader checks and matching image pin `d54f967` pass.
No clock correction or NTP service/configuration change was performed.
The refreshed ONL home/source/client handoff and wiki publication are complete;
see the verified handoff record below.

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
Neither mode requires or proves synchronized UTC. The previous `eecff61` lacks
these fields; the newly deployed `702155b` passes this verifier.

## Source and standalone ARM evidence

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

## Live deployment and runtime

Only the stopped server executable was replaced. The normal runtime restart
reloaded the same installed FPGA; full zero-BIAS Configure preceded alignment
and captures. MAC/IP, DHCP, SSH, identity files, libraries and NTP settings were
preserved. The previous executable remains in RAM; no image backup, partition
change or cleanup was performed.

- Both AFE orders pass aggregate BIAS/BIASCTRL zero, five-AFE alignment, fresh
  register reads and all 40 spybuffer channels. The complete test passes again
  after the other checks. Canonical FE hash remains
  `c858989d7e847a98146c39ad50ec1f053c67acc78ea3c268d6a880341ad8d503`.
- Bookkeeping is responsive on all 48 maintenance observations, including 32
  during Configure; rejection and direct-write invalidation checks pass.
  Maximum measured round trip: 289 ms. No automatic server restarts.
- All six existing suites pass: v0.5/register telemetry, 80 physical-channel
  ADC acquisitions, six-route SFP collection, regulators, FPGA health and
  identity/management-link reporting. These do not establish analog calibration.
- Live clock CLI and default/opt-in/default timesync requests pass with matching
  source/schema and stable configuration/process identity. Private peer values
  remain only in memory, never in evidence output. The service still reports
  zero processed NTP packets; offset and age remain unavailable, kernel unsynced.
- Complete runtime archive loads all three private dependencies from its own
  extracted payload and `libsystemd` from the existing OS. Packaged `--help`
  passes on the actual ARM board without starting another hardware server.
- Matching image pin, all 127 packaging tests and actual archive staging pass,
  including the recipe's decisions for nine synthetic overlay-minor pairs.
  This is not a BitBake or complete image-build qualification.

Runtime archive SHA-256:
`b2b05463c2944d4c94dd6e77accdd47c192cbbff575e8adbac80d57adb1099bd`.
Live qualification SHA-256:
`63bacb2563d6d245a14618c40b199acac7b7fe412f3db2127933d32a18f5b8a3`.
Evidence: `timesync.16nLdZFs/live-abi20.y1YrFtvK`; complete local payload under
`timesync.16nLdZFs/runtime-702155b`. Native runtime test files remain in
`/tmp/daphne-runtime-702155b.XXfrhkz0`. The native smoke did not change services.

Command-error evidence is retained: journal reading required sudo; a mistyped
verifier filename was corrected. The metadata CLI's successful two-read default
was followed by its explicit three-read system-status comparison. No server
guard or hardware test was weakened for these command corrections.

Health remains **11 PASS / 1 external-timing FAIL / 3 UNKNOWN**, not overall OK.
Approved time-source identity and fresh physical NTP samples remain unverified; no time or network
configuration change is implied. New firmware, full-stream, Hermes delivery,
analog metrology and full-image qualification remain separate gates.

## Verified ONL handoff and wiki

On `np04-onl-004`:

```bash
cd "$HOME/daphne015-server-runtime-702155b"
sha256sum --check --strict SHA256SUMS
```

All **26 payload files** match locally and on ONL; directory mode 0700 and
file modes 0600 are verified. Manifest SHA-256:
`870e72b423283f5c74b4d66e3313031a328d6a41ce2afb6d89193f15fd206a78`.
The runtime archive is unchanged from native/live qualification.

Server source export base is `702155b`; OS integration export base `7c51383`
includes the image pin and library dependency. Only the prerequisite README
differs inside their server subtrees. File-by-file comparison verifies all
unlisted content against its own Git base: 1,214 server / 1,382 OS regular files
unchanged, 19 / 22 text files with known MAC/IP placeholders, and one serialized
seed request omitted per export. All 13 changed Python/shell examples per export
pass syntax checks. The manifests describe every change; this is not an exact
Git snapshot, signed source, or a general secret-audit guarantee.

Matching generated bindings and the exported clock client pass imports and the
actual three-request read-only RPC check from ONL, using its existing Python
3.9.16, protobuf 6.33.5 and pyzmq 25.1.2. No packages were installed. This is
an additional ONL check, not a rerun there of all 185 workstation Python tests.
Before/after board guards match services, PIDs, boot, protected files and
generator/current-selector policy. No private peer details were requested or
recorded. The service still reports unsynchronized/no processed NTP sample.

Local evidence: `timesync.16nLdZFs/onl-handoff-check.json`. The handoff includes
`onl-clock-client.json` and `source-export-audit.json`; the ONL client test
directory is retained at `$HOME/.daphne-client-check.aveffcWr`. Older handoffs remain
unchanged. Exported docs retain their snapshot date; the adjacent README records
the completed handoff without making the source archive self-referential.

Wiki commit `6ca5868` is published and its remote Git revision verified:
[clock explanation](https://github.com/DUNE-DAQ/daphne-os/wiki/DAPHNE-015-host-clock-and-timesync),
[runtime location](https://github.com/DUNE-DAQ/daphne-os/wiki/DAPHNE-015-qualified-server-runtime)
and [updated build commands](https://github.com/DUNE-DAQ/daphne-os/wiki/Building-daphne-server-and-clients).
All six edited pages pass local-link and shell-example syntax checks; no build
example was executed as a wiki-validation step. The OS development branch itself
was not pushed; only privacy-filtered sources were copied to ONL.
