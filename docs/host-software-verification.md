# Kernel and OS release observations

Collector `710e336` adds `SystemStatusSnapshot.host_software`, field **31**.
This is a source-tested candidate, **not yet installed**. DAPHNE-015 still runs
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

Initial worktree build: **32 host C++ suites** and the full AArch64 server build
pass. Twelve new Python tests pass, including the actual CLI against a local
synthetic server. Tests cover precedence, no merging, missing/invalid fields,
UTF-8/escaping, size limits, clock failures, protobuf presence, stale samples,
restart/correlation/schema rejection, and suppression of unrelated private
response data. These are software checks, not deployed RPC qualification.

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

Remaining: clean-source/native ARM checks, guarded live RPC/full regression,
runtime assembly/pin/ONL/wiki handoff. Full-stream, new firmware and full-image
qualification remain distinct; the broader 251-row semantic audit is not closed.
