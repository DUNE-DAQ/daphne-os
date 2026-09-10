# Management Ethernet telemetry — native-qualified, not deployed

Source: collector `d9c4732`, health correction `b631894`, client/probe `52e4cc9`,
minimal-runtime probe fix `bffea24`. The running server remains **3f636f4**;
the new server has cross-compiled, but its service/RPC deployment is pending.

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
- Before/after guards match the running server/Hermes executables, libraries,
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

This flag is intentionally **not expected to pass on current server 3f636f4**.
The updated FPGA-health verifier also expects the new carrier/state evidence.
Next: clean candidate/runtime packaging, guarded deployment, live RPC/default
redaction tests, full zero-BIAS FE/alignment/capture and collector regression,
then refresh the image pin and ONL runtime handoff. Preserve the old handoff.
I065/I068–I070 and the full I085 gateway/VLAN inventory comparison are not closed
by this work. Database assignments, firmware routing, SFP wiring/population and
the other [completion-plan gaps](server-v05-completion-plan.md) remain open.
