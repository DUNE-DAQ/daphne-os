# Dual-gateware 2026.08.31 RC1

Status: engineering release candidate. The FPGA artifacts and integrated OS
image build successfully. Inherited design-wide CDC/methodology review and
board qualification are still required before production promotion.

## What is in the release

One PetaLinux image carries two FPGA applications and one server executable.
They are separate artifacts: changing mode does not rebuild the OS or replace
the server.

| Part | Exact source | Installed identity |
| --- | --- | --- |
| Self-trigger gateware | `3f17f1bdb14f13fd64dac0d8866dc3dda9e8dd96` | ABI 2.0, variant 1, build `0x03F17F1B`, app `daphne_selftrigger_ol_3f17f1b` |
| Full-stream gateware | `b24e416bf56c8424ab679924f1476597bb24186b` | ABI 2.0, variant 2, build `0x0B24E416`, app `daphne_fullstream_ol_b24e416` |
| `daphne-server` | `77b39b7eb75204e1f2025f251a3a76ecf69d1d74` | One AArch64 executable with explicit self-trigger and full-stream modes |
| `daphnemodules` | `9d807840f249763607a1e31bb78e44de8ba8a082` | Package version 3.0.4; one client build for both modes |
| Image integration | `ae2c7be986ba4930968a2821afc641d5f52591a4` | PetaLinux 2026.1 minimal profile |
| Campaign tooling | `93db1ad0392918d8a0e6d4603bdddd96cbac0aae` | Strict board records, sequential rollout, and per-board qualification |
| Overlay/runtime hotfix | `0b4f916e3e59ba72f66eaa07f5ce1f2cfc420de8` | Correct Kria FPGA-region overlays and use `xmutil` for application switching |

The full-stream build-wrapper correction is commit
`bff0ee134b12e9e98dc72d99e3917454b02ea38d`. It was made after the immutable
`b24e416` FPGA artifact and does not change that artifact or its build ID.

The collected image archive is
`daphne-dual-gateware-2026.08.31-rc1-petalinux.tgz`, SHA-256
`59e8f55bfae94b1d1f61942c5c8c960421652d922f8894d3e8c46f6767d51ed2`.
Its root filesystem was checked after the build for the exact server, private
libraries, two immutable FPGA applications, switching command, profiles, and
systemd launch contract.

This RC does not update QSPI and does not include a separately packaged
`BOOT.BIN`. QSPI boot firmware remains a separate qualification path; normal
rollout uses the inactive eMMC slot.

## Published source branches

| Component | Repository | Branch | Pinned commit |
| --- | --- | --- | --- |
| Release integration, image integration, and campaign tooling | `DUNE-DAQ/daphne-firmware` | `release/dual-gateware-2026.08.31-rc1` | `0b4f916` (`ae2c7be` image, `93db1ad` campaign) |
| Self-trigger gateware | `DUNE-DAQ/daphne-firmware` | `marroyav/selftrigger-dual-abi-v2` | `3f17f1b` |
| Full-stream gateware | `marroyav/daphne-fullstream-firmware` | `marroyav/fullstream-mux-a002` | `b24e416` |
| Full-stream build tooling | `marroyav/daphne-fullstream-firmware` | `release/fullstream-build-tools-2026.08.31-rc1` | `bff0ee1` |
| Server | `ecristal/daphneZMQ` | `release/dual-gateware-server-2026.08.31-rc1` | `77b39b7` |
| Client package 3.0.4 | `DUNE-DAQ/daphnemodules` | `release/dual-gateware-client-3.0.4-rc1` | `9d80784` |

All branch tips above are published. The server development alias
`marroyav/dual-gateware-abi-v2` is also published at the same `77b39b7`
commit.

## September 4 hardware correction

DAPHNE-007 bring-up showed that the original generated DTBO placed
`firmware-name` on the AXI bus fragment. `xmutil` could therefore attach the
peripheral nodes without programming the FPGA. Commit `0b4f916` fixes the
packager to emit separate `&fpga_full` and `&amba` fragments, uses the
immutable application `.bin` name, and makes the service helpers prefer the
Kria `xmutil` application path.

On DAPHNE-007, corrected self-trigger and full-stream applications reported
their expected ABI 2 identities and builds, service-controlled switching
passed in both directions, and a QSPI-to-eMMC boot reached the complete
runtime target with self-trigger selected. This is bring-up evidence, not a
production qualification record; data-path, rollback-injection, and extended
four-link tests remain open.

That autonomous boot also required a one-time persistent U-Boot environment
for the replacement SOM. The exact DAPHNE-007 `netinit`, DHCP `preboot`,
eMMC `bootcmd`, identity, `saveenv`, power-cycle, and readback steps are in
[the deployment procedure](../dual-gateware-deployment.md#persist-the-qspi-boot-environment-after-recovery).
This changes QSPI environment records only; it is not a QSPI `BOOT.BIN`
update. The documented fixed slot-A command is for the recovered two-partition
image and must not overwrite the campaign A/B boot environment.

The frozen image archive identified above was built before `0b4f916` and does
not contain this correction. Do not distribute that archive as the corrected
dual-gateware image. Rebuild the PetaLinux image from the published release
branch before a new-board or fleet deployment.

## Supported combinations

| Active gateware | Server launch mode | DAQ client |
| --- | --- | --- |
| Self-trigger `3f17f1b` | `self-trigger` | Package 3.0.3 or 3.0.4 |
| Full-stream `b24e416` | `full-stream` | Package 3.0.4 |

The server checks the live FPGA magic, ABI, variant, and build ID before it
writes registers. A mismatch exits with status 78 instead of running against
the wrong address map. Explicit full-stream mode also rejects an empty channel
plan before touching hardware.

Self-trigger owns the `0xA0010000` register window. Full-stream owns the new
`0xA0020000` window. Both expose their common identity at `0x940000F0`.

## Install and switch

Use the collected PetaLinux bundle with `scripts/deploy/daphne_deploy.sh`.
Deployment writes the inactive eMMC slot and leaves the active slot available
for rollback. Each board needs its own reviewed board configuration and pinned
SSH host-key fingerprint; the image bundle is shared by every board.

After boot, use the DAPHNE wrapper rather than calling `xmutil` directly:

```sh
sudo daphne-gateware status
sudo daphne-gateware switch full-stream
sudo daphne-gateware switch self-trigger
```

To change the mode selected at the next boot:

```sh
sudo daphne-gateware set-default full-stream
sudo reboot
```

The wrapper stops the runtime services, quiesces the active data path, changes
the FPGA application, verifies its identity, and starts the server in the
matching mode. It rolls back if loading or verification fails.

See [Dual-gateware deployment](../dual-gateware-deployment.md) for image deployment and
[the PetaLinux guide](../kr260-petalinux-build-guide.md) for recovery details.

## Release evidence

- Self-trigger: synthesis, placement, routing, timing, DRC, bitstream, XSA,
  DTBO, archive, and checksum gates pass. Post-route WNS is `0.071 ns`; WHS is
  `0.010 ns`.
- Full-stream: synthesis, placement, routing, DRC, and bitstream generation
  pass. Post-route WNS is `1.257 ns`; WHS is `0.010 ns`. The new mux contributes
  no critical CDC findings; inherited design-wide CDC and methodology findings
  remain open for review or a documented baseline.
- The exact original full-stream output manifest and all 17 files it covers are
  retained under `artifacts/full-stream/source-output/`.
- Server: the pinned AArch64 bundle passes architecture, checksum, ABI-contract,
  required-option, recipe-layout, and PetaLinux 2026.1 QEMU checks.
- Client: a clean DUNE-DAQ `fddaq-v5.6.2-a9-1` build and all three relevant
  test suites pass.
- PetaLinux: all 7,093 BitBake tasks succeeded. Bundle checksums pass, and the
  installed AArch64 server launches from the extracted root filesystem under
  QEMU with both required gateware-selection options.
- Campaign: all 58 deployment and qualification tests pass. A qualification
  record is bound to the exact campaign summary, release ID, extracted image
  manifest, root filesystem, gateware build IDs, artifacts, and evidence
  hashes. The Draft 2020-12 schemas reject incomplete PASS claims.

The XXV Ethernet feature-key warnings still appear under Vivado 2026.1, even
though the floating Enterprise entitlement has a `2026.07` version limit and
bitstream generation succeeds. A long four-link board run remains mandatory
to rule out evaluation-time behavior.

## Promotion gate

Before tagging this RC as production, boot it on representative boards and
record evidence with `scripts/deploy/daphne_qualification.py` for:

- self-trigger to full-stream to self-trigger switching;
- failed-load rollback and recovery of the previous mode;
- correct first frame, board-channel IDs, AFE mapping, and trigger behavior;
- all four Ethernet links under a run long enough to cover license-timeout risk;
- server rejection of an intentionally mismatched mode or build ID;
- inactive-slot deployment, trial boot, confirmation, and rollback.

Do not promote solely from build success. Hardware evidence is part of this
release contract. Approved board records, host fingerprints, recovery access,
DAQ commands and channel plans, and Ethernet thresholds have not yet been
supplied; the checker therefore leaves every board unqualified by default.
