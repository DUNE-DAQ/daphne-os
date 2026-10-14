#!/usr/bin/env python3
"""Assemble the versioned process in a persistent station directory."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
from prepare_release import prepare


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--artifacts', type=Path, required=True, help='Pinned BOOT.BIN and rootfs.wic.gz')
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--inventory-repo', type=Path, required=True, help='hardware-database Git checkout')
    parser.add_argument('--no-install', action='store_true', help='Use existing Python dependencies')
    args = parser.parse_args()
    directory = args.directory.expanduser().resolve()
    if str(directory).startswith(('/tmp/', '/var/tmp/')):
        parser.error('Use a persistent directory outside /tmp and /var/tmp')
    if directory.exists() and any(directory.iterdir()):
        parser.error('Choose a new empty station directory; existing state is never overwritten')
    source = Path(__file__).resolve().parent
    release = json.loads((source / 'release.json').read_text())
    # Verify both artifacts before creating the station.
    for name, expected in release['artifacts'].items():
        data = (args.artifacts / name).read_bytes()
        if len(data) != expected['size'] or hashlib.sha256(data).hexdigest() != expected['sha256']:
            parser.error(f'Artifact mismatch: {name}')
    revision = release['hardware_database_revision']
    inventory = subprocess.run(['git', '-C', str(args.inventory_repo), 'archive', revision,
                               'tools/daphne_production', 'tools/daphne_production_cli.py',
                               'schemas/daphne-production', 'migrations/production'],
                              check=True, capture_output=True).stdout
    directory.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source / 'bin', directory / 'bin', ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copy2(args.config, directory / 'station.json')
    shutil.copy2(source / 'release.json', directory / 'release.json')
    for name in ('database', 'records', 'evidence', 'results', 'kit/inventory', 'kit/bin'):
        (directory / name).mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(inventory)) as archive:
        for member in archive.getmembers():
            if member.issym() or member.islnk() or Path(member.name).is_absolute() or '..' in Path(member.name).parts:
                raise ValueError('Unsafe inventory archive member')
        archive.extractall(directory / 'kit/inventory')
    repo = source.parents[1]
    for name in ('serial_catch_uboot.py', 'uboot_dump_i2c_eeprom.py', 'uboot_serial.py'):
        shutil.copy2(repo / 'scripts/remote' / name, directory / 'kit/bin' / name)
    derived = prepare(args.artifacts, directory, release)
    shutil.copy2(source / 'bootstrap-qualified-ram.tcl', directory / 'qualified-ram/bootstrap-qualified-ram.tcl')
    if (source / 'qa').exists():
        shutil.copytree(source / 'qa', directory / 'qa')
        shutil.copytree(repo / 'daphne-server', directory / 'qa/vendor/daphne-server',
                        ignore=shutil.ignore_patterns('__pycache__', '*.log'))
    if not args.no_install:
        subprocess.run([sys.executable, '-m', 'venv', str(directory / '.venv')], check=True)
        subprocess.run([str(directory / '.venv/bin/python'), '-m', 'pip', 'install',
                        '-r', str(source / 'requirements.txt')], check=True)
    for p in (directory / 'bin').iterdir():
        if p.is_file():
            p.chmod(0o755)
    revision_proc = subprocess.run(['git', '-C', str(repo), 'rev-parse', 'HEAD'],
                                   capture_output=True, text=True, check=True)
    provenance = {'source_revision': revision_proc.stdout.strip(),
                  'hardware_database_revision': revision, 'derived_sha256': derived,
                  'qualification': release['qualification']}
    provenance['process_sha256'] = {str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest()
                                    for p in sorted(directory.rglob('*'))
                                    if p.is_file() and '.venv' not in p.parts and '__pycache__' not in p.parts}
    (directory / 'station-manifest.json').write_text(json.dumps(provenance, indent=2) + '\n')
    print(f'Station assembled: {directory}. No board commands were sent.')


if __name__ == '__main__':
    main()
