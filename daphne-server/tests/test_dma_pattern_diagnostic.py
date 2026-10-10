"""Prove diagnostics detect raw bit corruption that ADC display can conceal."""
import importlib.util
from pathlib import Path
import unittest

import numpy as np

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts/validation/diagnose_dma_patterns.py'
spec = importlib.util.spec_from_file_location('dma_patterns', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PatternDiagnosticTests(unittest.TestCase):
    def test_ramp_wrap_and_bit11_flip(self):
        words = np.array([0xfff4, 0xfff8, 0xfffc, 0, 4], dtype=np.uint16)[:, None]
        self.assertEqual(module.analyze(words, 'ramp')[0]['errors'], 0)
        words[2, 0] ^= 1 << 11
        row = module.analyze(words, 'ramp')[0]
        self.assertEqual(row['errors'], 2)
        self.assertGreater(row['raw_bit_mismatches'][11], 0)
        self.assertEqual(row['first_errors'][0]['xor'], 1 << 11)

    def test_toggle_phase_repeated_endpoint_and_illegal_first_word(self):
        for values in ([0, 0xfffc, 0, 0xfffc], [0xfffc, 0, 0xfffc, 0]):
            self.assertEqual(module.analyze(np.array(values)[:, None], 'toggle')[0]['errors'], 0)
        row = module.analyze(np.array([0xfffc, 0xfffc, 0])[:, None], 'toggle')[0]
        self.assertEqual(row['errors'], 1)
        row = module.analyze(np.array([0xf7fc, 0, 0xfffc])[:, None], 'toggle')[0]
        self.assertEqual(row['invalid_toggle_words'], 1)

    def test_constant_identifies_false_negative_and_padding(self):
        words = np.array([0xff80, 0xf780, 0xff81], dtype=np.uint16)[:, None]
        row = module.analyze(words, 'constant', 0x3fe0)[0]
        self.assertEqual(row['errors'], 2)
        self.assertEqual(row['nonzero_padding'], 1)
        self.assertEqual(row['raw_bit_mismatches'][11], 1)
        self.assertEqual(row['raw_bit_mismatches'][0], 1)

    def test_normal_adc_records_outliers_without_claiming_digital_error(self):
        words = np.array([0xff80, 0xff84, 0xf780, 0xff80], dtype=np.uint16)[:, None]
        row = module.analyze(words, 'normal-adc')[0]
        self.assertEqual(row['outliers_gt_256'], 1)
        self.assertEqual(row['outlier_windows'][0]['tick'], 2)
        self.assertEqual(row['errors'], 0)


if __name__ == '__main__':
    unittest.main()
