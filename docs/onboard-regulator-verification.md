# Onboard regulator telemetry: DAPHNE-015

Server/client source **`a729c2b`**, collector **`eeb670b`**, PMBus correction
**`df3162b`**. Self-trigger ABI-2 firmware remains **`0x03F17F1B`**.
These are onboard regulators, independent of the absent mezzanines.

## What changed

The inherited regulator driver assumed `/dev/i2c-2` and interpreted the VOUT
mantissa as signed. It now selects the PL controller at `9c000000` by device-tree
identity and decodes unsigned linear VOUT using the observed `VOUT_MODE`.
Byte reads use the kernel SMBus API with PEC, not raw I2C reads that bypass PEC.
The constructor only opens devices/configures host-side PEC; it does not
initialize, trim or otherwise write regulator configuration.

New request flag `ReadSystemStatusRequest.include_regulator_telemetry` (field 7)
returns four `SystemStatusSnapshot.regulators` entries (field 27). Default
requests do not access these devices. Invalid requests collect nothing; failed
FPGA prerequisites yield explicit unavailable entries without PL I2C access.
`OnboardRegulatorTelemetry` is the new capability.

| Address | Schematic reference / rail | First independent C++ probe |
| --- | --- | --- |
| `0x12` | U39, +3.3VD PL digital | 3.3008 V, 0.3125 A, 34 C |
| `0x16` | U42, +2.1V analog intermediate | 2.0762 V, 0.9375 A, 36 C |
| `0x32` | U33, +3.6V analog intermediate | 3.6641 V, 1.0625 A, 35 C |
| `0x36` | U36, +1.8VD PL digital | 1.7910 V, 0.5000 A, 34 C |

Mapping: `DAPHNE_Mezz_V2_Schematic.pdf`, drawing 177020 rev 0, sheets 11/12;
SHA-256 `d9750668c02f5af5024301bf820f3e248858cd4ffd93af05db637a2165b78794`.
The four live module IDs, capability, revision and mode agree with the expected
PJT004 profile. This is not independent PCB-revision or metrology verification.
The PS +3.3VDPS/+1.8VDPS rails use different devices; do not rename these as PS rails.

## Read contract and limits

Each module uses an adapter lock and mandatory kernel-checked PEC, with 20
allow-listed byte/word reads. Module type, PMBus revision, PEC capability and
VOUT mode bracket telemetry. Raw values carry per-read quality and monotonic
time. Partial failures remain visible; a bad/changed bracket withholds decoded
values. A five-second acquisition-age budget stops further reads and marks stale
evidence; it is not a hard deadline on a blocking kernel call. Modules and
registers are read sequentially, not as a hardware-latched snapshot. Stop the
server before external FPGA reprogramming; these checks are not a reload lock.

The [manufacturer datasheet, revision 10.7](https://www.omnionpower.com/assets/pdfs/windchill/data-sheet/pjt004_ds.pdf)
defines `READ_VOUT` (`0x8B`), `READ_IOUT` (`0x8C`) and `READ_TEMPERATURE_2`
(`0x8E`). Output voltage is sensed internally at the remote-sense amplifier;
reported current covers sourcing, not sinking current. Temperature is the
module's external-to-controller measurement, **not board ambient or SoC die**.
Raw factory current calibration is retained and never reapplied or rewritten.
Module protection settings are unchanged. Host alarms reuse the configurable,
provisional **85/95/105 C** thresholds; they do not control power.

Two evidence gaps stay explicit:

- `STATUS_MFR_SPECIFIC` (`0x80`) is documented, but two PEC reads failed on
  U39 without changing its CML flag. It is **unqualified**, not proven
  unsupported. Monitoring leaves its raw value absent and does not retry it.
- The schematic mentions input-voltage monitoring, but the module's supported
  command table does not list `READ_VIN`. No speculative `0x88` read or VIN
  value is supplied.

U42/U33 already had `STATUS_CML=0x02` / `STATUS_WORD=0x0002` before these probes.
Their `OTHER_COMMUNICATION_FAULT` flags are reported before/after, not cleared
or blamed on the new reader. Fault/warning flags can be latched history.
Successful readout does not certify rail health, load voltage, calibration or
the origin of a fault. The existing 15-item FPGA checklist is unchanged and is
not a substitute for these additional regulator observations.

No regulator PAGE/OPERATION, power, limits, calibration, EEPROM/store/restore,
fault-clear, mux, BIAS, network or recovery writes are in this collector.

## Commands

Build using the [server/client guide](https://github.com/DUNE-DAQ/daphne-os/wiki/Building-daphne-server-and-clients).
Native/ARM unit tests are hardware-free. The explicit ARM probe runs on the board:

```bash
sudo env LD_LIBRARY_PATH=/usr/lib/daphne-server \
  ./regulator_probe --read-onboard-regulators
```

Through the approved SSH control forward, with matching generated protobufs:

```bash
python daphne-server/scripts/verify_regulator_monitor.py \
  --endpoint tcp://127.0.0.1:44015 --proto-dir /path/to/arm-build/srcs/protobuf \
  --expected-build-id 0x03F17F1B --mode self-trigger \
  --read-regulators --with-sfp
```

The seven-exchange client independently decodes raw values/flags, checks fresh
acquisitions, default opt-in behavior, invalid requests, combined SFP reads and
unchanged FE/process evidence. Output includes regulator evidence only, not
private identity/network replies. Exit zero means **readout verified**, not
"all regulators healthy". Full-stream selection is unit-tested, not board-qualified.

## Deployment and evidence

The stopped-service replacement preserved the previous executable as
`/usr/bin/daphneServer.pre-regulators-a729c2b`. No new OS or firmware image was
flashed; restarting the runtime may reload the same installed application.
The private identity artifact, population policy and protected files were not
replaced. Complete zero-BIAS/BIASCTRL FE configuration was restored afterward.

Passed: **23 native and 23 on-board ARM C++ suites, 93 Python tests**,
independent Python decoding of the actual C++ probe, and the seven-exchange live
regulator/SFP qualification before and after the wider regression. Also passed:
153 aggregate exchanges (two AFE orders, all five aligned, all 40 waveforms),
93 ADC exchanges (80 CRC-checked conversions), 11 telemetry/rejection exchanges,
five identity checks and four FPGA-health exchanges. The existing local-clock
health result remains 11 pass, external timing not ready and three unknown.
The final full FE hash is unchanged and valid:
`c858989d7e847a98146c39ad50ec1f053c67acc78ea3c268d6a880341ad8d503`.
BIAS/BIASCTRL remain zero, offset 2200/x1, trim zero, VGAIN 1700. Independent
final checks confirm protected hashes, live approved MAC/IP/gateway, private
identity files and ADC/SFP mux states unchanged. No automatic server restarts;
regulator CML values still match the pre-test baseline. No full-stream hardware
or physical alarm-trip/calibration qualification is claimed.

Evidence is under `completion-VEpMKkGG/regulator-*` and `pmbus-core-*`.
Waveform evidence SHA-256:
`9acc8f749e72afa25cebf9b54888786b1cb218cf56ea98495af6bc3b6085f9f1`.

Installed executable SHA-256:
`c218e75ded4f2b940e288cc9c27bb6b792ee8b562ed05cc49a6e17aab3688341`.
Candidate archive SHA-256:
`7d78e81d1337786282924877e8c1995c68058a08548a81bfc0338ee4c65d4967`.
