# DAPHNE-006 clean rehearsal on Cooper

Run this after verifying reliable QSPI boot with the saved environment and a
reachable controller. It requires the currently installed working OS to read
exact eMMC geometry before erasing. Connect only DAPHNE-006, keep USB connected,
and close other serial programs.

The command erases the full 64 MiB QSPI and eMMC user/boot areas, and clears FTDI
EEPROM. It preserves factory SoM identity EEPROM, RPMB, OTP and eFuses. QSPI is
checked blank over its full range; eMMC erase commands cover each entire area,
with blank samples from its beginning and end. This is a software reset rehearsal,
not a secure physical-media sanitization procedure.

Open a fresh terminal with
`/srv/daphne-deployment/station/bin/start-manual-session --clean`.
Type only these three commands, one at a time:

<!-- manual-history:start -->
```bash
sudo /usr/local/sbin/daphne-deploy DAPHNE-006 192.168.0.206 V2 --check --clean
sudo /usr/local/sbin/daphne-deploy DAPHNE-006 192.168.0.206 V2 --clean
exit
```
<!-- manual-history:end -->

For the second command, select JTAG boot, power on, and press Enter when asked.
It captures factory identity and exact storage geometry, erases the software
areas and FTDI, verifies FTDI defaults after remote USB reset, then programs
the named FTDI identity and deploys the hash-pinned release from scratch.

Once image readback passes, power off, select QSPI, and leave power off. Press
Enter. Power on only when **Power on the board in QSPI mode now** appears.
The command catches U-Boot, saves the environment, provisions Linux, reboots
and checks normal QSPI boot plus TCP port 40001. Do not type board commands.

Require **DEPLOYMENT PASSED** and, after `exit`, **HISTORY MATCHES THE MANUAL
exactly**. Logs are under `/srv/daphne-deployment/station/evidence/DAPHNE-006/`.
If a stage fails, stop and correct the versioned process. Start a fresh manual
terminal for the next complete rehearsal; do not add undocumented workarounds.

The clean rehearsal has not yet been completed. Individual programming,
readback, provisioning and normal QSPI boot steps passed on October 14, 2026.
