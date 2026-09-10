# Import hardware-database timing and MAC assignments

Tool commit `0c9d1b7`. Monitoring only: it produces a private identity artifact,
not network files or hardware commands. The deployed `3f636f4` server already
supports these fields; no server/protobuf/firmware rebuild is required.

## Why another input is needed

The CERN `ehn1-vst-daphne15` records provide crate/slot/detector and one Hermes
MAC/IP assignment. A read-only inventory of all 15 XML files and the work area's
`fddaq-v5.6.0-rc4-a9` appmodel schemas confirms that `DaphneV2BoardConf` has no
timing-endpoint or management-MAC attribute, and no superclass supplying one.
`tp_conf` is trigger configuration, not a timing assignment. This is a bounded
source/schema inspection, not proof of the active run-control database.

The existing hardware-database **`daphne.board-config`, version 1** export has
`network.production_mac` and `runtime.timing_endpoint`. The importer now combines
those with the verified OKS artifact, using the existing strict deployment
contract validator without invoking its renderer. No database is queried or changed.

## Prepare, do not apply

Use a full daphne-os checkout containing the tool commit. The previous
`daphne015-server-runtime-3f636f4` source handoff predates this importer.
An exact minimal tool layout is also saved on ONL in the owner-only home
directory **`daphne015-identity-import-0c9d1b7`**. Its eight file checksums and
Python 3.9 CLI help pass there. `SHA256SUMS` digest:
`b3cae7a14424cdbf614882cbd6ab37ff1ae9f373d031027618de9e7a644323ff`.
Read its `README.md`; it includes matching bindings but no private input or
synthetic assignment. It does not replace the existing runtime handoff.
Obtain an approved database export, its expected SHA-256 and explicit asset ID
through the normal assignment process. Do not substitute an observed seed/example,
edit `authorized`, or invent a timing address to make validation pass.

```bash
python3 daphne-server/scripts/prepare_identity_assignment.py \
  --review-file /private/path/identity-review.json \
  --source-root /private/path/ehn1-vst-daphne15 \
  --approved-link-file /private/path/10-ff0b.link \
  --approved-network-file /private/path/20-ff0b.network \
  --management-interface eth0 \
  --proto-dir /path/to/matching/protobuf \
  --hardware-db-config /private/path/board-config-v1.json \
  --hardware-db-asset-id "$EXPECTED_ASSET_ID" \
  --hardware-db-sha256 "$EXPECTED_BOARD_CONFIG_SHA256" \
  --output /private/path/new-identity.pb
```

All three new options must be supplied together. Without them, original artifact
bytes/semantics are unchanged. The export must be authorized, name the explicitly
selected asset and match the preserved management MAC and verified IPv4/baseline.
An EEPROM-based MAC policy must also agree with the export's factory MAC.
Timing must be an explicit 16-bit `0x` hexadecimal literal; zero retains field
presence. Names, bare decimal strings, overflow and malformed records are refused.

The output is exclusive-create, mode 0600; stdout contains hashes/status only.
Existing placement, Hermes assignments and approved baseline remain unchanged.
Added values reference the exact JSON bytes under the logical source name
`hardware-database/<input-basename>`, asset ID and dotted JSON attribute path.
The combined source-manifest hash is recomputed; DB revision numbers are retained
in the scope metadata. This is not authentication, physical SOM identification,
live database polling, or an implicit network/timing configuration update.

Before any separately controlled installation, the existing ARM
`identity_probe --validate-only` checks structure without network observation. Its normal mode
also compares the approved host baseline; see [identity deployment boundaries](board-identity-verification.md).
Do not install the synthetic test artifacts as board assignments.

## Evidence and remaining input

18 new importer tests; all **137 Python tests pass** with both host and ARM-build
bindings. Shared deployment regression: **69 passed, one optional jsonschema
test skipped**. The existing C++ loader accepts zero/ordinary/maximum-address
fixtures and rejects corrupted provenance on both x86 and the actual ARM board.
The ARM check used `--validate-only`; installed server/libraries, services, boot
and protected/private files were unchanged. These are synthetic software checks.

Evidence: `protocol-server.Mh4iBcOB/identity-gap.CFUMbteO`, including the redacted
CERN inventories, test logs and `native-artifact-loader.txt`.
No approved DAPHNE-015 hardware-database export was located, so its installed
private artifact remains unchanged and these two assignments remain unavailable.
Physical Hermes connector/LinkId mapping and additional link assignments are
not supplied by this database format and are still unresolved.
