#!/usr/bin/env python3
"""Bounded experimental activation on daphne-10; requires root and staged hashes.

prepare stops the old test server only after backing up its runtime. activate
requires a fresh idle proof before removing its overlay. Default boot is kept.
No unload is attempted when quiescence fails. Frontend calibration is separate.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

STAGE = Path('/home/petalinux/dma-persistent-stage-20261011')
OLD = Path('/opt/daphne-dma-trigger-manual-20261011')
NEW = Path('/opt/daphne-dma-persistent-manual-20261012')
BACKUP = STAGE / 'backup-20261012'
ACTIVE = Path('/run/daphne-gateware/active.env')
APP = 'daphne_selftrigger_ol_630a9da'
RUNTIME_FILES = ('/run/daphne-gateware/active.env',
                 '/run/systemd/system/daphne-dma-manual.service',
                 '/run/systemd/system/firmware.service.d/dma-manual.conf',
                 '/run/daphne-dma-trigger-fw-stop.sh')


def run(*args):
    print('RUN', *args, flush=True)
    subprocess.run(args, check=True, timeout=60)


def verify(path, digest):
    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise RuntimeError(f'Hash mismatch: {path}')


def preflight():
    assert os.geteuid() == 0
    assert subprocess.check_output(['uname', '-r']).decode().strip() == '6.18.10-xilinx-g4f7afe14f724'
    assert Path('/etc/daphne-gateware/default-profile').read_text().strip() == 'self-trigger'
    assert 'APP=daphne_afe_trigger_1d17a11\n' in ACTIVE.read_text()
    verify(STAGE / 'server-arm-artifacts/daphneServer', '928686a809e160f03b8471dc72c0c3f57d6d18436915f44bfcfc9cb59c024417')
    verify(STAGE / 'server-arm-artifacts/daphne-afe-dma-quiesce', '2acd53b90f2f9b9f9f27bbc17c0a6aff27837f3b873e6f21c170898ce92a428a')
    verify(STAGE / 'driver-arm-artifacts/daphne-afe-dma.ko', 'd25ab970bb5288e1d419974f63ab92e9427163a34ec68a9d2a3c0f0f5f9a4255')
    for line in (STAGE / 'firmware' / (APP+'.SHA256SUMS')).read_text().splitlines():
        digest, name = line.split()
        verify(STAGE / 'firmware' / name, digest)
    verify(STAGE / 'dtbo-linux-630a9da' / (APP+'.dtbo'),
           '3ad11bb16a1718eb0eff6200eb230443ce0a5bcd024eacd0ca4149303e64222d')


def prepare():
    assert not BACKUP.exists(), 'Refusing to overwrite restoration evidence'
    BACKUP.mkdir()
    (BACKUP / 'boot-id').write_bytes(Path('/proc/sys/kernel/random/boot_id').read_bytes())
    for index, name in enumerate(RUNTIME_FILES):
        shutil.copy2(name, BACKUP / f'runtime-{index}')
    (BACKUP / 'runtime-paths.json').write_text(json.dumps(RUNTIME_FILES))
    shutil.copytree(OLD, BACKUP / 'old-runtime')
    shutil.copytree('/lib/firmware/xilinx/daphne_afe_trigger_1d17a11', BACKUP / 'old-firmware')
    for tag, command in (('modules', ['lsmod']), ('units', ['systemctl', 'cat', 'firmware.service', 'daphne-dma-manual.service']),
                         ('memory', ['cat', '/proc/meminfo'])):
        (BACKUP / f'{tag}.txt').write_bytes(subprocess.check_output(command))
    run('systemctl', 'stop', 'daphne-dma-manual.service')
    run(str(STAGE / 'server-arm-artifacts/daphne-afe-dma-quiesce'))
    (BACKUP / 'idle-proven').write_text('All engines halted; driver released\n')
    print('PREPARED: backup complete, old server stopped, live idle proven', flush=True)


def activate():
    assert (BACKUP / 'idle-proven').exists()
    assert Path('/proc/sys/kernel/random/boot_id').read_bytes() == (BACKUP / 'boot-id').read_bytes()
    assert not NEW.exists(), 'Refusing to overwrite experimental installation'
    fw = Path('/lib/firmware/xilinx') / APP
    assert not fw.exists(), 'Firmware directory already exists; inspect before continuing'
    run(str(STAGE / 'server-arm-artifacts/daphne-afe-dma-quiesce'))
    run('systemctl', 'stop', 'endpoint.service', 'clockchip.service', 'daphne-gateware-verify.service',
        'firmware.service', 'daphne-gateware-prepare.service')
    assert not list(Path('/sys/kernel/config/device-tree/overlays').iterdir())
    for module in ('daphne_afe_dma', 'daphne_dma_bounded'):
        if (Path('/sys/module') / module).exists():
            run('rmmod', module)
    NEW.mkdir()
    for name in ('daphneServer', 'daphne-afe-dma-quiesce', 'daphne-afe-session-probe'):
        shutil.copy2(STAGE / 'server-arm-artifacts' / name, NEW / name)
        (NEW / name).chmod(0o755)
    shutil.copy2(STAGE / 'driver-arm-artifacts/daphne-afe-dma.ko', NEW / 'daphne-afe-dma.ko')
    shutil.copy2(BACKUP / 'old-runtime/daphne_dma_bounded.ko', NEW / 'daphne_dma_bounded.ko')
    shutil.copytree(STAGE / 'server-arm-artifacts/protobuf', NEW / 'protobuf')
    shutil.copytree(STAGE / 'firmware' / APP, fw)
    shutil.copy2(STAGE / 'dtbo-linux-630a9da' / (APP+'.dtbo'), fw / (APP+'.dtbo'))
    ACTIVE.write_text('PROFILE=raw-dma\nAPP='+APP+'\nGATEWARE_MODE=raw-dma\nIDENTITY_MAGIC=0x44415048\nIDENTITY_ABI_MAJOR=2\nIDENTITY_ABI_MINOR=0\nIDENTITY_VARIANT=3\nIDENTITY_BUILD_ID=0x0630A9DA\n')
    guard = Path('/run/daphne-dma-persistent-fw-stop.sh')
    guard.write_text('#!/bin/sh\nset -eu\nif grep -qx GATEWARE_MODE=raw-dma /run/daphne-gateware/active.env; then\n '+str(NEW / 'daphne-afe-dma-quiesce')+'\nfi\nexec /usr/local/bin/daphne-fw-stop.sh\n')
    guard.chmod(0o755)
    Path(RUNTIME_FILES[2]).write_text('[Service]\nExecStop=\nExecStop='+str(guard)+'\n')
    Path(RUNTIME_FILES[1]).write_text('[Unit]\nDescription=DAPHNE persistent DMA experimental session\nRequires=firmware.service endpoint.service\nAfter=firmware.service endpoint.service\nPartOf=firmware.service\n\n[Service]\nType=simple\nExecStart='+str(NEW / 'daphneServer')+' --dma --gateware-mode raw-dma --expected-gateware-build-id 0x0630a9da --bind tcp://*:40001\nTimeoutStopSec=30s\nRestart=no\n')
    run('systemctl', 'daemon-reload')
    run('systemctl', 'reset-failed', 'firmware.service', 'daphne-gateware-prepare.service', 'daphne-gateware-verify.service')
    run('systemctl', 'start', 'firmware.service', 'daphne-gateware-verify.service')
    run('/usr/sbin/daphne-gateware', 'verify')
    run('insmod', str(NEW / 'daphne_dma_bounded.ko'))
    for address in ('b0020000', 'b0040000', 'b0060000'):
        name = address+'.dma'
        device = Path('/sys/bus/platform/devices') / name
        assert (device / 'driver').resolve().name == 'xilinx-vdma'
        (device / 'driver_override').write_text('daphne-dma-bounded')
        Path('/sys/bus/platform/drivers/xilinx-vdma/unbind').write_text(name)
        Path('/sys/bus/platform/drivers/daphne-dma-bounded/bind').write_text(name)
        assert (device / 'driver').resolve().name == 'daphne-dma-bounded'
    run('insmod', str(NEW / 'daphne-afe-dma.ko'), 'max_pool_mib=448')
    run('systemctl', 'start', 'clockchip.service', 'endpoint.service')
    run(str(NEW / 'daphne-afe-dma-quiesce'))
    run('systemctl', 'start', 'daphne-dma-manual.service')
    run('systemctl', 'is-active', 'firmware.service', 'daphne-gateware-verify.service',
        'clockchip.service', 'endpoint.service', 'daphne-dma-manual.service')
    print('ACTIVATED: frontend configuration/alignment and client tests still required', flush=True)


def idle_unbound():
    """Only for the hardware-only DT, before a consumer has ever bound."""
    assert os.geteuid() == 0 and not Path('/dev/daphne-afe-dma').exists()
    driver = Path('/sys/bus/platform/drivers/daphne-afe-dma')
    assert not any(p.is_symlink() and p.name != 'module' for p in driver.iterdir())
    assert not (Path('/sys/bus/platform/devices/b0080000.afe_dma_capture') / 'driver').exists()
    def read(address):
        return int(subprocess.check_output(['devmem', hex(address), '32']).strip(), 16)
    assert read(0x940000fc) == 0x0630a9da
    assert not (read(0xb0080028) & 1)
    for address in (0xb0020030, 0xb0040030, 0xb0060030):
        assert not (read(address) & 5) and (read(address+4) & 1)
    print('UNBOUND IDLE PROVEN: no consumer has bound; controller stopped and all engines HALTED', flush=True)


def repair_dtbo():
    assert Path('/proc/sys/kernel/random/boot_id').read_bytes() == (BACKUP / 'boot-id').read_bytes()
    assert 'APP='+APP+'\n' in ACTIVE.read_text()
    idle_unbound()
    run('tar', '-xzf', str(STAGE / 'dtbo-linux-630a9da.tar.gz'), '-C', str(STAGE))
    corrected = STAGE / 'dtbo-linux-630a9da' / (APP+'.dtbo')
    verify(corrected, '3ad11bb16a1718eb0eff6200eb230443ce0a5bcd024eacd0ca4149303e64222d')
    guard = Path('/run/daphne-dma-persistent-fw-stop.sh')
    guard.write_text('#!/bin/sh\nset -eu\npython3 '+str(STAGE / 'raw_dma_session_activate.py')+' idle-unbound\nexec /usr/local/bin/daphne-fw-stop.sh\n')
    guard.chmod(0o755)
    run('systemctl', 'stop', 'endpoint.service', 'clockchip.service', 'daphne-gateware-verify.service',
        'firmware.service', 'daphne-gateware-prepare.service')
    assert not list(Path('/sys/kernel/config/device-tree/overlays').iterdir())
    for module in ('daphne_afe_dma', 'daphne_dma_bounded'):
        run('rmmod', module)
    installed = Path('/lib/firmware/xilinx') / APP / (APP+'.dtbo')
    shutil.copy2(installed, STAGE / 'hardware-only-original.dtbo')
    shutil.copy2(corrected, installed)
    guard.write_text('#!/bin/sh\nset -eu\n'+str(NEW / 'daphne-afe-dma-quiesce')+'\nexec /usr/local/bin/daphne-fw-stop.sh\n')
    run('systemctl', 'reset-failed', 'firmware.service', 'daphne-gateware-prepare.service', 'daphne-gateware-verify.service')
    run('systemctl', 'start', 'firmware.service', 'daphne-gateware-verify.service')
    run('/usr/sbin/daphne-gateware', 'verify')
    run('insmod', str(NEW / 'daphne_dma_bounded.ko'))
    for address in ('b0020000', 'b0040000', 'b0060000'):
        name = address+'.dma'
        device = Path('/sys/bus/platform/devices') / name
        assert (device / 'driver').resolve().name == 'xilinx-vdma'
        (device / 'driver_override').write_text('daphne-dma-bounded')
        Path('/sys/bus/platform/drivers/xilinx-vdma/unbind').write_text(name)
        Path('/sys/bus/platform/drivers/daphne-dma-bounded/bind').write_text(name)
        assert (device / 'driver').resolve().name == 'daphne-dma-bounded'
    run('insmod', str(NEW / 'daphne-afe-dma.ko'), 'max_pool_mib=448')
    assert Path('/dev/daphne-afe-dma').is_char_device()
    run('systemctl', 'start', 'clockchip.service', 'endpoint.service')
    run(str(NEW / 'daphne-afe-dma-quiesce'))
    run('systemctl', 'start', 'daphne-dma-manual.service')
    print('LINUX DTBO ACTIVE: consumer bound; live driver idle proof passed', flush=True)


def restore_baseline():
    """Restore only this recorded runtime; never force unload after a failed proof."""
    assert os.geteuid() == 0
    assert Path('/proc/sys/kernel/random/boot_id').read_bytes() == (BACKUP / 'boot-id').read_bytes()
    assert 'APP='+APP+'\n' in ACTIVE.read_text()
    assert not (BACKUP / 'restore-attempted').exists()
    run('systemctl', 'stop', 'daphne-dma-manual.service')
    run(str(NEW / 'daphne-afe-dma-quiesce'))
    (BACKUP / 'restore-attempted').touch()
    run('systemctl', 'stop', 'endpoint.service', 'clockchip.service', 'daphne-gateware-verify.service',
        'firmware.service', 'daphne-gateware-prepare.service')
    assert not list(Path('/sys/kernel/config/device-tree/overlays').iterdir())
    for module in ('daphne_afe_dma', 'daphne_dma_bounded'):
        run('rmmod', module)
    for index, name in enumerate(RUNTIME_FILES):
        shutil.copy2(BACKUP / f'runtime-{index}', name)
    run('systemctl', 'daemon-reload')
    run('systemctl', 'reset-failed', 'firmware.service', 'daphne-gateware-prepare.service', 'daphne-gateware-verify.service')
    run('systemctl', 'start', 'firmware.service', 'daphne-gateware-verify.service')
    run('/usr/sbin/daphne-gateware', 'verify')
    run('insmod', str(OLD / 'daphne_dma_bounded.ko'))
    for address in ('b0020000', 'b0040000', 'b0060000'):
        name = address+'.dma'
        device = Path('/sys/bus/platform/devices') / name
        assert (device / 'driver').resolve().name == 'xilinx-vdma'
        (device / 'driver_override').write_text('daphne-dma-bounded')
        Path('/sys/bus/platform/drivers/xilinx-vdma/unbind').write_text(name)
        Path('/sys/bus/platform/drivers/daphne-dma-bounded/bind').write_text(name)
        assert (device / 'driver').resolve().name == 'daphne-dma-bounded'
    run('insmod', str(OLD / 'daphne-afe-dma.ko'), 'max_pool_mib=448')
    run('systemctl', 'start', 'clockchip.service', 'endpoint.service')
    run(str(OLD / 'daphne-afe-dma-quiesce'))
    run('systemctl', 'start', 'daphne-dma-manual.service')
    (BACKUP / 'restore-returned').touch()
    print('BASELINE RUNTIME RESTORED: frontend configuration/alignment must be measured again', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('prepare', 'activate', 'idle-unbound', 'repair-dtbo', 'restore-baseline'))
    args = parser.parse_args()
    if args.phase in ('prepare', 'activate'):
        preflight()
    {'prepare': prepare, 'activate': activate, 'idle-unbound': idle_unbound,
     'repair-dtbo': repair_dtbo, 'restore-baseline': restore_baseline}[args.phase]()
