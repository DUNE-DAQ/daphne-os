#!/usr/bin/env python3
import pathlib,hashlib,json,zlib,gzip,shutil,serial,time,re,sys
from station_config import load_station
root=pathlib.Path(__file__).resolve().parents[1]
station=load_station(root)
if not __debug__: raise SystemExit('Do not run deployment scripts with Python -O')
asset=sys.argv[1]
assert re.fullmatch(r'DAPHNE-[0-9]{3}',asset)
r=root/'evidence'/asset/'eeprom'
e=root/'evidence'/asset/('flash-'+time.strftime('%Y%m%dT%H%M%SZ',time.gmtime()))
e.mkdir(parents=True,exist_ok=False)
m=root/'kit/image'
identity=json.loads((r/'som-eeprom-decoded.json').read_text())
assert identity['eeprom']['fru_checksum_valid'] is True
mac=identity['som']['factory_mac_id_0']
assert re.fullmatch(r'(?:[0-9a-f]{2}:){5}[0-9a-f]{2}',mac)
config=json.loads((root/'records'/asset/'board-config-v1.json').read_text()); ip=config['network']['ipv4_address']
device=sys.argv[2]
print('Evidence:',e,flush=True)
manifest=json.loads((m/'manifest.json').read_text()); compressed=(m/'rootfs.wic.gz').read_bytes()
assert hashlib.sha256(compressed).hexdigest()==manifest['sha256']
assert len(compressed)==manifest['compressed_size'] and f'{zlib.crc32(compressed):08x}'==manifest['crc32']
raw=gzip.decompress(compressed); assert len(raw)==manifest['uncompressed_size']; assert hashlib.sha256((r/'som-eeprom.bin').read_bytes()).hexdigest()==identity['eeprom']['sha256']
q=(root/'kit/boot/BOOT.BIN').read_bytes()
assert hashlib.sha256(q).hexdigest()=='da30be96dfd9e02d76e957d0cbb3d38d2bfe6d8c9019b1ac417108ca64024da8'
stage=pathlib.Path(station['tftp_root'])/station['tftp_release_path']; assert stage.is_dir()
shutil.copyfile(m/'rootfs.wic.gz',stage/'rootfs.wic.gz'); (stage/'rootfs.wic.gz').chmod(0o644)
assert hashlib.sha256((stage/'rootfs.wic.gz').read_bytes()).hexdigest()==manifest['sha256']
s=serial.Serial(device,115200,timeout=.1,exclusive=True)
log=(e/'flash-verified.log').open('wb'); seq=0
s.write(b'\r');time.sleep(.5);log.write(s.read_all())
def run(c,timeout=180):
 global seq
 seq+=1;token=f'FLASH_STEP_{seq:03d}'; print(c,flush=True)
 s.write((c+'; echo '+token+':$?\r').encode());out=b'';deadline=time.monotonic()+timeout
 while time.monotonic()<deadline:
  b=s.read(8192);out+=b;log.write(b);log.flush()
  match=re.search(rb'\r?\n'+token.encode()+rb':([0-9]+)\r?\n',out)
  if match and out.rstrip().endswith(b'ZynqMP>'):
   if int(match.group(1)): raise RuntimeError(out.decode(errors='replace'))
   return out.decode(errors='replace')
 raise RuntimeError('TIMEOUT '+c+'; no further commands issued')
def crc(addr,length,expected):
 out=run(f'crc32 0x{addr:x} 0x{length:x}'); found=re.search(r'==> ([0-9a-fA-F]{8})',out)
 assert found and found.group(1).lower()==expected,(expected,out)
def mark(t):
 (e/'flash-status.txt').write_text(t+'\n');print(t,flush=True)
try:
 run('i2c dev '+str(station['eeprom_i2c_bus'])); identity=run('i2c md 0x50 0x0.2 0x100')
 data=b''.join(bytes.fromhex(x) for x in re.findall(r'^\s*[0-9a-f]{4}: ((?:[0-9a-f]{2} ){15}[0-9a-f]{2})',identity,re.M))
 assert data==(r/'som-eeprom.bin').read_bytes()[:256], 'SoM identity mismatch'
 run('setenv -f ethaddr '+mac);run('setenv ipaddr '+ip);run('setenv serverip '+station['fixture_server_ip']);run('setenv ethact ethernet@ff0b0000');run('setenv ethrotate no');run('setenv netretry no');run('setenv autoload no');run('mw.l 0xff5e0050 0x06010c00');run('mw.l 0xfd402860 0x80');run('mw.l 0xff0b0004 0x092e0c4a');run('gpio set 52');run('mw.l 0xff0b0200 0x1340');run('sleep 2');pcs=run('md.l 0xff0b0200 1');assert '00001140' in pcs,pcs;run('ping '+station['fixture_server_ip'])
 out=run('tftpboot 0x10000000 '+station['tftp_release_path']+'/BOOT.BIN');assert 'Bytes transferred = 9661828 ' in out
 crc(0x10000000,len(q),'4b5ef7a3');run('sf probe 0 0 0')
 mark('QSPI write starting; source size and CRC verified')
 run(f'sf update 0x10000000 0 0x{len(q):x}',300)
 run(f'sf read 0x18000000 0 0x{len(q):x}');crc(0x18000000,len(q),'4b5ef7a3')
 run(f'cmp.b 0x10000000 0x18000000 0x{len(q):x}');mark('QSPI VERIFIED')
 out=run('tftpboot 0x10000000 '+station['tftp_release_path']+'/rootfs.wic.gz');assert f'Bytes transferred = {len(compressed)} ' in out
 crc(0x10000000,len(compressed),manifest['crc32']);run('mmc dev 0 0');run('mmc rescan')
 mark('QSPI VERIFIED; eMMC write starting; source size and CRC verified')
 out=run(f'gzwrite mmc 0 0x10000000 0x{len(compressed):x} 0x100000 0 0x{len(raw):x}',300)
 assert re.search(rf'{len(raw)}\s+bytes,\s+crc',out),out
 mark('QSPI VERIFIED; eMMC written, full readback in progress')
 for offset in range(0,len(raw),0x4000000):
  part=raw[offset:offset+0x4000000]; assert len(part)%512==0
  run(f'mmc read 0x18000000 0x{offset//512:x} 0x{len(part)//512:x}')
  crc(0x18000000,len(part),f'{zlib.crc32(part):08x}')
  print(f'eMMC readback verified {offset+len(part)}/{len(raw)} bytes',flush=True)
 run('mmc rescan');print(run('part list mmc 0'),flush=True);print(run('fatls mmc 0:1'),flush=True)
 mark('QSPI AND EMMC FULL READBACK VERIFIED; QSPI reboot/environment configuration pending')
except Exception as exc:
 mark('STOPPED: '+str(exc));raise
finally:
 s.close();log.close()
