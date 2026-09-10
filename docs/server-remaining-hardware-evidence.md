# Remaining hardware/configuration evidence

Investigation notes, not completed register qualification. No private network
values are reproduced here. See [the task checklist](server-v05-completion-plan.md).

## CERN DAPHNE-15 configuration

Candidate directory on ONL:
`/nfs/home/marroyav/fddaq-v5.6.0-rc4-a9-1/ehn1-vst-daphne15`.

- `segments/pds-vst.data.xml`: `DaphneV2BoardConf`
  `daphne_mezz-daphne-15-conf`, with address and crate/slot/detector attributes.
- `hw/senders/pds-vst-senders.data.xml`: `HermesDataSender` `hds-daphne15`
  uses `NetworkInterface` `nw-np02-daphne-015-10g`, containing a Hermes MAC/IP.
  Its stream `GeoId` placement agrees with the board configuration.
- The board management address resolves to the same IP as DAPHNE-015's DNS
  record; the Hermes sender's `control_host` also resolves to that same board
  (comparisons only; no network values published). Placement agrees at
  crate **4**, slot **1**, detector **8**. The application connects this board
  configuration to `daphne15-connection` and sender `hds-daphne15`.
- No timing-endpoint assignment was found in this candidate's XML files yet.
  Confirm the intended authoritative NP02/VST source and trace schema defaults
  or another assignment record before treating an omitted field as assigned.
  `tp_conf` is present, but encodes trigger parameters, **not** a timing-endpoint
  address; do not reinterpret it. The inspected records provide one Hermes
  interface, not an assignment for every physical link, and do not supply a
  management MAC assignment.
- Several separately inspected `pds/configs/vst` JSON copies identify board
  **61**, not **15**. Do not use those as DAPHNE-015 assignments.

Import identity attributes only. Never apply the candidate's bias, analog,
clock or network settings as a side effect of collecting metadata. Report
assigned and observed identity separately, with source IDs and content revision;
an unknown second Hermes link or timing assignment is not zero.

## Current ADC: why copying the old handler is insufficient

Original daphneZMQ commit `a4e19e1` already supplied the raw current-read handler
inherited here. It accesses AXI Quad SPI at `0x9c020000` directly. The separate
ADS1260-labelled constructor attempts `/dev/spidev3.0`; those are two different
paths. Do not exercise raw MMIO while the Linux SPI driver owns that controller.

The available carrier schematic is drawing **177020 rev 0, 2026-05-22**,
SHA-256 `d9750668c02f5af5024301bf820f3e248858cd4ffd93af05db637a2165b78794`.
Sheet 7 explicitly identifies onboard **U6 ADS1261** and **five differential
inputs**, one per AFE:

| AFE | DA input | DB input |
| --- | --- | --- |
| 0 | AIN1 | AIN0 |
| 1 | AIN3 | AIN2 |
| 2 | AIN5 | AIN4 |
| 3 | AIN7 | AIN6 |
| 4 | AIN9 | AIN8 |

The old handler instead defaults to `(channel+1)` against mux code zero
(**AINCOM**, not AIN0) for channels 0..9. That is not the schematic's five
differential pairs. TI Table 43 encodes AIN0 as 1, AIN1 as 2, etc. The schematic asks
for internal reference/clock and conversion-ready checking. Establish installed
board revision, input polarity and shunt/conditioning scale before publishing
amperes. Preserve raw signed codes and explicit quality. The absence of
mezzanines does not imply the onboard ADC is absent. Sheet 5 adds the second
selector: two ADG1609s per AFE select one of eight trim-current paths. Shared
enable/address controls are at `0x94000010/14` in both ABIs. Use break-before-make
(both disabled while changing address), select exactly one enable, and restore
the previous safe state after measurement. The ADC's five pairs alone are not
the workbook's 40 physical channels. No installed current calibration has yet
been established.

## SFP wiring

Sheet 8 shows six connectors, including SCL/SDA nets and pull-ups. Sheet 14
shows U32 TCA9548A at PL-I2C address `0x72` routing them as follows:

| Mux channel | Net/connector role |
| --- | --- |
| 0 | GTH2 / data |
| 1 | GTH1 / data |
| 2 | GTH0 / data |
| 3 | TMG / timing |
| 4 | GTH3 / data |
| 5 | GTR / PS 1-Gb control link |

This drawing alone does **not** confirm the reported wiring fault or the
installed PCB revision. Qualify each path with narrowly targeted reads and
explicit unavailable/error status. Do not infer module absence from an I2C
failure, reset the shared mux, change TX-disable, or disturb the management SFP.
U43 at `0x71` is the separate mezzanine mux, not this SFP mux.

Live collector results: GTH0, TMG and GTR answer with valid EEPROM checksums;
GTH1/GTH2/GTH3 do not answer A0 reads. All routes restore to `0x00`. The latter
three are **unknown presence**, not verified absent or faulty. Operator cage
population and installed PCB revision have been requested. TMG advertises TX
disabled; TMG/GTR both report confirmed RX high-warning flags. No TX/power
changes were made. See [qualification and limitations](sfp-diagnostics-verification.md).
