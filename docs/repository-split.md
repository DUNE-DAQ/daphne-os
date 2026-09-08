# Repository split and provenance

| Repository | Responsibility |
| --- | --- |
| [daphne-firmware](https://github.com/DUNE-DAQ/daphne-firmware) | HDL, constraints, Vivado/FuseSoC builds, logic/formal tests, hardware artifact generation |
| [daphne-os](https://github.com/DUNE-DAQ/daphne-os) | PetaLinux, server and client schemas, runtime services, OS images, recovery and deployment campaigns |

## Imported sources

OS tooling and recipes were transferred from firmware commit
`6d5c49db02286aff07bd6f2208f5e5f71f63af19`. Tracked modes and blob hashes were
compared before removing the firmware-side copies. OS wrappers now use
`DAPHNE_OS_ROOT`; input XSA, gateware output directories, and runtime bundles
remain explicit. Firmware DTBO generation and packaging tests stay with their
hardware producer.

New `COLLECT-METADATA.txt` files identify this checkout with `os_git_commit`
and `os_git_dirty`, replacing the pre-split `firmware_git_*` collector fields.
Gateware source hashes remain in each input overlay's `BUILD-METADATA.txt`;
the OS commit must never be interpreted as an FPGA build ID.

The previous `daphne-os` default tree at
`ae95b0dfa8e127a11dcc5c5a038bf67388e55cc5` contained legacy HDL. Its history is
retained unchanged; only the active migration tree replaces that legacy HDL
with the OS stack. Do not use that historical OS tree to build current HDL.

## Full daphneZMQ history

The server was imported without squashing from
`ecristal/daphneZMQ@77b39b7eb75204e1f2025f251a3a76ecf69d1d74` into
`daphne-server/`. Its imported tree is
`9cf22e0e0216a6535eeb882687d46b02f575b42f`. Original commit IDs, parents,
authors, timestamps, and notices are preserved; the upstream repository is not
rewritten or modified.

All 245 commits reachable from the upstream's 25 branches and 15 tags at the
migration snapshot are preserved. Branches become
`archive/daphneZMQ/<original-branch>` and tags become
`archive/daphneZMQ/<original-tag>`. Those references retain the original server
repository layout; only the active OS tree places it under `daphne-server/`.
The exact ref mapping and commit inventory are in
[daphne-server-history.json](daphne-server-history.json).

For example, after fetching the OS repository:

```bash
git log origin/archive/daphneZMQ/main -- srcs/server_controller/main.cpp
git show 77b39b7:srcs/protobuf/daphneV3_high_level_confs.proto
git log --all --graph --oneline
```

Do not squash-merge the history import: use a normal merge so original server
commits remain ancestors of the OS integration branch. The archive refs also
retain branches not reachable from the tested dual-gateware server revision.
No promise is made about already-deleted or unadvertised upstream refs.

## Releases and credentials

Published dual-gateware RC1 tags, assets, and source pins are not retagged by
this migration. Historical manifests keep their original repository URLs,
hashes, and paths. Moving ownership does not rebuild or requalify an image,
change the board environment, or reflash hardware.

See [the credential audit](security-audit.md) for the full-history scan and
the narrowly verified public ZeroMQ fixtures. No workstation credential files,
private reports, board passwords, or SSH keys are part of this migration.
