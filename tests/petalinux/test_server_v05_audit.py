"""Audit completeness guards; these do not prove register semantics or hardware."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('server_v05_audit', ROOT / 'scripts/check_server_v05_audit.py')
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


class ServerV05AuditTests(unittest.TestCase):
    def setUp(self):
        self.rows = audit.read_rows(ROOT / 'docs/server-v05-row-audit.csv')
        self.metadata = json.loads((ROOT / 'docs/server-v05-row-audit.json').read_text())

    def check(self):
        return audit.validate(ROOT, self.rows, self.metadata)

    def test_complete_snapshot_and_all_referenced_sources(self):
        self.assertEqual(sum(self.check().values()), 251)
        self.assertFalse(self.metadata['full_goal_complete'])

    def test_omitted_and_added_rows_rejected(self):
        for rows in (self.rows[:-1], self.rows + [self.rows[0]]):
            with self.subTest(count=len(rows)), self.assertRaises(ValueError):
                audit.validate(ROOT, rows, self.metadata)

    def test_duplicate_id_rejected(self):
        self.rows[1]['id'] = self.rows[0]['id']
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            self.check()

    def test_workbook_row_order_rejected(self):
        self.rows[0], self.rows[1] = self.rows[1], self.rows[0]
        with self.assertRaisesRegex(ValueError, 'order'):
            self.check()

    def test_original_meaning_and_variable_cannot_drift(self):
        for field in audit.SEMANTIC_KEYS:
            rows = copy.deepcopy(self.rows)
            rows[0][field] += ' changed'
            with self.subTest(field=field), self.assertRaises(ValueError):
                audit.validate(ROOT, rows, self.metadata)

    def test_unknown_state_group_and_blank_mapping_rejected(self):
        for field, value in [('implementation', 'complete'), ('evidence_group', 'unknown'),
                             ('mapping', ''), ('remaining_work', ' ')]:
            rows = copy.deepcopy(self.rows)
            rows[0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                audit.validate(ROOT, rows, self.metadata)

    def test_counts_require_explicit_update(self):
        self.rows[0]['implementation'] = 'implemented'
        with self.assertRaisesRegex(ValueError, 'counts'):
            self.check()

    def test_ledger_cannot_claim_goal_completion(self):
        self.metadata['full_goal_complete'] = True
        with self.assertRaisesRegex(ValueError, 'completion claim'):
            self.check()

    def test_missing_or_escaping_reference_rejected(self):
        for name in ('docs/does-not-exist.md', '../outside.md', '/outside.md'):
            data = copy.deepcopy(self.metadata)
            data['evidence_groups']['authority']['evidence_refs'] = [name]
            with self.subTest(name=name), self.assertRaises(ValueError):
                audit.validate(ROOT, self.rows, data)

    def test_source_change_rejected_without_modifying_repo(self):
        name = next(iter(self.metadata['reviewed_code_sha256']))
        self.metadata['reviewed_code_sha256'][name] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'Reviewed code changed'):
            self.check()

    def test_blank_workbook_cells_equal_blank_export_cells(self):
        audit.compare_sources([{'id': 'I009'}], [{'id': 'I009', 'reviewer': ''}],
                              ('id', 'reviewer'), 'fixture')
        with self.assertRaises(ValueError):
            audit.compare_sources([{'id': 'I009'}], [{'id': 'I009', 'reviewer': 'named'}],
                                  ('id', 'reviewer'), 'fixture')

    def test_unpinned_workbook_and_export_rejected_before_parsing(self):
        with tempfile.TemporaryDirectory(prefix='daphne-audit-test-') as temporary:
            path = Path(temporary) / 'not-the-source'
            path.write_bytes(b'synthetic wrong input, not a workbook or source export')
            with mock.patch.object(audit.zipfile, 'ZipFile') as parser:
                with self.assertRaisesRegex(ValueError, 'Workbook hash'):
                    audit.read_workbook(path, self.metadata)
                parser.assert_not_called()
            with self.assertRaisesRegex(ValueError, 'Source export hash'):
                audit.read_export(path, self.metadata)


if __name__ == '__main__':
    unittest.main()
