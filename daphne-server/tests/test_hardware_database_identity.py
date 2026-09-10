"""Synthetic DB exports only; never read private board files or contact hardware."""
import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import stat
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import daphneV3_high_level_confs_pb2 as h
import prepare_identity_assignment as prepare
import test_identity_assignment as fixtures


class HardwareDatabaseIdentityTests(unittest.TestCase):
    def setUp(self):
        self.base = fixtures.IdentityAssignmentTests()
        self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        self.root = self.base.root
        self.path = self.root / 'board-config-v1.json'
        self.asset = 'DAPHNE-EXAMPLE-015'
        self.artifact = self.base.build()
        self.record = {
            'contract': 'daphne.board-config', 'version': 1,
            'asset': {'asset_id': self.asset, 'carrier_revision': 'EXAMPLE'},
            'som': {'uuid': '00000000-0000-4000-8000-000000000015',
                    'serial': 'EXAMPLE-015', 'product': 'EXAMPLE-K26',
                    'factory_mac_id_0': '02:aa:bb:00:00:15'},
            'network': {'mac_source': 'legacy_override', 'production_mac': '02:aa:bb:00:00:15',
                        'ipv4_address': '192.0.2.20', 'hostname': 'expected.example',
                        'vlan': None, 'authorized': True},
            'runtime': {'timing_endpoint': '0x0015', 'firmware_release': 'EXAMPLE-RELEASE'},
            'source': {'assignment_revision': 2, 'asset_record_revision': 3},
        }

    def write(self, record=None):
        self.path.write_text(json.dumps(self.record if record is None else record))
        return hashlib.sha256(self.path.read_bytes()).hexdigest()

    def merge(self, *, digest=None, asset=None, artifact=None):
        return prepare.add_hardware_database(
            self.artifact if artifact is None else artifact, self.base.review, self.path,
            self.asset if asset is None else asset, self.write() if digest is None else digest, h)

    def rejected(self, **kwargs):
        before = self.artifact.SerializeToString(deterministic=True)
        with self.assertRaises(prepare.IdentityError) as caught:
            self.merge(**kwargs)
        self.assertEqual(before, self.artifact.SerializeToString(deterministic=True))
        for private in ('192.0.2.20', '02:aa:bb:00:00:15', self.asset, 'EXAMPLE-015'):
            self.assertNotIn(private, str(caught.exception))

    def test_import_has_exact_provenance_without_mutating_base(self):
        before = self.artifact.SerializeToString(deterministic=True)
        value = self.merge()
        self.assertEqual(before, self.artifact.SerializeToString(deterministic=True))
        a = value.assignments
        self.assertEqual(a.management_mac_address.value, '02:aa:bb:00:00:15')
        self.assertEqual(a.timing_endpoint_address.value, 21)
        self.assertTrue(a.timing_endpoint_address.HasField('value'))
        self.assertEqual(value.binding, self.artifact.binding)
        for name in ('crate_id', 'slot_id', 'detector_id', 'management_address', 'hermes_interfaces'):
            self.assertEqual(getattr(a, name), getattr(self.artifact.assignments, name))
        self.assertEqual(a.timing_endpoint_address.source.object_class, 'DaphneBoardConfigV1')
        self.assertEqual(a.timing_endpoint_address.source.object_id, self.asset)
        self.assertEqual(a.timing_endpoint_address.source.attribute, 'runtime.timing_endpoint')
        self.assertEqual(a.management_mac_address.source.attribute, 'network.production_mac')
        self.assertEqual(a.management_mac_address.source.file, 'hardware-database/board-config-v1.json')
        self.assertEqual(a.management_mac_address.source.sha256, self.write())
        self.assertEqual(len(a.sources), 4)
        self.assertEqual([s.file for s in a.sources], sorted(s.file for s in a.sources))
        manifest = [{'file': s.file, 'bytes': s.bytes, 'sha256': s.sha256} for s in a.sources]
        self.assertEqual(a.source_revision_sha256, hashlib.sha256(
            json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()).hexdigest())
        self.assertIn('assignment=2, asset=3', ' '.join(a.limitations))
        self.assertIn('not authenticated', ' '.join(a.limitations))
        self.assertFalse(a.hermes_interfaces[0].physical_connector.HasField('value'))

    def test_explicit_zero_and_maximum_endpoint_have_presence(self):
        for word, expected in [('0x0', 0), ('0x0000', 0), ('0xffff', 65535), ('0xAbCd', 43981)]:
            with self.subTest(word=word):
                self.record['runtime']['timing_endpoint'] = word
                field = self.merge().assignments.timing_endpoint_address
                self.assertTrue(field.HasField('value'))
                self.assertEqual(field.value, expected)

    def test_ambiguous_or_overwide_endpoint_is_rejected(self):
        for word in ('21', '0015', '0X15', 'endpoint-15', '0x10000', '-1', '0x', ' 0x15', '0x15 ', 21, True, None):
            with self.subTest(word=word):
                self.record['runtime']['timing_endpoint'] = word
                self.rejected()

    def test_authorization_requires_boolean_true(self):
        for value in (False, 0, 1, 'true', '1', None):
            self.record['network']['authorized'] = value
            self.rejected()

    def test_asset_requires_explicit_exact_selector(self):
        for asset in ('', '../board', 'wrong-board', 'A' * 129):
            self.rejected(asset=asset)

    def test_pinned_hash_is_required_and_changed_bytes_are_refused(self):
        digest = self.write()
        for wrong in ('', '0' * 64, digest.upper(), digest + '0'):
            self.rejected(digest=wrong)
        self.path.write_bytes(self.path.read_bytes() + b'\n')
        self.rejected(digest=digest)
        changed = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.assertEqual(self.merge(digest=changed).assignments.management_mac_address.source.sha256, changed)

    def test_mac_must_match_preserved_baseline_and_be_unicast(self):
        for mac in ('02:aa:bb:00:00:16', '01:aa:bb:00:00:15', '00:00:00:00:00:00'):
            self.record['network']['production_mac'] = mac
            self.rejected()
        self.record['network']['production_mac'] = '02:AA:BB:00:00:15'
        self.assertEqual(self.merge().assignments.management_mac_address.value, '02:aa:bb:00:00:15')

    def test_ipv4_must_match_both_review_and_baseline(self):
        self.record['network']['ipv4_address'] = '192.0.2.21'
        self.rejected()
        self.record['network']['ipv4_address'] = '192.0.2.20'
        self.base.review['target_check']['resolved_ipv4'] = '192.0.2.21'
        self.rejected()
        self.base.review['target_check']['resolved_ipv4'] = '192.0.2.20'
        self.base.review['target_check']['status'] = 'not_checked'
        self.rejected()

    def test_baseline_with_different_address_is_rejected(self):
        self.artifact.binding.expected_ipv4_cidrs[:] = ['192.0.2.21/24']
        self.rejected()

    def test_eeprom_policy_requires_consistent_factory_mac(self):
        self.record['network']['mac_source'] = 'som_eeprom'
        self.merge()
        self.record['som']['factory_mac_id_0'] = '02:aa:bb:00:00:16'
        self.rejected()

    def test_source_revision_type_and_bounds_are_checked(self):
        for key in ('assignment_revision', 'asset_record_revision'):
            for value in (0, -1, True, '2', 1 << 63):
                record = copy.deepcopy(self.record)
                record['source'][key] = value
                digest = self.write(record)
                self.rejected(digest=digest)

    def test_full_existing_board_config_contract_is_validated(self):
        for mutate in (
            lambda r: r.update(version=True), lambda r: r.update(version=2),
            lambda r: r.update(unexpected='private-value'), lambda r: r.pop('som'),
            lambda r: r['som'].update(uuid='invalid'), lambda r: r['network'].update(vlan=0),
            lambda r: r['source'].update(unexpected=1), lambda r: r['asset'].update(carrier_revision=''),
        ):
            changed = copy.deepcopy(self.record)
            mutate(changed)
            self.rejected(digest=self.write(changed))

    def test_invalid_duplicate_and_oversize_json_is_rejected(self):
        for raw in (b'', b'not-json', b'{"secret":1,"secret":2}', b'\xff', b' ' * 65537):
            self.path.write_bytes(raw)
            self.rejected(digest=hashlib.sha256(raw).hexdigest())

    def test_existing_assignment_is_never_overwritten(self):
        self.artifact.assignments.timing_endpoint_address.value = 0
        self.rejected()
        self.artifact.assignments.timing_endpoint_address.ClearField('value')
        self.artifact.assignments.management_mac_address.source.object_id = 'other'
        self.rejected()

    def test_source_collision_and_limit_fail_without_mutation(self):
        self.artifact.assignments.sources.add(file='hardware-database/board-config-v1.json', sha256='a' * 64, bytes=1)
        self.rejected()
        self.artifact.assignments.sources.pop()
        self.artifact.assignments.limitations.extend(['scope'] * 16)
        self.rejected()

    def arguments(self, output):
        return ['--review-file', str(self.base.review_file), '--source-root', str(self.root),
                '--approved-link-file', str(self.base.link), '--approved-network-file', str(self.base.network),
                '--management-interface', 'eth0', '--proto-dir', str(Path(h.__file__).parent),
                '--output', str(output)]

    def test_cli_output_is_private_redacted_and_not_overwritten(self):
        output = self.root / 'identity.pb'
        args = self.arguments(output) + ['--hardware-db-config', str(self.path),
            '--hardware-db-asset-id', self.asset, '--hardware-db-sha256', self.write()]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(prepare.main(args), 0)
        payload = output.read_bytes()
        self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
        self.assertEqual(payload, self.merge().SerializeToString(deterministic=True))
        report = json.loads(out.getvalue())
        self.assertTrue(report['hardware_db_imported'])
        self.assertEqual(report['source_revision_sha256'], self.merge().assignments.source_revision_sha256)
        for private in (self.asset, '192.0.2.20', '02:aa:bb:00:00:15', 'EXAMPLE-015'):
            self.assertNotIn(private, out.getvalue() + err.getvalue())
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(prepare.main(args), 1)
        self.assertEqual(output.read_bytes(), payload)

    def test_cli_partial_options_fail_before_creating_output(self):
        options = [('--hardware-db-config', str(self.path)), ('--hardware-db-asset-id', self.asset),
                   ('--hardware-db-sha256', self.write())]
        for mask in range(1, 7):
            output = self.root / ('partial-' + str(mask) + '.pb')
            extra = [value for i, pair in enumerate(options) if mask & (1 << i) for value in pair]
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(prepare.main(self.arguments(output) + extra), 1)
            self.assertFalse(output.exists())

    def test_cli_invalid_export_does_not_create_an_artifact(self):
        self.record['network']['authorized'] = False
        output = self.root / 'refused.pb'
        args = self.arguments(output) + ['--hardware-db-config', str(self.path),
            '--hardware-db-asset-id', self.asset, '--hardware-db-sha256', self.write()]
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(prepare.main(args), 1)
        self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
