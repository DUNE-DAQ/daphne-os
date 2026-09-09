# DAPHNE-015: ADS1261 raw readout

Server `e247dfd`, qualification client `0e0a4ea`; self-trigger ABI 2 firmware
`0x03F17F1B` unchanged. This qualifies onboard raw readout, **not calibrated
SiPM current**. No mezzanines are fitted.

## What changed

- Replaced the old raw SPI-controller MMIO handler and unused zero-returning
  current-monitor startup path with the kernel-owned SPI device. Bind by
  controller `9c020000`, chip-select 0 and driver identity, not a bus number.
- Identify U6 as ADS1261 before resetting/configuring the ADC. Check command
  echoes, register readback, CRC, fresh-data status and bounded ready polling.
- Select all 40 physical paths: eight external-mux positions per AFE, then
  the schematic's five differential DA-minus-DB ADC input pairs. Disable both
  mux banks before selecting, enable exactly one, and restore the prior state
  after success or failure. No BIAS, trim, power or TX-enable commands.
- Return signed 24-bit code, nominal differential volts, channel/mux/profile,
  source, acquisition times, restoration result and explicit quality. Amperes
  remain absent with `CURRENT_MONITOR_UNAVAILABLE`, never a fabricated zero.

The profile uses the internal nominal 2.5-V reference, gain 1/PGA bypass and
400-SPS single-shot conversion. Bypass supports the near-ground trim inputs;
this is not a gain-32 calibrated-current measurement. The former negative mux
code zero meant AINCOM, not AIN0. See the
[schematic evidence](server-remaining-hardware-evidence.md).

## Client change required

Request/response IDs remain **244/245**. New clients must explicitly set
`cmd_readCurrentMonitor.physical_channel` (optional field 3), **0..39**.
Explicit zero has wire presence. Omitted physical channel, out-of-range values,
and mixing a nonzero legacy `currentMonitorChannel` selector with the new field
are rejected before measurement. Do not silently reinterpret an old ADC-input
request as a physical-channel request. Regenerate the Python/C++ protobufs.

Legacy response `currentValue` remains a sign-extended raw code encoded as
uint32 on success, not amperes. Prefer `raw_code` and check `success`, `quality`
and optional-field presence. A failed response's zero/default is not a reading.

## Verification

All **17 native and 17 ARM C++ suites** passed, including 480 mux restoration
cases, transport faults, CRC/identity errors, saturation, ready timeout and
request/payload validation. All **45 tracked Python tests** passed. The separate
untracked waveform-artifact test could not import NumPy in the client venv;
it is not included in that count and was left untouched.

Live DAPHNE-015: ID **0x81**, **80 successful acquisitions** (all 40 channels
twice), status **0x04**, valid CRCs and fresh timestamps. Four malformed/ambiguous
requests were rejected; **93 total exchanges** passed. Raw codes ranged
1317..3303, nominal differential voltage 0.3925..0.9844 mV. Those small values
are not a zero-current calibration or proof of installed sensor readout.

Both carrier-mux registers were independently read as zero before and after;
every response also reported restoration. The process and valid applied-FE
hash were unchanged by monitoring. A full zero-BIAS configuration preceded
ADC testing. Board wall time is unverified; use monotonic time for freshness.

The subsequent **153-exchange** full zero-BIAS regression passed in both AFE
orders: five aligned AFEs, fresh register readback and all 40 spybuffer channels.
The five-exchange voltage/temperature/alarm/service check passed, as did final
bookkeeping. No automatic server restarts occurred. All eight protected file
checksums and the live management MAC/IP/gateway matched their approved
configuration. The final profile remains offset 2200/x1, trim 0, VGAIN 1700,
BIAS 0 and BIASCTRL 0, with the existing enable policy unchanged.

Run only after restoring the complete reference zero-BIAS FE configuration,
using the approved localhost SSH forward and matching generated protobufs:

```bash
python daphne-server/scripts/verify_current_monitor.py \
  --endpoint tcp://127.0.0.1:44015 \
  --proto-dir /path/to/arm-build/srcs/protobuf \
  --expected-build-id 0x03F17F1B --measure-current
```

This opt-in test configures the ADC and temporarily selects measurement muxes;
it is not a passive register read. Do not run the legacy full smoke test merely
to read current: it contains other hardware operations.

Candidate SHA-256:
`82dd8ee69c6ed268f4760abe55e3be86b78855541edb2c16ac424a23978d2178`.
Previous executable: `/usr/bin/daphneServer.pre-ads1261-e247dfd`.
Evidence: `completion-VEpMKkGG/ads1261-*`.

Still unqualified: absolute current scale/polarity and per-channel calibration,
known-stimulus analog channel mapping/settling, installed PCB revision, and live
full-stream-ABI behavior. The 100-ms data-ready poll bound is not a guaranteed
deadline for a blocked kernel SPI ioctl. No FPGA rebuild was needed for raw
readout; both firmware sources already expose the carrier mux controls.
