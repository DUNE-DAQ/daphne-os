"""Hardware-free guards for the zero-only aggregate qualification client."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from verify_aggregate_zero_bias import check_bias_acknowledgements, make_zero_bias_request


class ZeroBiasTests(unittest.TestCase):
    def test_profiles_are_complete_zero_only_and_keep_ids(self):
        for order in ([0, 1, 2, 3, 4], [4, 1, 3, 0, 2]):
            profile = make_zero_bias_request(order)
            self.assertEqual(profile["biasctrl"], 0)
            self.assertEqual([afe["id"] for afe in profile["afes"]], order)
            self.assertTrue(all(afe["v_bias"] == 0 for afe in profile["afes"]))
            self.assertEqual(len(profile["channels"]), 40)
            self.assertTrue(all(ch["offset"] == 2200 and ch["gain"] == 1 and ch["trim"] == 0
                                for ch in profile["channels"]))

    def test_bad_afe_lists_are_rejected(self):
        for order in ([], [0, 1, 2, 3], [0, 1, 2, 3, 3], [0, 1, 2, 3, 5]):
            with self.assertRaises(ValueError):
                make_zero_bias_request(order)

    def test_acknowledgements_cannot_hide_skipped_zero(self):
        order = [4, 1, 3, 0, 2]
        lines = [f"AFE BIAS command sent for AFE {afe}. BIAS code: 0.\n" for afe in order]
        self.assertEqual(check_bias_acknowledgements("".join(lines), order), [(afe, 0) for afe in order])
        for message in ("", "".join(lines[:-1]), "".join(lines + lines[:1]),
                        "".join(reversed(lines)), "".join(lines).replace("BIAS code: 0", "BIAS code: 1", 1)):
            with self.assertRaises(ValueError):
                check_bias_acknowledgements(message, order)


if __name__ == "__main__":
    unittest.main()
