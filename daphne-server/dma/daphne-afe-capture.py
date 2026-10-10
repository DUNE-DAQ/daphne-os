#!/usr/bin/env python3
"""Explicit finite AFE chunk test; does not change gateware or runtime services."""
import argparse, array, ctypes, fcntl, json, os, select, signal, struct, sys, time
from pathlib import Path

class Config(ctypes.LittleEndianStructure):
    _fields_=[(k,ctypes.c_uint32) for k in ('abi','flags','length','count','timeout_ms','expected_build_id')]+[('channel_mask',ctypes.c_uint64)]
class Status(ctypes.LittleEndianStructure):
    _fields_=([(k,ctypes.c_int32 if k=='error' else ctypes.c_uint32) for k in
      ('abi','state','error','flags','active_routes','hardware_status','hardware_error','guards_ok','build_id','format','captured_ticks','reserved')]+
      [(k,ctypes.c_uint64) for k in ('channel_mask','timestamp','allocated_bytes','start_ns','end_ns')]+
      [(k,ctypes.c_uint64*3) for k in ('valid_bytes','transfer_bytes','received_bytes','accepted_beats')]+
      [(k,ctypes.c_uint32*3) for k in ('dma_status','dma_control')])

def ioctl(direction,number,size=0): return (direction<<30)|(size<<16)|(ord('A')<<8)|number
PREPARE=ioctl(1,0x40,32);START=ioctl(0,0x41);GET_STATUS=ioctl(2,0x42,208)
SELECT_ROUTE=ioctl(1,0x43,4);ABORT=ioctl(0,0x44)
def status(fd):
    buf=bytearray(208);fcntl.ioctl(fd,GET_STATUS,buf,True)
    return Status.from_buffer_copy(buf)
def as_dict(s):
    return {name:list(value) if isinstance(value,ctypes.Array) else value
            for name,_ in s._fields_ for value in [getattr(s,name)]}
def configuration(channels,length,count,flags,timeout,build):
    if not channels or len(set(channels))!=len(channels) or any(c<0 or c>39 for c in channels):
        raise ValueError('channels must be unique integers 0..39')
    if not (1<=length<=0xffffffff and 1<=count<=0xffffffff and length*count<=0xffffffff):
        raise ValueError('L*C must fit a nonzero 32-bit tick count')
    if not (10<=timeout<=600000 and 0<=build<=0xfffffff): raise ValueError('invalid timeout/build ID')
    if flags not in (1,2,3): raise ValueError('explicit pattern or frontend alignment acknowledgement required')
    lengths=[2*length*count*sum(r*16<=ch<min(40,(r+1)*16) for ch in channels) for r in range(3)]
    if any(n>256*1024*1024 for n in lengths): raise ValueError('route exceeds 256 MiB; reduce C')
    return Config(1,flags,length,count,timeout,build,sum(1<<ch for ch in channels)),lengths
def verify_pattern(data,channels,offset):
    words=array.array('H');words.frombytes(data)
    if sys.byteorder!='little': words.byteswap()
    for j,value in enumerate(words,offset):
        expected=(channels[j%len(channels)]<<10)|((j//len(channels))&1023)
        if value!=expected: raise ValueError(f'pattern mismatch at word {j}: {value:#06x} != {expected:#06x}')

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--acquisition',required=True,choices=['dma-afe'])
    ap.add_argument('--channels',required=True,help='canonical IDs, e.g. 1,5,9,15')
    ap.add_argument('--length',type=int,required=True,help='L: samples per waveform')
    ap.add_argument('--count',type=int,required=True,help='C: consecutive waveforms in this chunk')
    ap.add_argument('--expected-build-id',type=lambda s:int(s,0),required=True)
    ap.add_argument('--pattern',action='store_true',help='pattern before CDC, not physical AFE samples')
    ap.add_argument('--frontend-aligned',action='store_true',help='explicitly confirm prior AFE alignment/configuration')
    ap.add_argument('--timeout-ms',type=int,default=10000)
    ap.add_argument('--device',default='/dev/daphne-afe-dma')
    ap.add_argument('--output',type=Path,required=True,help='new directory for progressive raw files and metadata')
    args=ap.parse_args()
    try:
        channels=sorted(int(s) for s in args.channels.split(','))
        cfg,lengths=configuration(channels,args.length,args.count,int(args.pattern)|int(args.frontend_aligned)*2,
                                  args.timeout_ms,args.expected_build_id)
    except ValueError as exc: ap.error(str(exc))
    assert ctypes.sizeof(Config)==32 and ctypes.sizeof(Status)==208
    args.output.mkdir(parents=True,exist_ok=False)
    fd=None
    old={sig:signal.getsignal(sig) for sig in (signal.SIGTERM,signal.SIGINT)}
    def interrupt(sig,frame): raise KeyboardInterrupt(f'signal {sig}')
    for sig in old: signal.signal(sig,interrupt)
    try:
        fd=os.open(args.device,os.O_RDONLY|os.O_CLOEXEC)
        fcntl.ioctl(fd,PREPARE,bytes(cfg));fcntl.ioctl(fd,START)
        poller=select.poll();poller.register(fd,select.POLLIN|select.POLLERR|select.POLLHUP)
        deadline=time.monotonic()+args.timeout_ms/1000+5
        while True:
            s=status(fd)
            if s.state!=2: break
            if time.monotonic()>deadline: raise TimeoutError('userspace watchdog; cancel without retry')
            poller.poll(100)
        if s.state!=3 or s.error or s.hardware_error or not s.guards_ok:
            raise RuntimeError(f'invalid chunk: {as_dict(s)}')
        if s.captured_ticks!=args.length*args.count or list(s.valid_bytes)!=lengths:
            raise RuntimeError('chunk length mismatch')
        for r,n in enumerate(lengths):
            if not n: continue
            if s.transfer_bytes[r]!=(n+15)//16*16 or s.received_bytes[r]!=s.transfer_bytes[r]:
                raise RuntimeError('DMA transfer length mismatch')
            fcntl.ioctl(fd,SELECT_ROUTE,struct.pack('<I',r))
            selected=[ch for ch in channels if r*16<=ch<min(40,(r+1)*16)]
            received=0
            with (args.output/f'route{r}.raw16').open('xb') as out:
                while received<n:
                    data=os.read(fd,min(4*1024*1024,n-received))
                    if not data or len(data)%2: raise RuntimeError('short/odd raw16 read')
                    if args.pattern: verify_pattern(data,selected,received//2)
                    out.write(data);received+=len(data)
        # Prove halt before closing/freeing, then inspect the reopened client.
        fcntl.ioctl(fd,ABORT)
        cleanup=status(fd)
        if cleanup.state==6 or any(not (v&1) for v in cleanup.dma_status) or any(v&5 for v in cleanup.dma_control):
            raise RuntimeError('halt/reset not proven; do not unload the overlay')
        os.close(fd);fd=None
        with_fd=os.open(args.device,os.O_RDONLY|os.O_CLOEXEC)
        try:
            released=status(with_fd)
            if released.state!=0 or released.allocated_bytes: raise RuntimeError('buffers not released after close')
        finally: os.close(with_fd)
        report={'result':'PASS','source':'pre-CDC-pattern' if args.pattern else 'physical-AFE',
                'channels':channels,'L':args.length,'C':args.count,'format':'raw16-le-tick-major',
                'timestamp_valid':bool(s.hardware_status&64),'pattern_verified':args.pattern,'status':as_dict(s)}
        report['DMA_bytes_per_second']=sum(s.received_bytes)*1e9/(s.end_ns-s.start_ns)
        report['cleanup_verified']=True
        (args.output/'metadata.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report))
    except BaseException as exc:
        if fd is not None:
            try:
                fcntl.ioctl(fd,ABORT)
                (args.output/'failure.json').write_text(json.dumps({'error':str(exc),'status':as_dict(status(fd))},indent=2)+'\n')
            except Exception as abort_exc: print(f'abort/status failed: {abort_exc}',file=sys.stderr)
        raise
    finally:
        if fd is not None: os.close(fd)
        for sig,handler in old.items(): signal.signal(sig,handler)
if __name__=='__main__': main()
