#!/usr/bin/env python3
"""Validate a normalized raw-dma DTS and attach Linux diagnostic consumers.

Input is firmware's normalized DTS with resolved local labels, not a legacy
overlay or a hardware-only XSA. Compile the result with dtc -@. This utility
does not install/load firmware, change services, or change default profiles.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re


def clean(text: str) -> str:
    # Preserve offsets for edits. Quoted strings are not comments.
    return re.sub(r'"(?:[^"\\]|\\.)*"|/\*.*?\*/|//[^\n]*',
                  lambda m: m.group() if m.group().startswith('"') else
                  ''.join('\n' if c == '\n' else ' ' for c in m.group()), text, flags=re.S)


class Node:
    def __init__(self, text, name, declaration, opening, parent):
        self.text, self.name = text, name
        self.declaration, self.opening = declaration, opening
        self.parent, self.children, self.closing = parent, [], None

    def direct(self):
        body = self.text[self.opening + 1:self.closing]
        for child in reversed(self.children):
            begin, end = child.declaration - self.opening - 1, child.closing - self.opening
            body = body[:begin] + ' ' * (end - begin) + body[end:]
        return body

    def strings(self, prop):
        match = re.search(r'(?<![\w,#-])' + re.escape(prop) + r'\s*=\s*([^;]+);', self.direct())
        return re.findall(r'"([^"]*)"', match[1]) if match else []

    def cells(self, prop):
        match = re.search(r'(?<![\w,#-])' + re.escape(prop) + r'\s*=\s*<([^>]+)>\s*;', self.direct())
        if not match:
            raise ValueError(f'{self.name}: missing numeric property {prop}')
        try:
            return [int(word, 0) for word in match[1].split()]
        except ValueError as e:
            raise ValueError(f'{self.name}: unresolved numeric property {prop}') from e

    def flag(self, prop):
        return bool(re.search(r'(?<![\w,#-])' + re.escape(prop) + r'\s*;', self.direct()))


def parse(text):
    text = clean(text)
    nodes, stack, boundary = [], [], 0
    for m in re.finditer(r'"(?:[^"\\]|\\.)*"|[{};]', text):
        token = m.group()
        if token == '{':
            declaration = boundary
            while declaration < m.start() and text[declaration].isspace():
                declaration += 1
            node = Node(text, text[declaration:m.start()].strip(), declaration,
                        m.start(), stack[-1] if stack else None)
            if stack:
                stack[-1].children.append(node)
            nodes.append(node)
            stack.append(node)
            boundary = m.end()
        elif token == ';':
            boundary = m.end()
        elif token == '}':
            if not stack:
                raise ValueError('unbalanced DTS braces')
            stack.pop().closing = m.start()
            boundary = m.end()
    if stack:
        raise ValueError('unbalanced DTS braces')
    return nodes


def validate(text):
    nodes = parse(text)
    controllers = [n for n in nodes if 'xlnx,axi-dma-1.00.a' in n.strings('compatible')]
    if len(controllers) != 3:
        raise ValueError('raw-dma requires exactly three DMA controllers')
    if any(n.flag('dma-coherent') for n in nodes):
        raise ValueError('noncoherent raw-dma overlay must not claim dma-coherent')
    by_address = {}
    for n in controllers:
        reg = n.cells('reg')
        if len(reg) != 4 or reg[0] or reg[2:] != [0, 65536] or reg[1] in by_address:
            raise ValueError('invalid/duplicate DMA aperture')
        by_address[reg[1]] = n
    paths = []
    for path in range(3):
        base = 0xB0020000 + path * 0x20000
        n = by_address.get(base)
        if n is None:
            raise ValueError(f'missing DMA at {base:#x}')
        for prop, expected in (('#dma-cells', 1), ('xlnx,addrwidth', 40), ('xlnx,sg-length-width', 26)):
            if n.cells(prop) != [expected]:
                raise ValueError(f'incorrect {prop}')
        if not n.flag('xlnx,include-sg') or len(n.children) != 1:
            raise ValueError('expected SG and a single S2MM channel')
        channel = n.children[0]
        if channel.strings('compatible') != ['xlnx,axi-dma-s2mm-channel'] or \
                channel.cells('xlnx,datawidth') != [128] or channel.flag('xlnx,include-dre'):
            raise ValueError('expected 128-bit S2MM without DRE')
        if channel.cells('interrupts') != [0, 104 + path, 4] or \
                not re.search(r'interrupt-parent\s*=\s*<&gic>\s*;', n.direct() + channel.direct()):
            raise ValueError('wrong GIC interrupt contract; use normalized DTS with &gic')
        names = n.strings('clock-names')
        expected = {'s_axi_lite_aclk', 'm_axi_sg_aclk', 'm_axi_s2mm_aclk'}
        if len(names) != 3 or set(names) != expected:
            raise ValueError('wrong DMA clock names')
        clocks = re.search(r'(?<![\w,-])clocks\s*=([^;]+);', n.direct())
        refs = re.findall(r'<([^>]+)>', clocks[1]) if clocks else []
        if len(refs) != 3 or len(set(r.strip() for r in refs)) != 1:
            raise ValueError('DMA clocks must all use PL2')
        ref = refs[0].split()
        if ref == ['&zynqmp_clk', '73'] or (len(ref) == 2 and ref[0] == '&zynqmp_clk' and int(ref[1], 0) == 73):
            pass
        elif len(ref) == 1 and ref[0].startswith('&'):
            providers = [p for p in nodes if p.name.split(':')[0].strip() == ref[0][1:]]
            if len(providers) != 1 or providers[0].cells('clock-frequency') != [199998001]:
                raise ValueError('wrong PL2 frequency')
        else:
            raise ValueError('unresolved PL2 clock')
        producers = []
        for candidate in nodes:
            if not candidate.strings('compatible') or 'dma-diagnostic-source' not in ','.join(candidate.strings('compatible')):
                continue
            if candidate.cells('reg') == [0, base + 65536, 0, 4096]:
                producers.append(candidate)
        if len(producers) != 1 or producers[0].children:
            raise ValueError(f'missing/ambiguous diagnostic producer for path {path}')
        paths.append((path, n, producers[0]))
    return paths


def transform(text):
    paths = validate(text)
    edits = []
    all_labels = set(re.findall(r'\b([A-Za-z_][\w]*):\s*[^;{}]*{', clean(text)))
    for path, dma, producer in paths:
        if ':' in dma.name:
            label = dma.name.split(':')[0].strip()
        else:
            label = f'daphne_raw_dma_{path}'
            if label in all_labels:
                raise ValueError('diagnostic DMA label collision')
            edits.append((dma.declaration, dma.declaration, label + ': '))
        if any(re.search(r'(?<![\w,#-])' + prop + r'\s*[=;]', producer.direct())
               for prop in ('dmas', 'dma-names', 'reg-names', 'daphne,path-id')):
            raise ValueError('producer already has Linux consumer properties')
        body = text[producer.opening + 1:producer.closing]
        masked = producer.text[producer.opening + 1:producer.closing]
        base = 0xB0020000 + path * 0x20000
        reg = f'reg = <0 0x{base+65536:x} 0 0x1000>, <0 0x940000e0 0 0x20>, <0 0x{base+0x30:x} 0 8>;'
        body_edits = []
        for prop, replacement in (('compatible', 'compatible = "daphne,raw-dma-diagnostic-v1";'),
                                  ('reg', reg)):
            matches = list(re.finditer(r'(?<![\w,#-])' + prop + r'\s*=[^;]+;', masked))
            if len(matches) != 1:
                raise ValueError(f'producer requires exactly one {prop}')
            body_edits.append((matches[0].start(), matches[0].end(), replacement))
        for begin, end, replacement in sorted(body_edits, reverse=True):
            body = body[:begin] + replacement + body[end:]
        body += f'\n  reg-names = "producer", "identity", "dma-monitor";\n  daphne,path-id = <{path}>;\n  dmas = <&{label} 1>;\n  dma-names = "rx";\n'
        edits.append((producer.opening + 1, producer.closing, body))
    for begin, end, replacement in sorted(edits, reverse=True):
        text = text[:begin] + replacement + text[end:]
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    if args.input.resolve() == args.output.resolve() or args.output.exists():
        parser.error('choose a new output; firmware inputs are never overwritten')
    original = args.input.read_bytes()
    result = transform(original.decode()).encode()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(result)
    record = {'schema': 1, 'input_sha256': hashlib.sha256(original).hexdigest(),
              'output_sha256': hashlib.sha256(result).hexdigest(),
              'hardware_tested': False, 'consumer_abi': 1}
    args.output.with_suffix('.linux-dma.json').write_text(json.dumps(record, indent=2) + '\n')
    print('raw-dma Linux consumer DTS prepared; compile and verify the new DTBO separately')


if __name__ == '__main__':
    main()
