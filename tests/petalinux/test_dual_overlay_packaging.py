#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[2]
STAGE_SCRIPT = ROOT / "scripts/petalinux/stage_overlay_into_project.sh"
RECIPE_SOURCE = (
    ROOT / "petalinux/meta-daphne/recipes-firmware/daphne-overlay"
)


class DualOverlayPackagingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.project = self.base / "project"
        self.recipe = (
            self.project
            / "project-spec/meta-daphne/recipes-firmware/daphne-overlay"
        )
        self.recipe.parent.mkdir(parents=True)
        shutil.copytree(RECIPE_SOURCE, self.recipe)
        (self.project / "build/conf").mkdir(parents=True)

        self.staged = self.recipe / "files/staged"
        shutil.rmtree(self.staged)
        self.staged.mkdir()
        (self.staged / "prior-state").write_text("preserve on failure\n")
        self.version_inc = self.recipe / "daphne-overlay-version.inc"
        self.version_inc.write_text("ORIGINAL=1\n")

        profile_dir = (
            self.project
            / "project-spec/meta-daphne/recipes-core/daphne-services/files"
        )
        profile_dir.mkdir(parents=True)
        self.self_profile = profile_dir / "daphne-gateware-self-trigger.conf"
        self.full_profile = profile_dir / "daphne-gateware-full-stream.conf"
        self.self_profile.write_text(
            "PROFILE=self-trigger\n"
            "APP=daphne_selftrigger_ol_release_sha7\n"
            "GATEWARE_MODE=self-trigger\n"
        )
        self.full_profile.write_text(
            "PROFILE=full-stream\n"
            "APP=daphne_fullstream_ol_release_sha7\n"
            "GATEWARE_MODE=full-stream\n"
        )
        self.original_self_profile = self.self_profile.read_text()
        self.original_full_profile = self.full_profile.read_text()

        self.fake_bin = self.base / "fake-bin"
        self.fake_bin.mkdir()
        fake_fdtget = self.fake_bin / "fdtget"
        fake_fdtget.write_text(
            "#!/bin/sh\n"
            "dtbo=$3\n"
            "node=$4\n"
            "layout=$(sed -n 's/^layout=//p' \"$dtbo\")\n"
            "case \"$layout:$node\" in\n"
            "  amba:/amba_pl|fragment:/fragment@0/__overlay__)\n"
            "    sed -n 's/^firmware_name=//p' \"$dtbo\"\n"
            "    exit 0\n"
            "    ;;\n"
            "esac\n"
            "exit 1\n"
        )
        fake_fdtget.chmod(0o755)
        self.env = os.environ.copy()
        self.env["PATH"] = f"{self.fake_bin}:{self.env['PATH']}"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def make_bundle(
        self,
        output: Path,
        mode: str,
        sha: str,
        *,
        layout: str,
        firmware_name: str | None = None,
        app_manifest: bool = True,
    ) -> str:
        if mode == "self-trigger":
            overlay_prefix = "daphne_selftrigger_ol"
        else:
            overlay_prefix = "daphne_fullstream_ol"
        app = f"{overlay_prefix}_{sha}"
        app_dir = output / app
        app_dir.mkdir(parents=True)
        (app_dir / f"{app}.bin").write_bytes(f"binary:{app}\n".encode())
        (app_dir / f"{app}.dtbo").write_text(
            f"layout={layout}\n"
            f"firmware_name={firmware_name or f'{app}.bin'}\n"
        )
        (app_dir / "shell.json").write_text(
            '{ "shell_type" : "XRT_FLAT", "num_slots": "1" }\n'
        )
        archive = output / f"{app}.zip"
        with zipfile.ZipFile(archive, "w") as bundle:
            for path in sorted(app_dir.iterdir()):
                bundle.write(path, f"{app}/{path.name}")

        covered = [
            archive,
            app_dir / f"{app}.bin",
            app_dir / f"{app}.dtbo",
            app_dir / "shell.json",
        ]
        lines = [
            f"{self.digest(path)}  {path.relative_to(output)}\n" for path in covered
        ]
        manifest_text = "".join(lines)
        if app_manifest:
            (output / f"{app}.SHA256SUMS").write_text(manifest_text)
        # Each independent packager owns this compatibility manifest. Calling
        # make_bundle twice in one output directory intentionally overwrites it
        # and models the real shared-output failure mode.
        (output / "SHA256SUMS").write_text(manifest_text)
        return app

    def run_stage(
        self,
        self_output: Path,
        full_output: Path,
        *extra: str,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                str(STAGE_SCRIPT),
                str(self.project),
                "--self-trigger-output",
                str(self_output),
                "--full-stream-output",
                str(full_output),
                *extra,
            ],
            env=self.env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def run_shared_stage(
        self,
        output: Path,
        *extra: str,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                str(STAGE_SCRIPT),
                str(self.project),
                "--output-dir",
                str(output),
                *extra,
            ],
            env=self.env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def assert_prior_state_preserved(self) -> None:
        self.assertEqual(
            (self.staged / "prior-state").read_text(), "preserve on failure\n"
        )
        self.assertEqual(self.version_inc.read_text(), "ORIGINAL=1\n")
        self.assertEqual(self.self_profile.read_text(), self.original_self_profile)
        self.assertEqual(self.full_profile.read_text(), self.original_full_profile)

    def test_stages_two_exact_apps_and_local_manifests(self) -> None:
        self_output = self.base / "self-output"
        full_output = self.base / "full-output"
        self_output.mkdir()
        full_output.mkdir()
        self_app = self.make_bundle(
            self_output, "self-trigger", "abcdef1", layout="amba"
        )
        full_app = self.make_bundle(
            full_output, "full-stream", "1234abc", layout="fragment"
        )

        result = self.run_stage(
            self_output,
            full_output,
            "--self-trigger-sha",
            "abcdef1",
            "--full-stream-sha",
            "1234abc",
        )
        self.assertEqual(result.returncode, 0, result.stderr)

        expected = (("self-trigger", self_app), ("full-stream", full_app))
        for mode, app in expected:
            app_stage = self.staged / mode
            self.assertEqual(
                {path.name for path in app_stage.iterdir()},
                {
                    f"{app}.bin",
                    f"{app}.dtbo",
                    "shell.json",
                    "BUILD-METADATA.txt",
                    "SHA256SUMS",
                },
            )
            for line in (app_stage / "SHA256SUMS").read_text().splitlines():
                expected_digest, relative = line.split(maxsplit=1)
                self.assertEqual(self.digest(app_stage / relative), expected_digest)

        version = self.version_inc.read_text()
        self.assertIn('DAPHNE_DUAL_OVERLAY_STAGED = "1"', version)
        self.assertIn(f'DAPHNE_SELF_TRIGGER_APP = "{self_app}"', version)
        self.assertIn(f'DAPHNE_FULL_STREAM_APP = "{full_app}"', version)
        self.assertIn(f"APP={self_app}\n", self.self_profile.read_text())
        self.assertIn(f"APP={full_app}\n", self.full_profile.read_text())
        self.assertNotIn("release_sha7", self.self_profile.read_text())
        self.assertNotIn("release_sha7", self.full_profile.read_text())
        self.assertFalse((self.staged / "prior-state").exists())

    def test_shared_output_uses_per_app_manifests_after_root_overwrite(self) -> None:
        shared_output = self.base / "shared-output"
        shared_output.mkdir()
        self_app = self.make_bundle(
            shared_output, "self-trigger", "abcdef1", layout="amba"
        )
        full_app = self.make_bundle(
            shared_output, "full-stream", "1234abc", layout="fragment"
        )

        root_manifest = (shared_output / "SHA256SUMS").read_text()
        self.assertNotIn(self_app, root_manifest)
        self.assertIn(full_app, root_manifest)
        self.assertTrue((shared_output / f"{self_app}.SHA256SUMS").is_file())
        self.assertTrue((shared_output / f"{full_app}.SHA256SUMS").is_file())

        result = self.run_shared_stage(
            shared_output,
            "--self-trigger-sha",
            "abcdef1",
            "--full-stream-sha",
            "1234abc",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            f"source_manifest={self_app}.SHA256SUMS",
            (self.staged / "self-trigger/BUILD-METADATA.txt").read_text(),
        )
        self.assertIn(
            f"source_manifest={full_app}.SHA256SUMS",
            (self.staged / "full-stream/BUILD-METADATA.txt").read_text(),
        )

    def test_separate_outputs_accept_legacy_root_manifests(self) -> None:
        self_output = self.base / "self-output"
        full_output = self.base / "full-output"
        self_output.mkdir()
        full_output.mkdir()
        self.make_bundle(
            self_output,
            "self-trigger",
            "abcdef1",
            layout="amba",
            app_manifest=False,
        )
        self.make_bundle(
            full_output,
            "full-stream",
            "1234abc",
            layout="fragment",
            app_manifest=False,
        )

        result = self.run_stage(self_output, full_output)
        self.assertEqual(result.returncode, 0, result.stderr)
        for mode in ("self-trigger", "full-stream"):
            metadata = (self.staged / mode / "BUILD-METADATA.txt").read_text()
            self.assertIn("source_manifest=SHA256SUMS", metadata)

    def test_missing_second_variant_does_not_replace_prior_state(self) -> None:
        self_output = self.base / "self-output"
        full_output = self.base / "full-output"
        self_output.mkdir()
        full_output.mkdir()
        self.make_bundle(self_output, "self-trigger", "abcdef1", layout="amba")

        result = self.run_stage(self_output, full_output)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("full-stream output must contain exactly one", result.stderr)
        self.assert_prior_state_preserved()

    def test_checksum_failure_does_not_replace_prior_state(self) -> None:
        self_output = self.base / "self-output"
        full_output = self.base / "full-output"
        self_output.mkdir()
        full_output.mkdir()
        self_app = self.make_bundle(
            self_output, "self-trigger", "abcdef1", layout="amba"
        )
        self.make_bundle(full_output, "full-stream", "1234abc", layout="fragment")
        (self_output / self_app / f"{self_app}.bin").write_bytes(b"tampered\n")

        result = self.run_stage(self_output, full_output)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("checksum mismatch", result.stderr)
        self.assert_prior_state_preserved()

    def test_suffixed_manifest_path_cannot_replace_exact_artifact(self) -> None:
        self_output = self.base / "self-output"
        full_output = self.base / "full-output"
        self_output.mkdir()
        full_output.mkdir()
        self_app = self.make_bundle(
            self_output, "self-trigger", "abcdef1", layout="amba"
        )
        self.make_bundle(full_output, "full-stream", "1234abc", layout="fragment")
        manifest = self_output / f"{self_app}.SHA256SUMS"
        required = f"{self_app}.zip"
        backup = self_output / f"{required} backup"
        shutil.copy2(self_output / required, backup)
        exact_line = f"{self.digest(self_output / required)}  {required}\n"
        replacement = f"{self.digest(backup)}  {required} backup\n"
        manifest.write_text(
            manifest.read_text().replace(exact_line, replacement, 1)
        )

        result = self.run_stage(self_output, full_output)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            f"must contain exactly one checksum for {required}", result.stderr
        )
        self.assert_prior_state_preserved()

    def test_duplicate_manifest_path_is_rejected(self) -> None:
        self_output = self.base / "self-output"
        full_output = self.base / "full-output"
        self_output.mkdir()
        full_output.mkdir()
        self_app = self.make_bundle(
            self_output, "self-trigger", "abcdef1", layout="amba"
        )
        self.make_bundle(full_output, "full-stream", "1234abc", layout="fragment")
        manifest = self_output / f"{self_app}.SHA256SUMS"
        required = f"{self_app}.zip"
        duplicate = f"{self.digest(self_output / required)}  {required}\n"
        manifest.write_text(manifest.read_text() + duplicate)

        result = self.run_stage(self_output, full_output)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            f"must contain exactly one checksum for {required}", result.stderr
        )
        self.assert_prior_state_preserved()

    def test_ambiguous_build_requires_explicit_sha(self) -> None:
        self_output = self.base / "self-output"
        full_output = self.base / "full-output"
        self_output.mkdir()
        full_output.mkdir()
        self.make_bundle(self_output, "self-trigger", "abcdef1", layout="amba")
        self.make_bundle(self_output, "self-trigger", "7654321", layout="amba")
        self.make_bundle(full_output, "full-stream", "1234abc", layout="fragment")

        result = self.run_stage(self_output, full_output)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("found 2", result.stderr)
        self.assert_prior_state_preserved()

    def test_dtbo_firmware_name_must_match_app_sha(self) -> None:
        self_output = self.base / "self-output"
        full_output = self.base / "full-output"
        self_output.mkdir()
        full_output.mkdir()
        self.make_bundle(self_output, "self-trigger", "abcdef1", layout="amba")
        self.make_bundle(
            full_output,
            "full-stream",
            "1234abc",
            layout="fragment",
            firmware_name="daphne_fullstream_ol_deadbee.bin",
        )

        result = self.run_stage(self_output, full_output)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("expected 'daphne_fullstream_ol_1234abc.bin'", result.stderr)
        self.assert_prior_state_preserved()

    def test_commit_failure_rolls_back_payload_metadata_and_profiles(self) -> None:
        self_output = self.base / "self-output"
        full_output = self.base / "full-output"
        self_output.mkdir()
        full_output.mkdir()
        self.make_bundle(self_output, "self-trigger", "abcdef1", layout="amba")
        self.make_bundle(full_output, "full-stream", "1234abc", layout="fragment")

        real_mv = shutil.which("mv")
        self.assertIsNotNone(real_mv)
        failed_once = self.base / "mv-failed-once"
        fake_mv = self.fake_bin / "mv"
        fake_mv.write_text(
            "#!/bin/sh\n"
            "for destination do :; done\n"
            f"if [ \"$destination\" = \"{self.full_profile}\" ] && "
            f"[ ! -e \"{failed_once}\" ]; then\n"
            f"  : > \"{failed_once}\"\n"
            "  exit 99\n"
            "fi\n"
            f"exec \"{real_mv}\" \"$@\"\n"
        )
        fake_mv.chmod(0o755)

        result = self.run_stage(self_output, full_output)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(failed_once.exists())
        self.assert_prior_state_preserved()

    def test_recipe_installs_both_apps_and_both_firmware_aliases(self) -> None:
        recipe = (RECIPE_SOURCE / "daphne-overlay.bb").read_text()
        self.assertIn("${DAPHNE_SELF_TRIGGER_APP}.bin", recipe)
        self.assertIn("${DAPHNE_FULL_STREAM_APP}.bin", recipe)
        self.assertIn("${DAPHNE_SELF_TRIGGER_FIRMWARE_NAME}", recipe)
        self.assertIn("${DAPHNE_FULL_STREAM_FIRMWARE_NAME}", recipe)
        self.assertNotIn('DAPHNE_OVERLAY_APP = "daphne"', recipe)
        self.assertIn('do_fetch[prefuncs] += "validate_dual_overlay"', recipe)
        self.assertNotIn("python __anonymous", recipe)
        self.assertIn("verify_manifest_path_once", recipe)
        self.assertIn("must contain exactly one checksum", recipe)

if __name__ == "__main__":
    unittest.main()
