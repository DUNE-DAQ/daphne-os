# Deploy the dual-gateware release

This is the short operator procedure for installing one qualified image on
several DAPHNE boards. The detailed build and recovery material remains in the
[PetaLinux build guide](kr260-petalinux-build-guide.md).

The 2026.08.31 RC1 image is an engineering candidate, not a production fleet
release. Use the ring procedure below until its hardware gates are complete.
The frozen `59e8f55b...` image archive predates the FPGA-region overlay fix in
`0b4f916`; rebuild from `release/dual-gateware-2026.08.31-rc1` before using
this procedure on another board. Do not present the older archive as the
corrected release image.

## Release agreement

| Mode | FPGA source | Server | DAQ client |
| --- | --- | --- | --- |
| Self-trigger | `3f17f1b` | `77b39b7`, mode `self-trigger` | `daphnemodules` 3.0.3 or 3.0.4 |
| Full-stream | `b24e416` | `77b39b7`, mode `full-stream` | `daphnemodules` 3.0.4 |

The common client package is `daphnemodules` 3.0.4 at commit `9d80784`,
built and tested with DUNE-DAQ `fddaq-v5.6.2-a9-1`. The image server listens on
TCP port 40001. Full-stream requires a nonempty ordered list of at most 32
unique board-channel IDs from 0 through 39. Self-trigger leaves that list
empty.

## Prepare the boards

Use one shared, checksummed PetaLinux bundle. Each board also needs:

- a reviewed `daphne.board-config` record rendered with
  `scripts/deploy/render_board_config.py`;
- its management host or IP address;
- its pinned ED25519 SSH host-key fingerprint;
- network admission and a recovery path.

Render each approved `daphne.board-config` record before creating the campaign
CSV:

```bash
python3 scripts/deploy/render_board_config.py \
  --record boards/DAPHNE-001.json \
  --record-sha256 <record-sha256> \
  --expected-firmware-release dual-gateware-2026.08.31-rc1 \
  --output boards/DAPHNE-001 \
  --prefix <site-prefix> \
  --gateway <gateway-ip> \
  --dns <dns-ip>
```

Repeat with the corresponding record and output directory for every board.
The renderer refuses records that are not approved for network admission or
do not name this exact firmware release. The network prefix is deliberately
required; do not assume `/24`.

Do not disable SSH host-key checking. Stop the external DUNE-DAQ run before an
image deployment or gateware switch.

Create a campaign CSV. Relative `board_config` paths are resolved from the CSV
directory.

```csv
board,host,board_config,host_key_sha256,user,control_host
DAPHNE-001,daphne-001.example,boards/DAPHNE-001,SHA256:<fingerprint>,petalinux,
DAPHNE-002,daphne-002.example,boards/DAPHNE-002,SHA256:<fingerprint>,petalinux,
```

Board IDs, hosts, configuration directories, and fingerprints must be unique.
The campaign wrapper validates every row and the complete bundle checksum set
before contacting the first board.

## Dry-run the campaign

The wrapper is sequential and stops on the first failure. Its default makes no
board writes. It does create a local evidence directory containing read-only
snapshots of the exact deployer, board configurations, and required image
files; relay mode may also create temporary files on the control host.

```bash
python3 scripts/deploy/daphne_deploy_campaign.py campaign.csv \
  --bundle /path/to/petalinux-bundle \
  --evidence-dir evidence/canary-dry-run
```

Review every resolved board, host, current slot, target slot, configuration,
and fingerprint in the per-board logs and `campaign-summary.json`.

## Stage the inactive slots

Use a new evidence directory and add `--execute` only after the complete dry
run passes:

```bash
python3 scripts/deploy/daphne_deploy_campaign.py campaign.csv \
  --bundle /path/to/petalinux-bundle \
  --evidence-dir evidence/canary-install \
  --execute
```

This writes each board's inactive eMMC slot. It does not update QSPI, change a
MAC address, overwrite the active slot, or reboot the board. A successful row
is recorded as `staged`, not qualified. The wrapper rejects
`--execute --reboot` because it has no unattended post-boot health gate. Do not
use `--continue-on-error` for a release rollout.

## Persist the QSPI boot environment after recovery

This separate, one-time serial-console step is required when recovery or a
blank SOM leaves the QSPI U-Boot environment unset. `saveenv` writes only the
redundant U-Boot environment in QSPI; it does not install or replace QSPI boot
firmware. The commands below are the values validated on DAPHNE-007 on
2026-09-04 after writing the two-partition eMMC image.

This boot command deliberately pins the FAT boot partition to `mmc 0:1` and
the root filesystem to `/dev/mmcblk0p2`. Do not install it on a board already
using the campaign's A/B environment: that environment must retain its
`active_slot` selection and rollback commands.

At the U-Boot serial prompt, first verify that the protected MAC matches the
approved SOM/database identity. DAPHNE-007 must report
`00:0a:35:23:a1:90`; stop if it does not. Do not copy this MAC to another
board and do not force an `ethaddr` rewrite merely because U-Boot rejects an
attempt to replace an already-protected correct value.

```text
printenv ethaddr
setenv ipaddr
setenv ethact ethernet@ff0b0000
setenv serverip 192.168.0.104
setenv netmask 255.255.255.0
setenv hostname daphne007
setenv board_id DAPHNE-007
setenv netinit 'mw.l 0xff5e0050 0x06010c00; mw.l 0xfd402860 0x00000080; mw.l 0xff0b0200 0x00000140; mw.l 0xff0b0004 0x092e0c4a; sleep 2'
setenv preboot 'run netinit; setenv autoload no; dhcp'
setenv bootcmd 'mmc dev 0; fatload mmc 0:1 0x18000000 Image; fatload mmc 0:1 0x40000000 system.dtb; setenv bootargs "earlycon console=ttyPS1,115200 root=/dev/mmcblk0p2 rootwait rw"; booti 0x18000000 - 0x40000000'
setenv bootdelay 2
setenv autoload no
printenv ethaddr ethact serverip netmask hostname board_id netinit preboot bootcmd bootdelay autoload
saveenv
```

For another board, obtain `ethaddr`, `hostname`, `board_id`, `serverip`, and
`netmask` from its approved board record and site configuration; never derive
or increment identities at the console. Require `Saving Environment to
SPIFlash... OK` before continuing. Then power off, select physical QSPI boot
mode, power on, interrupt the first autoboot, and repeat the `printenv`
readback above. The boot log must identify QSPI boot and Linux must mount
`/dev/mmcblk0p2` as `/`.

After allowing that boot to complete, verify the root, the complete service
chain, the listening server, and the selected gateware application:

```sh
findmnt -n -o SOURCE /
sudo systemctl --no-pager --full status \
  daphne-runtime.target daphne-gateware-prepare.service firmware.service \
  daphne-gateware-verify.service clockchip.service endpoint.service \
  hermes.service daphne.service
sudo systemctl --failed --no-pager
sudo ss -ltnp | grep ':40001'
sudo daphne-gateware status
```

Saving this environment is independent of selecting self-trigger or
full-stream. Use `daphne-gateware` for application switching and next-boot
application defaults; do not edit `bootcmd` when changing FPGA modes.

Reboot one staged board at a time from its serial console or a site-approved,
pinned SSH session. After it returns, verify the selected slot and runtime
before rebooting another board:

```bash
./scripts/deploy/daphne_deploy.sh \
  --board DAPHNE-001 \
  --host daphne-001.example \
  --host-key-sha256 SHA256:<fingerprint> \
  --verify

ssh petalinux@daphne-001.example sudo daphne-gateware status
```

The deploy log's target slot must now be the active and last-good slot, with
`upgrade_available=0`. The status must show healthy runtime services, the
expected immutable app, server mode, ABI 2, variant, and build ID. Save both
commands' output as separate hardware-qualification evidence; the campaign
summary deliberately covers deployment only.

Use the same `daphnemodules` 3.0.4 client artifact throughout the campaign.
An empty `full_stream_channels` list selects self-trigger. Full-stream requires
1 through 32 unique board-channel IDs in the range 0 through 39; list order is
output order. Record the client artifact hash and exact list with each board's
qualification evidence.

## Record qualification

After a staged board has rebooted and passed the checks above, create its
record from the frozen campaign summary and release contract:

```bash
python3 scripts/deploy/daphne_qualification.py init \
  --campaign-summary evidence/canary-install/campaign-summary.json \
  --board DAPHNE-001 \
  --compatibility docs/releases/dual-gateware-2026.08.31-rc1.json \
  --output evidence/canary-install/DAPHNE-001-qualification.json
```

The new record is deliberately `NOT_RUN`. Fill its site-approved DAQ command,
DAQ configuration digest, Ethernet duration and counter thresholds, then add
the observed results and checksummed evidence for every gate. Evidence paths
are relative to the record. The schema and unqualified example are under
`scripts/deploy/schemas/` and `scripts/deploy/examples/`.

Check it against the same two frozen inputs:

```bash
python3 scripts/deploy/daphne_qualification.py check \
  evidence/canary-install/DAPHNE-001-qualification.json \
  --campaign-summary evidence/canary-install/campaign-summary.json \
  --compatibility docs/releases/dual-gateware-2026.08.31-rc1.json
```

Exit 0 means qualified, 1 means valid but incomplete or failed, and 2 means
invalid or tampered. The checker verifies identities, thresholds, and evidence
hashes; the named reviewer remains responsible for inspecting the evidence and
approving the site test policy.

## Switch gateware safely

Never run raw `xmutil unloadapp` while DAPHNE services are active. On the
board, use:

```sh
sudo daphne-gateware list
sudo daphne-gateware status
sudo daphne-gateware switch full-stream
sudo daphne-gateware status
```

`switch` changes the running FPGA application but not the next-boot default.
After the new mode passes its data test, persist it separately:

```sh
sudo daphne-gateware set-default full-stream
```

Reverse the same steps with `self-trigger`. The wrapper stops the services,
quiesces the data path, loads and verifies the selected application, and then
starts the same server in the matching mode. A failed switch automatically
attempts to restore the previous application.

## Rollout rings

Use the same image and client build throughout the campaign:

1. Canary: one board, two complete switch cycles, rollback injection, and the
   full data/link test.
2. Pilot: two or three boards, sequentially, stopping on the first failure.
3. Fleet: only after the RC is promoted and its production gates are signed
   off. Keep the generated JSON summary and board logs with the release.

For every board record the asset ID, SOM UUID, MAC, host-key fingerprint,
board-config checksum, image manifest checksum, client artifact hash and
channel list, active/default profiles before and after, observed FPGA identity,
data result, timestamps, operator, and both deployment and qualification log
locations.

## Failure handling

If a data test fails after a successful switch, switch back to the previous
profile and restore its default. If automatic rollback fails, isolate the
board, keep the runtime stopped, and collect:

```sh
sudo daphne-gateware status
sudo journalctl -u daphne-runtime.target -u firmware.service -u daphne.service
```

Do not continue the campaign and do not manually unload the FPGA application.
Use the active eMMC slot or the documented serial/JTAG recovery path.
