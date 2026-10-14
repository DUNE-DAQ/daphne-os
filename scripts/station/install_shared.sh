#!/usr/bin/env bash
# Install a reviewed station for all server users; retain sudo for hardware writes.
set -euo pipefail
[[ $EUID == 0 ]] || { echo 'Run with sudo' >&2; exit 2; }
source_dir=${1:?Usage: install_shared.sh EXISTING_DEPLOYMENT_DIRECTORY [DESTINATION]}
destination=${2:-/srv/daphne-deployment}
[[ ! -e $destination ]] || { echo "Destination already exists: $destination" >&2; exit 2; }
install -d -m 0755 "$destination"
for name in repo hardware-database artifacts station; do
  cp -a --reflink=auto "$source_dir/$name" "$destination/$name"
done
rm -rf -- "$destination/station/.venv"
python3 -m venv "$destination/station/.venv"
"$destination/station/.venv/bin/python" -m pip install --no-index "$destination/artifacts/pyserial-3.5-py2.py3-none-any.whl"
python3 - "$destination" <<'PY'
import json, pathlib, shutil, sys
root = pathlib.Path(sys.argv[1])
p = root / 'station/station.json'
config = json.loads(p.read_text())
shutil.copy2(config['fixture_public_key'], root / 'fixture.pub')
config['fixture_public_key'] = str(root / 'fixture.pub')
p.write_text(json.dumps(config, indent=2) + '\n')
PY
chown -hR root:root "$destination"
find "$destination" -type d -exec chmod 0755 {} +
find "$destination" -type f -exec chmod a+r,go-w {} +
find "$destination/station/bin" -maxdepth 1 -type f -exec chmod 0755 {} +
printf 'Shared deployment installed at %s\nAll users can read it; hardware writes use sudo.\n' "$destination"
