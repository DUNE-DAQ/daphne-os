#!/usr/bin/env python3
"""Check row-audit completeness/provenance, not the truth of human assessments.

Read-only, standard library only. Optional original workbook/export checks need
the exact hash-pinned user-provided artifacts. No hardware/network access.
"""
import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile

HEADERS = ('id', 'workbook_row', 'variable', 'meaning', 'priority', 'mode',
           'implementation', 'evidence_group', 'mapping', 'remaining_work')
SEMANTIC_KEYS = HEADERS[:6]
XLSX_COLUMNS = {
    'A': 'id', 'B': 'variable', 'C': 'meaning', 'D': 'nature', 'E': 'producer',
    'F': 'authority', 'G': 'mode', 'H': 'status', 'I': 'priority', 'J': 'why',
    'K': 'origin', 'L': 'wire', 'M': 'dtype', 'N': 'unit', 'O': 'scope',
    'P': 'executor', 'Q': 'route', 'R': 'consumers', 'S': 'validation',
    'T': 'evidence', 'U': 'decision', 'V': 'review', 'W': 'reviewer',
    'X': 'review_notes', 'Y': 'original_row', 'Z': 'original_node',
    'AA': 'legacy_status', 'AB': 'lifecycle', 'AC': 'implementation',
    'AD': 'implementation_basis',
}


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_rows(path):
    with path.open(encoding='utf-8', newline='') as stream:
        reader = csv.DictReader(stream)
        require(tuple(reader.fieldnames or ()) == HEADERS, 'Unexpected audit columns')
        return list(reader)


def validate(root, rows, metadata):
    require(metadata['format'] == 'daphne-server-v05-row-audit-v1', 'Unknown audit format')
    require(metadata['snapshot_only'] is True and metadata['full_goal_complete'] is False,
            'An audit ledger must not silently become a completion claim')
    require(len(rows) == metadata['row_count'] == 251, 'Expected exactly 251 rows')
    require(len({r['id'] for r in rows}) == len(rows), 'Duplicate audit ID')
    require([r['workbook_row'] for r in rows] == [str(i) for i in range(6, 257)],
            'Workbook row order/gaps differ')
    definitions = metadata['implementation_definitions']
    require(set(definitions) == {'implemented', 'partial', 'missing', 'contract-pending'},
            'Unexpected assessment states')
    groups = metadata['evidence_groups']
    used = set()
    for row in rows:
        require(set(row) == set(HEADERS) and all(isinstance(v, str) and v.strip() for v in row.values()),
                'Missing/empty audit cell')
        require(re.fullmatch(r'(?:I|SV)[0-9]{3}', row['id']), 'Invalid audit ID')
        require(row['implementation'] in definitions, 'Unknown assessment state')
        require(row['evidence_group'] in groups, 'Unknown evidence group')
        used.add(row['evidence_group'])
    require(used == set(groups), 'Unused or omitted evidence group')
    semantics = [{k: row[k] for k in SEMANTIC_KEYS} for row in rows]
    canonical = json.dumps(semantics, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
    require(digest(canonical) == metadata['source_semantics_sha256'], 'Original row semantics changed')
    counts = dict(Counter(r['implementation'] for r in rows))
    require(counts == metadata['expected_counts'], 'Assessment counts need an explicit snapshot update')
    code_paths = set()
    for group in groups.values():
        for key in ('source_refs', 'evidence_refs'):
            require(group[key], 'Empty reference group')
            for name in group[key]:
                path = Path(name)
                require(not path.is_absolute() and '..' not in path.parts, 'Reference escapes repository')
                require((root / path).is_file(), 'Reference file is missing: ' + name)
        require(group['limit'] and group['evidence_scope'], 'Missing qualification boundary')
        code_paths.update(group['source_refs'])
    require(code_paths == set(metadata['reviewed_code_sha256']), 'Code pin inventory differs')
    for name, expected in metadata['reviewed_code_sha256'].items():
        require(digest((root / name).read_bytes()) == expected,
                'Reviewed code changed; refresh this snapshot: ' + name)
    return counts


def read_export(path, metadata):
    require(digest(path.read_bytes()) == metadata['source_export_sha256'], 'Source export hash mismatch')
    with path.open(encoding='utf-8', newline='') as stream:
        result = list(csv.DictReader(stream))
    require(len(result) == 251 and len({r['id'] for r in result}) == 251, 'Source export IDs differ')
    require(all(r['tab'] == metadata['worksheet'] for r in result), 'Wrong source tab')
    return result


def read_workbook(path, metadata):
    # The exact workbook hash is checked before XML parsing. Nothing is extracted.
    require(digest(path.read_bytes()) == metadata['workbook_sha256'], 'Workbook hash mismatch')
    ns = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with zipfile.ZipFile(path) as archive:
        def xml(name):
            info = archive.getinfo(name)
            require(info.file_size <= 16 * 1024 * 1024, 'Workbook XML exceeds bound')
            raw = archive.read(name)
            require(not re.search(br'<!\s*(?:DOCTYPE|ENTITY)\b', raw, re.I), 'Unexpected XML declaration')
            return ET.fromstring(raw)
        book = xml('xl/workbook.xml')
        rels = {r.attrib['Id']: r.attrib['Target'] for r in xml('xl/_rels/workbook.xml.rels')}
        selected = [s for s in book.findall('m:sheets/m:sheet', ns)
                    if s.attrib['name'] == metadata['worksheet']]
        require(len(selected) == 1, 'Workbook sheet is missing/ambiguous')
        ref = selected[0].attrib['{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id']
        target = rels[ref]
        target = target.lstrip('/') if target.startswith('/') else 'xl/' + target
        strings = []
        if 'xl/sharedStrings.xml' in archive.namelist():
            strings = [''.join(s.itertext()) for s in xml('xl/sharedStrings.xml').findall('m:si', ns)]
        result = []
        for row in xml(target).findall('m:sheetData/m:row', ns):
            if int(row.attrib['r']) < 6:
                continue
            values = {'workbook_row': row.attrib['r']}
            for cell in row.findall('m:c', ns):
                column = re.sub('[0-9]+$', '', cell.attrib['r'])
                if column not in XLSX_COLUMNS:
                    continue
                value = cell.find('m:v', ns)
                kind = cell.attrib.get('t')
                if kind == 'inlineStr':
                    value = ''.join(cell.find('m:is', ns).itertext())
                elif kind == 's':
                    value = strings[int(value.text)]
                else:
                    value = value.text if value is not None else ''
                values[XLSX_COLUMNS[column]] = value
            require(re.fullmatch(r'(?:I|SV)[0-9]{3}', values.get('id', '')), 'Unexpected workbook data row')
            result.append(values)
    require(len(result) == 251, 'Workbook does not contain 251 data rows')
    return result


def compare_sources(rows, original, keys, label):
    require(len(rows) == len(original), label + ' row count differs')
    for actual, expected in zip(rows, original):
        require(all(actual.get(k, '') == expected.get(k, '') for k in keys), label + ' row data differs')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--source-export', type=Path)
    parser.add_argument('--workbook', type=Path)
    args = parser.parse_args(argv)
    root = args.repo_root.resolve()
    rows = read_rows(root / 'docs/server-v05-row-audit.csv')
    metadata = json.loads((root / 'docs/server-v05-row-audit.json').read_text())
    counts = validate(root, rows, metadata)
    original = read_export(args.source_export, metadata) if args.source_export else None
    workbook = read_workbook(args.workbook, metadata) if args.workbook else None
    if original is not None:
        compare_sources(rows, original, [k for k in SEMANTIC_KEYS if k != 'workbook_row'], 'Export')
    if workbook is not None:
        compare_sources(rows, workbook, SEMANTIC_KEYS, 'Workbook')
    if original is not None and workbook is not None:
        compare_sources(workbook, original, XLSX_COLUMNS.values(), 'All 30 workbook/export columns')
    print(json.dumps({'audit_structure_verified': True, 'rows': len(rows), 'counts': counts,
                      'source_export_verified': original is not None,
                      'workbook_verified': workbook is not None,
                      'semantic_assessments_independently_proved': False}, indent=2))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, KeyError, OSError, ET.ParseError, zipfile.BadZipFile) as error:
        print('Audit check failed: ' + str(error))
        raise SystemExit(1)
