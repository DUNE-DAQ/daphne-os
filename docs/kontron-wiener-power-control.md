# DAPHNE Rack-Power Remote Control

## Purpose and scope

This guide describes how to monitor and control the two remotely managed power
layers used for DAPHNE work:

- the Raritan PX4 rack PDU that distributes and switches upstream AC power;
- the Kontron Hartmann-WIENER system that generates the regulated DAPHNE DC
  rails.

Operators can use either:

- a local engineering desktop on the controls network; or
- a central Linux server reached through SSH.

It covers the common Ethernet interface used by PL5xx supplies, CML shelf
managers, MARATON remote controllers, and MPOD controllers. It does **not**
define DAPHNE voltage, current, ramp, or trip settings. Those values must come
from an approved run card for the exact supply, output module, cable, and load.

EDMS 2383681 identifies the DAPHNE output module and physical power topology,
but it does not identify the installed chassis/controller, network address,
firmware, MIB, SNMP channel instances, or credentials. Complete the inventory
in this document and obtain the approved run card before enabling writes.

## DAPHNE power baseline from EDMS 2383681

The controlled design source is *DUNE FD1-HD Photon Detector System Grounding
and Shielding Document*, EDMS 2383681, version 6.0 (January 2025), together with
the cold-warm schematic revision 10. The locally downloaded EDMS package has
SHA-256
`d8a58adea5cb38c04b5d84abe97900ea713c9ef42980bdab5c1781d44f71a942`.

For DAPHNE, that source establishes:

| Item | Design baseline |
|---|---|
| Output module | 8-channel WIENER MPV8060 low-voltage module |
| Nominal board input | 48 V |
| Channel allocation | One dedicated power-supply channel per DAPHNE board |
| Return | Floating at the supply; connected to DAPHNE `CH_GND` and `GND` at the load |
| Sense wiring | Power and sense wires are joined at the load, through the DAPHNE F1/F3 arrangement |
| Distribution | MPV8060 DSUB37 outputs, passive 16-channel Power Interface Distribution box, then one DSUB9 cable per DAPHNE |
| Approximate distance | Supply rack 20--25 m from the warm electronics; documented DSUB9 cable length 30 m |
| Grounding | Supply rack has an independent cavern-safety-ground connection; preserve the documented cable-shield and single cryostat-ground topology |

EDMS 2383681 also records 0.46 A idle current, an estimated 33 W / 0.69 A at
full load, and calculated cable drops of 0.55 V and 0.83 V respectively. It
states a 1 A MPV8060 channel maximum and a calculated 1.2 V cable drop at that
current. These are design and measurement references, **not** approved remote
setpoints, alarm thresholds, current limits, or trip limits. Do not copy them
into control software as operating limits.

The same EDMS document assigns MPV8030 channels to the calibration-module
`power` inputs and MPV8060 channels to their `bias` inputs. Those loads are not
DAPHNE channels and must have separate inventory, run cards, and authorization;
never infer a load type from the output-module model alone.

The following controlled inputs are still required:

- [EDMS 2383689](https://edms.cern.ch/document/2383689), *Power supplies for
  DAPHNE and calibration modules*, for the detailed supply/cable definition and
  any released operating parameters;
- [EDMS 2840128](https://edms.cern.ch/document/2840128) for the Power Interface
  Distribution box definition;
- the approved electrical-safety/run-card material, including EDMS 3224728
  where applicable;
- the installed chassis and controller identity, firmware, vendor MIB, and
  controller-to-physical-channel map; and
- a locally verified rack/slot/channel-to-DAPHNE asset map.

Treat this source hierarchy explicitly: EDMS 2383681 controls the documented
topology and grounding intent; the released supply document and run card
control operating values; the installed firmware's MIB controls SNMP object
names, types, ranges, and enumerations. A value appearing in one layer does not
replace a required value from another.

## Upstream AC layer: Raritan PX4-54A7CR-A0

The supplied product reference identifies a Raritan `PX4-54A7CR-A0`: a 1U,
single-phase, outlet-metered and outlet-switched rack PDU with ten NEMA 5-20R
outlets, an IEC C20 inlet, and a 100--120 V / 20 A input rating (16 A rated
load, up to 1.9 kVA). Treat those values as procurement information until the
received unit's nameplate and configuration page have been checked.

This PDU controls **AC outlets**, not MPV8060 output channels. If a WIENER
chassis is connected to one PX4 outlet, switching that outlet can remove power
from every DAPHNE channel in that chassis. Normal board-level operations must
therefore use the WIENER channel controller. Reserve PX4 outlet switching for
an approved rack startup, shutdown, maintenance, or recovery procedure.

PX4 provides an HTTPS web interface, SSH command-line access, SNMP v2/v3,
JSON-RPC, Redfish, and Modbus/TCP. For automation, prefer a dedicated PX4 API
account with the minimum outlet permissions and either JSON-RPC over HTTPS or
SNMPv3. Do not share the browser administrator account with production
software. Record the exact firmware and use the matching Raritan SDK or MIB;
API and object behavior is firmware-specific.

Raritan reports a flash-write-cycle issue in Xerus firmware 4.0.0 through
4.3.12 and recommends 4.3.13 or later. This issue does not affect outlet power
state, but an affected unit should have a vendor-supported upgrade planned
before production use. Never downgrade firmware, and do not upgrade until the
controller type, current version, configuration backup, compatibility, and
maintenance window have been verified.

Before enabling PX4 writes, record:

```yaml
asset_id: RARITAN-PX4-EXAMPLE-001
manufacturer: Raritan
model: PX4-54A7CR-A0
serial_number: exact nameplate value
controller_type: exact value reported by the unit
firmware: exact reported Xerus version
mac_address: controller Ethernet MAC
ipv4_address: approved static address or DHCP reservation
controls_vlan: VLAN-ID
api: json-rpc-https | snmpv3
read_credential_id: secret-manager reference
switch_credential_id: secret-manager reference
outlet_map_revision: controlled document revision
outlets:
  1:
    label: exact durable outlet label
    downstream_asset: exact WIENER chassis or other rack asset
    permitted_operations: [status]
```

Map all ten outlets, including unused ones. Disable switching permission for
unused or uncommissioned outlets. The outlet map must name the downstream
asset; descriptions such as `supply` or `rack` are not sufficient for remote
operation.

## Supported control paths

| Controller family | Normal remote path | Initial/local setup | MIB starting point |
|---|---|---|---|
| Ethernet option on PL5xx or older crate | Embedded web page and SNMP v2c | Front panel; USB/serial on some variants | `WIENER-CRATE-MIB` |
| CML00/CML01 shelf manager | Embedded web page and SNMP; SYScontrol where supported | USB or local display, depending on option | `HEL-CRATE-MIB` on newer CML; `WIENER-CRATE-MIB` on older units |
| MARATON RCM | SNMP over Ethernet | USB configuration utility | `WIENER-CRATE-MIB` |
| MPOD controller | Embedded web page and SNMP v2c | USB2 for setup/firmware; optional local display | MIB supplied with the installed MPOD controller firmware |

The MPOD controller provides Ethernet, a web server, SNMP v2c, USB setup, and
a hardware interlock. The PL5xx Ethernet option and MARATON/CML controllers
provide similar remote monitoring, but their object names and channel layouts
are not interchangeable.

## Safety boundary

Remote control is not an emergency-off system and does not replace a hardware
interlock, disconnect, breaker, lockout/tagout procedure, or local verification.

Before any write:

1. Identify the physical supply and controller by asset label and model.
2. Confirm the output-to-load cable map.
3. Confirm the approved set points and trip limits for that load.
4. Verify the hardware interlock and cooling state.
5. Read the present output state, measurements, and fault words.
6. Hold an exclusive software lock for the supply.
7. Log the operator, reason/work order, old state, requested state, and result.

Never automatically re-enable a channel after an over-current, over-voltage,
over-temperature, fan, interlock, or communication fault. A failed readback is
an unknown state, not evidence that an output is off.

For work on cables or hardware, switch off remotely, verify voltage and current
have fallen to the approved safe thresholds, then use the physical isolation
procedure.

## Recommended network architecture

### Central server: preferred for routine operation

```text
operator desktop
      |
      | SSH with named account
      v
power-control server -- audit log / lock / approved wrapper
      |
      | controls VLAN, authenticated APIs
      v
Raritan PX4 outlet -- AC -- Kontron/WIENER controller
                               |
                               | hardware interlock / regulated DC
                               v
                            DAPHNE
```

Only the control server should know write credentials for either layer.
Operator desktops receive SSH access to a restricted wrapper, not unrestricted
PX4 API access or `snmpset`. This gives one place for authorization, locking,
logging, monitoring, and later integration with the board-production database.

Recommended firewall policy:

- allow HTTPS to the PX4 and WIENER controller only from the control server and
  an approved engineering subnet when their web interfaces are needed;
- allow SNMP polling and writes only from the control server;
- allow SNMP traps to the monitoring server if traps are configured;
- deny access from general-purpose and public networks.

These controllers commonly use SNMP v2c community strings, which are not a
modern authenticated/encrypted control mechanism. Keep them on an isolated
controls VLAN or behind a managed VPN and source-address ACL. Do not expose a
controller directly to the Internet.

### Direct desktop: acceptable for commissioning

A desktop on the same approved controls network can use:

- the PX4 HTTPS interface for nameplate/configuration verification and
  authorized outlet monitoring;
- the controller's embedded web interface for identification and basic manual
  monitoring/control;
- Net-SNMP command-line tools for deterministic reads and carefully reviewed
  writes; or
- the vendor SYScontrol/MUSEcontrol utility when it supports the installed
  controller and desktop operating system.

Prefer Ethernet even when working locally. USB is primarily useful for first
network configuration, recovery, or firmware maintenance and may require a
model-specific driver and vendor utility.

Do not attempt to tunnel SNMP by forwarding a random TCP port through SSH.
SNMP normally uses UDP; run the approved command on the control server through
SSH instead.

## Inventory required before connection

Create one controlled record per supply:

```yaml
asset_id: WIENER-EXAMPLE-001
location: RACK-ROW-U
manufacturer: Kontron Hartmann-WIENER
chassis_model: exact chassis designation; not established by EDMS 2383681
controller_model: exact front-panel/controller designation
controller_firmware: exact reported version
output_module: WIENER MPV8060
mac_address: controller Ethernet MAC
ipv4_address: approved static address or DHCP reservation
controls_vlan: VLAN-ID
mib_file: exact filename
mib_sha256: SHA256-of-vendor-file
read_credential_id: secret-manager reference
write_credential_id: secret-manager reference
interlock: description and test record
channel_map_revision: controlled document revision
topology_source: EDMS 2383681 v6.0 / schematic rev 10
supply_definition: EDMS 2383689 revision
distribution_box_definition: EDMS 2840128 revision
approved_run_card: controlled document and revision
```

Do not store community strings in this repository or in the hardware database.
Store secret references only.

Create a separate PX4 record using the upstream inventory example above. Link
the WIENER asset to its PX4 asset and outlet, but do not collapse the AC outlet
and DC channel into a single identifier or state.

## Install client tools

### Debian or Ubuntu

```bash
sudo apt-get update
sudo apt-get install snmp
```

### Fedora, Rocky Linux, or RHEL

```bash
sudo dnf install net-snmp-utils
```

### macOS

```bash
brew install net-snmp
```

On Windows, use the embedded web page, a vendor-supported SYScontrol build, or
run the Linux Net-SNMP tools in WSL from a network where UDP access to the
controller is permitted.

Obtain the exact MIB delivered with the controller firmware or from Kontron
support. Do not copy an arbitrary MIB from another supply. On a dedicated Linux
control server it can be installed, for example, as:

```bash
sudo install -o root -g root -m 0644 VENDOR-MIB.txt /usr/share/snmp/mibs/
sha256sum /usr/share/snmp/mibs/VENDOR-MIB.txt
```

If the distribution disables MIB loading by default, select the file explicitly:

```bash
export MIBDIRS="+/usr/share/snmp/mibs"
export MIBS="+WIENER-CRATE-MIB"
```

Use `HEL-CRATE-MIB` instead when that is the MIB supplied for the controller.

## Establish read-only communication

Set placeholders for the current terminal. Do not paste a real community into
documentation, tickets, chat, or shell scripts committed to Git.

These direct commands pass the expanded community to a client process and are
appropriate only on a secured commissioning host. Do not enable shell tracing.
For routine operation, the server wrapper should retrieve credentials from a
root-owned secret store immediately before use and never include them in logs.

```bash
SUPPLY_HOST='<approved-hostname-or-ip>'
RO_COMMUNITY='<read-only-community>'
MIB='WIENER-CRATE-MIB'
```

First verify ordinary network identity:

```bash
getent ahostsv4 "$SUPPLY_HOST"
ping -c 2 "$SUPPLY_HOST"
```

Then query only the standard SNMP system subtree. Net-SNMP defaults to the
standard SNMP agent UDP port unless a device-specific address says otherwise.

```bash
snmpwalk -v2c -c "$RO_COMMUNITY" -t 1 -r 2 \
  "$SUPPLY_HOST" .1.3.6.1.2.1.1
```

Record the reported description, object ID, name, firmware/version information,
and controller MAC. If the standard subtree is not implemented, use the
vendor-MIB root documented for that controller rather than assuming the unit is
unreachable.

Test MIB loading separately from network access:

```bash
snmptranslate -m "+$MIB" -Tp | less
snmptranslate -m "+$MIB" -Td "$MIB"::crate
```

The CML manual uses a read-only walk of the `crate` subtree:

```bash
snmpwalk -v2c -c "$RO_COMMUNITY" -t 1 -r 2 \
  -m "+$MIB" "$SUPPLY_HOST" "$MIB"::crate
```

If symbolic names fail but numeric OIDs work, the problem is local MIB loading,
not the controller.

## Discover channels without guessing indexes

WIENER MIB revisions commonly expose output-table objects with names similar
to:

- `outputName`;
- `outputSwitch`;
- `outputVoltage`;
- `outputMeasurementSenseVoltage`;
- `outputMeasurementCurrent`; and
- `outputStatus`.

Treat those as discovery hints, not a portable API. Confirm every object in the
installed MIB:

```bash
snmptranslate -m "+$MIB" -Td "$MIB"::outputSwitch
snmptranslate -m "+$MIB" -On "$MIB"::outputSwitch
```

Walk the read-only name, measurement, and status columns and save both symbolic
and numeric output. Exact instances may encode slot and channel numbers and
must be matched to the physical cable map.

```bash
snmpwalk -v2c -c "$RO_COMMUNITY" -m "+$MIB" \
  "$SUPPLY_HOST" "$MIB"::outputName
snmpwalk -v2c -c "$RO_COMMUNITY" -m "+$MIB" \
  "$SUPPLY_HOST" "$MIB"::outputMeasurementSenseVoltage
snmpwalk -v2c -c "$RO_COMMUNITY" -m "+$MIB" \
  "$SUPPLY_HOST" "$MIB"::outputMeasurementCurrent
snmpwalk -v2c -c "$RO_COMMUNITY" -m "+$MIB" \
  "$SUPPLY_HOST" "$MIB"::outputStatus
```

If an object is absent, stop and consult the exact MIB. Do not substitute a
similar-looking OID from another controller.

## Controlled writes

`snmptranslate -Td` shows whether an object is writable, its ASN.1 type, range,
and enumerated values. Use those definitions. Do not assume that integer `0`
means off or `1` means on; historical MIB/firmware combinations may differ.

The generic write sequence is:

```bash
RW_COMMUNITY='<read-write-community>'
INSTANCE='<instance-copied-from-the-verified-read-only-walk>'

# 1. Describe the object and capture its allowed values.
snmptranslate -m "+$MIB" -Td "$MIB"::outputSwitch

# 2. Read the exact instance before changing it.
snmpget -v2c -c "$RO_COMMUNITY" -m "+$MIB" \
  "$SUPPLY_HOST" "$MIB"::outputSwitch."$INSTANCE"

# 3. Set the exact type/value specified by that MIB.
snmpset -v2c -c "$RW_COMMUNITY" -m "+$MIB" \
  "$SUPPLY_HOST" "$MIB"::outputSwitch."$INSTANCE" \
  '<TYPE>' '<VALUE-FROM-MIB>'

# 4. Read back command, voltage, current, and status.
snmpget -v2c -c "$RO_COMMUNITY" -m "+$MIB" \
  "$SUPPLY_HOST" \
  "$MIB"::outputSwitch."$INSTANCE" \
  "$MIB"::outputMeasurementSenseVoltage."$INSTANCE" \
  "$MIB"::outputMeasurementCurrent."$INSTANCE" \
  "$MIB"::outputStatus."$INSTANCE"
```

The angle-bracketed fields are intentionally not executable values. Replace
them only after verifying the installed MIB and approved channel map.

Do not change voltage, current limit, ramp, trip, group, or fault-action objects
with ad-hoc `snmpset` commands. Those settings should be generated from a
versioned run card and checked against model-specific bounds before a write.

## Safe switch-off procedure

1. Acquire the exclusive supply lock.
2. Confirm asset ID, controller identity, channel name, and physical load.
3. Read and log switch state, sense voltage, current, and status/fault words.
4. Issue the MIB-defined off value.
5. Poll until the command reports off and measurements are below approved safe
   thresholds, or until the approved timeout expires.
6. If readback fails or remains energized, stop and escalate locally.
7. Release the lock only after the final state is logged.

For a multi-channel load, use the approved shutdown order. Do not assume a
crate-level off is electrically equivalent to the required channel sequence.

## Safe switch-on procedure

1. Acquire the exclusive supply lock.
2. Confirm the work authorization and that no person is working on the load.
3. Verify interlock, cooling, fan, temperature, and input-power state.
4. Verify the channel is off and has no uncleared fault.
5. Read back the approved set point, current limit, ramp, trip, and group
   behavior without changing them.
6. Issue the MIB-defined on value to one approved channel/group at a time.
7. Poll switch state, measured voltage/current, and status through the complete
   ramp interval.
8. Switch off and stop on an unexpected measurement, trip, timeout, or loss of
   communication. Do not retry automatically.

## Whole-chassis AC shutdown and startup

These procedures apply only when the approved operation requires switching the
PX4 outlet feeding a WIENER chassis. Do not use the PX4 `cycle` action as a
shortcut for a DAPHNE reset.

For shutdown:

1. Acquire one lock covering the PX4 outlet, WIENER chassis, and every
   downstream channel.
2. Verify the PX4 outlet map and enumerate all downstream loads.
3. Apply the approved DAPHNE shutdown order at the WIENER channel layer.
4. Verify every downstream channel reports off and its measurements meet the
   approved safe thresholds.
5. If required by the WIENER manual/run card, use its controller-level shutdown
   before removing AC.
6. Switch off the mapped PX4 outlet and verify both commanded state and
   outlet-level measurements.
7. Log both layers' final states before releasing the lock.

For startup:

1. Acquire the same combined lock and confirm the work authorization.
2. Verify the WIENER channels will remain off when AC is restored. The PX4 and
   WIENER power-on-state policies must be tested; do not assume either device's
   default behavior.
3. Switch on the mapped PX4 outlet and verify its state and AC measurements.
4. Wait for the WIENER controller, cooling, interlock, and communications to
   reach their approved healthy states.
5. Read back all DC settings and confirm that no output enabled unexpectedly.
6. Apply the approved one-channel-at-a-time DAPHNE startup procedure.
7. Preserve all AC- and DC-layer evidence under the same operation ID.

If PX4 communication is lost after an outlet command, the AC state is unknown.
Do not infer it from the WIENER network response; obtain independent readback
or local verification.

## Server-side operating pattern

Operators should normally invoke a restricted command on the control server:

```bash
ssh power-control.example \
  'sudo -u daphne-power /opt/daphne-power/bin/powerctl status WIENER-ASSET CHANNEL'
```

The future `powerctl` wrapper should:

- accept asset and logical outlet/channel names, never arbitrary OIDs or API
  object paths;
- model PX4 outlets and WIENER channels as separate, linked resources;
- resolve the controller, MIB, and SNMP instance from controlled inventory;
- default to read-only status;
- require `--apply`, an operator identity, and a reason for writes;
- take locks across the full affected power tree before any state-changing
  sequence;
- allow only released operations such as `status`, `on`, and `off`;
- validate set points against the released run card;
- perform pre-read and post-read verification;
- write structured evidence to the production database or an append-only log;
- clear write credentials from its environment; and
- fail closed on timeout, inconsistent identity, stale configuration, or
  unknown status bits.

Do not expose a generic web endpoint that accepts an SNMP OID and value. If a
service API is added, it should expose logical, authorized operations and use
the same lock, validation, and evidence path as the CLI.

## Monitoring

A server may poll read-only measurements and status at a conservative rate.
Start with a 5–10 second interval unless the controller manual specifies a
different safe rate. Store timestamp, asset, channel, command state, measured
voltage/current, temperature, status word, and communication health.

SNMP traps can reduce fault-notification latency, but they do not replace
polling or post-command readback. Trap receivers normally listen on UDP 162 and
must be tested with the exact controller firmware and firewall policy.

Monitoring must never automatically clear a trip or turn an output back on.

## Troubleshooting

| Symptom | Checks |
|---|---|
| No ping or web page | Power/link LEDs, cable, controls VLAN, DHCP/static address, local display/front-panel configuration, firewall |
| Web works, SNMP times out | UDP SNMP ACL, source address, SNMP version, community, controller configuration |
| Numeric OID works, symbolic OID fails | Correct MIB file, `MIBDIRS`, `MIBS`, missing dependent MIBs, MIB syntax errors |
| `No Such Object` or empty output table | Wrong controller MIB/firmware, wrong subtree, module not discovered on internal CAN bus |
| SET reports authorization or not-writable error | Read-only credential, source ACL, object is read-only, wrong MIB; do not weaken access controls blindly |
| SET succeeds but readback disagrees | Wrong instance, interlock/trip, ramp still active, controller fault, stale MIB; switch off if safe and escalate |
| Output trips | Preserve status and measurements, leave off, inspect hardware/interlock/load; do not auto-reenable |

## Commissioning checklist

- [ ] PX4 nameplate, serial number, controller type, firmware, MAC, IP, and
      controls VLAN recorded from the received unit rather than the reseller
      listing.
- [ ] Firmware checked against the Raritan flash-write-cycle advisory; any
      required upgrade completed through an approved maintenance procedure.
- [ ] All PX4 outlets durably labeled and mapped to exact downstream assets;
      unused outlets have no switching permission.
- [ ] PX4 power-on behavior and every connected WIENER chassis's post-AC-loss
      behavior tested with safe loads before DAPHNE connection.
- [ ] EDMS 2383689, EDMS 2840128, and the applicable approved safety/run-card
      revisions obtained and reviewed against the as-built rack.
- [ ] Asset, model, controller, firmware, MAC, IP, VLAN, and location recorded.
- [ ] Every DAPHNE has exactly one dedicated MPV8060 channel in the controlled
      map; rack, chassis, slot, connector, channel, cable, and board identity
      have been independently cross-checked.
- [ ] Floating return, load-end sense connection, shield termination, cavern
      safety ground, and the rack's single cryostat-ground path match the
      approved design and as-built inspection.
- [ ] Exact vendor MIB and SHA-256 recorded.
- [ ] Physical channel map independently reviewed.
- [ ] Read-only and read/write credentials separated.
- [ ] Controller reachable only from approved networks/hosts.
- [ ] Hardware interlock tested.
- [ ] Read-only system and output walks archived.
- [ ] Every writable object/type/enumeration verified from the installed MIB.
- [ ] Approved run card and safe thresholds available.
- [ ] Off procedure tested with a safe or disconnected load.
- [ ] On procedure tested one channel at a time.
- [ ] Server lock, authorization, and audit logging tested.
- [ ] Loss-of-network, bad credential, trip, and inconsistent-readback cases tested.

## References

- [Raritan PX4-54A7CR-A0 reseller listing](https://matrixsolutionsinc.com/raritan-px4-54a7cr-a0-outlet-metered-and-switched-1u-10-outlet-120v-20a/)
  for the candidate SKU and electrical/form-factor description; verify against
  the received unit.
- [Raritan PX4 technical specifications](https://www.raritan.com/products/power/power-distribution/rack-pdu/tech-specs)
  for supported remote-management and automation interfaces.
- [Raritan PX4 support and firmware downloads](https://www.raritan.com/support/product/pdu-g4)
  for current firmware advisories, user guides, MIBs, and JSON-RPC bindings.
- DUNE [EDMS 2383681](https://edms.cern.ch/document/2383681), *DUNE FD1-HD
  Photon Detector System Grounding and Shielding Document*, version 6.0,
  January 2025; cold-warm schematic revision 10. Controlled source for the
  DAPHNE topology summarized above.
- DUNE [EDMS 2383689](https://edms.cern.ch/document/2383689), *Power supplies
  for DAPHNE and calibration modules*. Required controlled source; not present
  in the local download at the time of writing.
- DUNE [EDMS 2840128](https://edms.cern.ch/document/2840128), Power Interface
  Distribution box documentation. Required controlled source; not present in
  the local download at the time of writing.
- DUNE [EDMS 3224728](https://edms.cern.ch/document/3224728), electrical-safety
  documentation referenced by EDMS 2383681.
- [Kontron/WIENER Ethernet option](https://www.kontron.com/en/products/ethernet-option/p188858)
- [Kontron MPOD controller](https://www.kontron.com/en/products/mpod-controller-lv-hv-or-both/p187736)
- [Kontron CML00 manual](https://www.kontron.com/downloads/datasheets/c/chassis-monitor-and-control/cml00_manual_rev_6.pdf?product=188816)
- [Kontron MARATON technical manual](https://www.kontron.com/downloads/manuals/m/maraton-moderate-he-manual.pdf?product=187860)
- [Kontron PL512 product page](https://www.wiener-d.com/product/pl512-power-supply-system/)
- [Net-SNMP command manuals](https://www.net-snmp.org/docs/man/)
- [Net-SNMP `snmpset` tutorial](https://www.net-snmp.org/tutorial/tutorial-5/commands/snmpset.html)
