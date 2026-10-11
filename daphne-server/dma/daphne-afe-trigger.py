#!/usr/bin/env python3
"""Explicit triggered-DDR qualification; no firmware/service/SPI changes.

software: wait for hardware ARMED then emit MMIO trigger.
external/timing: wait for the physical hardware event, with bounded timeout.
This uses the new kernel API directly; server/protobuf integration is separate.
"""
import argparse, array, ctypes, fcntl, importlib.util, json, os, select, struct, sys, time
from pathlib import Path
spec=importlib.util.spec_from_file_location('finite_capture',Path(__file__).with_name('daphne-afe-capture.py'))
finite=importlib.util.module_from_spec(spec);spec.loader.exec_module(finite)
class TriggerConfig(ctypes.LittleEndianStructure):
    _fields_=[(k,ctypes.c_uint32) for k in ('abi','flags','length','pretrigger','period_ticks','ring_ticks','source','timeout_ms','expected_build_id','reserved')]+[('channel_mask',ctypes.c_uint64)]
class TriggerStatus(ctypes.LittleEndianStructure):
    _fields_=[('capture',finite.Status)]+[(k,ctypes.c_uint64) for k in ('stream_ticks','trigger_index','trigger_timestamp','window_first')]+[(k,ctypes.c_uint32) for k in ('abi','armed','trigger_flags','ignored_triggers','pretrigger','period_ticks','ring_ticks','source')]
assert ctypes.sizeof(TriggerConfig)==48 and ctypes.sizeof(TriggerStatus)==272
PREPARE=finite.ioctl(1,0x45,48);ARM=finite.ioctl(0,0x46)
TRIGGER=finite.ioctl(0,0x47);STATUS=finite.ioctl(2,0x48,272)
def status(fd):
    buf=bytearray(272);fcntl.ioctl(fd,STATUS,buf,True)
    return TriggerStatus.from_buffer_copy(buf)
def verify(data,channels,word_offset,first):
    words=array.array('H');words.frombytes(data)
    if sys.byteorder!='little': words.byteswap()
    for j,value in enumerate(words,word_offset):
        expected=(channels[j%len(channels)]<<10)|((first+j//len(channels))&1023)
        if value!=expected: raise RuntimeError(f'pattern mismatch word {j}: {value:#x} != {expected:#x}')
def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--channels',required=True)
    ap.add_argument('--length',type=int,required=True)
    ap.add_argument('--pretrigger',type=int,required=True)
    ap.add_argument('--period-ticks',type=int,default=65536)
    ap.add_argument('--ring-ticks',type=int,help='default: round L+2*period up to a period')
    ap.add_argument('--source',choices=['software','external','timing'],required=True)
    ap.add_argument('--expected-build-id',type=lambda s:int(s,0),required=True)
    ap.add_argument('--timeout-ms',type=int,default=10000)
    ap.add_argument('--pattern',action='store_true')
    ap.add_argument('--frontend-aligned',action='store_true')
    ap.add_argument('--device',default='/dev/daphne-afe-dma')
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    channels=sorted(int(x) for x in args.channels.split(','))
    flags=int(args.pattern)+2*int(args.frontend_aligned)
    finite.configuration(channels,args.length,1,flags,args.timeout_ms,args.expected_build_id)
    period=args.period_ticks
    ring=args.ring_ticks or ((args.length+3*period-1)//period)*period
    if not (0<=args.pretrigger<args.length and 8<=period<=1048576 and period&(period-1)==0 and
            ring%period==0 and ring>=args.length+2*period and ring//period<=512):
        ap.error('invalid P/period/ring geometry')
    config=TriggerConfig(1,flags,args.length,args.pretrigger,period,ring,
                         ['software','external','timing'].index(args.source),args.timeout_ms,
                         args.expected_build_id,0,sum(1<<c for c in channels))
    args.output.mkdir(parents=True,exist_ok=False)
    fd=os.open(args.device,os.O_RDONLY|os.O_CLOEXEC)
    try:
        fcntl.ioctl(fd,PREPARE,bytes(config));fcntl.ioctl(fd,ARM)
        deadline=time.monotonic()+args.timeout_ms/1000+5;sent=False
        poller=select.poll();poller.register(fd,select.POLLIN|select.POLLERR|select.POLLHUP)
        while True:
            s=status(fd)
            if s.capture.state!=2: break
            if args.source=='software' and s.armed and not sent:
                try: fcntl.ioctl(fd,TRIGGER);sent=True
                except BlockingIOError: pass
            if time.monotonic()>deadline: raise TimeoutError('acquisition timeout')
            poller.poll(10)
        if s.capture.state!=3 or s.capture.error or not s.capture.guards_ok or not(s.trigger_flags&2):
            raise RuntimeError(f'invalid result: {finite.as_dict(s.capture)}')
        if s.trigger_index-s.window_first!=args.pretrigger:
            raise RuntimeError('incorrect pretrigger index')
        for r in range(3):
            selected=[c for c in channels if r*16<=c<min(40,(r+1)*16)]
            if not selected: continue
            fcntl.ioctl(fd,finite.SELECT_ROUTE,struct.pack('<I',r))
            remaining=args.length*len(selected)*2;received=0
            if s.capture.valid_bytes[r]!=remaining: raise RuntimeError('invalid waveform size')
            with (args.output/f'route{r}.raw16').open('xb') as out:
                while remaining:
                    data=os.read(fd,min(1<<20,remaining))
                    if not data or len(data)%2: raise RuntimeError('short/odd waveform')
                    if args.pattern: verify(data,selected,received//2,s.window_first)
                    out.write(data);received+=len(data);remaining-=len(data)
        report={k:getattr(s,k) for k,_ in s._fields_ if k!='capture'}
        report.update(result='PASS',L=args.length,P=args.pretrigger,channels=channels,
                      source=args.source,pattern=args.pattern,timestamp_valid=bool(s.trigger_flags&1),
                      capture=finite.as_dict(s.capture),format='raw16-le-tick-major')
        (args.output/'metadata.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report))
    finally:
        # Driver close aborts/proves halt and releases DDR. Never unload an overlay
        # to recover from QUARANTINED: descriptors and payload must stay pinned.
        os.close(fd)
if __name__=='__main__': main()
