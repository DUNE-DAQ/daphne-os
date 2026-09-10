"""Run the real overlay recipe guard/URI expressions with synthetic data.

No BitBake parser, FPGA artifacts or physical timing are qualified by this test.
"""
from pathlib import Path
import re
import types
import unittest

ROOT = Path(__file__).resolve().parents[2]
RECIPE = ROOT / "petalinux/meta-daphne/recipes-firmware/daphne-overlay/daphne-overlay.bb"


class Refused(RuntimeError):
    pass


def fatal(message):
    raise Refused(message)


class OverlayAbiContractTests(unittest.TestCase):
    def setUp(self):
        self.recipe = RECIPE.read_text()
        body = re.search(r"^python validate_dual_overlay \(\) \{\n(.*?)^\}", self.recipe, re.M | re.S)
        self.assertIsNotNone(body)
        namespace = {"bb": types.SimpleNamespace(fatal=fatal)}
        exec("def validate(d):\n" + body.group(1), namespace)
        self.validate = namespace["validate"]
        self.values = {"DAPHNE_DUAL_OVERLAY_STAGED": "1"}
        for prefix, app in (("DAPHNE_SELF_TRIGGER", "daphne_selftrigger_ol_abcdef1"),
                             ("DAPHNE_FULL_STREAM", "daphne_fullstream_ol_abcdef2")):
            self.values.update({prefix + "_APP": app, prefix + "_FIRMWARE_NAME": app + ".bin",
                                prefix + "_ABI_MINOR": "0", prefix + "_IDENTITY_SEALED": "0"})
        self.datastore = types.SimpleNamespace(getVar=self.values.get)

    def test_all_nine_abi_pairs_require_their_own_evidence_uris(self):
        expressions = re.findall(r"\$\{@(.*?)\}", self.recipe)
        self.assertEqual(len(expressions), 4)
        for left in ("0", "1", "2"):
            for right in ("0", "1", "2"):
                for prefix, minor in (("DAPHNE_SELF_TRIGGER", left), ("DAPHNE_FULL_STREAM", right)):
                    self.values[prefix + "_ABI_MINOR"] = minor
                    self.values[prefix + "_IDENTITY_SEALED"] = "1"
                self.validate(self.datastore)
                uris = " ".join(eval(expression, {"d": self.datastore}) for expression in expressions)
                for mode, minor in (("self-trigger", left), ("full-stream", right)):
                    self.assertIn(f"file://staged/{mode}/GATEWARE-IDENTITY.json", uris)
                    self.assertEqual(f"file://staged/{mode}/post_route_timestamp_snapshot.rpt" in uris, minor != "0")

    def test_missing_legacy_declarations_allowed_but_empty_or_unknown_refused(self):
        for prefix in ("DAPHNE_SELF_TRIGGER", "DAPHNE_FULL_STREAM"):
            self.values.pop(prefix + "_ABI_MINOR")
            self.values.pop(prefix + "_IDENTITY_SEALED")
        self.validate(self.datastore)
        for prefix in ("DAPHNE_SELF_TRIGGER", "DAPHNE_FULL_STREAM"):
            for field, bad in (("_ABI_MINOR", ""), ("_ABI_MINOR", "3"), ("_ABI_MINOR", "02"),
                               ("_IDENTITY_SEALED", ""), ("_IDENTITY_SEALED", "2")):
                self.values[prefix + field] = bad
                with self.assertRaisesRegex(Refused, "Invalid/unsealed"):
                    self.validate(self.datastore)
                del self.values[prefix + field]

    def test_both_extensions_require_sealed_identity_in_either_mode(self):
        for prefix in ("DAPHNE_SELF_TRIGGER", "DAPHNE_FULL_STREAM"):
            for minor in ("1", "2"):
                self.values[prefix + "_ABI_MINOR"] = minor
                with self.assertRaisesRegex(Refused, "Invalid/unsealed"):
                    self.validate(self.datastore)
            self.values[prefix + "_ABI_MINOR"] = "0"

    def test_dynamic_guard_inputs_have_task_dependencies(self):
        dependencies = re.search(r'validate_dual_overlay\[vardeps\] \+= "(.*?)"', self.recipe, re.S).group(1).split()
        for prefix in ("DAPHNE_SELF_TRIGGER", "DAPHNE_FULL_STREAM"):
            for suffix in ("_APP", "_FIRMWARE_NAME", "_ABI_MINOR", "_IDENTITY_SEALED"):
                self.assertIn(prefix + suffix, dependencies)


if __name__ == "__main__":
    unittest.main()
