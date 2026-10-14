# Deploy DAPHNE-006 on Cooper

The board label is **DAPHNE-006**, carrier revision **V2**, fixture address
**192.168.0.206**. Connect only this board. Close other serial programs.
Keep the USB cable connected throughout. The process programs FTDI, boot
firmware, and the OS, verifies readback, saves U-Boot settings, provisions
Linux, and checks unattended QSPI boot and the network controller.

Open the isolated manual terminal by running
`/srv/daphne-deployment/station/bin/start-manual-session` from your own terminal.
It creates a new Bash history file and prints its location. Type exactly the
three lines below, one at a time. Wait for each command to finish. Answers to
the deployment's physical-switch prompts do not enter Bash history.

<!-- manual-history:start -->
```bash
sudo /usr/local/sbin/daphne-deploy DAPHNE-006 192.168.0.206 V2 --check
sudo /usr/local/sbin/daphne-deploy DAPHNE-006 192.168.0.206 V2
exit
```
<!-- manual-history:end -->

The second command asks you to select JTAG boot and power on. Once flash
readback passes, it asks you to power off, select QSPI, and leave power off.
Press Enter. Power on only after **Power on the board in QSPI mode now** appears.
It catches U-Boot automatically; do not type board commands.

Success is **DEPLOYMENT PASSED**, with evidence under
`/srv/daphne-deployment/station/evidence/DAPHNE-006/`. After `exit`, the terminal
wrapper checks that the saved history exactly matches this Markdown command
block. If any stage fails, stop; fix the versioned process and repeat in a new
manual terminal. Do not add undocumented recovery commands.

This command overwrites the release image and provisions Linux. It does not
erase the full SoM storage or clear an already-programmed FTDI EEPROM. A full
erase-and-redeploy rehearsal is still pending; the factory SoM identity EEPROM
must be preserved. Analog, timing and DAQ qualification are separate checks.
