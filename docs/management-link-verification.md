# Management Ethernet telemetry — deployed on DAPHNE-015

Source: collector `d9c4732`, health correction `b631894`, client/probe `52e4cc9`,
minimal-runtime probe fix **bffea24**, now deployed. Clean source and ARM
build reproduce the previously tested bytes exactly; unrelated work is excluded.

## What this adds

Workbook Server Platform **I071–I084** now have a read-only Linux collector:
operational state, carrier, speed, duplex, MTU, RX/TX bytes/packets/errors/drops,
and carrier-change count. This is the management Ethernet interface, not Hermes.
I084 counts kernel carrier changes, not every operational-state transition.

Results are in `board_identity.management.link`, field 15 of
`ManagementNetworkObservation`, within request 324/response 325. Private parent
identity details still require `include_identity_details=true`; that opt-in is
not authentication. Fourteen typed measurements retain individual quality,
units and host acquisition times. Missing/unknown data has no value, not zero.

Only the interface selected by the existing protected identity artifact is read.
A pinned sysfs directory and matching ifindex samples bracket collection; the
existing controller/MAC/IPv4 comparison surrounds it. Each attribute is bounded
to 64 bytes. Eighteen fixed attribute reads per attempt, at most three identity
attempts; no scans, commands, sockets, DHCP/MAC/IP changes or counter resets.
Kernel calls have no hard deadline. Samples are sequential, not atomic.

Speed/duplex are withheld unless carrier and operational state both remain up
in the two samples. Equal samples cannot exclude an intervening transient.
Counters are exported as uint64; carrier changes have a 32-bit export range.
Hardware counter width, reset epoch and rates are not inferred.

The health checklist now requires measured carrier-up and operational-up instead
of accepting `IFF_RUNNING` alone: that Linux flag also covers **unknown** state.
Missing/stale/changing evidence produces UNKNOWN; an observed absent/down NIC
produces FAIL. This still does not prove remote reachability or Hermes delivery.
See the kernel's [state semantics](https://docs.kernel.org/networking/operstates.html),
[sysfs attributes](https://www.kernel.org/doc/Documentation/ABI/testing/sysfs-class-net)
and [counter semantics](https://docs.kernel.org/networking/statistics.html).

## Verification completed

- All **27 host and 27 native ARM C++ suites** pass, including malformed input,
  unknown negotiation, zero/full-width counters, interface replacement, stale
  evidence, carrier loss, duplicate fields and conservative health evaluation.
- All **144 tracked Python tests** pass with both protobuf binding versions.
- The actual ARM collector read DAPHNE-015 twice; all 14 fields were GOOD.
  Both replies pass independent Python wire validation with both bindings.
  Observed link: **1 Gb/s, full duplex, MTU 1500**, carrier present, zero reported
  RX/TX errors/drops, carrier-change count 1. These are samples, not a guarantee.
- During standalone-probe qualification, before/after guards match the running server/Hermes executables, libraries,
  service instances/PIDs/restarts, boot, protected network files and private
  identity. No service restart, firmware reload, MMIO, I2C or SPI operation.

Evidence directory: `management-link.skEsLwel`. Native qualification SHA-256:
`443e36f39dd4b79788b06222bd52c980187c6cd26852020e575c48369e8e8b05`.
Probe SHA-256:
`8e3641bc48d7c53d6bd04d6cfbf9bcbea87787d124c23ddfd529ff4dbaec2ee3`.
The owner-only board test directory `/tmp/daphne-link-native.XX9k4SmX` is retained.
Its test archive contains no private identity artifact or server replacement.

## Repeat safely

Build matching server/tests/bindings using the existing build instructions. The
standalone probe loads the installed private identity, verifies its management
baseline and emits only the link submessage as protobuf hex inside JSON:

```bash
sudo env LD_LIBRARY_PATH=/usr/lib/daphne-server \
  /path/to/management_link_probe /etc/daphne-identity.pb
```

Do not print the parent identity message. The probe's initial ARM JSON-helper
link failed on an extra Abseil symbol; `bffea24` uses core protobuf serialization
and works with the already installed minimal libraries.

After a separately qualified server installation, the existing client can
require all 14 fields and up negotiation:

```bash
python daphne-server/scripts/verify_board_identity.py \
  --endpoint tcp://127.0.0.1:44015 \
  --proto-dir /path/to/matching/protobuf \
  --identity-file /private/path/daphne015-identity.pb \
  --expected-build-id 0x03F17F1B --require-link-status
```

This flag now passes on the deployed bffea24 server. It is not expected to pass
on historical server 3f636f4. Updated FPGA-health verification likewise needs
the new carrier/state evidence.

## Live deployment and regression

Only `/usr/bin/daphneServer` was replaced after confirming the previous process
stopped. The normal runtime restart reloaded the **same** installed FPGA image,
`3f17f1b`, self-trigger ABI 2.0. The previous binary remains in RAM under
`/run/daphne-candidate-bffea24/previous-server`; older backups are retained.

The pre-FE policy guard failed immediately after reload; its raw mismatching
value was not recorded. Full zero-BIAS Configure restored the expected policy,
and the **unchanged** guard passed: generator enable 1, current selectors 0/0.
No weakened assertion or extra low-level register write was used.

Two 153-exchange aggregate runs bracketed bookkeeping qualification. Both AFE
orders, all five alignments and all 40 spybuffer channels passed. Bookkeeping
verified responsive heartbeat, gain-3 preflight rejection, direct-write
invalidation and canonical-hash restoration. Final FE remains offset 2200/x1,
trim 0, VGAIN 1700, all BIAS/BIASCTRL zero.

Six further suites passed: v0.5 telemetry/services/rejections (17 exchanges),
ADS1261 (93, including 80 CRC-checked acquisitions), SFP (5), regulators (7),
FPGA health (4), and identity with all 14 link fields required (5). Additional
live guards verify default redaction, fresh detailed link data, unchanged FE
bookkeeping and ABI 2.0 timestamp/parser-history unavailability.

Final PID **27394**, zero automatic restarts; service instance
`b25ec246b89d4ce6b2dc82559300fd18`. Private identity and all protected files match.
Root space remains writable with 23,662,592 bytes available; no cleanup/resizing.
Health remains **11 PASS / 1 external-timing FAIL / 3 UNKNOWN**, not overall OK.

Server SHA-256:
`cc8bf6c96ac8c97b7eef37d8e6bb794755a2d6aab7955c75e9bab2f6a9fd1ded`.
Live evidence: `management-link.skEsLwel/live-abi20.jMV1yCCS`; qualification SHA-256:
`aea8e0081cdc60a88e5c8526bc9beeeccced3185515a0f43509b356fb61ddaf2`.

The complete runtime archive SHA-256 is
`ff956a4fc41dec8035c6a0cb8a857b4aa2256d01321a639548214458cb8c1dad`.
It retains the exact legacy Hermes/private-library bytes, with no private
configuration. Native loader smoke resolves all three private libraries inside
the archive and passes `--help`, with runtime/boot/protected files unchanged.
Actual staging and recipe decisions accept all nine synthetic overlay-minor
pairs; this is not a BitBake/image or routed-firmware test. The image contract
now pins bffea24 and retains supported minors 0/1/2.

All **124 packaging tests** pass, including explicit rejection of the previous
3f636f4 archive under the new source pin. Test update: `214b676`.

The owner-only ONL handoff is `daphne015-server-runtime-bffea24`; see
[runtime contents and verification](qualified-server-runtime.md). It includes
matching bindings, native/live evidence and privacy-filtered source exports.
No private identity or network configuration is included.

I065/I068–I070 and the full I085 gateway/VLAN inventory comparison are not closed
by this work. Database assignments, firmware routing, SFP wiring/population and
the other [completion-plan gaps](server-v05-completion-plan.md) remain open.
