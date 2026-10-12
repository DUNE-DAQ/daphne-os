"""Safety regressions for mode transition ordering, without hardware access."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('manual_mode', Path(__file__).with_name('daphne_manual_mode.py'))
mode = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mode)


class TransitionSafety(unittest.TestCase):
    def test_failed_idle_proof_never_stops_firmware_or_unloads(self):
        gw = Mock()
        current = Mock(gateware_mode='raw-dma')
        with patch.object(mode, 'run') as run, patch.object(mode, 'active', return_value=True), \
                patch.object(mode, 'quiesce', side_effect=RuntimeError('quarantine')):
            with self.assertRaisesRegex(RuntimeError, 'quarantine'):
                mode.stop_runtime(gw, current)
        self.assertEqual(run.call_args_list[0].args, ('systemctl', 'stop', 'daphne.service', 'hermes.service', mode.MANUAL))
        self.assertEqual(run.call_count, 1)
        gw.atomic_write.assert_not_called()

    def test_guard_never_unloads_on_proof_failure(self):
        gw = Mock()
        gw.load_active_profile.return_value.gateware_mode = 'raw-dma'
        with patch.object(mode, 'quiesce', side_effect=RuntimeError('owned')), patch.object(mode, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'owned'):
                mode.guard(gw)
        run.assert_not_called()

    def test_default_guard_never_probes_dma_addresses(self):
        gw = Mock()
        gw.load_active_profile.return_value.gateware_mode = 'self-trigger'
        with patch.object(mode, 'quiesce') as quiesce, patch.object(mode, 'run') as run:
            mode.guard(gw)
        quiesce.assert_not_called()
        run.assert_called_once_with('/usr/local/bin/daphne-fw-stop.sh')

    def test_existing_dma_keeps_experiment_configuration(self):
        gw = Mock()
        gw.load_profile.return_value.gateware_mode = 'self-trigger'
        gw.load_profile.return_value.app = 'default-app'
        gw.load_active_profile.return_value.app = mode.APP
        gw.Profile.return_value.app = mode.APP
        with patch.object(mode, 'active', return_value=True), patch.object(mode, 'health'), \
                patch.object(mode, 'check_assets'), patch.object(mode, 'frontend') as frontend, \
                patch.object(mode, 'stop_runtime') as stop, patch.object(mode, 'install_runtime_files') as install:
            mode.switch(gw, 'dma')
        stop.assert_not_called()
        install.assert_not_called()
        gw.atomic_write.assert_not_called()
        frontend.assert_called_once_with('status')


if __name__ == '__main__':
    unittest.main()
