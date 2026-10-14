# DAPHNE deployment process

Clone `daphne-os` and `hardware-database` on the programming server. Install
Vivado 2026.1, Python 3.9 or newer with venv/pip, `psmisc`, and `iproute`.
Python 3.9–3.12 supports the optional pinned QA dependencies.

Keep the release images and station state outside Git and outside `/tmp`.
The required `BOOT.BIN` and `rootfs.wic.gz` hashes are in `release.json`.
They are the September 17 minimal copper release, not the dual-gateware RC.

## Prepare the server

Copy `station.example.json` to a local file and set its tool, network, TFTP,
and fixture SSH public-key paths. Configure the fixture interface with the
specified server address, and enable the server's TFTP service.

```bash
python3 scripts/station/setup_station.py \
  --directory "$HOME/daphne-deployment/station" \
  --artifacts "$HOME/daphne-deployment/artifacts" \
  --config /path/to/station.json \
  --inventory-repo /path/to/hardware-database
```

The installer checks the frozen image hashes, snapshots the pinned database
source, recovers boot payloads and Linux readback references, and records source
and file hashes. It sends no board commands and never overwrites station state.
Back up `database/`, `records/`, `evidence/`, and `results/` after each run.

## Deploy one board

Use one connected board, booted in JTAG mode. Close other serial programs.
For the guided command and exact Bash history audit, follow
[FOR_DUMMIES.md](FOR_DUMMIES.md). The lower-level steps below explain the same
process for recovery. Use a root shell for these steps. Set the physical asset
label and its allocated fixture address; never copy another SOM's identity.

After reliable normal boot, [CLEAN_REHEARSAL.md](CLEAN_REHEARSAL.md) describes the
full software-storage and FTDI erase followed by deployment. Physical boot-mode
switch changes remain operator steps. The clean rehearsal is not yet verified.

```bash
sudo -s
cd /srv/daphne-deployment/station
B=DAPHNE-006
IP=192.168.0.206
bin/deploy-jtag "$B" "$IP" V2
```

The process attempts a logical reconnect and then a USB bus reset after FTDI
programming. It verifies the new serial identity and UART before continuing.
This succeeded remotely on DAPHNE-006 on October 14. If it requests a physical
reconnect, reconnect USB and repeat the command.
Require **QSPI AND EMMC FULL READBACK VERIFIED** before changing boot mode.

Power off, select QSPI boot, keep USB connected, and start:

```bash
UART=$(readlink -f /dev/serial/by-id/*${B/-/}*if01-port0)
bin/capture-qspi-boot "$B" "$UART"
```

Power on when it is waiting. After **Verified QSPI boot**:

```bash
python3 bin/configure-qspi.py "$B" "$UART"
bin/boot-provision-shell "$B" "$UART" &&
python3 bin/provision-linux "$B" "$UART"
```

U-Boot input uses CR; Linux input uses LF. The boot helper waits for Linux and
checks a working root shell. No `stty` workaround is needed. Provisioning sets
the hostname, network, and supplied public key; it does not set default passwords.

After provisioning succeeds, reboot and check normal QSPI boot automatically:

```bash
bin/verify-normal-boot "$B" "$UART"
```

Require QSPI boot mode, a valid saved environment, the allocated hostname,
the DAPHNE controller startup and reachable TCP port 40001. Optional full QA
uses `bin/run-qa "$B" "$IP"` after installing
`requirements-qa.txt` into the station venv. Successful image writes are not
analog, timing, or DAQ qualification.

## Recovery provenance

The campaign wrappers were recovered from the September 30 saved source record.
The LF handling and Linux readiness correction passes the original 12 simulated
serial tests. On DAPHNE-006, October 14, remote FTDI reset, RAM boot through TF-A,
EEPROM capture, QSPI and complete eMMC readback, Linux boot to the provisioning
shell, and Linux provisioning passed. Logs are in the persistent station's
`evidence/DAPHNE-006/`. Autonomous QSPI boot, saved environment, runtime service
startup and TCP port 40001 also passed. Fresh manual-only clean redeployment and
analog/timing/DAQ acceptance remain unverified.

## Shared operator access

After assembling and reviewing a station, run `install_shared.sh` as root with
the existing deployment directory. It creates `/srv/daphne-deployment`, copies
the source repositories, artifacts and station state, relocates the venv and
public key, and makes the installation readable by all users with root-only
writes. Then run `install_operator_access.py` as root from the reviewed source.
It grants existing regular login accounts the validated `daphne-deploy` command
through sudo; it does not grant a general root shell. On Cooper, `/tools` uses
the sticky bit so operators cannot replace another owner's tool directory.

On a new server, provision Vivado, the fixture interface, TFTP service, the two
hash-pinned release files, and a local fixture public key first. Clone
`https://github.com/DUNE-DAQ/daphne-os.git` and
`https://github.com/marroyav/hardware-database.git`; fetch the inventory revision
named in `release.json`. Assemble with `setup_station.py`, then install shared
access. The tested Cooper image copies are in `/srv/daphne-deployment/artifacts/`.
Git contains the deployment process and pinned identities; release binaries and
per-board state stay in the persistent station.
