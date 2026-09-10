# DAPHNE-015 identity assignments and live network readback

Deployed server **`0150b66`**, artifact builder **`bbbb9ea`**, qualification
client **`4d551e0`**. Firmware remains self-trigger ABI 2, **`0x03F17F1B`**.
No OS/firmware flash or Vivado build was required.

## What the server reports

Request **324**, response **325**, now carries `board_identity`. By default it
reports the loaded artifact/source hashes and management-binding result without
private values. Set `ReadSystemStatusRequest.include_identity_details=true`
(field 6) for assignments, their provenance, the approved host baseline, and
live management-interface observations.

| Identity | Assignment / observation |
| --- | --- |
| Crate / slot / detector | Explicit OKS **4 / 1 / 8**, with object/attribute/file hashes. Not FPGA readback; old I058/I059/I061 offsets overlap ABI-2 controls |
| Management IP | Assigned IPv4 literal from the selected board object, separate from live Linux IPv4/prefix readback |
| Management MAC | Database assignment unavailable. The existing protected `.link` value is a **host baseline**, compared with live MAC readback, not relabeled as a DB assignment |
| Timing endpoint | Database assignment unavailable. `EndpointStatus.endpoint_address` field 22 reports actual `ep_ctrl_reg[15:0]`, including explicit zero; it does not establish timing readiness or an approved address |
| Hermes MAC/IP | One source-referenced interface assignment. No live Hermes-transmitter register readback, additional link assignments, or physical SFP/LinkId mapping is fabricated |

Assignments, baseline and observations are separate protobuf messages. Missing
values have no scalar wire presence and carry an unavailable reason. The
source manifest hash is checked, but is not a signature or proof that the
configuration is active in run control. The source files are an explicit-field
snapshot, not a fully schema-resolved/transactional OKS database read.

An identity-binding match means the selected Linux controller, MAC and complete
IPv4/prefix set match the supplied host baseline. It does **not** certify link
readiness, physical asset identity, optics, FPGA health or approved packet-header
contents. `SystemStatus.success` does not imply a matching identity binding.

## Prepare the private artifact

Follow-up `0c9d1b7` adds an optional [hardware-database import](hardware-database-identity-import.md)
for approved timing and management-MAC assignments. It reuses the existing wire
format and preserves the network baseline; no new real assignment is installed.

First use [the review extractor](oks-identity-review.md) on ONL. Preserve the
same three input files and copies of the already approved `10-ff0b.link` and
`20-ff0b.network`; do not edit or apply them. In a Python environment with the
matching generated protobufs (qualified runtime: protobuf 6.30.1):

```bash
python daphne-server/scripts/prepare_identity_assignment.py \
  --review-file /private/path/daphne015-identity-review.json \
  --source-root /private/path/ehn1-vst-daphne15 \
  --approved-link-file /private/path/10-ff0b.link \
  --approved-network-file /private/path/20-ff0b.network \
  --management-interface eth0 \
  --proto-dir /path/to/arm-build/srcs/protobuf \
  --output /private/path/daphne015-identity.pb
```

This re-extracts the actual source files and rejects a changed review/source,
missing target comparison, ambiguous baseline, or target IP outside that
baseline. It preserves the literal assignment rather than replacing it with
DNS output. The binary output is exclusive-create, mode **0600**. No DNS,
SSH, server command, network setter, MMIO, SPI or I2C operation is performed.
The reviewed DNS result remains an observation, not authentication.

On the Kria, before installing the application, use the matching ARM probe:

```bash
export LD_LIBRARY_PATH=/usr/lib/daphne-server
/path/to/identity_probe /private/path/daphne015-identity.pb
```

Run this as the staging file's owner. The probe only reads local network
identity and prints hashes/result, not addresses. `--validate-only` checks the
artifact without observing the network; it is not board qualification.

## Loading and private-data boundaries

The deployed root-owned `/etc/daphne-identity.pb` is selected by
`/etc/systemd/system/daphne.service.d/70-identity.conf`:

```ini
[Service]
Environment=DAPHNE_IDENTITY_FILE=/etc/daphne-identity.pb
```

Equivalent CLI: `--identity-file PATH`. An explicitly configured missing,
malformed, noncanonical, symlinked or non-private file is rejected with exit
**78 before hardware initialization**. Omitted configuration leaves assignments
unavailable. Loading is once per process, not automatic DB polling/reload.
No network, clock, analog or packet-header configuration is applied.

Runtime observations use read-only Linux `getifaddrs` and the interface's
device-tree controller link; two matching samples are required. See
[the Linux interface API](https://man7.org/linux/man-pages/man3/getifaddrs.3.html).
Sequential samples are not an atomic snapshot or a guaranteed kernel-call
deadline. Errors/mismatches are reported without changing network settings.
Host wall time is unverified; use monotonic time/process identity for age.

Private-detail opt-in is **not authentication**. Use the approved access-controlled
transport. Do not publish the artifact, source config snapshots, or complete
private protocol replies. The qualification client prints only redacted results.

## Verification

```bash
python daphne-server/scripts/verify_board_identity.py \
  --endpoint tcp://127.0.0.1:44015 \
  --proto-dir /path/to/arm-build/srcs/protobuf \
  --identity-file /private/path/daphne015-identity.pb \
  --expected-build-id 0x03F17F1B
```

The five-exchange test checks default redaction, two fresh detailed acquisitions,
exact assignment/provenance equality, live baseline agreement, optional presence,
timing-address decoding and unchanged FE/process bookkeeping.

All **19 native and 19 ARM C++ suites**, and **82 tracked Python tests**, passed.
The actual ARM probe matched DAPHNE-015 before and after installation. Literal
invalid-artifact startup was rejected with exit 78. The live identity API passed.
After full zero-BIAS restoration, the **153-exchange waveform regression**
passed in both AFE orders, with all five AFEs aligned and all 40 channels checked.
The **93-exchange ADC**, five-exchange SFP and **11-exchange telemetry/rejection**
regressions passed. SFP RX warnings on TMG/GTR and unknown presence on three
cages remain visible; these tests do not resolve those hardware limitations.

Deployment guards first refused a sudo/staging-owner mismatch, leaving the
old server untouched. A subsequent stop guard required explicit confirmation
that the service had stopped before replacement. Both records are retained;
the final installation used a stopped-service continuation, not a second
concurrent server. The installed file is root-owned/private and all eight
protected-file hashes matched. BIAS/BIASCTRL were restored to zero; offset
2200/x1, trim zero and VGAIN 1700, with the existing enable policy retained.
Final independent reads confirmed SFP mux `0x00`, both ADC carrier selectors
zero, and the approved live management MAC/IP/gateway unchanged. The final
identity and bookkeeping checks passed; configuration remained valid, with
no automatic server restarts.

Application SHA-256:
`7ffbc5ed93b27088d1304a967ae284687e77a09c96af176a6218359833873554`.
Private artifact SHA-256:
`d2a801455554fe2e1346f33f7f814bb7a8b929a7e4e28c5b41aeff857dbd254a`.
Source revision:
`9dc51032d423353b06373bf65093c464e49c9ec2b0f16c3de5438437f9c86ff2`.
Previous application: `/usr/bin/daphneServer.pre-identity-0150b66`.
Evidence: `completion-VEpMKkGG/identity-*`.

Still open: actual crate/slot/detector hardware/packet-header readback, approved
timing and management-MAC assignments, physical Hermes mapping/readback, live
full-stream qualification, and the broader [FPGA-health/firmware gaps](server-v05-completion-plan.md).
