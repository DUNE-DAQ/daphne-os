# PL I2C Linux Binding Blocker

Status: resolved as a general binding blocker on the tested boards by the May
9, 2026 updates recorded at the end of this file. This is a historical incident
record, not the current highest-priority issue. Keep it for recovery context.

## Priority

This was the highest-priority firmware integration issue observed after the
March 31, 2026 board validation of `origin/marroyav/formal_verification` at
commit `7f032ac`.

The overlay loads successfully through `xmutil`, but the Linux-visible PL I2C
path needed for clock-chip control does not come back on the target.

## Observed behavior on target

Board:

- `NP04-DAPHNE-014`

Firmware under test:

- branch: `origin/marroyav/formal_verification`
- commit: `7f032ac`
- app payload: `daphne_selftrigger_ol_7f032ac`

Runtime facts observed on the board after `xmutil loadapp`:

- the PL app loads successfully and reaches FPGA manager state `operating`
- only `/dev/i2c-1` is present in Linux
- `/dev/i2c-2` is absent
- `i2cdetect -y 1` does not show the clock generator at `0x70`
- the service-chain clock configuration step fails immediately because
  `clk_conf.sh` expects bus `2`, chip `0x70`
- direct endpoint probing through `devmem` can hang the board once the external
  timing clock path is not configured

## Why this points to firmware / DT integration

The hardware design still instantiates the PL AXI IIC controller:

- `axi_iic_0` is created in
  [daphne_bd_gen.tcl](https://github.com/DUNE-DAQ/daphne-firmware/blob/develop/xilinx/daphne_bd_gen.tcl)
- its AXI-Lite register window is still assigned at `0x9C000000`
- its interrupt is routed through `axi_intc_0`

So the problem is not that the I2C block disappeared from the design.

The failure is at the Linux integration boundary:

- the generated overlay and runtime bind path are not restoring a Linux-usable
  PL I2C device for this firmware build
- `daphne-server` currently depends on that Linux path through `/dev/i2c-2`
  for the clock generator and other mezzanine I2C devices

## Working hypothesis

The most likely root cause is that the generated PL device-tree overlay is not
describing or binding the AXI IIC path correctly on target, even though the
underlying hardware exists.

Supporting evidence:

- the packaging flow still emits `dtc` warnings around PL interrupt-provider
  formatting
- both `axi_iic_0` and `axi_quad_spi_0` depend on the PL AXI interrupt
  controller path
- the board loses the expected Linux-visible PL I2C bus after loading the new
  overlay

This should be treated as a DT overlay / Linux probe failure until proven
otherwise.

## Required fix

The immediate requirement is:

1. load the firmware overlay on target
2. verify that the PL AXI IIC controller appears as a Linux device
3. verify that the expected PL I2C bus node is created
4. verify that the clock generator at `0x70` is reachable through that path

This is the acceptance bar, not just:

- `.bit` generated
- `.dtbo` generated
- `xmutil loadapp` returned success

## Short-term fallback

If restoring the Linux I2C binding takes longer, a temporary workaround is
possible:

- access the AXI IIC controller directly over AXI-Lite at `0x9C000000` through
  `/dev/mem`
- use polling instead of relying on the Linux `xiic-i2c` driver path

That would remove the dependency on `/dev/i2c-2`, but it is still a workaround.
The primary fix remains: restore the Linux-visible PL I2C contract.

## Next validation commands on target

After the next firmware/overlay fix, the target validation should start with:

```bash
ls -l /dev/i2c-*
sudo i2cdetect -y 1
dmesg -T | egrep -i 'xiic|i2c|9c000000|9c010000|irq|amba_pl'
find /sys/devices/platform/amba_pl -maxdepth 2 | sort
find /sys/bus/platform/devices -maxdepth 1 | egrep '9c000000|i2c|xiic'
```

The service-chain validation should only continue after the expected PL I2C
device is present again.

## May 9, 2026 update

The blocker is now narrower than the original statement above.

Current comparison:

- `NP04-DAPHNE-014` is booting with `/dev/mmcblk0p2` as the real `/` rootfs,
  and exposes both `/dev/i2c-1` and `/dev/i2c-2`.
- `NP04-DAPHNE-015` now has one persistent mixed deploy that boots with
  `/dev/mmcblk0p2` as the real `/` rootfs.
- The first repo-owned `firmware.service` implementation on `015` appeared to
  succeed, but the overlay had actually failed to apply because the DT overlay
  requested `daphne_selftrigger_7353a17.bit.bin` and that firmware alias was
  missing under `/lib/firmware/`.
- Once that alias was installed, `015` immediately reached FPGA state
  `operating`, exposed `/dev/i2c-2`, and bound both
  `/sys/bus/platform/devices/9c000000.i2c` and
  `/sys/bus/platform/devices/9c010000.interrupt-controller`.
- The repo-owned service no longer hardcodes one fixed bus number: on `014` it
  auto-discovers bus `2`, and on `015` it now does the same after the overlay
  bind succeeds.

So this is not simply "the overlay can never expose the timing I2C bus".
The stronger working hypothesis is now:

- the `014` boot payload and device-tree/runtime combination bind the
  PL timing I2C path correctly;
- the current repo overlay package originally missed one required firmware-name
  alias for the `015` DT overlay path;
- the remaining `015` work has moved up-stack from Linux I2C visibility to
  service/runtime packaging, not PL I2C binding itself.

## May 9, 2026 later update

The next boot-side root cause is now also understood.

What changed:

- the original repo-built `system.dtb` for `015` baked the generated base
  `pl-bus` into the non-overlay DT, including:
  - `interrupt-controller@9c010000`
  - `i2c@9c000000`
  - `axi_quad_spi@9c020000`
- that base DT arrangement reproduced the old early-boot `rcu_sched` stall
  before root handoff on `015`;
- removing the generated base PL bus from the repo-owned
  `system-user.dtsi` fixes that early-boot failure;
- with that DT fix in place, a one-shot serial/U-Boot boot on `015` using the
  proven older kernel plus the fixed repo-owned DTB and current ramdisk now:
  - boots through ext4-root userspace,
  - loads the overlay,
  - binds the PL timing path again,
  - and starts `firmware`, `clockchip`, `endpoint`, `hermes`, and `daphne`.
- after making `gem0` explicitly boot as the management `sgmii` fixed-link and
  installing that rebuilt DTB into `/boot/system.dtb`, the same full service
  chain now also comes back on the normal persistent reboot path.
- after replacing the live top-level boot `Image` with the repo-built one, the
  same normal reboot path still comes back on `015` with the full timing
  service chain active.

So the blocker is no longer "Linux can never see the PL I2C bus". The current
remaining gap is narrower:

- preserve the expected management-network identity while we move to the
  longer-term fleet update and rollback model;
- qualify the A/B boot and rescue contract around this now-working kernel/DT
  and timing path.
