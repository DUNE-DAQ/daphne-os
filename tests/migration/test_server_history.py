"""Exercise archive provenance checks against real, isolated Git histories."""

import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[2] / "scripts/check_server_history.py"
SPEC = importlib.util.spec_from_file_location("check_server_history", SCRIPT)
HISTORY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HISTORY)


class ServerHistoryTests(unittest.TestCase):
    def git(self, *args):
        return subprocess.check_output(
            ["git", "-C", str(self.root), *args], text=True,
            stderr=subprocess.PIPE,
        ).strip()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.git("init", "-b", "develop")
        self.git("config", "user.name", "History test")
        self.git("config", "user.email", "history@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        payload = self.root / "payload.txt"
        payload.write_text("initial\n")
        self.git("add", "payload.txt")
        self.git("commit", "-m", "Initial source")
        self.initial = self.git("rev-parse", "HEAD")
        payload.write_text("archived\n")
        self.git("commit", "-am", "Archived source")
        self.source = self.git("rev-parse", "HEAD")
        self.tree = self.git("rev-parse", "HEAD^{tree}")
        self.ref = "refs/heads/archive/daphneZMQ/feature/test"
        self.git("update-ref", self.ref, self.source)
        (self.root / "daphne-server").mkdir()
        self.git("mv", "payload.txt", "daphne-server/payload.txt")
        self.git("commit", "-m", "Import source under server prefix")
        self.record = {
            "commits": [self.initial, self.source],
            "commit_count": 2,
            "refs": [{"destination": self.ref, "object": self.source}],
            "import_commit": self.git("rev-parse", "HEAD"),
            "import_prefix": "daphne-server",
            "active_source_commit": self.source,
            "active_source_tree": self.tree,
        }
        (self.root / "docs").mkdir()

    def verify(self):
        (self.root / "docs/daphne-server-history.json").write_text(
            json.dumps(self.record)
        )
        with patch.object(HISTORY, "ROOT", self.root):
            return HISTORY.main()

    def descendant(self):
        return self.git("commit-tree", self.tree, "-p", self.source, "-m", "Advance")

    def test_unchanged_archive_passes(self):
        self.assertEqual(self.verify(), 0)

    def test_fast_forward_branch_preserves_original_inventory(self):
        self.git("update-ref", self.ref, self.descendant())
        self.assertEqual(self.verify(), 0)

    def test_remote_tracking_fast_forward_passes(self):
        self.git("update-ref", self.ref.replace("refs/heads/", "refs/remotes/origin/"),
                 self.descendant())
        self.git("update-ref", "-d", self.ref)
        self.assertEqual(self.verify(), 0)

    def test_rewound_branch_is_rejected(self):
        self.git("update-ref", self.ref, self.initial)
        with self.assertRaisesRegex(ValueError, "lost original history"):
            self.verify()

    def test_unrelated_branch_with_identical_tree_is_rejected(self):
        unrelated = self.git("commit-tree", self.tree, "-m", "Unrelated")
        self.git("update-ref", self.ref, unrelated)
        with self.assertRaisesRegex(ValueError, "lost original history"):
            self.verify()

    def test_tag_must_remain_exact_even_for_a_descendant(self):
        tag = self.ref.replace("refs/heads/", "refs/tags/")
        self.record["refs"][0]["destination"] = tag
        self.git("update-ref", tag, self.source)
        self.assertEqual(self.verify(), 0)
        self.git("update-ref", tag, self.descendant())
        with self.assertRaisesRegex(ValueError, "Archived tag changed"):
            self.verify()


if __name__ == "__main__":
    unittest.main()
