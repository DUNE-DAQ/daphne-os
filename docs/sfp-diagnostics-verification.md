# DAPHNE-015 SFP diagnostics

Server/client source `1dc613e`. Opt-in request **324**,
`ReadSystemStatusRequest.include_sfp_diagnostics=true`; response **325** contains
six `SFPMonitor` records. Default status requests perform no SFP accesses.
These records describe physical connectors, not an approved Hermes LinkId map.

## Register coverage

| Workbook rows | Export / limitation |
| --- | --- |
| I227 | Optional `present=true` from verified SFP EEPROM. I2C failure leaves presence unknown, never false |
| I228–I230 | Optional LOS, TX fault and TX-disable observations, only when module-advertised. Not independent GPIO readback |
| I231 | `rate_select_raw`: A2 status bits only. Physical rate-select wiring/function remains unqualified |
| I232–I239 | Vendor, OUI, part, revision, serial, date, nominal signaling rate and optical wavelength. Unspecified values absent; copper compliance bytes are not wavelength |
| I240–I244 | Temperature, voltage, laser bias and optical power; per-quantity quality, raw codes, calibration and factory thresholds |
| I245–I248 | Raw/decoded alarm and warning flags, DOM advertisement and separate A0/A2 readability. Check quality separately from successful byte transfer |
| I200–I202 | Each acquired SFP temperature also carries the host's observation-only 85/95/105-C alarm policy and monotonic sample age |

I238's workbook `Mbps` label needs care: `nominal_signaling_rate_mbd` reports
module line signaling rate in **MBd**, not payload throughput or negotiated
Ethernet speed. Timing-role values remain named `TMG`; monitoring does not
give this server authority to change timing-link policy.

## Access and decoding

The [schematic](server-remaining-hardware-evidence.md) routes U32 mux `0x72`
on PL I2C `9c000000`: channels 0..5 = GTH2, GTH1, GTH0, TMG, GTH3, GTR.
Linux adapter numbering is discovered from controller identity. The collector
uses a cooperative adapter lock and the server's PL-bus mutex; kernel-owned
slave addresses are not forcibly claimed. Mux selection is checked and the
previous safe route restored after success/failure. A restoration failure
invalidates data and stops further routes; no automatic mux reset is attempted.
Only lower A0/A2 regions are read, in bounded chunks. No EEPROM data, TX-disable,
rate-select, GPIO, power, clock, general-call or page-selection writes are exposed.
Pointer writes needed for EEPROM reads and mux-route writes are the only writes.
See [Linux's I2C interface](https://docs.kernel.org/i2c/dev-interface.html) and
[TI's mux datasheet](https://www.ti.com/lit/ds/symlink/tca9548a.pdf).

Decoding follows [SFF-8472 Rev 12.5a](https://members.snia.org/document/dl/25916):
identity/diagnostic checksums, internal or external calibration, and advertised
optional status. Address-change/legacy diagnostic modes are explicitly unsupported.
TX power is withheld when an advertised disable state is asserted. Raw evidence
is retained on errors. Asserted basic flags are read again at least 100 ms later;
both reads and their union are reported, not silently cleared. Vendor latch
semantics still apply. A modern module's startup-only diagnostic checksum may
disagree after enhanced-control changes; this implementation withholds values
and reports that possibility rather than bypassing integrity checks.

Host acquisition time is not a module ADC conversion timestamp. Sequential
reads and identity rechecks do not provide an atomic hot-swap-proof snapshot or
prove that a module's internal ADC is continuously updating. Kernel I2C timeout
behavior is not a server-enforced hard deadline. Consumers must check quality,
optional-field presence, age, and server reachability.

## Hardware evidence and remaining wiring question

The standalone collector and integrated API both identified **GTH0, TMG and
GTR**, with valid EEPROM checksums and module-internal calibration. Five
quantities were available on GTH0/GTR and four on TMG; TMG advertised TX disabled,
so its TX power was unavailable, not reported as a valid zero.

TMG and GTR reported **RX high-warning flags (`0x0080`)**, confirmed on the
second read. A successful readout test does not erase these warnings or mean
the links are healthy. No attempt was made to change optical power or TX state.

GTH1/GTH2/GTH3 did not answer A0 reads. Their presence is unknown. All six
paths are drawn in the available carrier schematic (177020 rev 0, 2026-05-22),
but the installed PCB revision and population of those cages are not confirmed.
The suspected one-port I2C wiring defect is **not established or ruled out**.
Confirm population/revision and test the suspect cage with a known module in a
planned maintenance window; do not unplug the management link remotely.

## Reproduce

After building matching protobufs, use the approved localhost SSH forward:

```bash
python daphne-server/scripts/verify_sfp_monitor.py \
  --endpoint tcp://127.0.0.1:44015 \
  --proto-dir /path/to/arm-build/srcs/protobuf \
  --expected-build-id 0x03F17F1B \
  --require-inventory GTH0 TMG GTR --read-sfp
```

This explicitly authorizes measurement-mux routing, not passive monitoring or
arbitrary scans. It checks two acquisitions per route, independently decodes
raw values/thresholds/flags, verifies unrequested diagnostics stay off, and
checks unchanged process/FE bookkeeping. It permits honestly reported errors
on non-required cages; those paths are not thereby hardware-qualified.

Unit tests cover all six routes and 42 previous-route restoration combinations,
transport failures, short reads, hot-swap detection, checksums, signed values,
internal/external calibration, non-finite calibration, absent fields,
factory flags, advertised status, and host temperature alarm age/quality.
External calibration and injected failures have synthetic, not live-module,
qualification. Full-stream hardware, physical rate-select wiring and protection
monitor latency with populated mezzanines remain unqualified.

## Final qualification

All **18 native and 18 ARM C++ suites**, plus **53 tracked Python tests**, passed.
The final integrated API's five-exchange SFP check passed twice per route,
including independently verified inventory fields. Three required identities
and 14 available diagnostic quantities were verified per acquisition; three
unanswered paths remained errors with unknown presence. The final 93-exchange
ADC test passed (40 channels twice), followed by the 11-exchange temperature,
voltage, service and rejection check. The 153-exchange full zero-BIAS waveform
regression also passed after installing this executable.

The mux was independently read back as **0x00**; ADC carrier selectors also
remained zero. All eight protected checksums and the live approved management
MAC/IP/gateway matched. No automatic server restarts occurred. Full FE
configuration remained valid. BIAS/BIASCTRL were left zero, offset 2200/x1,
trim zero and VGAIN 1700; existing generator/protection-enable policy unchanged.

Server SHA-256:
`007c4df1f495d4720ab4b1ae97111c29ba4911cae5e45b6e77b5c7961424af45`.
Firmware remains self-trigger ABI 2, build **0x03F17F1B**. No synthesis/reflash
was needed. Previous application:
`/usr/bin/daphneServer.pre-sfp-inventory-1dc613e`.
Evidence directory: `completion-VEpMKkGG`, final files prefixed `sfp-inventory-`,
plus `sfp-final-board.txt`, `sfp-live-final.json` and `sfp-final-python-tests.txt`.
