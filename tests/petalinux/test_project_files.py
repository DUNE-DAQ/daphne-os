from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("project_files_under_test", ROOT / "scripts/petalinux/project_files.py")
FILES = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FILES)


class ProjectFilesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)

    def test_managed_block_replacement_preserves_unrelated_text_and_is_idempotent(self) -> None:
        begin, end = "# BEGIN managed", "# END managed"
        original = "operator = 1\n"
        created = FILES.replace_block(original, begin, end, "PROFILE=developer")
        self.assertTrue(created.startswith(original))
        self.assertEqual(created, FILES.replace_block(created, begin, end, "PROFILE=developer\n"))
        updated = FILES.replace_block(created + "after = 2\n", begin, end, "PROFILE=minimal")
        self.assertNotIn("PROFILE=developer", updated)
        self.assertTrue(updated.endswith("after = 2\n"))

    def test_malformed_managed_blocks_fail_without_changing_file(self) -> None:
        path = self.base / "local.conf"
        for text in ("# BEGIN\n", "# END\n", "# END\n# BEGIN\n", "# BEGIN\n# BEGIN\n# END\n"):
            with self.subTest(text=text):
                path.write_text(text)
                with self.assertRaises(ValueError):
                    FILES.update_block(path, "# BEGIN", "# END", "new")
                self.assertEqual(path.read_text(), text)

    def test_block_update_preserves_permissions(self) -> None:
        path = self.base / "local.conf"
        path.write_text("operator = 1\n")
        path.chmod(0o640)
        FILES.update_block(path, "# BEGIN", "# END", "new")
        self.assertEqual(path.stat().st_mode & 0o777, 0o640)

    def directories(self) -> tuple[Path, Path]:
        staged, destination = self.base / "staged", self.base / "destination"
        for directory, value in ((staged, "new"), (destination, "old")):
            directory.mkdir()
            (directory / "payload").write_text(value)
        return staged, destination

    def test_publication_failure_restores_previous_directory(self) -> None:
        staged, destination = self.directories()
        real_replace = FILES.os.replace
        def fail_publish(source, target):
            if Path(source) == staged:
                raise OSError("simulated publication failure")
            return real_replace(source, target)
        with patch.object(FILES.os, "replace", side_effect=fail_publish):
            with self.assertRaisesRegex(OSError, "publication failure"):
                FILES.publish_directory(staged, destination)
        self.assertEqual((destination / "payload").read_text(), "old")
        self.assertEqual((staged / "payload").read_text(), "new")
        self.assertEqual(list(self.base.glob(".destination.previous-*")), [])

    def test_failed_restore_keeps_recoverable_backup(self) -> None:
        staged, destination = self.directories()
        real_replace = FILES.os.replace
        def fail_publish_and_restore(source, target):
            if Path(source) != destination:
                raise OSError("simulated failure")
            return real_replace(source, target)
        with patch.object(FILES.os, "replace", side_effect=fail_publish_and_restore):
            with self.assertRaises(OSError):
                FILES.publish_directory(staged, destination)
        backups = list(self.base.glob(".destination.previous-*/destination/payload"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), "old")

    def test_publication_success_replaces_output_and_removes_backup(self) -> None:
        staged, destination = self.directories()
        FILES.publish_directory(staged, destination)
        self.assertEqual((destination / "payload").read_text(), "new")
        self.assertEqual(list(self.base.glob(".destination.previous-*")), [])

    def test_unowned_or_symlinked_output_is_not_replaced(self) -> None:
        staged, destination = self.directories()
        with self.assertRaisesRegex(ValueError, "not created by this collector"):
            FILES.publish_directory(staged, destination, marker="meta/COLLECT-METADATA.txt")
        link = self.base / "linked-output"
        link.symlink_to(destination, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            FILES.publish_directory(staged, link)
        self.assertEqual((destination / "payload").read_text(), "old")

    def layer_source(self) -> Path:
        source = self.base / "source"
        for relative in FILES.STAGED_PATHS:
            target = source / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.name == "staged":
                target.mkdir()
                (target / "payload").write_text("unqualified placeholder")
            else:
                target.write_text("QUALIFIED=0\n")
        for mode in ("self-trigger", "full-stream"):
            target = source / FILES.PROFILE_DIR / f"daphne-gateware-{mode}.conf"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f"PROFILE={mode}\nAPP=placeholder\nIDENTITY_ABI_MAJOR=2\nIDENTITY_ABI_MINOR=0\nSETTING=new\n")
        return source

    def test_refresh_preserves_staged_payloads_metadata_and_app_bindings(self) -> None:
        source = self.layer_source()
        destination = self.base / "layer"
        FILES.refresh_layer(source, destination)
        for relative in FILES.STAGED_PATHS:
            target = destination / relative
            (target / "payload" if target.is_dir() else target).write_text("project-owned")
        profile = destination / FILES.PROFILE_DIR / "daphne-gateware-self-trigger.conf"
        profile.write_text("PROFILE=self-trigger\nAPP=daphne_selftrigger_ol_123abcd\nIDENTITY_ABI_MAJOR=2\nIDENTITY_ABI_MINOR=1\nSETTING=old\n")
        FILES.refresh_layer(source, destination)
        for relative in FILES.STAGED_PATHS:
            target = destination / relative
            self.assertEqual((target / "payload" if target.is_dir() else target).read_text(), "project-owned")
        self.assertIn("APP=daphne_selftrigger_ol_123abcd", profile.read_text())
        self.assertIn("SETTING=new", profile.read_text())
        self.assertIn("IDENTITY_ABI_MAJOR=2\nIDENTITY_ABI_MINOR=1\n", profile.read_text())
        self.assertIn("APP=placeholder", (source / FILES.PROFILE_DIR / profile.name).read_text())

    def test_legacy_symlink_is_detached_without_modifying_source(self) -> None:
        source = self.layer_source()
        destination = self.base / "layer"
        destination.symlink_to(source, target_is_directory=True)
        FILES.refresh_layer(source, destination)
        self.assertFalse(destination.is_symlink())
        payload = Path(FILES.STAGED_PATHS[0]) / "payload"
        (destination / payload).write_text("project A")
        self.assertEqual((source / payload).read_text(), "unqualified placeholder")

    def test_projects_do_not_share_staged_files(self) -> None:
        source = self.layer_source()
        first, second = self.base / "first", self.base / "second"
        for destination in (first, second):
            FILES.refresh_layer(source, destination)
        payload = Path(FILES.STAGED_PATHS[0]) / "payload"
        (first / payload).write_text("project A")
        self.assertEqual((second / payload).read_text(), "unqualified placeholder")

    def test_bad_app_binding_leaves_old_layer_untouched(self) -> None:
        source = self.layer_source()
        destination = self.base / "layer"
        FILES.refresh_layer(source, destination)
        profile = destination / FILES.PROFILE_DIR / "daphne-gateware-self-trigger.conf"
        profile.write_text("APP=one\nAPP=two\n")
        with self.assertRaisesRegex(ValueError, "one APP binding"):
            FILES.refresh_layer(source, destination)
        self.assertEqual(profile.read_text(), "APP=one\nAPP=two\n")

    def test_bad_abi_binding_leaves_old_layer_untouched(self) -> None:
        source = self.layer_source()
        destination = self.base / "layer"
        FILES.refresh_layer(source, destination)
        profile = destination / FILES.PROFILE_DIR / "daphne-gateware-self-trigger.conf"
        for binding in ("IDENTITY_ABI_MAJOR=3\nIDENTITY_ABI_MINOR=0\n", "IDENTITY_ABI_MAJOR=2\nIDENTITY_ABI_MINOR=2\n",
                        "IDENTITY_ABI_MAJOR=2\nIDENTITY_ABI_MINOR=0\nIDENTITY_ABI_MINOR=1\n", "IDENTITY_ABI_MAJOR=2\n"):
            original = "APP=daphne_selftrigger_ol_123abcd\n" + binding
            profile.write_text(original)
            with self.assertRaises(ValueError):
                FILES.refresh_layer(source, destination)
            self.assertEqual(profile.read_text(), original)
