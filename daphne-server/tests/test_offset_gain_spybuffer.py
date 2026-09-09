"""Hardware-free tests of analog-comparison statistics and false-pass guards."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "offset_test", Path(__file__).resolve().parents[1] / "scripts" / "verify_offset_gain_spybuffer.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class OffsetComparisonTests(unittest.TestCase):
    def test_repeat_precedes_potentially_clipping_control(self):
        self.assertEqual(module.setting_sequence(), (
            ("a_2200_x1", 2200, 1), ("b_1100_x2", 1100, 2),
            ("repeat_2200_x1", 2200, 1), ("control_1100_x1", 1100, 1)))

    def test_full_profile_is_zero_bias_and_complete(self):
        for code, gain in ((2200, 1), (1100, 2), (1100, 1)):
            profile = module.zero_bias_profile(code, gain)
            self.assertEqual(profile["biasctrl"], 0)
            self.assertEqual([c["id"] for c in profile["channels"]], list(range(40)))
            self.assertTrue(all(c["offset"] == code and c["gain"] == gain and c["trim"] == 0
                                for c in profile["channels"]))
            self.assertEqual([a["id"] for a in profile["afes"]], list(range(5)))
            self.assertTrue(all(a["v_bias"] == 0 and a["attenuators"] == 1700
                                and a["adc"]["resolution"] is False and a["adc"]["output_format"] is True
                                for a in profile["afes"]))

    def test_full_profile_rejects_invalid_offset_gain(self):
        for code, gain in ((2200, 2), (2701, 1), (-1, 1), (1100, 0), (1100, 3)):
            with self.assertRaises(ValueError):
                module.zero_bias_profile(code, gain)

    def noisy(self, baseline):
        return module.summarize([[baseline - 1, baseline, baseline + 1],
                                 [baseline + 1, baseline - 1, baseline]])

    def test_equivalent_outputs_and_responsive_control(self):
        result = module.compare(self.noisy(5000), self.noisy(5008), self.noisy(9000), self.noisy(5001), 164)
        self.assertTrue(result["comparison_pass"])
        self.assertEqual(result["equivalent_delta_adc"], 8)

    def test_stale_identical_captures_do_not_pass(self):
        stale = module.summarize([[4999, 5000, 5001]] * 2)
        self.assertFalse(module.compare(stale, stale, self.noisy(9000), stale, 164)["comparison_pass"])

    def test_rails_do_not_pass(self):
        clipped = module.summarize([[16383] * 8, [16382] + [16383] * 7])
        self.assertFalse(module.compare(clipped, clipped, self.noisy(9000), clipped, 164)["comparison_pass"])

    def test_no_response_and_drift_do_not_pass(self):
        a = self.noisy(5000)
        self.assertFalse(module.compare(a, a, a, a, 164)["comparison_pass"])
        self.assertFalse(module.compare(a, a, self.noisy(9000), self.noisy(5200), 164)["comparison_pass"])

    def test_invalid_samples_rejected(self):
        for frames in ([], [[]], [[1], []], [[-1, 1]], [[16384, 1]]):
            with self.assertRaises(ValueError):
                module.summarize(frames)

    def test_twos_complement_zero_crossing_is_not_clipping(self):
        zero = module.summarize([[16383, 0, 1], [1, 16383, 0]], "twos-complement")
        control = module.summarize([[16353, 16354, 16355], [16355, 16353, 16354]], "twos-complement")
        self.assertEqual(zero["baseline"], 0)
        self.assertEqual(zero["rail_fraction"], 0)
        result = module.compare(zero, zero, control, zero, 164)
        self.assertEqual(result["control_delta_adc"], -30)
        self.assertTrue(result["comparison_pass"])

    def test_twos_complement_rails_fail(self):
        clipped = module.summarize([[8191, 8191, 8191], [8190, 8191, 8191]], "twos-complement")
        result = module.compare(clipped, clipped, self.noisy(1000), clipped, 164)
        self.assertFalse(result["comparison_pass"])


if __name__ == "__main__":
    unittest.main()
