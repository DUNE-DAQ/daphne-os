"""No hardware: verify opt-in profile and unload guard failures are propagated."""
import importlib.machinery
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
FILES = ROOT/'petalinux/meta-daphne/recipes-core/daphne-services/files'
loader = importlib.machinery.SourceFileLoader('dma_gateware',str(FILES/'daphne-gateware'))
spec = importlib.util.spec_from_loader(loader.name,loader)
gateware = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = gateware
loader.exec_module(gateware)

class RawRuntimeTests(unittest.TestCase):
    def test_profile_is_optional_and_build_id_from_metadata(self):
        profile = gateware.profile_from_path(FILES/'daphne-gateware-raw-dma.conf','raw-dma')
        self.assertEqual(profile.variant,3)
        self.assertEqual(profile.build_id_spec,'metadata')
        self.assertEqual((FILES/'daphne-gateware-default-profile').read_text().strip(),'self-trigger')

    def test_quiesce_propagates_idle_proof_failure_without_any_mmio(self):
        profile=gateware.profile_from_path(FILES/'daphne-gateware-raw-dma.conf','raw-dma')
        with patch.object(gateware,'require_root'), patch.object(gateware,'load_active_profile',return_value=profile), \
             patch.object(gateware,'run_command',side_effect=gateware.GatewareError('halt unproven')) as run, \
             patch.object(gateware,'read_word') as read, patch.object(gateware,'write_word') as write:
            with self.assertRaisesRegex(gateware.GatewareError,'halt unproven'): gateware.quiesce_active()
            run.assert_called_once_with(['/usr/bin/daphne-afe-dma-quiesce'])
            read.assert_not_called();write.assert_not_called()

    def test_server_and_hermes_raw_profile_selection(self):
        service=(FILES/'daphne.service').read_text()
        self.assertIn('set -- --dma',service)
        self.assertIn('ExecStopPost=/usr/sbin/daphne-gateware quiesce',service)
        self.assertIn('ExecCondition=',(FILES/'hermes.service').read_text())
        self.assertIn('daphne-afe-dma-quiesce',(FILES/'daphne-fw-stop.sh').read_text())

    def test_identity_rejected_before_reading_optional_capability(self):
        profile = gateware.profile_from_path(FILES/'daphne-gateware-raw-dma.conf','raw-dma')
        state = MagicMock(); state.read_text.return_value = 'operating'
        overlays = MagicMock(); overlays.is_dir.return_value = True
        overlay = MagicMock(); (overlay / 'status').is_file.return_value = True
        (overlay / 'status').read_text.return_value = 'applied'
        overlays.iterdir.return_value = [overlay]
        identity = dict(magic=profile.magic,abi=profile.abi_word,variant=1,build_id=123)
        with patch.object(gateware,'Path',side_effect=[state,overlays]), \
             patch.object(gateware,'expected_build_id',return_value=123), \
             patch.object(gateware,'probe_identity',return_value=identity), \
             patch.object(gateware,'read_word') as read:
            with self.assertRaisesRegex(gateware.GatewareError,'identity mismatch'):
                gateware.verify_profile(profile)
            read.assert_not_called()

if __name__=='__main__':unittest.main()
