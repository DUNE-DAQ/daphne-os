#!/usr/bin/env python3
import pathlib,serial,re,time,zlib,json,sys
from station_config import load_station
root=pathlib.Path(__file__).resolve().parents[1]
station=load_station(root)
if not __debug__: raise SystemExit('Do not run deployment scripts with Python -O')
asset=sys.argv[1]; assert re.fullmatch(r'DAPHNE-[0-9]{3}',asset)
e=root/'evidence'/asset
r=e/'eeprom'
record=json.loads((root/'records'/asset/'board-config-v1.json').read_text())
mac=record['som']['factory_mac_id_0']
ip=record['network']['ipv4_address']
assert re.fullmatch(r'(?:[0-9a-f]{2}:){5}[0-9a-f]{2}',mac)
assert re.fullmatch(r'[0-9.]+',ip)
assert re.search(r'Bootmode: +QSPI_MODE', (e/'qspi-first-boot.log').read_text())
s=serial.Serial(sys.argv[2],115200,timeout=.1,exclusive=True)
f=(e/'persistent-settings.log').open('wb');seq=0
s.write(b'\r');time.sleep(.5);f.write(s.read_all())
def run(c):
 global seq
 seq+=1;t=f'ENV_STEP_{seq}';s.write((c+'; echo '+t+':$?\r').encode());out=b'';deadline=time.monotonic()+90
 while time.monotonic()<deadline:
  b=s.read(4096);out+=b;f.write(b);f.flush()
  m=re.search(rb'\r?\n'+t.encode()+rb':([0-9]+)\r?\n',out)
  if m and out.rstrip().endswith(b'ZynqMP>'):
   assert int(m.group(1))==0,out.decode(errors='replace')
   print(out.decode(errors='replace'),flush=True);return out.decode(errors='replace')
 raise RuntimeError('Timeout '+c)
try:
 run('i2c dev '+str(station['eeprom_i2c_bus']));out=run('i2c md 0x50 0x0.2 0x100')
 data=b''.join(bytes.fromhex(x) for x in re.findall(r'^\s*[0-9a-f]{4}: ((?:[0-9a-f]{2} ){15}[0-9a-f]{2})',out,re.M));assert data==(r/'som-eeprom.bin').read_bytes()[:256]
 run('mmc dev 0 0')
 for name,addr in [('Image',0x18000000),('system.dtb',0x40000000)]:
  expected=(root/'kit/image'/('verify-'+name)).read_bytes();out=run(f'fatload mmc 0:1 0x{addr:x} {name}');assert f'{len(expected)} bytes read' in out
  out=run(f'crc32 0x{addr:x} 0x{len(expected):x}');assert f'==> {zlib.crc32(expected):08x}' in out
 commands=[
 'setenv -f ethaddr '+mac,
 'setenv ethact ethernet@ff0b0000','setenv ethrotate no','setenv netretry no',
 'setenv hostname '+record['network']['hostname'], 'setenv board_id '+asset, 'setenv ipaddr '+ip,'setenv serverip '+station['fixture_server_ip'],'setenv netmask '+station['netmask'],
 "setenv netinit 'mw.l 0xff5e0050 0x06010c00; mw.l 0xfd402860 0x80; mw.l 0xff0b0200 0x1340; mw.l 0xff0b0004 0x092e0c4a; sleep 2'",
 "setenv preboot 'run netinit'",
 "setenv bootcmd 'mmc dev 0 0 && fatload mmc 0:1 0x18000000 Image && fatload mmc 0:1 0x40000000 system.dtb && setenv bootargs earlycon console=ttyPS1,115200 root=/dev/mmcblk0p2 rootwait rw && booti 0x18000000 - 0x40000000'",
 'setenv bootdelay 2','setenv autoload no',
 'saveenv','printenv ethaddr serverip netmask netinit preboot bootcmd bootdelay']
 for c in commands:run(c)
 (e/'environment-status.txt').write_text('Persistent environment saved in QSPI; autonomous reboot validation pending\n')
finally:s.close();f.close()
