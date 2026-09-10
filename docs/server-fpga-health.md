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
management interface/baseline observations. On deployed ABI 2.0, three
requirements remain UNKNOWN: live timestamp progress, Hermes data-path
operation, and external reset epoch. The new [ABI 2.1 timestamp support](native-timestamp-verification.md)
can assess native progress; it is source-tested but not deployed. Hermes and
reset epoch remain UNKNOWN in either ABI. SFP diagnostics or successful
oneshot services cannot satisfy those requirements. Neither ABI can currently
earn an overall OBSERVED_OK result.

## Deployed AFE reset follow-up

Deployed server **4e74f10** adds the sampled `afe_reset_released`
prerequisite; see [AFE reset health verification](afe-reset-health-verification.md).
The full live regression confirms 16 checks: 12 PASS, one external-timing FAIL
and three UNKNOWN. The additional
check does not introduce an SC power/bias decision or treat transient SPI busy
as a hardware fault.

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

## Deployed qualification, DAPHNE-015

Server source **`8a53161`**, client **`1431858`**, unchanged self-trigger ABI-2
firmware **`0x03F17F1B`**. Server binary SHA-256:
`e5adb2768f794091edff7eef5f6834cf108511949b1619059b450ee8203aaca5`.

The update stops the runtime and explicitly confirms the server PID is zero
before replacing the binary. Starting the runtime can reload the same installed
FPGA application; no new OS/bitstream was flashed. Previous executable retained:
`/usr/bin/daphneServer.pre-fpga-health-8a53161`. Identity artifact/drop-ins and
protected network/SSH/firmware files remain unchanged.

Qualification passed:

- 21 native C++ suites, the same 21 ARM64 executables on the board, 87 tracked
  Python tests, plus the real kernel configuration-status probe.
- Health client: four exchanges, twice, independently comparing raw words with
  named checks. STAT `0x16907ffc`; **11 PASS, one FAIL (external timing), three
  UNKNOWN**. Local-clock operation is expected to report NOT_READY for this
  externally timed acquisition checklist.
- Complete zero-BIAS/BIASCTRL restoration and bookkeeping checks; 153 aggregate
  exchanges across two AFE orders, five-AFE alignment and all 40 spy waveforms.
- 93 ADC exchanges including 80 CRC-checked conversions; five SFP, five private
  identity/redaction, and 11 telemetry/rejection regression exchanges.

All retained FE evidence is valid, final offset 2200/x1, BIAS/BIASCTRL zero;
canonical hash `c858989d7e847a98146c39ad50ec1f053c67acc78ea3c268d6a880341ad8d503`.
SFP warning flags remain visible; the physical wiring/population question is
not resolved by this pass. No hardware fault, reset, or corrupted image was
injected; those failure paths were tested with mocks.

Evidence: `completion-VEpMKkGG/fpga-health-*`, including the guarded deployment
and final-board scripts. The initial final-board helper used a nonexistent I2C
class path and stopped before the mux check; the corrected helper verifies
`/sys/bus/i2c/devices/i2c-1/of_node` before reading the selected mux. Both logs
are retained. The server itself already uses controller-based bus discovery.

## Client command

Use matching generated protobufs and an approved SSH forward. This requests
private details for comparison but prints only redacted checklist results:

```bash
python daphne-server/scripts/verify_fpga_health.py \
  --endpoint tcp://127.0.0.1:44015 \
  --proto-dir /path/to/arm-build/srcs/protobuf \
  --expected-build-id 0x03F17F1B --mode self-trigger \
  --require-bench-profile
```

Exit zero means **reporting verified**, not "FPGA fully healthy." The bench
option requires exactly the qualified local-clock profile above. Do not use it
as a production external-timing requirement or authorization check.

The client defaults to exact ABI `0x20000`; a qualified ABI 2.1 deployment must
explicitly use `--expected-abi 0x20001` and its actual build ID. Its bench profile
additionally requires native local-counter progress. See the timestamp guide
for source-only verification and remaining deployment gates.
