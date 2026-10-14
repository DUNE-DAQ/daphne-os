#!/usr/bin/env python3
"""Grant existing regular users only the fixed, validated deployment entry point."""
import os
from pathlib import Path
import pwd
import re
import shutil
import subprocess
import tempfile

if os.geteuid() != 0:
    raise SystemExit('Run as root')
station = Path('/srv/daphne-deployment/station')
for path in (station, station / 'bin', station / 'station.json'):
    stat = path.stat()
    if stat.st_uid != 0 or stat.st_mode & 0o022:
        raise SystemExit(f'Station must be root owned and not group/world writable: {path}')
users = sorted(p.pw_name for p in pwd.getpwall() if 1000 <= p.pw_uid < 65534
               and re.fullmatch(r'[a-z_][a-z0-9_-]*', p.pw_name)
               and p.pw_shell not in ('/sbin/nologin', '/usr/sbin/nologin', '/bin/false'))
if not users:
    raise SystemExit('No regular operator accounts found')
launcher = Path('/usr/local/sbin/daphne-deploy')
shutil.copyfile(Path(__file__).with_name('daphne-deploy'), launcher)
launcher.chmod(0o755)
os.chown(launcher, 0, 0)
text = ('# Restricted DAPHNE deployment access; no general root shell.\n'
        'User_Alias DAPHNE_OPERATORS = ' + ', '.join(users) + '\n'
        'DAPHNE_OPERATORS ALL=(root) NOPASSWD: NOSETENV: /usr/local/sbin/daphne-deploy\n')
with tempfile.NamedTemporaryFile(mode='w', prefix='daphne-sudoers-', delete=False) as temp:
    temp.write(text)
    temporary = Path(temp.name)
try:
    subprocess.run(['visudo', '-cf', str(temporary)], check=True)
    target = Path('/etc/sudoers.d/daphne-deployment')
    shutil.copyfile(temporary, target)
    target.chmod(0o440)
    os.chown(target, 0, 0)
    subprocess.run(['visudo', '-c'], check=True)
finally:
    temporary.unlink()
print('Deployment access installed for: ' + ', '.join(users))
