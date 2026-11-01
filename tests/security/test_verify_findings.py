import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/security/verify_findings.py"
SPEC = importlib.util.spec_from_file_location("verify_findings", SCRIPT)
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)
FIXTURE = "daphne-server/third_party/zeromq-4.3.4/tests/test_wss_transport.cpp"
STATUS_TEST = "tests/petalinux/test_daphne_service_status.py"
STATUS_TEST_COMMIT = "ba2c8bb9b7faeffdff4ebf58c089373103d0d506"


class SecretFindingReviewTests(unittest.TestCase):
    def fixture_finding(self) -> dict:
        return {"File": FIXTURE, "RuleID": "private-key", "StartLine": 38, "Commit": ""}

    def test_unchanged_public_fixture_is_accepted(self) -> None:
        # Compare repository bytes, independent of Windows checkout line endings.
        finding = self.fixture_finding()
        finding["Commit"] = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        self.assertTrue(VERIFY.is_public_fixture(finding, ROOT))

    def status_test_finding(self) -> dict:
        return {"File": STATUS_TEST, "RuleID": "daphne-literal-password",
                "StartLine": 55, "Commit": STATUS_TEST_COMMIT}

    def test_reviewed_synthetic_password_in_history_is_accepted(self) -> None:
        self.assertTrue(VERIFY.is_public_fixture(self.status_test_finding(), ROOT))

    def test_status_fixture_has_no_rule_or_path_wide_exception(self) -> None:
        for changes in ({"RuleID": "private-key"}, {"StartLine": 54},
                        {"File": "tests/petalinux/another_test.py"}):
            with self.subTest(changes=changes):
                finding = self.status_test_finding()
                finding.update(changes)
                self.assertFalse(VERIFY.is_public_fixture(finding, ROOT))

    def test_status_fixture_current_bytes_and_changed_input(self) -> None:
        data = subprocess.run(
            ["git", "-C", str(ROOT), "show", f"{STATUS_TEST_COMMIT}:{STATUS_TEST}"],
            capture_output=True, check=True,
        ).stdout
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / STATUS_TEST
            path.parent.mkdir(parents=True)
            path.write_bytes(data)
            finding = self.status_test_finding()
            finding["Commit"] = ""
            self.assertTrue(VERIFY.is_public_fixture(finding, root))
            changed = data.replace(b'"secret"', b'"changed"')
            self.assertNotEqual(changed, data)
            path.write_bytes(changed)
            self.assertFalse(VERIFY.is_public_fixture(finding, root))

    def test_changed_fixture_is_not_path_allowlisted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / FIXTURE
            path.parent.mkdir(parents=True)
            path.write_text("changed public fixture\n")
            self.assertFalse(VERIFY.is_public_fixture(self.fixture_finding(), root))

    def test_unexpected_rule_or_location_is_rejected(self) -> None:
        finding = self.fixture_finding()
        finding["RuleID"] = "unexpected-rule"
        self.assertFalse(VERIFY.is_public_fixture(finding, ROOT))
        finding = self.fixture_finding()
        finding["StartLine"] = 1
        self.assertFalse(VERIFY.is_public_fixture(finding, ROOT))

    def test_outside_path_or_invalid_commit_is_rejected(self) -> None:
        finding = self.fixture_finding()
        finding["File"] = "../" + FIXTURE
        self.assertFalse(VERIFY.is_public_fixture(finding, ROOT))
        finding = self.fixture_finding()
        finding["Commit"] = "HEAD:path"
        self.assertFalse(VERIFY.is_public_fixture(finding, ROOT))

    def test_report_values_are_not_printed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            report = Path(temporary) / "report.json"
            report.write_text(json.dumps([{
                "File": "example.txt", "RuleID": "unexpected-rule", "StartLine": 1,
                "Secret": "PAYLOAD_A", "Match": "PAYLOAD_B",
            }]))
            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(report)], text=True, capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("PAYLOAD_A", result.stdout + result.stderr)
            self.assertNotIn("PAYLOAD_B", result.stdout + result.stderr)

    def test_invalid_report_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            report = Path(temporary) / "report.json"
            report.write_text("{}")
            result = subprocess.run([sys.executable, str(SCRIPT), str(report)], capture_output=True)
            self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
