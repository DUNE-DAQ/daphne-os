# Raw DMA diagnostics — point 3

This is an experimental, explicitly selected diagnostic. It receives the
firmware producer's deterministic pattern, **not AFE samples**. Physical
waveforms, finite channel jobs, DDR rings/credits and server/Ethernet delivery
belong to later points 4–7. Point 3 remains pending board qualification.

The existing spybuffer implementation, RPCs, clients, gateware modes, services
and defaults are preserved. `daphneServer` does not link the diagnostic library
and does not accept raw-dma as legacy `full-stream`. Its existing identity
admission rejects variant 3 before constructing `Daphne`/`SpyBuffer`. A matching
legacy gateware image is required for the spybuffer regression.

## Components and ownership

- [Kernel client](../daphne-server/kernel/daphne-dma-diag/daphne-dma-diag.c):
  producer control and coherent payload allocations through the Linux DMA API.
- [Local ABI](../daphne-server/kernel/daphne-dma-diag/daphne_dma_uapi.h):
  exclusive per-route file descriptors, PREPARE/START/STOP/ABORT, status,
  allocation address inspection and sequential read of completed data.
- [Reusable C++ library](../daphne-server/dma/capture.hpp): validation, multi-route
  orchestration, streaming pattern verification and a Linux backend.
- `daphne-dma-diag`: independent command-line tool emitting JSON Lines.
- [DTS preparation](../scripts/petalinux/prepare_raw_dma_dts.py) and opt-in
  PetaLinux kernel configuration/module recipe.

The Xilinx DMAengine provider owns all DMA register writes, hardware SG
descriptors and IRQs. The client exclusively requests a channel at PREPARE,
not probe/open. Its only writes are to the diagnostic producer. A read-only
DMA status monitor verifies stop/reset; it does not program the engine. Do not
bind a second provider or program the same DMA through userspace. The tool
does not use `/dev/mem` for registers, payloads or descriptors.

PREPARE validates configuration/build identity, resets through DMAengine,
reserves the aggregate memory budget and allocates **all** job buffers before
any START. Payload allocations use the provider's 40-bit DMA device and retain
the complete returned addresses. Coherent allocations on noncoherent HP ports
use the DMA API's appropriate CPU mapping; no `dma-coherent` DT claim is made.
DMA barriers delimit publication and consumption. There are no streaming
mappings to synchronize separately in this version.

Allocations contain 64-byte leading guards and at least 64 bytes of trailing
guard/page padding. SG entries describe only payload, aligned to 16 bytes.
Each packet is split into at most 64 segments of up to 4 MiB, below the 26-bit
descriptor limit. DMAengine manages its own 64-byte-aligned hardware descriptors.
Packet boundaries never share a segment. The default aggregate allocation
budget is 448 MiB (including guards/page padding), leaving room within the
512 MiB CMA pool. It is a ceiling, not an allocation guarantee; the allocator
may fail much earlier. `max_pool_mib` may be set to 1–480 at module loading for
allocation-failure testing. Jobs have at most 16,384 payload blocks and packets
of at most 256 MiB. These are diagnostic policy limits, not waveform limits.

CPU payload access is permitted only after a successful complete/drained job.
`read()` copies completed data after timing has ended; this version deliberately
has no userspace mmap or shared slots. Closing the descriptor terminates DMA
and frees its allocations, including on process death. Errors never expose
unqualified data as completed captures.

## Completion, STOP and recovery

One DMAengine transaction is posted per packet. A work item rearms the next
packet against already allocated payloads. This keeps IRQ coalescing at one
transaction and allows accurate per-packet callback result/residue checks on
STOP. Between packets the producer may experience Linux scheduling
backpressure; that cost is part of the measured throughput. This diagnostic
does not demonstrate a continuous AFE stream.

STOP writes producer command 2 and keeps supplying the current packet's
capacity until producer done and its DMA completion agree. If the first beat
of the next packet is already pending, that packet is supplied and drained.
STOP can therefore include another packet. The job timeout also bounds STOP.

Abort, timeout, failed transfers and close call `dmaengine_terminate_sync()`.
This path resets the DMA/producer with the expected Xilinx implementation.
Afterwards the client independently requires S2MM halted, RUN/RESET clear and
producer not busy. Some provider versions return success despite reset failure;
the return value alone is insufficient. If cessation cannot be proven, memory,
channel and module are quarantined until reboot. This deliberate retention must
be logged as a failure, not normal resource recovery. Never free potentially
active DMA memory to make an error test pass.

Terminal status preserves the completion/failure snapshot. For an ordinary
abort/error it includes pre-reset progress and register state; quarantine
reports the failed stop/reset state. A `route_failure` JSON record is emitted
before userspace cleanup can discard that evidence.

The selected kernel/provider must support callback results, accurate completed
residue, S2MM SG, high address words and synchronous termination/reset. Missing
result support causes a diagnostic failure. Audit the **actual** provider source
and record its commit/configuration before board qualification; the workstation
reference build is not that audit. See the
[DMAengine API](https://docs.kernel.org/driver-api/dmaengine/client.html) and
[Xilinx provider source](https://github.com/Xilinx/linux-xlnx/blob/master/drivers/dma/xilinx/xilinx_dma.c).

Keep the raw overlay and DMA provider loaded throughout each test session.
Do not switch/reprogram PL with an open diagnostic descriptor, including while
prepared. Use explicit operator-controlled installation/activation and close
all captures first. Compilation never installs, loads modules, switches
gateware, restarts services or accesses board registers.

## Build on DAPHNE or a matching Linux host

From the OS checkout, build the independent executable and hardware-free tests:

```sh
cmake -S daphne-server/dma -B build/dma-diag -DCMAKE_BUILD_TYPE=Release
cmake --build build/dma-diag --parallel 2
ctest --test-dir build/dma-diag --output-on-failure
build/dma-diag/daphne-dma-diag --help
```

This requires C++17, CMake and Linux UAPI headers, without Protobuf, ZeroMQ,
libi2c or the full server's AArch64/NEON dependency. The optional server build
flag `DAPHNE_BUILD_DMA_DIAG=ON` adds the separate target, default OFF; it does
not change acquisition selection. A full server build remains a separate
native AArch64 regression using the existing helper.

The module needs the **matching configured kernel build**, generated headers
and `Module.symvers`. A userspace developer image alone is insufficient:

```sh
uname -r
test -f /lib/modules/$(uname -r)/build/Module.symvers
make -C daphne-server/kernel/daphne-dma-diag \
  KDIR=/lib/modules/$(uname -r)/build
```

Use `KDIR=/path/to/matching/kernel/build` and the appropriate `ARCH=arm64`
and `CROSS_COMPILE=...` on a build host. Do not load the workstation x86 module
on DAPHNE. Platform-driver remove callbacks support the reference 6.8 API and
the newer 6.11+ form; other target differences must be fixed/tested against
its actual kernel rather than inferred from the PetaLinux version.

For a separate PetaLinux developer **test project**, refresh its private layer
and append the settings in
[raw-dma-test.conf.example](../petalinux/config/kr260/raw-dma-test.conf.example)
to that project's `build/conf/local.conf`. Supply a pinned source directory.
The optional recipe packages the module; it does not autoload it or install
the userspace executable. The extra `kernel-devsrc` package is optional and
needs additional rootfs space. BitBake/PetaLinux image builds remain untested
on this workstation and must be run on the matching build host.

Only `DAPHNE_ENABLE_RAW_DMA_DIAG=1` selects the DMA kernel fragment. It sets
a persistent 512 MiB CMA **kernel default**. An explicit existing `cma=` bootarg
overrides it: inspect `/proc/cmdline` and the source boot configuration for
the test project, retain every other bootarg and replace only that CMA value
with `cma=512M` if necessary. Check the final kernel `.config` and boot output;
do not infer CMA from the recipe. Production projects keep their defaults.

## Hardware handoff and DT

Consume bit/bin, XSA, normalized DTS/DTBO and checksum/identity manifest from
the **same real firmware build**. Request the normalized DTS as an additional
handoff input if it is absent. The hardware-only validation XSA is unsuitable
for deployment. Preserve the received artifacts unchanged.

The OS adds Linux client properties to the three existing producer nodes in
a **derived** raw overlay. It preserves all DMA provider register, clock and
IRQ properties and rejects a legacy or incomplete hardware description:

```sh
python3 scripts/petalinux/prepare_raw_dma_dts.py \
  /path/to/handoff/normalized-raw.dts build/raw-linux/raw-linux.dts
dtc -@ -I dts -O dtb -o build/raw-linux/raw-linux.dtbo \
  build/raw-linux/raw-linux.dts
sha256sum build/raw-linux/raw-linux.dtbo
```

The tool requires normalized numeric registers/IRQs and labeled local clocks
plus `&gic`; decompiled numeric fixups are deliberately rejected. It adds local
DMA labels if needed and `dmas = <&provider 1>` for S2MM. Do not load the derived
overlay on top of the original raw overlay: they describe the same providers.
Record both the original handoff and derived DTBO checksums, and the preparation
record emitted beside the DTS. This is an experimental activation path, outside
the frozen dual-gateware release packaging/selector. That selector still owns
only self-trigger/full-stream; do not add raw-dma as an alias or use its legacy
runtime service chain for this test.

See [the hardware contract](raw-dma-hardware-contract.md) before activation.
After explicit operator activation and loading the matching Xilinx/client
modules, `/dev/daphne-dma0` through `2` should appear with mode 0600.

## Diagnostic commands

The tool requires explicit acquisition selection and the manifest's expected
28-bit firmware build ID. The examples use a placeholder shell variable:

```sh
export DMA_BUILD_ID=0x01234567  # replace with the actual handoff identity
build/dma-diag/daphne-dma-diag
build/dma-diag/daphne-dma-diag --acquisition dma-diagnostic \
  --expected-build-id "$DMA_BUILD_ID" --routes 0,1,2 \
  --rates 5/8,5/8,5/16 --beats 1048576 --packets 4 --validate-only
```

The first command reports that spybuffer remains the default and **does not
open any DMA device**. It is not itself a spybuffer acquisition command.
`--validate-only` validates dimensions without allocation/hardware access.

On the board, explicitly run a selected route:

```sh
sudo build/dma-diag/daphne-dma-diag --acquisition dma-diagnostic \
  --expected-build-id "$DMA_BUILD_ID" --routes 0 --beats 1048576 \
  --packets 4 --seed 4294967280 --rates 5/8 --repeat 10 \
  > route0.jsonl 2> route0.stderr
```

Repeat with routes 1 and 2, then `--routes 0,1,2 --rates 5/8,5/8,5/16`.
Start times are sequential software writes, not synchronized AFE capture.
Each route reports all DMA allocation addresses, bytes completed, actual
producer counters, guards and verification. Combined throughput divides the
sum of received bytes by earliest START to latest completion. Timing includes
IRQ/work scheduling; payload reading/verification occurs afterwards.

Use `--stop-after-ms 1` for drained STOP or `--abort-after-ms 1` for intentional
abort, with an offered rate/job duration long enough to keep the job active.
An abort reports `verified:false` and is not successful capture qualification.
SIGINT/SIGTERM abort; SIGKILL exercises kernel close cleanup. Reopen/repeat
after every case. A configured kernel timeout is tested using a low offered
rate, small `--timeout-ms` and a large finite request. If a job has already
completed before a cancellation deadline, the result is ordinary completion;
inspect the state rather than assume the requested test occurred.

## Board qualification and evidence

Record the OS source commit/diff, compiler, kernel version/config/provider
source, loaded DT, firmware variant/build/capabilities, original/derived
checksums, `/proc/cmdline`, CMA total/free, allocation addresses, commands,
stdout/stderr and kernel logs. The JSON output is evidence, not an automatic
qualification decision. Use [the qualification template](raw-dma-qualification-template.json)
and keep logs next to it. On failure, retain `dmesg` as well as the failure JSON.

Required tests:

- Individual routes and all three concurrently, multiple seeds including wrap,
  packet sizes from one beat through multi-segment and >64 MiB packets,
  repeated complete data/guard/counter checks.
- Real returned addresses, including high words if the allocator supplies them.
  Above-4-GiB mock addresses are unit-test coverage only. Record uncovered
  address ranges; do not manufacture physical addresses.
- Small diagnostic budget / insufficient CMA, partial allocation, competing
  opens (`EBUSY`), STOP, timeout/error, abort/reset, process death and reopen.
  Compare sustained CMA/resource usage, check guard integrity and DMA cessation.
- Sustained individual/combined throughput with representative PS/Ethernet
  load. Offered fractions 5/8, 5/8 and 5/16 exercise 2+2+1 GB/s; only completed
  bytes/time measure throughput. Record gaps from packet rearming, duration,
  load, repeats, errors and margin; do not equate offered rate with DDR rate.
- Spybuffer regression under compatible legacy gateware, no DMA selection.

Stop after point 3. A missing handoff, target build, failed board test or
insufficient throughput leaves qualification pending and blocks functional
progress to points 5/7. See [local verification](raw-dma-local-verification.md).
