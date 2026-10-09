# Raw DMA point 3 — workstation verification

Date: 2026-10-09. OS base: `0f7f1c6` on `codex/afe0-synthetic-config`, plus
the working-tree DMA diagnostic changes. Status: **implemented, pending target
build and board qualification**. No firmware source changes, board connection,
module loading, overlay activation, deployment or service changes occurred.

Firmware contract references are recorded in
[raw-dma-hardware-contract.md](raw-dma-hardware-contract.md). No deployable
handoff identity or board kernel is qualified by this record.
The companion source checkout inspected was `2ca8afd` on
`test/dma_ethernet_aquisition`.

## Passed without hardware

| Check | Environment | Result |
| --- | --- | --- |
| Standalone C++ executable/library build | Ubuntu 24.04 WSL, GCC/G++ 13.3.0, Debug | PASS |
| DMA unit suite + selection omitted | CTest, `build/dma-unit` | 2/2 PASS |
| Kernel module compile/modpost/link, W=1 | Extracted Ubuntu x86 headers `6.8.0-101-generic` | PASS |
| Existing server Python unit suite | Windows Python 3.12/Conda | 72/72 PASS |
| Existing gateware admission C++ test, including raw rejection | WSL G++ 13.3.0 | PASS |
| Existing spybuffer readout-inhibit guard C++ test | WSL G++ 13.3.0 | PASS |
| PetaLinux regression suite including new DTS tests | WSL, LF copies under `build/dma-linux-regression-lf` | 75/75 PASS |
| DTS tests after comment-preservation fix | WSL, including `dtc -@` | 8/8 PASS |
| Derived DT overlay compilation | Fixture, WSL `dtc -@` | PASS |
| CLI three-route `--validate-only` | WSL, no device opened | PASS |

DMA tests exercise the driver's shared configuration/geometry validator,
4-KiB/64-KiB page and guard accounting, excessive/zero sizes, invalid rates and
build IDs, route conflicts, all preparations before any START, allocation/start
failure cleanup through the backend abstraction, short/corrupt data, all four
pattern words, seed wrap, fragmented reads, guard failures, drained STOP,
intentional abort, signal cancellation and kernel-error propagation.
Omitted selection never invokes the backend factory. Above-4-GiB addresses in
these tests are **mock metadata**, not a hardware allocator result.

The 75-test suite ran before the final added comment-preservation regression;
the complete eight-test DTS subset passed again after that focused change.

The reference module build used downloaded header packages extracted under
`build/`, without system installation or module loading. It produced `.ko`
and passed modpost. The compiler identification differs in package suffix from
the reference kernel compiler, and BTF was skipped because its `vmlinux` is
absent. This is a compile/API check only, not an AArch64/PetaLinux or hardware
test. The exact board kernel, its Xilinx provider implementation and generated
DT still need verification.

The Windows sandbox initially blocked Python temporary directories. The same
72-test suite passed outside that restriction. Existing checkout scripts use
CRLF; Linux regressions were run against a copy with LF executable scripts,
without changing the originals. Tests used temporary fixtures, not a real
PetaLinux project or board services.

## Reproduction

On a Linux checkout:

```sh
cmake -S daphne-server/dma -B build/dma-unit -DCMAKE_BUILD_TYPE=Debug
cmake --build build/dma-unit --parallel 2
ctest --test-dir build/dma-unit --output-on-failure
python3 -m unittest discover -s tests/petalinux -p 'test_*.py'
python3 -m unittest discover -s daphne-server/tests -p 'test_*.py'
python3 scripts/check_documentation.py
git diff --check
```

For full server/AArch64 regressions, use the existing native build helper on
DAPHNE. For the diagnostic module use a matching configured kernel build,
not the workstation reference `.ko`.

## Still pending

- Matching PetaLinux/BitBake image and AArch64 executable/module builds.
- Matching real raw firmware bit/bin/XSA/DTS/DTBO and checksums/identity.
- Final kernel configuration, bootargs/CMA persistence and loaded DT checks.
- Actual allocation/memory ownership, cache correctness, descriptor high words,
  IRQ/error/timeout/reset handling, STOP boundary behavior and process-death
  cleanup in the kernel on DAPHNE.
- Sustained individual and simultaneous DDR integrity/throughput with load,
  allocation failures, repeated reopen, memory/resource leaks and guards.
- Spybuffer acquisition regression on compatible legacy gateware.

The mock/backend lifecycle tests cannot prove the real driver's teardown under
DMA activity. Record the board tests with
[the qualification template](raw-dma-qualification-template.json) and the
[runbook](raw-dma-diagnostics.md). Points 5 and 7 remain unimplemented and
blocked by the qualification dependencies in the firmware series.
