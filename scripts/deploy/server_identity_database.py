"""Monitoring-only import of a pinned hardware-database board-config-v1 export.

No database calls, network operations, configuration rendering or hardware writes.
Reuse the deployment contract validator, but never its rendering/apply path.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from render_board_config import validate_record


def merge_assignment(artifact, review, path, expected_asset, expected_sha256, high, identity):
    """Return a new artifact; refuse mismatched/unapproved evidence without mutation."""
    def need(condition, message):
        if not condition:
            raise identity.IdentityError(message)

    need(isinstance(expected_asset, str) and
         re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', expected_asset),
         'An explicit hardware-database asset selector is required')
    need(isinstance(expected_sha256, str) and
         re.fullmatch(r'[0-9a-f]{64}', expected_sha256),
         'An explicit lowercase hardware-database export SHA-256 is required')
    source_name = 'hardware-database/' + Path(path).name
    need(re.fullmatch(r'hardware-database/[A-Za-z0-9_.-]{1,128}', source_name) and
         '..' not in source_name, 'Unsupported hardware-database source filename')
    raw = identity.bounded_bytes(path)
    digest = hashlib.sha256(raw).hexdigest()
    need(digest == expected_sha256, 'Hardware-database export hash differs from the selected revision')
    try:
        record = json.loads(raw.decode('utf-8'), object_pairs_hook=identity.no_duplicate_keys)
        row = validate_record(record)
    except (SystemExit, ValueError, TypeError, KeyError, UnicodeError):
        # The shared validator may describe an unknown key; never echo private input.
        raise identity.IdentityError('Invalid hardware-database board-config-v1 export; details suppressed') from None
    need(row['asset_id'] == expected_asset, 'Hardware-database asset does not match the explicit selector')
    need(row['network_admission_approved'] == '1', 'Hardware-database network assignment is not authorized')
    mac = identity.mac_address(row['production_mac'])
    address = identity.ipv4(row['ipv4_address'])
    need(mac == artifact.binding.expected_mac_address,
         'Hardware-database MAC differs from the preserved management baseline')
    need(review['target_check']['status'] == 'matched' and
         address == review['target_check']['resolved_ipv4'] and
         address in {value.split('/')[0] for value in artifact.binding.expected_ipv4_cidrs},
         'Hardware-database IPv4 differs from the verified target or preserved baseline')
    if row['mac_source'] == 'som_eeprom':
        need(identity.mac_address(row['factory_mac_id_0']) == mac,
             'Hardware-database EEPROM MAC policy disagrees with its assignment')
    timing = row['timing_endpoint']
    # The existing deployment renderer exports ENDPOINT_ADDR_HEX. Require an
    # explicit hex literal: a free-form endpoint name or bare decimal is ambiguous.
    need(re.fullmatch(r'0x[0-9a-fA-F]{1,4}', timing),
         'Hardware-database timing endpoint must be an explicit 16-bit 0x hex literal')
    timing_value = int(timing, 16)
    revisions = record['source']
    need(all(type(value) is int and 0 < value <= 0x7fffffffffffffff
             for value in revisions.values()), 'Hardware-database source revisions exceed supported bounds')
    assigned = artifact.assignments
    for name in ('management_mac_address', 'timing_endpoint_address'):
        value = getattr(assigned, name)
        need(not value.HasField('value') and not value.HasField('source'),
             'Hardware-database import cannot overwrite an existing assignment')
    need(len(assigned.sources) < 32 and source_name not in {s.file for s in assigned.sources},
         'Hardware-database source conflicts with the existing manifest')
    limits = [value for value in assigned.limitations if value not in (
        'Management MAC is not supplied by this explicit-field mapping',
        'Timing-endpoint assignment needs a separately established source; tp_conf is not that address')]
    limits.extend([
        'Hardware-database export is explicitly selected and hash-bound, not authenticated or queried live; no settings are applied',
        'Hardware-database revisions: assignment=' + str(revisions['assignment_revision']) +
        ', asset=' + str(revisions['asset_record_revision']) + '; SOM identity is not independently observed'])
    need(0 < len(limits) <= 16, 'Hardware-database scope exceeds artifact limits')

    result = high.BoardIdentityAssignmentFile()
    result.CopyFrom(artifact)
    assigned = result.assignments
    sources = [{'file': source.file, 'sha256': source.sha256, 'bytes': source.bytes}
               for source in assigned.sources]
    sources.append({'file': source_name, 'sha256': digest, 'bytes': len(raw)})
    sources.sort(key=lambda item: item['file'])
    assigned.ClearField('sources')
    for source in sources:
        assigned.sources.add(**source)
    assigned.source_revision_sha256 = hashlib.sha256(
        json.dumps(sources, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    for name, value, attribute in (
            ('management_mac_address', mac, 'network.production_mac'),
            ('timing_endpoint_address', timing_value, 'runtime.timing_endpoint')):
        target = getattr(assigned, name)
        target.Clear()
        target.value = value
        target.source.CopyFrom(high.IdentityValueSource(
            file=source_name, sha256=digest, object_class='DaphneBoardConfigV1',
            object_id=expected_asset, attribute=attribute))
    assigned.ClearField('limitations')
    assigned.limitations.extend(limits)
    return result
