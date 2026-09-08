from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shlex
import shutil
import struct
import subprocess
import tarfile
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
STAGE_SCRIPT = ROOT / "scripts/petalinux/stage_runtime_into_project.sh"
RECIPE_SOURCE = (
    ROOT / "petalinux/meta-daphne/recipes-apps/daphne-server"
)
REQUIRED_COMMIT = "77b39b7eb75204e1f2025f251a3a76ecf69d1d74"
BUNDLE_NAME = "daphne-server-runtime-minimal.tgz"
SERVER_MEMBER = "home/petalinux/daphne-server/build-petalinux/daphneServer"


class StageRuntimeIntoProjectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.project = self.base / "project"
        self.recipe = (
            self.project
            / "project-spec/meta-daphne/recipes-apps/daphne-server"
        )
        (self.project / "build/conf").mkdir(parents=True)
        (self.recipe / "files/staged").mkdir(parents=True)
        shutil.copy2(
            RECIPE_SOURCE / "daphne-server-contract.inc",
            self.recipe / "daphne-server-contract.inc",
        )
        shutil.copy2(
            RECIPE_SOURCE / "daphne-server-version.inc",
            self.recipe / "daphne-server-version.inc",
        )
        self.staged = self.recipe / "files/staged"
        (self.staged / "prior-state").write_text(
            "preserve on validation failure\n", encoding="utf-8"
        )
        self.original_version = (
            self.recipe / "daphne-server-version.inc"
        ).read_text(encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def make_bundle(
        self,
        *,
        rich_metadata: bool = True,
        expected_options: bool = True,
        elf_machine: int = 183,
    ) -> tuple[Path, str]:
        source = self.base / "runtime-input"
        source.mkdir()
        binary = self.base / "daphneServer"
        options = b""
        if expected_options:
            options = b"--gateware-mode\x00--expected-gateware-build-id\x00"
        elf_ident = b"\x7fELF" + bytes((2, 1, 1, 0, 0)) + bytes(7)
        elf_header = elf_ident + struct.pack(
            "<HHIQQQIHHHHHH",
            2,  # ET_EXEC
            elf_machine,
            1,
            0,
            0,
            0,
            0,
            64,
            0,
            0,
            0,
            0,
            0,
        )
        binary.write_bytes(elf_header + b"DAPHNE_TEST\x00" + options)

        bundle = source / BUNDLE_NAME
        with tarfile.open(bundle, "w:gz") as archive:
            archive.add(binary, arcname=SERVER_MEMBER)

        bundle_sha = self.digest(bundle)
        if rich_metadata:
            metadata = (
                f"artifact={BUNDLE_NAME}\n"
                f"sha256={bundle_sha}\n"
                "created_utc=2026-08-31T19:24:29Z\n"
                f"server_git_commit={REQUIRED_COMMIT}\n"
                "source_tree_clean=true\n"
                "target_architecture=aarch64\n"
                f"binary_sha256={self.digest(binary)}\n"
                "legacy_recipe_compatible=true\n"
                "qemu_validation=PASS: --help advertises required options\n"
                "rich_provenance=preserve this exact record verbatim\n"
            )
            (source / "BUILD-METADATA.txt").write_text(
                metadata, encoding="utf-8"
            )
            (source / "SHA256SUMS").write_text(
                f"{bundle_sha}  {BUNDLE_NAME}\n", encoding="utf-8"
            )
        return bundle, bundle_sha

    def run_stage(
        self, bundle: Path, *, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(STAGE_SCRIPT), str(self.project), str(bundle)],
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def assert_prior_state_preserved(self) -> None:
        self.assertEqual(
            (self.staged / "prior-state").read_text(encoding="utf-8"),
            "preserve on validation failure\n",
        )
        self.assertEqual(
            (self.recipe / "daphne-server-version.inc").read_text(
                encoding="utf-8"
            ),
            self.original_version,
        )

    def test_preserves_and_qualifies_metadata_bound_runtime(self) -> None:
        bundle, bundle_sha = self.make_bundle()
        source_metadata = (bundle.parent / "BUILD-METADATA.txt").read_bytes()

        result = self.run_stage(bundle)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Release qualification:\n  PASS", result.stdout)
        self.assertEqual(
            (self.staged / "BUILD-METADATA.txt").read_bytes(), source_metadata
        )
        self.assertEqual(
            self.digest(self.staged / BUNDLE_NAME), bundle_sha
        )
        subprocess.run(
            ["sha256sum", "--check", "--strict", "SHA256SUMS"],
            cwd=self.staged,
            check=True,
            stdout=subprocess.PIPE,
            text=True,
        )
        version = (self.recipe / "daphne-server-version.inc").read_text(
            encoding="utf-8"
        )
        self.assertIn('DAPHNE_SERVER_RUNTIME_QUALIFIED = "1"', version)
        self.assertIn(
            f'DAPHNE_SERVER_RUNTIME_GIT_COMMIT = "{REQUIRED_COMMIT}"',
            version,
        )
        self.assertIn('DAPHNE_SERVER_RUNTIME_GATEWARE_ABI_MAJOR = "2"', version)
        self.assertIn(f'DAPHNE_SERVER_RUNTIME_SHA256 = "{bundle_sha}"', version)

    def test_bare_bundle_stages_only_as_unqualified_fallback(self) -> None:
        bundle, bundle_sha = self.make_bundle(rich_metadata=False)

        result = self.run_stage(bundle)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("UNQUALIFIED", result.stdout)
        metadata = (self.staged / "BUILD-METADATA.txt").read_text(
            encoding="utf-8"
        )
        self.assertIn(f"sha256={bundle_sha}", metadata)
        self.assertIn("provenance=external-unqualified-input", metadata)
        version = (self.recipe / "daphne-server-version.inc").read_text(
            encoding="utf-8"
        )
        self.assertIn('DAPHNE_SERVER_RUNTIME_QUALIFIED = "0"', version)
        self.assertIn(
            'DAPHNE_SERVER_RUNTIME_GATEWARE_ABI_MAJOR = "unqualified"',
            version,
        )

    def test_rejects_metadata_tar_digest_mismatch_without_mutation(self) -> None:
        bundle, bundle_sha = self.make_bundle()
        metadata = bundle.parent / "BUILD-METADATA.txt"
        metadata.write_text(
            metadata.read_text(encoding="utf-8").replace(
                f"sha256={bundle_sha}\n", f"sha256={'0' * 64}\n", 1
            ),
            encoding="utf-8",
        )

        result = self.run_stage(bundle)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SHA-256 mismatch", result.stderr)
        self.assert_prior_state_preserved()

    def test_rejects_wrong_server_commit_without_mutation(self) -> None:
        bundle, _ = self.make_bundle()
        metadata = bundle.parent / "BUILD-METADATA.txt"
        metadata.write_text(
            metadata.read_text(encoding="utf-8").replace(
                REQUIRED_COMMIT, "0" * 40
            ),
            encoding="utf-8",
        )

        result = self.run_stage(bundle)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not match required commit", result.stderr)
        self.assert_prior_state_preserved()

    def test_rejects_binary_without_required_cli_contract(self) -> None:
        bundle, _ = self.make_bundle(expected_options=False)

        result = self.run_stage(bundle)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "does not advertise required option --gateware-mode",
            result.stderr,
        )
        self.assert_prior_state_preserved()

    def test_rejects_non_aarch64_binary_despite_metadata_claim(self) -> None:
        bundle, _ = self.make_bundle(elf_machine=62)  # EM_X86_64

        result = self.run_stage(bundle)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not an ELF64 AArch64 executable", result.stderr)
        self.assert_prior_state_preserved()

    def test_rejects_mismatched_adjacent_checksum(self) -> None:
        bundle, _ = self.make_bundle()
        (bundle.parent / "SHA256SUMS").write_text(
            f"{'0' * 64}  {BUNDLE_NAME}\n", encoding="utf-8"
        )

        result = self.run_stage(bundle)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SHA-256 mismatch", result.stderr)
        self.assert_prior_state_preserved()

    def test_rejects_suffixed_checksum_path_substitution(self) -> None:
        bundle, bundle_sha = self.make_bundle()
        backup = bundle.parent / f"{BUNDLE_NAME} backup"
        shutil.copy2(bundle, backup)
        (bundle.parent / "SHA256SUMS").write_text(
            f"{bundle_sha}  {BUNDLE_NAME} backup\n", encoding="utf-8"
        )

        result = self.run_stage(bundle)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            f"must contain exactly one checksum for {BUNDLE_NAME}", result.stderr
        )
        self.assert_prior_state_preserved()

    def test_rejects_duplicate_checksum_path(self) -> None:
        bundle, bundle_sha = self.make_bundle()
        (bundle.parent / "SHA256SUMS").write_text(
            f"{bundle_sha}  {BUNDLE_NAME}\n"
            f"{bundle_sha}  {BUNDLE_NAME}\n",
            encoding="utf-8",
        )

        result = self.run_stage(bundle)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            f"must contain exactly one checksum for {BUNDLE_NAME}", result.stderr
        )
        self.assert_prior_state_preserved()

    def test_final_version_move_failure_rolls_back_payload_and_sentinel(self) -> None:
        bundle, _ = self.make_bundle()
        fake_bin = self.base / "fake-bin"
        fake_bin.mkdir()
        fail_marker = self.base / "mv-failed-once"
        real_mv = shutil.which("mv")
        self.assertIsNotNone(real_mv)
        fake_mv = fake_bin / "mv"
        fake_mv.write_text(
            "#!/bin/sh\n"
            "source_path=$2\n"
            "destination_path=$3\n"
            f"failure_marker={shlex.quote(str(fail_marker))}\n"
            "case \"$source_path:$destination_path\" in\n"
            "  */.daphne-server-version.*:*/daphne-server-version.inc)\n"
            "    if [ ! -e \"$failure_marker\" ]; then\n"
            "      : > \"$failure_marker\"\n"
            "      exit 71\n"
            "    fi\n"
            "    ;;\n"
            "esac\n"
            f"exec {shlex.quote(real_mv or '/usr/bin/mv')} \"$@\"\n",
            encoding="utf-8",
        )
        fake_mv.chmod(0o755)
        env = os.environ.copy()
        env["PATH"] = f"{fake_bin}:{env['PATH']}"

        result = self.run_stage(bundle, env=env)

        self.assertEqual(result.returncode, 71, result.stderr)
        self.assertTrue(fail_marker.is_file())
        self.assert_prior_state_preserved()

    def test_recipe_has_fail_closed_do_fetch_sentinel(self) -> None:
        recipe = (RECIPE_SOURCE / "daphne-server.bb").read_text(
            encoding="utf-8"
        )
        sentinel = (RECIPE_SOURCE / "daphne-server-version.inc").read_text(
            encoding="utf-8"
        )
        self.assertIn('do_fetch[prefuncs] += "validate_daphne_server_runtime"', recipe)
        self.assertIn("DAPHNE_SERVER_RUNTIME_QUALIFIED", recipe)
        self.assertIn('DAPHNE_SERVER_RUNTIME_QUALIFIED = "0"', sentinel)
        self.assertNotIn("bb.fatal", sentinel)
        self.assertIn("verify_manifest_path_once", recipe)
        self.assertIn("must contain exactly one checksum", recipe)


if __name__ == "__main__":
    unittest.main()
