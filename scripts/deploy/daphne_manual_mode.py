#!/usr/bin/env python3
"""Switch the installed daphne-10 runtime without changing its boot default."""
import argparse
import hashlib
import importlib.machinery
import importlib.util
import logging
import os
from pathlib import Path
import subprocess
import sys
import time

RUNTIME = Path('/opt/daphne-dma-persistent-manual-20261012')
APP = 'daphne_selftrigger_ol_630a9da'
HELPER = Path('/usr/local/libexec/daphne-manual-mode.py')
MANUAL = 'daphne-dma-manual.service'
CORE = ('firmware.service', 'daphne-gateware-verify.service', 'clockchip.service', 'endpoint.service')
STOP = ('daphne-runtime.target', 'daphne.service', 'hermes.service', MANUAL,
        'endpoint.service', 'clockchip.service', 'daphne-gateware-verify.service',
        'firmware.service', 'daphne-gateware-prepare.service')
HASHES = {
    RUNTIME / 'daphneServer': '61bdf401c915f91c399c978ac60ace3865641e57a7f49cd3069b7a787d7b56c5',
    RUNTIME / 'daphne-afe-dma-quiesce': '2acd53b90f2f9b9f9f27bbc17c0a6aff27837f3b873e6f21c170898ce92a428a',
    RUNTIME / 'daphne-afe-dma.ko': 'd25ab970bb5288e1d419974f63ab92e9427163a34ec68a9d2a3c0f0f5f9a4255',
    RUNTIME / 'daphne_dma_bounded.ko': '7d26fcfa954c7ad9b5542087a67c9d29d9e52755896f9a57a65faf6cf0cd89fe',
    Path('/lib/firmware/xilinx') / APP / (APP+'.bin'): '01a7735f4678e1302ae6534d5ada6c9ea95407ee1cdd29abf10cae69571a623e',
    Path('/lib/firmware/xilinx') / APP / (APP+'.dtbo'): '3ad11bb16a1718eb0eff6200eb230443ce0a5bcd024eacd0ca4149303e64222d',
    Path('/lib/firmware/xilinx') / APP / 'shell.json': 'c4a262e0dc8fdb6271ea495c609bd585f085f525b59c913041eae1ca94f790a9',
}


def run(*args, timeout=60):
    logging.info('RUN %s', ' '.join(map(str, args)))
    result = subprocess.run(list(map(str, args)), text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=timeout)
    if result.stdout.strip():
        logging.info('%s', result.stdout.strip())
    if result.returncode:
        raise RuntimeError(f'Command failed ({result.returncode}): {args}')
    return result.stdout


def active(unit):
    return subprocess.run(['systemctl', 'is-active', '--quiet', unit], timeout=15).returncode == 0


def gateware():
    loader = importlib.machinery.SourceFileLoader('installed_daphne_gateware', '/usr/sbin/daphne-gateware')
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


def check_assets():
    if os.uname().release != '6.18.10-xilinx-g4f7afe14f724':
        raise RuntimeError('Installed DMA modules require the qualified kernel; rebuild on daphne-dev first')
    for path, expected in HASHES.items():
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise RuntimeError(f'Qualified artifact hash mismatch: {path}')
    for name in ('daphne_afe_dma', 'daphne_dma_bounded'):
        file = 'daphne-afe-dma.ko' if name == 'daphne_afe_dma' else name+'.ko'
        release = subprocess.check_output(['modinfo', '-F', 'vermagic', str(RUNTIME / file)], text=True).split()[0]
        if release != os.uname().release:
            raise RuntimeError(f'Kernel/module vermagic mismatch: {name}')
    frontend('dependencies')


def frontend(command):
    run('python3', RUNTIME / 'client/daphne_dma_frontend.py', command, timeout=1800)


def quiesce():
    # Failure (including quarantine, live FD, or missing device) must stop unload.
    run(RUNTIME / 'daphne-afe-dma-quiesce')


def guard(gw):
    if gw.load_active_profile().gateware_mode == 'raw-dma':
        gw.verify_profile(gw.load_active_profile(), emit=False)
        quiesce()
    run('/usr/local/bin/daphne-fw-stop.sh')


def install_runtime_files():
    dropin = Path('/run/systemd/system/firmware.service.d/manual-mode.conf')
    dropin.parent.mkdir(parents=True, exist_ok=True)
    dropin.write_text('[Service]\nExecStop=\nExecStop=/usr/bin/python3 '+str(HELPER)+' guard\nTimeoutStopSec=60s\n')
    Path('/run/systemd/system/'+MANUAL).write_text(
        '[Unit]\nDescription=DAPHNE persistent DMA manual runtime\n'
        'Requires=firmware.service endpoint.service\nAfter=firmware.service endpoint.service\n'
        'PartOf=firmware.service\n\n[Service]\nType=simple\n'
        'ExecStart='+str(RUNTIME / 'daphneServer')+
        ' --dma --gateware-mode raw-dma --expected-gateware-build-id 0x0630a9da --bind tcp://*:40001\n'
        'TimeoutStopSec=30s\nRestart=no\n')
    run('systemctl', 'daemon-reload')


def stop_runtime(gw, profile):
    # Stop FD owners and prove idle while the original overlay is still present.
    run('systemctl', 'stop', 'daphne.service', 'hermes.service', MANUAL)
    if profile.gateware_mode == 'raw-dma':
        if (active('firmware.service') or list(Path('/sys/kernel/config/device-tree/overlays').iterdir()) or
                (Path('/sys/module') / 'daphne_afe_dma').exists()):
            quiesce()
        elif (Path('/sys/module') / 'daphne_dma_bounded').exists():
            raise RuntimeError('Bounded provider remains without a loaded image; inspect before continuing')
    else:
        gw.quiesce_active()
    run('systemctl', 'stop', *STOP, timeout=360)
    if any(active(unit) for unit in STOP):
        raise RuntimeError('Runtime units still active; leaving profile metadata unchanged')
    if list(Path('/sys/kernel/config/device-tree/overlays').iterdir()):
        raise RuntimeError('Overlay removal incomplete; refusing another image')
    # The guarded firmware stop proved quiescence before platform-driver removal.
    for module in ('daphne_afe_dma', 'daphne_dma_bounded'):
        if (Path('/sys/module') / module).exists():
            run('rmmod', module)


def health(units):
    for _ in range(5):
        missing = [unit for unit in units if not active(unit)]
        if missing:
            raise RuntimeError('Runtime unhealthy: '+', '.join(missing))
        time.sleep(.2)


def start_dma(gw, profile):
    run('systemctl', 'start', 'firmware.service', 'daphne-gateware-verify.service', timeout=90)
    gw.verify_profile(profile)
    run('insmod', RUNTIME / 'daphne_dma_bounded.ko')
    for address in ('b0020000', 'b0040000', 'b0060000'):
        name = address+'.dma'
        device = Path('/sys/bus/platform/devices') / name
        if (device / 'driver').resolve().name != 'xilinx-vdma':
            raise RuntimeError('Unexpected DMA provider: '+name)
        (device / 'driver_override').write_text('daphne-dma-bounded')
        Path('/sys/bus/platform/drivers/xilinx-vdma/unbind').write_text(name)
        Path('/sys/bus/platform/drivers/daphne-dma-bounded/bind').write_text(name)
        if (device / 'driver').resolve().name != 'daphne-dma-bounded':
            raise RuntimeError('Bounded DMA provider did not bind: '+name)
    run('insmod', RUNTIME / 'daphne-afe-dma.ko', 'max_pool_mib=448')
    if not Path('/dev/daphne-afe-dma').is_char_device():
        raise RuntimeError('DMA consumer did not bind; retaining overlay for inspection')
    run('systemctl', 'start', 'clockchip.service', 'endpoint.service', timeout=360)
    quiesce()
    run('systemctl', 'start', MANUAL)
    health(CORE+(MANUAL,))
    frontend('prepare')
    frontend('status')


def switch(gw, mode):
    default = gw.load_profile(gw.default_profile_name())
    gw.preflight(default)
    if default.gateware_mode != 'self-trigger':
        raise RuntimeError('This manual setup expects the existing self-trigger boot default')
    dma = gw.Profile('raw-dma', APP, 'raw-dma', 0x44415048, 2, 0, 3, '0x0630a9da')
    target = dma if mode == 'dma' else default
    target_id = gw.preflight(target)
    current = gw.load_active_profile()
    if current.app not in (APP, default.app):
        raise RuntimeError('Unexpected active app; inspect before changing its runtime')
    if mode == 'dma':
        check_assets()
    if active('firmware.service'):
        gw.verify_profile(current)
    if current.app == target.app and active('firmware.service'):
        if mode == 'dma':
            health(CORE+(MANUAL,))
            frontend('status')
        else:
            health(CORE+('daphne-runtime.target', 'hermes.service', 'daphne.service'))
        logging.info('%s already ready; current experiment configuration was preserved', mode)
        return
    install_runtime_files()
    stop_runtime(gw, current)
    gw.atomic_write(gw.ACTIVE_PATH, gw.render_active(target, target_id))
    run('systemctl', 'reset-failed', 'firmware.service', 'daphne-gateware-prepare.service',
        'daphne-gateware-verify.service')
    if mode == 'dma':
        start_dma(gw, target)
    else:
        run('systemctl', 'start', 'daphne-runtime.target', timeout=360)
        health(CORE+('daphne-runtime.target', 'hermes.service', 'daphne.service'))
        gw.verify_profile(target)
    logging.info('READY: %s, tcp://193.206.157.36:40001; boot default unchanged', mode)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('dma', 'default', 'defecto', 'status', 'guard'))
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('Use ~/scripts/daphne-mode, which requests sudo when needed')
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s',
                        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler('/var/log/daphne-manual-mode.log')])
    gw = gateware()
    try:
        if args.mode == 'guard':
            guard(gw)  # Called by firmware.service while the parent owns switch.lock.
        else:
            with gw.switch_lock():
                if args.mode == 'status':
                    profile = gw.load_active_profile()
                    logging.info('Boot default=%s; active=%s app=%s', gw.default_profile_name(), profile.gateware_mode, profile.app)
                    gw.verify_profile(profile)
                    if profile.gateware_mode == 'raw-dma':
                        health(CORE+(MANUAL,))
                        frontend('status')
                    else:
                        health(CORE+('daphne-runtime.target', 'hermes.service', 'daphne.service'))
                else:
                    switch(gw, 'default' if args.mode == 'defecto' else args.mode)
        return 0
    except Exception as error:
        logging.error('%s. No forced unload or reset was attempted; inspect the retained state before retrying.', error)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
