"""Load station settings without executing configuration as shell code."""
import ipaddress
import json
import os
from pathlib import Path


def load_station(root=None):
    root = Path(root or Path(__file__).resolve().parents[1])
    path = Path(os.environ.get('DAPHNE_STATION_CONFIG', root / 'station.json'))
    value = json.loads(path.read_text())
    for key in ('station_id', 'vivado_root', 'fixture_server_ip', 'fixture_prefix',
                'tftp_root', 'tftp_release_path', 'fixture_public_key'):
        if key not in value:
            raise ValueError(f'Missing station setting: {key}')
    ipaddress.IPv4Address(value['fixture_server_ip'])
    prefix = value['fixture_prefix']
    if type(prefix) is not int or not 0 <= prefix <= 32:
        raise ValueError('fixture_prefix must be an integer from 0 to 32')
    release_path = Path(value['tftp_release_path'])
    if release_path.is_absolute() or '..' in release_path.parts:
        raise ValueError('tftp_release_path must stay under tftp_root')
    value['netmask'] = str(ipaddress.IPv4Network(f'0.0.0.0/{prefix}').netmask)
    value.setdefault('hw_server_port', 3121)
    value.setdefault('eeprom_i2c_bus', 0)
    return value


if __name__ == '__main__':
    import shlex
    cfg = load_station()
    for name, value in {
        'HW': cfg['vivado_root'], 'HW_SERVER_PORT': cfg['hw_server_port'],
        'STATION_ID': cfg['station_id'],
    }.items():
        print(f'{name}={shlex.quote(str(value))}')
