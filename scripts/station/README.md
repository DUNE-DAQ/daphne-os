# DAPHNE deployment — copy and paste

This is the single operator guide. The scripts automate FTDI programming and
remote USB reset, JTAG RAM boot, identity capture, flash/readback, U-Boot
settings, Linux provisioning, and unattended QSPI boot verification.

On Cooper, use one connected **DAPHNE-006**, **V2**, **192.168.0.206**.
Close other serial programs; keep USB connected. All nine login accounts can
run the restricted deployment command. Server files are in
`/srv/daphne-deployment`; release images and board state stay outside Git.

## Deploy on Cooper

Open the isolated terminal with
`/srv/daphne-deployment/station/bin/start-manual-session`, then paste these
lines one at a time, waiting for each command to finish:

<!-- manual-history:normal:start -->
```bash
sudo /usr/local/sbin/daphne-deploy DAPHNE-006 192.168.0.206 V2 --check
sudo /usr/local/sbin/daphne-deploy DAPHNE-006 192.168.0.206 V2
exit
```
<!-- manual-history:normal:end -->

When prompted: select **JTAG** with power off, power on, then press Enter.
After flash readback passes: power off, select **QSPI**, leave power off, and
press Enter. Power on only after **Power on the board in QSPI mode now**.
The process catches U-Boot automatically; do not type board commands.

Require **DEPLOYMENT PASSED** and, after `exit`, **HISTORY MATCHES THE MANUAL
exactly**. Logs are in `station/evidence/DAPHNE-006/`. On failure, stop, fix
the versioned process, and start a fresh manual terminal. For another board,
change its physical asset label, allocated IP, and carrier revision in both
commands and in this guide before the history audit.

## Erase and redeploy rehearsal

Use after reliable QSPI boot has passed. This erases the entire 64 MiB QSPI,
eMMC user/boot areas, and FTDI EEPROM before redeployment. It preserves factory
SoM identity EEPROM, RPMB, OTP and eFuses. QSPI has a full blank check; eMMC
uses full-range erase commands with beginning/end blank samples.

Open `/srv/daphne-deployment/station/bin/start-manual-session --clean`, then:

<!-- manual-history:clean:start -->
```bash
sudo /usr/local/sbin/daphne-deploy DAPHNE-006 192.168.0.206 V2 --check --clean
sudo /usr/local/sbin/daphne-deploy DAPHNE-006 192.168.0.206 V2 --clean
exit
```
<!-- manual-history:clean:end -->

Follow the same JTAG/QSPI prompts above. The first run reads exact eMMC geometry
from the installed OS; retries retain that geometry and verify the live SoM
identity before erasing. A fully blank board uses normal deployment instead.

## Prepare another server (administrator, once)

Install Vivado 2026.1, Python 3.9+ with venv/pip, Git, psmisc, iproute and a
TFTP server. Configure the fixture interface and enable TFTP. Supply the
September 17 minimal-copper `BOOT.BIN` and `rootfs.wic.gz`; the installer checks
their frozen hashes. Cooper copies are in `/srv/daphne-deployment/artifacts/`.

Run as root in a new persistent deployment directory; put the two release
files in its `artifacts/` directory before the installer command. Set the
station JSON's tool, interface/address, TFTP and fixture public-key paths.

```bash
sudo -s
D=/srv/daphne-deployment
install -d -m 0755 "$D/artifacts"
git clone --branch marroyav/reproducible-deployment-station-20261014 https://github.com/DUNE-DAQ/daphne-os.git "$D/repo"
git clone --branch marroyav/daphne-production-qa https://github.com/marroyav/hardware-database.git "$D/hardware-database"
cp "$D/repo/scripts/station/station.example.json" "$D/station.json"
vi "$D/station.json"
python3 "$D/repo/scripts/station/setup_station.py" --directory "$D/station" --artifacts "$D/artifacts" --config "$D/station.json" --inventory-repo "$D/hardware-database"
find "$D" -type d -exec chmod 0755 {} +
find "$D" -type f -exec chmod a+r,go-w {} +
python3 "$D/repo/scripts/station/install_operator_access.py"
```

Keep fixture private keys outside this shared directory. Stage both release
files under the configured TFTP release path, readable by the TFTP service.
Protect shared tool directories against replacement by unprivileged users;
on Cooper `/tools` is mode 1777. Back up `database/`, `records/`, `evidence/`
and `results/` after runs. Never install the station under `/tmp`.

To update only the process while retaining board state (administrator):

```bash
D=/srv/daphne-deployment
git -C "$D/repo" pull --ff-only
python3 "$D/repo/scripts/station/setup_station.py" --directory "$D/station" --artifacts "$D/artifacts" --config "$D/station/station.json" --inventory-repo "$D/hardware-database" --no-install --update-process
python3 "$D/repo/scripts/station/install_operator_access.py"
```

Individual programming, full image readback, Linux provisioning and normal QSPI
boot passed on DAPHNE-006 on October 14, 2026. Complete software/FTDI erase also
passed; the full clean redeployment is still in progress. Analog, timing and
DAQ qualification are separate checks. U-Boot uses CR and Linux uses LF;
no console workaround or default password is required.
