# Raw DMA diagnostic — first board bring-up

Historical activation failure and recovery context. The later
[2026-10-12 qualification report](raw-dma-persistent-physical-results-2026-10-12.md)
records the working deployment and physical results; the pending statements
below describe the 2026-10-09 session.

Date: 2026-10-09. Evidence supplied by the operator from DAPHNE10 and its
PetaLinux build host. No direct board access was available to the OS agent.
Status: target compilation passed; overlay activation caused a reported
complete board lock-up. DMA acquisition and board qualification remain pending.

## Software and hardware inputs

- OS implementation: `aa1b7a0`; kernel compatibility correction: `00916bd`
  (omit `.llseek`). Operator reports successful rebuilding after the correction.
- Firmware handoff: `output-2ca8afd-raw-dma`, build identity `0x02ca8afd`.
- Board kernel and kernel-build-artifacts release:
  `6.18.10-xilinx-g4f7afe14f724`.
- Userspace compiler: GNU C++ 13.4.0 on the board.
- Module cross compiler: `aarch64-amd-linux-gcc`, from the matching Linux
  recipe's native sysroot; module build completed with `W=1`.
- Kernel configuration: `CONFIG_MODULES=y`, `CONFIG_XILINX_DMA=y`,
  `CONFIG_CMA=y`, `CONFIG_DMA_CMA=y`.
- Boot command line contains `cma=512M`; reported `CmaTotal=524288 kB`,
  `CmaFree=515080 kB` before activation.

## Completed checks

The standalone executable compiled on DAPHNE10 and both CTest tests passed.
The operator reported successful ARM64 architecture and matching vermagic
checks for the module. All firmware `SHA256SUMS` entries passed. The real
XSA passed the existing firmware validator for all three DMA paths.

The normalized `pl.dtsi` passed OS preparation and both derived DTBOs compiled.
Warnings concerned DMA child unit names without `reg`, the legacy SPI bus
name and unused address/size cells in the FPGA-region fragment. These builds
do not establish runtime hardware accessibility.

| Artifact | SHA-256 |
| --- | --- |
| Original normalized `pl.dtsi` | `75b1a937b0bc8fdac9b34aba692e853a58710e7075ca38f4e86727cb22b8200d` |
| Prepared `raw-linux.dts` | `e7416de2ec36ee9639eba310d44b585ba8edd506bbf93515dfeb9f5744658dae` |
| Prepared `raw-linux.dtbo` | `b4bb7f714b299cbf9fbdf0970d7a5e764753aebcbbb9a67df846c3124c567d99` |
| App DTBO with renamed `firmware-name` | `5e93f0bd765ef13780318ebf224483a0b5067b03f1b7013351d5f5f4f27fd5d6` |

## Activation failure

The separate application `daphne_rawdma_diag_2ca8afd` was installed, retaining
the existing applications. Its DTBO references `daphne_rawdma_diag_2ca8afd.bin`.
The transferred DTBO hash matched on the board.

The runtime target and firmware, server, Hermes, endpoint and clockchip services
were confirmed inactive. `xmutil listapps` showed all applications unloaded.
The attempted command chained `xmutil loadapp`, an operating-state check and
`insmod` using `&&`. Completion of the latter two steps was not confirmed.
No acquisition command was issued.

The last supplied kernel messages were:

```text
[ 2722.050886] irq-xilinx: /axi/interrupt-controller@9c010000: num_irq=32, edge=0x2
[ 2722.084848] xilinx-vdma b0020000.dma: Please ensure that IP supports buffer length > 23 bits
```

The operator subsequently confirmed a complete board lock-up and no available
reset method. Earlier MACB link messages at 226–229 seconds precede this
activation; they do not demonstrate a coincident Ethernet link failure.
Overlay property-leak warnings and an earlier interrupt-controller reference
imbalance were also present; their causal relationship remains unestablished.

The actual DTS excerpt specifies `clocking2` at 199998001 Hz, using
`zynqmp_clk 73`. The region-level reset list contains 116/117, but the `afi0`
node contains 116/117/118/119. Consequently, adding reset 118 to the region
alone is not an established fix.

## Remaining diagnosis and recovery

The last message places the failure during the first Xilinx DMA provider's
probe. Failure to complete an AXI register access is a hypothesis, not a
confirmed cause. Examine the exact deployed provider and AFI/fabric-clock
drivers, HPM1 accessibility, clock/reset state and boot PS initialization
against the real raw XSA. No speculative DT/reset changes were made.

Board testing awaits operator recovery. Retain this failed activation as
qualification evidence; do not repeat the same load or probe inaccessible
DMA registers before a revised diagnostic procedure is ready. Spybuffer
regression, DMA data verification, resource recovery and throughput remain
untested in this board session.
