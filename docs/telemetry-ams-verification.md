# DAPHNE-015: temperature export and voltage acquisition

Historical report. The subsequent
[schematic-backed carrier/services update](carrier-telemetry-and-services-verification.md)
resolves the voltage bus binding and GeneralInfo carrier-temperature binding.
The results below retain their original server provenance.

2026-09-09 (workstation date). Server **`2dd11b9` deployed** on the existing
self-trigger ABI 2.0 firmware `0x03F17F1B`; client verifier `9caab83`.
No new OS/FPGA image, bus assignment or network configuration was installed.

## Two small changes

| Commit | Change | What it proves |
| --- | --- | --- |
| `c4966e0` | Request one ADS7138 scan per ADC, not 7/3 scans | Mock acquisition now delivers the cache's required 7+3 values, not 49+9. Physical voltages remain unqualified |
| `2dd11b9` | Export `Temp_LPD`, `Temp_FPD`, `Temp_PL` through `SystemStatusSnapshot.temperatures` | Three named SoC die temperatures are readable through the deployed server |

Temperature discovery matches Linux IIO chip name `xilinx-ams` and channel
labels, not fixed device/channel numbers. It only reads existing sysfs files;
no I2C scan, address probe, device instantiation or sensor configuration.
Linux `in_tempY_input` already supplies millidegrees Celsius; divide by 1000,
without applying raw-channel scale again. See the
[Linux IIO ABI](https://raw.githubusercontent.com/torvalds/linux/master/Documentation/ABI/testing/sysfs-bus-iio).

Each request reads afresh. Missing readings are NaN/invalid/unavailable;
read errors or ambiguous identities are NaN/invalid/error. A real zero remains
valid. Additive `TemperatureStatus` fields 6–8 carry quality and host observation
times; fields 1–5 and request IDs 324/325 are unchanged. These times are **not
ADC conversion times or certified timing-endpoint timestamps**. The board wall
clock is unverified; do not use it as an accurate UTC acquisition timestamp.

Final protocol example: LPD 40.536 °C, FPD 40.753 °C, PL 39.479 °C; all good.
Sequential sysfs checks are consistent with these readings, not simultaneous
samples or a temperature-calibration test. These are **die temperatures, not
board ambient**. `GeneralInfo.temperature` remains deliberately unbound/NaN;
its workbook M009 issue is not closed by assigning it an arbitrary die sensor.
Named temperature export is a bounded contribution to I200–I202, not complete
coverage of PMBus, carrier, optical sensors or true source conversion times.
Measurement quality is not an implementation of I201's Warning/High/Critical
thermal thresholds or an interlock.

## Verification

- Seven C++ suites pass both natively and as ARM64 binaries on DAPHNE-015.
  Fixtures cover identity, renumbering, units, zero/negative readings, refreshed
  values, missing/malformed inputs, ambiguous labels/devices and protobuf.
- Five new Python temperature checks pass; 18 existing offset/zero-BIAS
  verifier checks also pass.
- Ten initial protocol exchanges pass, including invalid-request rejection and
  advancing temperature observation times. Nine final exchanges additionally
  confirm fresh register-51 readback (`0x58`) on all five AFEs.
- Full zero-BIAS regression passes: two AFE orders, 153 exchanges, five-AFE
  alignment and four usable, unclipped waveforms on each of 40 channels.
  Final BIAS/BIASCTRL command caches are zero; offset=2200/x1, trim=0,
  VGAIN=1700. Cache/command checks are not physical bias-voltage measurements.

## Why voltage telemetry is still unavailable

Read-only enumeration found:

| Current node | Controller / startup result |
| --- | --- |
| `/dev/i2c-0` | PS Cadence `ff030000` |
| `/dev/i2c-1` | PL AXI IIC `9c000000`; ADS7138 setup at `0x10`/`0x17` reports I/O errors |
| `/dev/i2c-2` | Absent; hardcoded mezzanine/regulator initialization fails |
| `/dev/spidev2.0` | PL AXI SPI `9c020000` |
| `/dev/spidev3.0` | Absent; hardcoded current-monitor initialization fails |

The live DT disables PS I2C `ff020000`. Reviewed dual-ABI firmware source also
disables I2C0 and enables I2C1 on MIO 24–25. Merely enabling another DT node or
renumbering adapters is not an established repair. Driver failure or absent
kernel client enumeration does **not** prove the physical ADC is absent.

Next: establish the monitor/service controller and any mux route against the
deployed firmware and board wiring, then implement identity-based binding and
validate narrowly targeted transactions. Do not blindly move ADCs to i2c-0,
scan buses, change clocks or enable mezzanine/regulator controls. No such
hardware changes were made in this update. GeneralInfo voltage quality stays
unavailable, without fabricated zero values.

External timing remains not-ready on the selected local clock. Full-stream,
nonzero bias and remaining offset-calibration differences remain unqualified.

## Repeat the read-only client check

Use the [server/client build guide](https://github.com/DUNE-DAQ/daphne-os/wiki/Building-daphne-server-and-clients)
and the approved localhost SSH forward. Regenerate Python protobuf modules
from this source; no client-side C++ compilation is required for this script.

```bash
python daphne-server/tests/test_ams_temperatures.py -v
python daphne-server/scripts/verify_server_v05.py \
  --endpoint tcp://127.0.0.1:44015 \
  --proto-dir /path/to/arm-build/srcs/protobuf \
  --expected-build-id 0x03F17F1B --mode self-trigger \
  --require-ams-temperatures
```

This command does not configure the board or request bus scans. Add
`--afe-readback` only when controller writes required for SPI reads are allowed.
For a maintenance restart, restore the full zero-BIAS setup with the command
in [aggregate BIAS verification](aggregate-bias-verification.md).

## Deployment and evidence

Candidate checksums, all seven ARM tests and `--help` passed before stopping
`daphne.service` and `daphne-runtime.target`. MainPID=0/inactive was checked,
the binary replaced atomically, then the runtime target restarted. It reloaded
the **same** FPGA app; the full FE configuration was restored afterward.
Previous binary: `/usr/bin/daphneServer.pre-ams-2dd11b9`.

Final server/runtime active; PID 9115, NRestarts=0. Protected network, SSH and
firmware-environment checksums match; approved live primary MAC/IP match too.
Server SHA-256:
`7c74ed82a268a907072314285a7296e3430e70a8a2971f89d12974278003ac8b`.
Raw capture SHA-256:
`e2be2d7ba383c521b6dab7a0c8fb79c3a13852aafa5876afe1e247c88dc87e74`.

Evidence directory: `telemetry-5d8lVH2y`. The ONL-home application bundle
`daphne015-telemetry-2dd11b9.tgz` contains server, seven ARM tests, generated
Python protocol, source, verifier scripts, raw captures and reports, with
internal/external checksums. Existing runtime libraries are reused. No Vivado
or reflash is needed; this is not a bootable OS/firmware image.
