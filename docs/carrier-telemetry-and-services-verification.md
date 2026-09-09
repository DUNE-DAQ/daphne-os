# DAPHNE-015: schematic-backed ADC, carrier temperature and services

2026-09-09 (workstation date). Server **`56b390f` deployed**, client verifier
`ed7db06`; self-trigger ABI 2.0 firmware remains **`0x03F17F1B`**. This follows
the [earlier AMS/scan-count update](telemetry-ams-verification.md), whose
unresolved voltage routing is now corrected. No OS or FPGA image was flashed.

## What the schematic settled

Internal reference: `DAPHNE_Mezz_V2_Schematic.pdf`, drawing 177020, revision 0,
dated 2026-05-22; SHA-256
`d9750668c02f5af5024301bf820f3e248858cd4ffd93af05db637a2165b78794`.
The drawing itself is not republished here.

| Component | Drawing | Wiring / live controller | Export |
| --- | --- | --- | --- |
| U37 ADS7138-Q1, `0x10` | Sheet 6 | PS I2C1, MIO24–25, `ff030000`; currently `/dev/i2c-0` | 3V3PDS, 1V8PDS, VBIAS0–4; channels 0–6 |
| U40 ADS7138-Q1, `0x17` | Sheet 6 | Same PS bus | 1V8A, 3V3A, Minus5VA; physical channels 2, 5, 7 |
| U9 MCP9808, `0x18` | Sheet 13 | Same PS bus, through U35 PCA9306 | `Carrier_U9_MCP9808` |
| Kria AMS | SoC / existing Linux IIO | `xilinx-ams` labels | Temp_LPD, Temp_FPD, Temp_PL |

The ADS7138 driver already exists in the old daphneZMQ `server` (`4be8e3a`),
`feature/BIAS_voltage_controller` (`9a5c3f9`) and
`feature/slow-control-emulator` (`c262397`) branches. Those implementations
hardcode `/dev/i2c-1`. On this OS that is the **PL** controller `9c000000`,
not the schematic's PS bus. The earlier fix `c4966e0` corrected scan counts;
`811bb87` now resolves the PS controller by OF identity and compatible string,
rejecting missing or ambiguous matches instead of guessing another bus.

Before changing the driver, narrow documented reads returned ADS7138 status
`0x81` at both addresses and MCP9808 manufacturer/device IDs `0x0054/0x0400`.
No broad scan was used. The deployed firmware source already enables PS I2C1
on MIO24–25: **this ADC fault needed a software binding fix, not synthesis**.
No Cooper synthesis was launched.

U9 is a real carrier sensor even with no mezzanines. Its ID, configuration
and temperature registers are read without configuring it; shutdown mode is
rejected rather than presenting a retained value as fresh. The decoder masks
comparator flags and handles signed temperatures. See the
[MCP9808 datasheet](https://ww1.microchip.com/downloads/en/DeviceDoc/25095A.pdf).
Existing ADS7138 conversion setup is retained; the status-read protocol is
described in the [ADS7138-Q1 datasheet](https://www.ti.com/lit/ds/symlink/ads7138-q1.pdf).

## Small commits and protocol behavior

- `c579b54`: explicit `--no-mezzanines` / `DAPHNE_NO_MEZZANINES=1` policy.
  Skips mezzanine-driver construction, mux access and downstream initialization.
  This is an operator declaration, not automatic presence detection.
- `811bb87`: stable PS-bus binding, plus corrected ADC channel labels.
- `56b390f`: identified carrier temperature, eight runtime-unit observations
  and bounded host metadata.
- `ed7db06`: client qualification switches and telemetry tests.

There are now **four identified temperature readings**, so no existing
temperature field was removed. `GeneralInfo.temperature` is bound to U9,
not an arbitrary die sensor; additive `temperature_status` field 13 carries
the same observation with identity, quality and times. Failures remain
NaN/invalid with explicit quality. No fictitious mezzanine readings are added.

`SystemStatusSnapshot.services` field 21 describes the runtime target,
gateware prepare/load/verify, clockchip, endpoint, hermes and daphne units.
It reports observed state/result, available PID/restart/exit information,
condition result, invocation ID and monotonic times. Missing numeric values
are absent, not fabricated zero. `server_instance_id` field 22 and server
uptime are derived from systemd only when its server PID matches this process.
Invocation ID is **not authentication or a heartbeat**.

The collector invokes one fixed, allow-listed `systemctl show` command, with
no shell, a 1-second timeout, 32 KiB limit and at most one query per second.
It does not return logs, command lines, environment dumps or credentials.
Kernel/OS versions and operator mezzanine policy are included. The FPGA app
name is labelled **configured**, not verified `xmutil` inventory.
An active service or successful oneshot does not prove timing or sensor health.

Temperature times are host observations, not sensor conversion times. Voltage
times describe the cached acquisition; no simultaneous ten-channel latch is
claimed. The board wall clock is unverified. Quality does not implement thermal
Warning/High/Critical thresholds, safety interlocks or analog calibration.

## Live verification

Ten C++ suites pass both natively and as ARM64 binaries on DAPHNE-015.
Twenty-nine Python checks pass. The final protocol check passes 16 exchanges,
including all four temperatures, fresh voltage acquisition, eight service
observations, invalid-request rejection and fresh register-51 readback `0x58`
on all five AFEs.

Example final snapshot (volts): 3V3PDS **3.304**, 1V8PDS **1.809**,
1V8A **1.801**, 3V3A **3.298**, Minus5VA **−5.028**. These five supply readings
are within 1% of nominal in this snapshot, not externally calibrated results.
VBIAS0–4 read **0.461, 0.271, 0.002, 0.000, 0.004 V** with BIAS/BIASCTRL
commands zero. Residuals are recorded, not clipped or interpreted as proof of
physical zero; their cause and bias calibration remain unqualified.
U9 reads **29.875 °C**; LPD/FPD/PL read **37.210/38.779/38.437 °C**.
The carrier reading is not a calibrated ambient measurement.

After restarting the runtime, full zero-BIAS configuration was restored and
tested in normal and shuffled AFE order: **153 exchanges**, five-AFE alignment,
and four usable, unclipped 1024-sample waveforms per channel on all 40 channels
in each pass. No low-level bias-write workaround or nonzero BIAS command.
Final offset=2200/x1, trim=0, VGAIN=1700; BIAS and BIASCTRL command caches zero.
Generator-enable policy was not changed.

Server PID 10387, automatic restarts 0; runtime/server active. Protected network,
SSH and firmware-setting checksums and approved live MAC/IP match predeployment.
External timing remains not-ready on the selected local clock (`0,3,0,6`).
Current-invocation logs contain no ADC initialization errors; remaining onboard
regulator/current-monitor driver warnings are not masked by this qualification.

## Repeat, without private site values

Use the [server/client build guide](https://github.com/DUNE-DAQ/daphne-os/wiki/Building-daphne-server-and-clients),
matching generated protobuf modules and the approved localhost SSH forward:

```bash
python daphne-server/scripts/verify_server_v05.py \
  --endpoint tcp://127.0.0.1:44015 \
  --proto-dir /path/to/arm-build/srcs/protobuf \
  --expected-build-id 0x03F17F1B --mode self-trigger \
  --require-ams-temperatures --require-carrier-temperature \
  --require-voltages --require-services
```

This check does not reconfigure the board. Add `--afe-readback` only when SPI
controller writes for reads are allowed. After any maintenance restart,
restore the full FE setup using the explicit zero-BIAS procedure in
[aggregate verification](aggregate-bias-verification.md) before alignment.

On a board the operator confirms has no mezzanines, install the optional
population drop-in during the application maintenance procedure:

```bash
sudo install -m 0644 daphne-server/configs/no-mezzanines.systemd.conf \
  /etc/systemd/system/daphne.service.d/60-no-mezzanines.conf
sudo systemctl daemon-reload
```

The drop-in takes effect at the next server start. It does not alter network,
clock, BIASCTRL or generator-enable settings. Do not use it on populated boards
without deliberately opting out of their access.

## Evidence and remaining work

Evidence directory: `carrier-services-tTrpPhNj`; ONL-home application bundle:
`daphne015-carrier-services-56b390f.tgz`. It contains the candidate, ten ARM
tests, matching Python protocol, source, clients, reports and raw captures,
with checksum manifests; it reuses existing runtime libraries. Not a boot image.
Previous binary retained as `/usr/bin/daphneServer.pre-carrier-services-56b390f`.

Server SHA-256:
`965727c05b0fc2d6aafe45feb57eae05db3ff52aaf34ea2c2109d90c1f210164`.
Raw capture SHA-256:
`97998c17142078cfb853b939ab15bd6c419d140580fbc1c0c79ad1398af6f340`.

Still separate work: sheet-7 onboard U6 **ADS1261** current monitor versus the
legacy ADS1260-labelled `/dev/spidev3.0` driver; sheet-11/12 onboard regulators
versus hardcoded `/dev/i2c-2`. These are not absent just because no mezzanines
are fitted. Establish chip/protocol and stable controller bindings before
enabling initialization writes. Firmware-only live timestamp/error/identity
exports, external timing, full-stream/DAQ, nonzero BIAS, analog calibration
and underground Ethernet-only boot recovery remain unqualified.
