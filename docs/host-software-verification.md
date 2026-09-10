# Kernel and OS release observations

Collector `710e336` adds `SystemStatusSnapshot.host_software`, field **31**.
Candidate `75972de` now passes clean host and native ARM qualification, but is
**not yet installed**. DAPHNE-015 still runs
server `702155b`; its runtime/image pin and ONL handoff remain unchanged.

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

After a separately qualified server installation, use matching source/bindings
and the approved SSH forward:

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

Remaining: guarded deployment/live RPC/full regression, runtime assembly/pin/
ONL/wiki handoff. Full-stream, new firmware and full-image
qualification remain distinct; the broader 251-row semantic audit is not closed.
