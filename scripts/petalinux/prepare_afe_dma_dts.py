#!/usr/bin/env python3
"""Add opt-in point-4 clients to a normalized hardware DTS; never load it."""
import argparse, hashlib, json, re
from pathlib import Path
import prepare_raw_dma_dts as raw

def transform(text):
    paths=raw.validate(text)
    candidates=[n for n in raw.parse(text) if any('afe-dma-capture' in s.replace('_','-') for s in n.strings('compatible'))]
    if len(candidates)!=1 or candidates[0].cells('reg')!=[0,0xb0080000,0,0x1000]:
        raise ValueError('require exactly one hardware capture controller at B0080000, 4 KiB')
    capture=candidates[0]
    if capture.children or re.search(r'\bdmas\s*=',capture.direct()): raise ValueError('controller already transformed or has children')
    label=capture.name.split(':')[0].strip() if ':' in capture.name else 'daphne_afe_capture'
    if ':' not in capture.name:
        if re.search(r'\b'+re.escape(label)+r'\s*:',raw.clean(text)): raise ValueError('capture label collision')
        text=text[:capture.declaration]+label+': '+text[capture.declaration:]
    result=raw.transform(text)
    nodes=raw.parse(result)
    capture=next(n for n in nodes if n.name.split(':')[0].strip()==label)
    body=result[capture.opening+1:capture.closing]
    regs='reg = <0 0xb0080000 0 0x1000>, <0 0x940000e0 0 0x20>, '+', '.join(f'<0 0x{0xb0020030+r*0x20000:x} 0 8>' for r in range(3))+';'
    for prop,replacement in [('compatible','compatible = "daphne,afe-dma-capture-v1";'),('reg',regs)]:
        body,n=re.subn(r'(?<![\w,#-])'+prop+r'\s*=[^;]+;',replacement,body)
        if n!=1: raise ValueError('ambiguous capture '+prop)
    labels=[n.name.split(':')[0].strip() if ':' in n.name else f'daphne_raw_dma_{r}' for r,n,_ in paths]
    body+='\n  reg-names = "controller", "identity", "monitor0", "monitor1", "monitor2";\n'
    body+='  dmas = '+', '.join(f'<&{name} 1>' for name in labels)+';\n  dma-names = "rx0", "rx1", "rx2";\n'
    edits=[(capture.opening+1,capture.closing,body)]
    producers=[n for n in nodes if n.strings('compatible')==['daphne,raw-dma-diagnostic-v1']]
    if len(producers)!=3: raise ValueError('missing diagnostic consumers')
    for n in producers:
        edits.append((n.closing,n.closing,f'\n  daphne,capture-controller = <&{label}>;\n'))
    for begin,end,replacement in sorted(edits,reverse=True): result=result[:begin]+replacement+result[end:]
    return result

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('input',type=Path);ap.add_argument('output',type=Path)
    args=ap.parse_args()
    if args.output.exists() or args.input.resolve()==args.output.resolve(): ap.error('choose a new output')
    source=args.input.read_bytes();result=transform(source.decode()).encode()
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_bytes(result)
    args.output.with_suffix('.linux-afe.json').write_text(json.dumps({'schema':1,'input_sha256':hashlib.sha256(source).hexdigest(),
       'output_sha256':hashlib.sha256(result).hexdigest(),'consumer_abi':1,'hardware_tested':False},indent=2)+'\n')
    print('AFE/diagnostic Linux clients prepared; compile DTBO and verify handoff before loading')
if __name__=='__main__': main()
