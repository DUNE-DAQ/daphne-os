# Kernel and OS release observations

Collector `710e336` adds `SystemStatusSnapshot.host_software`, field **31**.
**Deployed server `75972de`** passes clean host/native ARM checks and live
self-trigger ABI 2.0 regression on DAPHNE-015. Complete runtime/native loader
and matching image pin `95e418d` pass. The refreshed ONL home/source/client
handoff and wiki publication are complete; the previous `702155b` handoff is unchanged.

## What is covered

| v0.5 row | Observation | Limit |
| --- | --- | --- |
| I091, KernelRelease | `uname:release` with quality and acquisition times | Running kernel label, not binary authentication |
| I092, OperatingSystemVersion | Separate `PRETTY_NAME`, `ID`, `VERSION_ID` | OS vendor metadata; not server or firmware version |
| I093, RootFilesystemBuildId (partial) | Optional `BUILD_ID`, `IMAGE_ID`, `IMAGE_VERSION` | Base/image labels only; no current installed-file manifest or rootfs integrity proof |

The [os-release specification](https://raw.githubusercontent.com/systemd/systemd/main/man/os-release.xml)
defines `BUILD_ID` as the original installation base; incremental changes need
not update it. The currently observed CERN release file supplies no `BUILD_ID`.
Do not use the server commit, PetaLinux release string or a freshly computed
hash of that text file as a substitute for a qualified rootfs build identity.

I094–I097 (active slot, boot marked good, reset reason and watchdog health)
remain separate gaps. The current deployment has no qualified A/B corruption
recovery contract; these fields are not inferred from service activity.

## Read and wire contract

Seven typed entries have optional text, individual quality, selected source,
monotonic acquisition brackets and unverified host-wall observation times.
Missing or empty optional labels are UNAVAILABLE, never fabricated defaults.
Malformed values and failed reads do not retain previous successful values.
Legacy `kernel_release` and `petalinux_version` mirror the exact successful
typed samples; failures leave those aliases empty.

The reader uses `uname` and `/etc/os-release`, falling back to
`/usr/lib/os-release` only when the first file is missing. It never merges the
two files. Normal release-file symlinks work; inputs must resolve to regular
files. Reads are limited to 16 KiB, each selected value to 256 UTF-8 bytes;
control characters and malformed quoting/encoding are rejected. Last duplicate
assignment wins as specified. Strings are decoded without expansion or shell
execution. Unknown keys, URLs and comments are not exported.

All OS fields come from one read; fstat metadata brackets detect ordinary file
changes during that read. This is not an atomic snapshot across the kernel and
release file, a hard syscall deadline, or protection from privileged tampering.
No network, clock, boot, EEPROM, power, I2C, SPI or FPGA changes are performed.

## Verification and commands

Clean source `75972de44150fb164886522ea79592a2cc638a1e`, server subtree
`0f19aab5c8d66ca779f8cd4e1048193127e60818`: **32 host C++ suites**, the full
AArch64 server build, and **197 Python tests with each independently generated
binding set** pass. The twelve new Python tests include the actual CLI against
a local synthetic server. Tests cover precedence, no merging, missing/invalid fields,
UTF-8/escaping, size limits, clock failures, protobuf presence, stale samples,
restart/correlation/schema rejection, and suppression of unrelated private
response data. These are software checks, not deployed RPC qualification.

All **32 exact clean-build ARM suite binaries** also pass on DAPHNE-015. The
candidate loader/help and two compiled build-metadata samples match the source,
tree and both schema hashes. Two actual `host_software_probe` reads report:

- Kernel `6.18.10-xilinx-g4f7afe14f724`.
- OS `petalinux`, version `2026.1-release-s06060014`, with its PetaLinux display name.
- `BUILD_ID`, `IMAGE_ID` and `IMAGE_VERSION`: UNAVAILABLE, not substituted.

Both workstation binding sets independently decode/audit the native proof and
produce identical reports. Inherited read-only clock/timesync probes pass too;
the board remains unsynchronized, with no processed NTP samples.

Before/after native guards match service PIDs/invocations, boot, exact installed
server/libraries, protected network/SSH/identity files, release file and time
configuration. A final FPGA/generator/current-selector read-only guard passes.
No server restart, package installation, hardware configuration or clock update.

Evidence: `host-software.MSil6c4w/native-qualification.json`, its two binding
audits, clean build/test logs and `post-native-board-guard.json`. Native staging
is `/tmp/daphne-host-software.XXRg0hm1` on the board, not an ONL runtime bundle.

| Exact artifact | SHA-256 |
| --- | --- |
| Candidate server | `f557d4e1da72f391f8ec4a423787895ff25a80baa56966c64894059c3c58823c` |
| Host-software probe | `a83884b7d3b802c390599778271efddf2c0e6ee0059dadbd73f624eacb24dd06` |
| Native proof | `006ac4dfed2b8386c5b55a41f6238643e07316453863cfa0c449fdc6d3406339` |
| Test-only archive | `6ea860d9cfb6e11f17354940f6e09e3fced27c0bf1b29b58cee42c5723f26ec6` |

The archive contains 40 regular files: software tests, explicit metadata probes,
candidate/help and qualification helpers. It is not a deploy image or complete
runtime. A copied guard UUID typo was caught locally before transfer; the
superseded local archive is retained as `native-tests.pre-guard-fix.tgz` and was
not sent to the board. The corrected guard retains the exact known boot identity;
no qualification check was relaxed.

The explicit `host_software_probe` reads only local kernel/release metadata;
it is not registered as an automatic hardware test. With a matching ARM build:

```bash
./host_software_tests
LD_LIBRARY_PATH=/usr/lib/daphne-server ./host_software_probe
```

With deployed `75972de`, use matching source/bindings and the approved SSH forward:

```bash
python3 daphne-server/scripts/verify_host_software.py \
  --endpoint tcp://127.0.0.1:44015 \
  --proto-dir /path/to/arm-build/srcs/protobuf \
  --server-source /path/to/daphne-server \
  --expected-server-commit "$SERVER_COMMIT"
```

The client makes one bookkeeping and two ordinary status requests, verifies
source/schema, process/boot continuity, fresh observations and legacy aliases.
It requires valid kernel/OS identification, but permits absent optional image
labels. It prints only selected metadata; no private identity/time-source
opt-ins. Exit zero means reporting verified, not boot health or rootfs integrity.

## Deployed live regression and runtime

Exact native-qualified server bytes replaced `/usr/bin/daphneServer` only after
the previous process exited. The normal runtime restart reloads the same FPGA
application (`3f17f1b`, self-trigger ABI 2.0). No new bitstream/OS image, library,
network, time, identity or partition changes. The previous executable is retained
in RAM under `/run/daphne-candidate-75972de/previous-server`; no recovery image
was created. Deployment one-shot `daphne-deploy-75972de.service` exited successfully.

The first post-start RPC check confirms the new source/schema, unchanged boot
and firmware, zero BIAS command caches, and deliberately invalid applied-config
evidence. Full zero-BIAS configuration precedes alignment or capture.

Verified on the installed server:

- Initial and final full aggregate passes: **153 exchanges each**, both AFE
  orders, all five alignments and all 40 usable spybuffer channels per order.
- Bookkeeping: 48 metadata-checked observations, 32 during Configure;
  maximum round trip **267.223 ms**. Rejected requests preserve applied state;
  a direct rewrite of the existing channel-0 offset invalidates it correctly.
- v0.5 status/rejections/AFE readback: 17 exchanges; ADC: 93 exchanges including
  80 CRC-checked physical-channel reads; SFP: 5; regulator: 7; FPGA health: 4;
  private identity/link reporting: 5.
- Actual kernel/OS client: 3 exchanges, matching native metadata and explicit
  unavailable build/image labels. Clock: 3; compiled build metadata: 3;
  timesync default/opt-in/default privacy: 5. No private peer values recorded.
- Before/after protected-file guards pass; no automatic restart. The new
  service invocation has no error-or-higher journal entries. Journal messages
  were counted privately, not exported.

Final FE hash:
`c858989d7e847a98146c39ad50ec1f053c67acc78ea3c268d6a880341ad8d503`.
BIAS/BIASCTRL commands remain zero, offset 2200/x1, trim 0, VGAIN 1700,
generator 1, current selectors 0/0. These are qualified command/configuration
observations, not a physical zero-voltage or metrology guarantee.
Health remains **11 PASS / 1 external-timing FAIL / 3 UNKNOWN**.

Live proof `host-software.MSil6c4w/live-abi20.3d4sWbOW/qualification.json` SHA-256:
`f3ce607148425dd54534b00f8aa171e9808ab3d492e86fa8b93210b964b2c30d`.
The complete `runtime-75972de/daphne-server-runtime-minimal.tgz` SHA-256 is
`2c2c8c39310f838fc93ee7b129204ec1f32272fdc35b12ed76d1ccea78e16e72`.
Its 15 regular members and four library aliases include the exact server,
unchanged qualified Hermes/protobuf/utf8/ZeroMQ dependencies and redacted
qualification records. OS-provided libsystemd remains unchanged/unbundled.

The extracted runtime passes native loader/`--help` smoke at
`/tmp/daphne-runtime-75972de.XXmEtUsj`; all three private dependencies resolve
inside the extracted bundle. Final live and post-runtime board guards match.
Image pin `95e418d`, **128 packaging tests**, actual archive staging and all nine
synthetic overlay-minor decisions pass. The unstaged version-include sentinel
remains fail-closed until a real project stages the matching runtime. These
checks are not BitBake, a full-image build, routed firmware or full-stream tests.

Approved rootfs identity, missing database assignments, hardware/metrology evidence,
new firmware, full-stream and full-image qualification remain separate gaps;
the broader 251-row semantic audit is not closed.

## Verified ONL source/client handoff

On `np04-onl-004`:

```bash
cd "$HOME/daphne015-server-runtime-75972de"
sha256sum --check --strict SHA256SUMS
```

All **30 payload files**, the extracted runtime's internal payload manifest and
owner-only modes (directory 0700, files 0600) pass on ONL. Manifest SHA-256:
`9e330b487124094311ee621222900bce6e46294b5dd66221ec7dee918d5bbce3`.
The runtime is the same native/live-qualified archive, not rebuilt. The prior
`702155b` handoff's manifest and all payload hashes also still pass.

Server source export base `75972de` and OS integration base `2dc221e` have
identical server subtrees. All unlisted files compare byte-for-byte against
their respective Git bases. Known private MAC/IPv4 literals in legacy examples,
scripts and docs are replaced in 19 server/22 OS text files; one serialized
seed request is omitted per archive. Thirteen changed Python/shell examples
per export pass syntax checks. Production/build sources and schemas are unchanged;
uncommitted work is excluded. These are modified exports, not exact Git snapshots
or a general secret-audit guarantee. No private assignment artifact is bundled.

ONL's existing Python 3.9.16, protobuf 6.33.5 and pyzmq 25.1.2 pass imports and
all three exported clients: kernel/OS, clock and compiled build metadata,
three read-only exchanges each. One additional bookkeeping request checks the
same qualified process/boot and valid unchanged applied FE hash. The final
read-only board guard matches the deployed qualification guard, including
protected files, PIDs/invocations, boot and generator/current selectors.
No packages, server restart, network/time/identity changes or hardware writes.
Optional image labels remain unavailable; kernel/time-service reports remain
unsynchronized with no processed NTP samples. This does not rerun all 197 Python
tests on ONL or provide a new physical analog qualification.

Evidence: `host-software.MSil6c4w/onl-handoff-check.txt`,
`post-onl-client-board-guard.json`, and the handoff's `source-export-audit.json`
and `onl-*-client.json` files. The extracted client is retained under
`$HOME/.daphne-client-75972de.Hsi9K4Fn` on ONL. The bundle README describes the
completed handoff; exported historical notes precede this documentation update.

Wiki commit `f97ab5f` is published and its remote Git revision verified:
[kernel/OS explanation and commands](https://github.com/DUNE-DAQ/daphne-os/wiki/DAPHNE-015-kernel-and-OS-metadata),
[runtime location and hashes](https://github.com/DUNE-DAQ/daphne-os/wiki/DAPHNE-015-qualified-server-runtime),
and [build instructions](https://github.com/DUNE-DAQ/daphne-os/wiki/Building-daphne-server-and-clients).
Seven edited pages pass 40 local-link and 13 shell-example syntax checks;
examples are not executed by that wiki check. The OS development branch itself
was not pushed; only privacy-filtered source exports were copied to ONL.
