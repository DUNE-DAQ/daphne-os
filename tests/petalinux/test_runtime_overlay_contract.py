"""Execute the actual recipe guard with a small BitBake datastore double.

These tests cover the guard's decisions, not BitBake parsing, task signatures,
ELF execution, image construction or physical firmware qualification.
"""
from pathlib import Path
import re
import types
import unittest


ROOT = Path(__file__).resolve().parents[2]
RECIPE = ROOT / "petalinux/meta-daphne/recipes-apps/daphne-server/daphne-server.bb"
CONTRACT = RECIPE.with_name("daphne-server-contract.inc")


class Refused(RuntimeError):
    pass


def fatal(message):
    raise Refused(message)


class RuntimeOverlayContractTests(unittest.TestCase):
    def setUp(self):
        self.recipe = RECIPE.read_text()
        body = re.search(
            r"^python validate_daphne_server_runtime \(\) \{\n(.*?)^\}",
            self.recipe, re.M | re.S)
        self.assertIsNotNone(body)
        namespace = {"bb": types.SimpleNamespace(fatal=fatal)}
        exec("def validate(d):\n" + body.group(1), namespace)
        self.validate = namespace["validate"]
        self.values = dict(re.findall(r'^(DAPHNE_\w+) = "([^"\n]*)"$', CONTRACT.read_text(), re.M))
        self.values.update({
            "DAPHNE_SERVER_RUNTIME_QUALIFIED": "1",
            "DAPHNE_SERVER_RUNTIME_GIT_COMMIT": self.values["DAPHNE_SERVER_REQUIRED_GIT_COMMIT"],
            "DAPHNE_SERVER_RUNTIME_EXECUTION_KIND": "qemu-aarch64",
            "DAPHNE_SERVER_RUNTIME_GATEWARE_ABI_MAJOR": "2",
            "DAPHNE_SERVER_RUNTIME_GATEWARE_ABI_MINORS": self.values["DAPHNE_SERVER_REQUIRED_GATEWARE_ABI_MINORS"],
            "DAPHNE_SERVER_RUNTIME_SHA256": "a" * 64,
            "DAPHNE_DUAL_OVERLAY_STAGED": "1",
            "DAPHNE_SELF_TRIGGER_ABI_MINOR": "0",
            "DAPHNE_FULL_STREAM_ABI_MINOR": "0",
        })

    def check(self):
        self.validate(types.SimpleNamespace(getVar=self.values.get))

    def use_legacy_contract(self):
        self.values.update({
            "DAPHNE_SERVER_REQUIRED_GIT_COMMIT": "77b39b7eb75204e1f2025f251a3a76ecf69d1d74",
            "DAPHNE_SERVER_RUNTIME_GIT_COMMIT": "77b39b7eb75204e1f2025f251a3a76ecf69d1d74",
            "DAPHNE_SERVER_REQUIRED_GATEWARE_ABI_MINORS": "0",
            "DAPHNE_SERVER_RUNTIME_GATEWARE_ABI_MINORS": "0",
        })

    def use_previous_abi21_contract(self):
        # Preserve the previous release's refusal independently of the new pin.
        self.values.update({
            "DAPHNE_SERVER_REQUIRED_GIT_COMMIT": "3556811fbe5bf01b7c66c862a8a6e1821a4f6246",
            "DAPHNE_SERVER_RUNTIME_GIT_COMMIT": "3556811fbe5bf01b7c66c862a8a6e1821a4f6246",
            "DAPHNE_SERVER_REQUIRED_GATEWARE_ABI_MINORS": "0 1",
            "DAPHNE_SERVER_RUNTIME_GATEWARE_ABI_MINORS": "0 1",
        })

    def test_recipe_requires_overlay_version_and_registers_guard(self):
        self.assertIn("require recipes-firmware/daphne-overlay/daphne-overlay-version.inc\n", self.recipe)
        self.assertIn('do_fetch[prefuncs] += "validate_daphne_server_runtime"', self.recipe)
        dependencies = re.search(r'validate_daphne_server_runtime\[vardeps\] \+= "(.*?)"',
                                 self.recipe, re.S).group(1)
        for prefix in ("DAPHNE_SELF_TRIGGER", "DAPHNE_FULL_STREAM"):
            self.assertIn(prefix + "_ABI_MINOR", dependencies.split())
            self.assertIn(prefix + "_IDENTITY_SEALED", dependencies.split())

    def test_prebuilt_timesync_user_requires_systemd_library_provider(self):
        # Recipe-source regression only; an image build must still resolve and
        # execute the target library. Do not bundle/replace the system copy.
        depends = re.search(r'^DEPENDS \+= "([^"]+)"', self.recipe, re.M).group(1).split()
        runtime = re.search(r'^RDEPENDS:\$\{PN\} \+= "([^"]+)"', self.recipe, re.M).group(1).split()
        self.assertIn("systemd", depends)
        self.assertIn("libsystemd", runtime)
        self.assertNotIn("libsystemd.so", self.recipe)

    def test_original_runtime_with_two_legacy_overlays(self):
        self.use_legacy_contract()
        self.check()
        del self.values["DAPHNE_SELF_TRIGGER_ABI_MINOR"]
        del self.values["DAPHNE_FULL_STREAM_ABI_MINOR"]
        self.check()

    def test_either_new_overlay_requires_new_server_even_if_other_is_legacy(self):
        self.use_legacy_contract()
        for prefix in ("DAPHNE_SELF_TRIGGER", "DAPHNE_FULL_STREAM"):
            with self.subTest(prefix=prefix):
                self.values[prefix + "_ABI_MINOR"] = "1"
                self.values[prefix + "_IDENTITY_SEALED"] = "1"
                with self.assertRaisesRegex(Refused, "does not support"):
                    self.check()
                self.values[prefix + "_ABI_MINOR"] = "0"

    def test_reviewed_source_contract_accepts_both_minor_combinations(self):
        # Real reviewed source pin; this remains a guard test, not hardware qualification.
        for left, right in (("0", "0"), ("0", "1"), ("1", "0"), ("1", "1")):
            with self.subTest(self_trigger=left, full_stream=right):
                for prefix, minor in (("DAPHNE_SELF_TRIGGER", left), ("DAPHNE_FULL_STREAM", right)):
                    self.values[prefix + "_ABI_MINOR"] = minor
                    self.values[prefix + "_IDENTITY_SEALED"] = "1"
                self.check()

    def test_minor_capabilities_require_explicit_restage(self):
        for stale in (None, "unstaged", "unqualified", "0", "1"):
            with self.subTest(stale=stale):
                self.values["DAPHNE_SERVER_RUNTIME_GATEWARE_ABI_MINORS"] = stale
                with self.assertRaisesRegex(Refused, "minor capabilities"):
                    self.check()

    def test_unknown_or_malformed_overlay_minor_is_never_legacy(self):
        for prefix in ("DAPHNE_SELF_TRIGGER", "DAPHNE_FULL_STREAM"):
            for minor in ("", "3", "01", "0 1", "65535", "-1"):
                with self.subTest(prefix=prefix, minor=minor):
                    self.values[prefix + "_ABI_MINOR"] = minor
                    with self.assertRaisesRegex(Refused, "does not support"):
                        self.check()
                    self.values[prefix + "_ABI_MINOR"] = "0"

    def test_new_overlay_must_be_sealed(self):
        self.values["DAPHNE_SERVER_REQUIRED_GATEWARE_ABI_MINORS"] = "0 1"
        self.values["DAPHNE_SERVER_RUNTIME_GATEWARE_ABI_MINORS"] = "0 1"
        for prefix in ("DAPHNE_SELF_TRIGGER", "DAPHNE_FULL_STREAM"):
            self.values[prefix + "_ABI_MINOR"] = "1"
            with self.assertRaisesRegex(Refused, "sealed identity"):
                self.check()
            self.values[prefix + "_ABI_MINOR"] = "0"

    def test_unknown_or_noncanonical_server_capability_sets_rejected(self):
        for value in (None, "", "0 1 2 3", "01", "1 0", "0 0", "0  1", "0 2"):
            with self.subTest(value=value):
                self.values["DAPHNE_SERVER_REQUIRED_GATEWARE_ABI_MINORS"] = value
                self.values["DAPHNE_SERVER_RUNTIME_GATEWARE_ABI_MINORS"] = value
                with self.assertRaisesRegex(Refused, "minor capabilities"):
                    self.check()

    def test_previous_abi21_release_pin_rejects_either_abi22_overlay(self):
        self.use_previous_abi21_contract()
        for prefix in ("DAPHNE_SELF_TRIGGER", "DAPHNE_FULL_STREAM"):
            self.values[prefix + "_ABI_MINOR"] = "2"
            self.values[prefix + "_IDENTITY_SEALED"] = "1"
            with self.assertRaisesRegex(Refused, "does not support"):
                self.check()
            self.values[prefix + "_ABI_MINOR"] = "0"

    def test_current_release_contract_accepts_all_nine_overlay_combinations(self):
        self.assertEqual(self.values["DAPHNE_SERVER_REQUIRED_GIT_COMMIT"],
                         "fb82e0a6f6607e9486a98ed6fc1a26b07b0b0665")
        self.assertEqual(self.values["DAPHNE_SERVER_REQUIRED_GATEWARE_ABI_MINORS"], "0 1 2")
        for left in ("0", "1", "2"):
            for right in ("0", "1", "2"):
                for prefix, minor in (("DAPHNE_SELF_TRIGGER", left), ("DAPHNE_FULL_STREAM", right)):
                    self.values[prefix + "_ABI_MINOR"] = minor
                    self.values[prefix + "_IDENTITY_SEALED"] = "1"
                self.check()

        for stale in ("0", "1", "0 1", "unstaged"):
            self.values["DAPHNE_SERVER_RUNTIME_GATEWARE_ABI_MINORS"] = stale
            with self.assertRaisesRegex(Refused, "minor capabilities"):
                self.check()

    def test_previous_abi22_runtime_does_not_satisfy_management_link_source_pin(self):
        self.values["DAPHNE_SERVER_RUNTIME_GIT_COMMIT"] = "3f636f4acf3f795e96d1e20e89936c6a861ac58a"
        with self.assertRaisesRegex(Refused, "release contract"):
            self.check()

    def test_previous_management_link_runtime_requires_older_build_identity_pin(self):
        self.values["DAPHNE_SERVER_RUNTIME_GIT_COMMIT"] = "bffea24fc16c93b263ffe5c83872832a7b7f7a82"
        with self.assertRaisesRegex(Refused, "release contract"):
            self.check()

    def test_previous_timesync_runtime_requires_older_os_metadata_pin(self):
        self.values["DAPHNE_SERVER_RUNTIME_GIT_COMMIT"] = "702155b8068823118fd7dbecd2f4a982ec031785"
        with self.assertRaisesRegex(Refused, "release contract"):
            self.check()

    def test_abi22_also_requires_sealed_identity_for_either_mode(self):
        for prefix in ("DAPHNE_SELF_TRIGGER", "DAPHNE_FULL_STREAM"):
            self.values[prefix + "_ABI_MINOR"] = "2"
            for sealed in (None, "", "0", "2"):
                self.values[prefix + "_IDENTITY_SEALED"] = sealed
                with self.assertRaisesRegex(Refused, "sealed identity"):
                    self.check()
            self.values[prefix + "_ABI_MINOR"] = "0"

    def test_unqualified_or_unstaged_inputs_rejected(self):
        for variable, text in (("DAPHNE_SERVER_RUNTIME_QUALIFIED", "bundle must be staged"),
                               ("DAPHNE_DUAL_OVERLAY_STAGED", "Both gateware overlays")):
            self.values[variable] = "0"
            with self.assertRaisesRegex(Refused, text):
                self.check()
            self.values[variable] = "1"

    def test_exact_commit_abi_and_digest_checks_remain(self):
        for variable, value, text in (
            ("DAPHNE_SERVER_RUNTIME_GIT_COMMIT", "c" * 40, "release contract"),
            ("DAPHNE_SERVER_REQUIRED_GIT_COMMIT", "", "Malformed"),
            ("DAPHNE_SERVER_RUNTIME_GATEWARE_ABI_MAJOR", "3", "ABI contract"),
            ("DAPHNE_SERVER_RUNTIME_SHA256", "A" * 64, "SHA-256"),
        ):
            original = self.values[variable]
            self.values[variable] = value
            with self.assertRaisesRegex(Refused, text):
                self.check()
            self.values[variable] = original

    def test_execution_kind_is_explicit_and_known(self):
        for kind in ("qemu-aarch64", "native-aarch64"):
            self.values["DAPHNE_SERVER_RUNTIME_EXECUTION_KIND"] = kind
            self.check()
        for kind in (None, "", "unstaged", "unqualified", "native", "x86_64", "qemu-aarch64 native-aarch64"):
            with self.subTest(kind=kind):
                self.values["DAPHNE_SERVER_RUNTIME_EXECUTION_KIND"] = kind
                with self.assertRaisesRegex(Refused, "execution method"):
                    self.check()


if __name__ == "__main__":
    unittest.main()
