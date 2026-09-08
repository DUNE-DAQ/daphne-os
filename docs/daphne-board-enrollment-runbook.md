# DAPHNE board enrollment: AMD comparison and one-board procedure

Status: proposed factory and deployment runbook

Implementation note: phase 1/2 production enrollment now uses the versioned
contracts and split lifecycle commands in the companion `hardware-database`
repository (`tools/daphne_production_cli.py`). The older one-step
`daphne_staging.py enroll` flow described as historical context below is an
HWDB-handoff prototype, not the production station interface. The firmware
renderer consumes `daphne.board-config` version 1 JSON and does not depend on
the database backend.

## The central decision

Production must explicitly choose whether the network MAC follows the Kria SOM
or the logical DAPHNE asset. The hardware database remains the approval and
network-admission authority in either case.

```text
Policy A -- som_eeprom
  SOM EEPROM MAC -> registered against asset -> network allowlist

Policy B -- daphne_pool
  DAPHNE asset -> allocated MAC -> provisioned U-Boot override -> allowlist
```

The SOM UUID is unknown until the SOM is powered and read. That is expected.
It is discovered during enrollment and bound to an existing DAPHNE asset
record. Under Policy A, replacing the SOM changes the MAC and requires a
database/network update. Under Policy B, replacing the SOM changes only the
SOM binding and the asset normally keeps its MAC, IP, and hostname.

Do not prepare a manually edited `UUID -> MAC -> IP` list. Reserve controlled
IP/endpoint pools and, only for Policy B, a MAC pool. Use one database
transaction to discover/bind the UUID and register, allocate, or recover the
board's assignments.

## AMD intended flow versus DAPHNE

| Topic | AMD/Xilinx intended Kria production flow | DAPHNE flow with fixed hardware |
|---|---|---|
| When identity is created | SOM/carrier manufacturer creates serial, revision, UUID, and MAC records during manufacturing. | DAPHNE creates the asset record before or during intake; SOM UUID is discovered at first powered enrollment. |
| Hardware identity storage | IPMI FRU EEPROM: SOM at `0x50`, carrier at `0x51` when present. | Existing SOM EEPROM at `0x50` plus scanned DAPHNE asset tag. The reviewed DAPHNE V2 carrier has no populated carrier FRU. |
| MAC source | Valid AMD MAC OEM record in EEPROM; K26 MAC ID 0 represents primary PS Ethernet. | Policy A registers that valid SOM MAC. Policy B allocates an approved DAPHNE MAC and retains the EEPROM MAC as observed hardware data. |
| Carrier recognition | U-Boot reads SOM and carrier EEPROMs, exports `board_*`/`card1_*`, and can select carrier-specific behavior. | Carrier type/revision is recorded against the scanned asset and fixed software release; it cannot be discovered automatically from carrier hardware. |
| U-Boot MAC | Xilinx U-Boot initializes `ethaddr`, `eth1addr`, ... from valid EEPROM MAC records when the environment has no valid override. | Policy A verifies/uses the EEPROM-derived `ethaddr`; Policy B provisions the database MAC into `ethaddr`. Random fallback is a failure. |
| Linux handoff | U-Boot can update `mac-address` and `local-mac-address` through `ethernetN` aliases in the working FDT. | Same handoff for either policy; Linux must not replace the FDT MAC. |
| IP address | Not defined by the AMD EEPROM identity scheme; the deployer supplies network policy. | Allocated from the DAPHNE/site IP pool and stored in the same board record. |
| Network admission | Outside the Kria EEPROM specification. | Network automation exports approved MAC/IP/VLAN entries directly from the hardware database. |
| SOM replacement | EEPROM identity naturally changes with the SOM. | Policy A registers the replacement SOM MAC and updates admission; Policy B keeps the asset MAC and reprovisions it on the replacement SOM. |

AMD's EEPROM guide explicitly says the UUID supports customer enrollment and
that board information is assigned at manufacturing time. DAPHNE moves part of
that manufacturing step to a controlled first-power enrollment station because
the released hardware cannot store the required DAPHNE carrier identity.

References:

- [AMD Kria IPMI EEPROM Design Guide](https://xilinx.github.io/kria-apps-docs/creating_applications/2022.1/build/html/docs/IPMI_EEPROM_design_guide.html)
- [AMD Kria EEPROM Mapping](https://xilinx.github.io/kria-apps-docs/creating_applications/2022.1/build/html/docs/EEPROM_mapping_for_Kria_products.html)
- [AMD Kria U-Boot Handoff](https://xilinx.github.io/kria-apps-docs/bootfw/build/html/docs/bootfw_uboot_handoff.html)
- [Xilinx U-Boot board EEPROM handling](https://github.com/Xilinx/u-boot-xlnx/blob/xlnx_rebase_v2026.01/board/xilinx/common/board.c)

## Information prepared before opening a SOM

Before powering any unit, approve allocation pools. Do not invent assignments
at the bench.

### DAPHNE asset pool

Prepare or print unique asset tags and board IDs, for example:

```text
asset_tag: NP04-DAPHNE-015
board_id:  daphne-015
```

Create the asset record with status `received` or `pending_enrollment`. At this
point the SOM UUID may be empty.

### MAC pool, only for a DAPHNE-owned override

Policy A needs no new pool for primary PS Ethernet: enrollment reads the valid,
unique SOM MAC and registers it in the database. Policy B requires a MAC block
approved by the organization/network authority. Record:

```yaml
pool_id: daphne-production-mac
start: "<first-approved-MAC>"
end: "<last-approved-MAC>"
allocation_policy: sequential
interfaces_per_board: 1  # or 2 if ff0c is deployed
```

Required capacity is:

```text
(production boards + spares + repair replacements + growth reserve)
    * MAC-bearing interfaces per board
```

Add operational headroom, commonly at least 20 percent. If two MACs are needed
per board, allocate them as a pair in one transaction so a partial assignment
cannot occur.

The existing locally administered `ba:be:...` pattern can be used only if the
network authority reserves it across every connected L2 domain. Prefer an
organization-owned IEEE allocation for long-lived production equipment.

### IP pool

The network team provides the subnet/VLAN and excluded addresses:

```yaml
pool_id: daphne-management-ip
subnet: "<approved-subnet/prefix>"
gateway: "<gateway>"
dns: ["<dns1>", "<dns2>"]
vlan: "<VLAN>"
excluded:
  - "<gateway>"
  - "<network infrastructure range>"
  - "<DHCP or reserved range>"
```

Reserve one management IP per DAPHNE board plus spares and growth. Static
addresses must be outside any uncontrolled DHCP pool, or be represented as
reservations managed from the same database export.

### Other pools/defaults

Approve before enrollment:

- hostname pattern and numeric range;
- timing endpoint address range;
- allowed firmware applications and timing profiles;
- carrier hardware revisions;
- default endpoint timeout/success states;
- clock-chip bus/address by carrier revision;
- database roles allowed to enroll, replace, retire, or authorize a unit.

### Capacity example

For 100 planned boards, 10 service spares, and 20 percent growth:

```text
allocatable board identities = ceil((100 + 10) * 1.20) = 132

Policy B, one overridden interface  -> reserve at least 132 MACs
Policy B, two overridden interfaces -> reserve at least 264 MACs
Policy A, primary SOM interface      -> register each valid EEPROM MAC
one management IP per board          -> reserve at least 132 usable IPs
one unique timing endpoint per board -> reserve at least 132 endpoints
```

Subnet capacity must be calculated after removing network, broadcast, gateway,
infrastructure, DHCP, and other excluded addresses. A `/24` has 256 total IPv4
addresses but fewer usable DAPHNE addresses; the network team must approve the
actual subnet rather than infer it from the board count alone.

## Database states and uniqueness

Recommended lifecycle:

```text
received
  -> pending_enrollment
  -> provisioned
  -> qa_passed
  -> production/network_authorized
  -> service or retired
```

Use database uniqueness constraints on:

- `asset_tag`;
- `board_id`;
- active `som_uuid` and SOM serial;
- each MAC address;
- each static IP;
- hostname;
- timing endpoint address when it must be unique.

Allocation must be transactional. Two enrollment stations must not be able to
claim the same MAC or IP. A failed enrollment keeps its reservation attached
to the pending asset until an authorized operator releases or retries it.

Every change records operator/station, timestamp, previous value, new value,
reason/work order, and database revision.

### Implemented production database and legacy HWDB adapter

The companion `hardware-database` repository implements the versioned
production lifecycle separately from the reviewable HWDB adapter:

```text
hardware-database/
  specs/staging/daphne_hwdb.toml
  specs/staging/daphne_observed_seed.toml
  specs/staging/daphne_assets_template.csv
  tools/daphne_staging.py
  tools/daphne_production_cli.py
  schemas/daphne-production/v1/
  migrations/production/{sqlite,postgresql}/
  specs/production/daphne-production-qa-v1.json
  build/daphne-staging.db                 # generated
  build/daphne-hwdb-export/               # generated review package
```

It models a DAPHNE assembly and replaceable K26 SOM as separate HWDB items,
linked through the `Kria SOM` functional position. EEPROM inspection and
network enrollment are proposed HWDB test records. The database enforces the
identity, network-value, endpoint and active-installation uniqueness rules
listed above.

Initialize and verify it with:

```bash
git clone --branch marroyav/daphne-production-qa --single-branch \
  git@github.com:marroyav/hardware-database.git
cd hardware-database
make daphne-staging
make daphne-validate
make daphne-test
make daphne-export
```

The SQLite database under `build/` is generated state, not the source of the
HWDB type definitions. The tool does not write to live HWDB and does not
allocate a plausible-looking DUNE PID. See
[`daphne-staging-database.md`](https://github.com/marroyav/hardware-database/blob/marroyav/daphne-production-qa/docs/daphne-staging-database.md)
for the schema, commands and handoff format.

## One-board enrollment procedure

### Step 1: identify the DAPHNE asset

1. Scan the DAPHNE asset-tag/board-ID label.
2. Query the hardware database.
3. If the asset does not exist, an authorized intake operation creates it in
   `pending_enrollment`; an ordinary bench script must not create anonymous
   production assets.
4. Confirm the physical carrier revision matches the record.

### Step 2: install and power the SOM in isolation

Use an enrollment network or disconnected fixture. Do not connect the board to
the production network because its current identity is not authorized yet.

Boot to the U-Boot prompt and collect:

```text
i2c dev 1
i2c md 0x50 0.2 0x100
env print board_name board_rev board_serial board_uuid ethaddr
```

The station parses and validates the full FRU, including checksums, product,
serial, UUID, and MAC ID 0, rather than relying only on copied console text.
If booted Linux exposes the `at24` driver, the same FRU can be captured from
`/sys/bus/i2c/devices/1-0050/eeprom` with appropriate read privileges.

The production reader should automate this rather than hard-code values:

1. Locate the SOM `24c64` whose device-tree address is `0x50`.
2. Read the FRU without writing to the device.
3. Validate the common header, board-area, and multirecord checksums.
4. Decode manufacturer, product, serial, binary UUID, and MAC ID 0 according
   to the AMD Kria mapping.
5. Reject a malformed record, invalid/unicast MAC, or duplicate UUID/MAC.
6. Write a raw dump and a decoded discovery record into the QA evidence set.

For reference, the 2026-07-14 read-only inspection of `NP04-DAPHNE-015`
decoded:

```yaml
som_product: SM-K26-XCL2GC-ED
som_serial: XFL1YQLNWT4C
som_uuid: 70c5439d-de29-4263-8066-99627ad4ae5e
observed_som_mac: "00:0a:35:0e:9b:63"
```

This is evidence from one SOM, not a value to copy to another board.

### Step 3: look up the SOM UUID

The station queries by `board_uuid`:

```text
UUID already bound to this asset
    -> resume/verify the existing enrollment; allocate nothing new

UUID bound to another active asset
    -> quarantine; possible swapped SOM, duplicate entry, or process error

UUID not present and valid
    -> continue with a new SOM-to-asset binding

UUID missing, all ff, malformed, or duplicated
    -> quarantine for manual identity procedure; never fabricate a UUID
```

If the UUID is new, store it as the installed SOM component of the scanned
DAPHNE asset. Also store the observed EEPROM MAC even if Policy B will override
it.

### Step 4: allocate or recover board assignments

Within one database transaction:

1. Lock the asset record and relevant pools.
2. If the asset already has MAC/IP/hostname assignments, reuse them.
3. Select the primary MAC according to the record's immutable policy:
   - `som_eeprom`: validate uniqueness and register MAC ID 0 from `0x50`;
   - `daphne_pool`: reuse the asset MAC or reserve the next approved MAC/pair.
4. Reserve the next free IP in the correct subnet/VLAN.
5. Generate the hostname from the approved board ID rule.
6. Allocate or select timing endpoint and runtime profile.
7. Bind the discovered SOM UUID/serial.
8. Set state to `pending_enrollment` and commit one new database revision.

This transaction produces the authoritative mapping, conceptually:

```text
asset tag / board ID
    -> installed SOM UUID
    -> MAC source and static MAC(s)
    -> static IP / hostname / VLAN
    -> timing endpoint / firmware profile
```

Store the result as one canonical database record, for example:

```yaml
asset_tag: NP04-DAPHNE-015
board_id: daphne-015
lifecycle_state: pending_enrollment
network_authorized: false

hardware:
  carrier_revision: DAPHNE_V2
  som_product: SM-K26-XCL2GC-ED
  som_serial: XFL1YQLNWT4C
  som_uuid: 70c5439d-de29-4263-8066-99627ad4ae5e
  observed_som_mac: "00:0a:35:0e:9b:63"

network:
  mac_source: som_eeprom       # or daphne_pool
  ff0b_mac: "00:0a:35:0e:9b:63"
  ipv4_cidr: "10.73.137.16/24"
  gateway4: "10.73.137.1"
  hostname_fqdn: NP04-DAPHNE-015.CERN.CH
  vlan: "<approved-vlan>"

runtime:
  endpoint_addr_hex: "0x15"
  firmware_app: daphne_selftrigger_ol_a389fcd
  timing_profile: "<approved-profile>"

record_revision: "<database-revision>"
```

The example combines the observed SOM identity with the currently deployed
board/network values only to demonstrate the schema. Production still requires
database approval and QA before authorization.

### Step 5: generate per-board assets

Generate from that exact database revision:

```text
daphne-uboot.env
daphne-board.env
systemd .network files
identity-manifest.json
SHA256SUMS
network-allowlist candidate record
```

An optional signed `daphne-identity.itb` may package the same immutable
deployment snapshot for U-Boot validation/recovery. FIT means Flattened Image
Tree; it is not the editable hardware database.

The identity manifest records the asset, database revision, generation tool
version, signing-key ID, and hashes. No operator edits these products by hand.

### Step 6: provision U-Boot and storage

1. Install the optional signed identity in its primary and recovery locations
   if that recovery design is enabled.
2. Under Policy A, verify U-Boot obtains the registered EEPROM MAC. Under
   Policy B, provision `ethaddr`/`eth1addr` into the redundant U-Boot
   environment before any Ethernet use.
3. Install the common production image and board configuration.
4. Power cycle.
5. Confirm U-Boot sees the registered static MAC before any Ethernet command.

If the environment is blank, Policy A can recover from the valid SOM EEPROM.
Policy B requires controlled reprovisioning or a verified signed recovery
identity. Missing approved identity is a quarantine condition, not permission
to use a random MAC.

### Step 7: offline QA

Verify:

```text
database MAC
  == U-Boot ethaddr
  == working FDT MAC
  == Linux interface MAC
```

When a signed identity is used, its MAC must be equal as well.

Also verify board ID, IP, hostname, endpoint, firmware application, timing
profile, database revision, artifact hashes, reboot persistence, environment
erase/recovery, and overlay behavior.

On failure, keep the asset `pending_enrollment` or set `service`; do not release
its allocation automatically for another board.

### Step 8: authorize the network

1. Mark QA evidence accepted.
2. Transition the board to `qa_passed`.
3. An authorized release action sets `network_authorized=true` and state
   `production`.
4. Network automation consumes the hardware-database export and installs the
   MAC/IP/VLAN allowlist entry.
5. Connect the board to the production network and confirm the switch learns
   the same registered MAC on the expected port.

The network must not authorize directly from a bench-generated file. It reads
the approved hardware-database state.

## Repeated enrollment loop

For a batch, the station repeats the same transaction:

```text
scan asset
  -> power SOM
  -> read/validate UUID
  -> database lookup
  -> existing binding? verify and resume
  -> new valid UUID? bind and register/allocate atomically
  -> generate/provision
  -> offline QA
  -> approve network
```

This naturally produces the long list, but the list is a database result—not a
manually assembled prerequisite.

For the campaign, first resolve whether the controlled scope is 192 production
carriers plus spares or 200 production carriers. Then import only the
authoritative carrier list:

```bash
cd hardware-database
cp specs/staging/daphne_assets_template.csv /controlled/daphne-assets.csv
# Fill only from the approved asset inventory; do not synthesize missing IDs.
python3 tools/daphne_staging.py import-assets /controlled/daphne-assets.csv
```

The resulting `pending` records intentionally have no SOM UUID, serial or
factory MAC. Those values appear only after the station reads each physical
EEPROM. The current `enroll` command accepts approved MAC/IP/hostname/endpoint
values and commits the full binding atomically; a pool service or network
authority must supply those assignments.

## Replacement rules

### SOM replacement

1. Put the DAPHNE asset into `service` and remove/suspend network authorization.
2. Retire the old active SOM binding with the work-order reason.
3. Read the replacement SOM UUID.
4. Bind it to the same DAPHNE asset.
5. Apply the selected policy:
   - `som_eeprom`: register the replacement SOM MAC and replace the network
     allowlist entry after QA;
   - `daphne_pool`: keep and reprovision the asset's existing MAC.
   Keep IP, hostname, and endpoint unless site policy requires a change.
6. Regenerate identity assets, reprovision, rerun QA, and reauthorize.

### Complete DAPHNE asset replacement

Create a new asset record unless installation policy explicitly defines the
network identity as belonging to a detector slot rather than the physical
board. That ownership rule must be decided once and encoded in the database;
operators must not decide it ad hoc.

## Implemented baseline and production gaps

Implemented on the companion `hardware-database` branch
`marroyav/daphne-production-qa`:

1. DAPHNE carrier, K26 SOM, installation, deployment and QA-event tables;
2. proposed HWDB component types, test types and connector relationship;
3. carrier CSV import before SOM discovery;
4. atomic enrollment with UUID/MAC/IP/hostname/endpoint uniqueness checks;
5. HWDB-shaped JSON/CSV export with unresolved IDs clearly blocked from
   submission;
6. validation and unit tests;
7. the directly observed DAPHNE-015 seed, marked unqualified because its MAC
   chain currently disagrees across boot layers.

Still required before production:

1. authoritative campaign input, controlled asset labels, and resolution of
   the 192-versus-200 scope;
2. HWDB-team review and official system, subsystem, type, test and item IDs;
3. integration of the K26 FRU decoder and raw EEPROM evidence capture;
4. an approved transactional allocator or API for MAC (Policy B only), IP,
   hostname and timing endpoint, plus the network authorization interface;
5. base-DT/U-Boot/Linux cleanup so one MAC reaches every boot layer;
6. per-board U-Boot, Linux, manifest and allowlist-candidate generation;
7. an idempotent enrollment-station client for power control, current
   monitoring, EEPROM capture, provisioning, cold boot and evidence upload;
8. lifecycle authorization, audit-history completion, backup/restore and
   multi-station concurrency tests.
