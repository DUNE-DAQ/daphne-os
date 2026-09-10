# FPGA health: evidence, not a green service light

## Contract

Additive system-status fields 25/26 expose programming observations and a named
checklist. Scope: **externally timed acquisition prerequisites**. A local-clock
bench can be functional while deliberately failing that requirement.

Each check is PASS, FAIL or UNKNOWN. Any FAIL gives NOT_READY; otherwise any
missing/stale evidence gives UNKNOWN. No run permit, interlock, reset, reload,
network change or power action follows from this assessment. Receipt times use
the board's monotonic clock; the maximum age is five seconds. They are not
hardware-latched timestamps or verified UTC.

The checklist covers kernel programming, configuration error/startup flags,
fabric/timing locks, timing resets, admitted image identity, external endpoint
readiness, complete executed FE configuration evidence, PL die temperature, and
management interface/baseline observations. Three requirements remain UNKNOWN:
live timestamp progress, Hermes data-path operation, and external reset epoch.
SFP diagnostics or successful oneshot services cannot satisfy those requirements.
Thus current ABI-2 cannot earn an overall OBSERVED_OK result.

## Why two different Linux statuses matter

At board kernel `6.18.10-xilinx-g4f7afe14f724`, the manager's `state` exposes cached
programming state. Its class-level `status` is empty because this driver supplies
no manager status callback. Empty is **not** a measured zero-error result.
[Kernel manager source](https://github.com/Xilinx/linux-xlnx/blob/4f7afe14f724/drivers/fpga/fpga-mgr.c).

The separate platform-device `device/status` requests configuration STAT through
PM firmware. The collector selects one ZynqMP manager by compatible string and
name, not a presumed `fpga0` index. It only reads STAT while the sampled manager
state is operating, and checks state again afterward. No key, firmware image,
debugfs configuration dump or arbitrary sysfs file is exported.
[ZynqMP driver](https://github.com/Xilinx/linux-xlnx/blob/4f7afe14f724/drivers/fpga/zynqmp-fpga.c).

STAT is not the PCAP interrupt-status word. The decoded checks use:

| STAT bits | Check |
| --- | --- |
| 29, 27, 22, 17, 16, 15, 0 | Packet, authentication, over-temperature, security, IDCODE or CRC faults |
| 14, 13, 12, 11, 7, 6, 5, 4 | DONE/INIT levels and released startup controls |
| 2 | Global MMCM/PLL lock indication |

A clear CRC flag does not prove continuous configuration-memory checking. These
are sampled global signals, not proof of application data flow.
[AMD UG570 STAT definition](https://docs.amd.com/r/en-US/ug570-ultrascale-configuration/Status-Register-00111).

## Read-only checks

Build the server/tests using the [build guide](https://github.com/DUNE-DAQ/daphne-os/wiki/Building-daphne-server-and-clients).
`fpga_health_tests` is hardware-free; `fpga_programming_probe` is an explicit
kernel readback diagnostic, never an automatic test. Run the ARM64 probe on the
board. It prints only programming evidence and exits zero when the sampled
startup/error prerequisites allow the status collector's MMIO reads.

```bash
./fpga_health_tests
./fpga_programming_probe
```

That prerequisite is **not a lock against concurrent external reprogramming**.
Always stop the server before changing the FPGA application. Matching image IDs
cannot detect an unload/reload of the same image between observations.

## Qualification boundary

Initial read-only inspection on DAPHNE-015 found manager state `operating`, an
applied overlay, and configuration STAT `0x16907ffc`. These are observations,
not a new bitstream validation. Server RPC integration and live qualification
of this feature are recorded separately when completed. Approved management
MAC/IP configuration and BIAS/BIASCTRL are unchanged by these collectors.
