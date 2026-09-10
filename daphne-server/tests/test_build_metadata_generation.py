"""Real CMake/Git fixtures; no FPGA access and no mutations of the source repo."""
import hashlib
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "cmake/server_build_info.cmake"
TARGET = ROOT / "cmake/server_build_target.cmake"


class BuildMetadataGenerationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="daphne-build-metadata-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repository"
        self.source = self.repo / "server with spaces"
        self.proto = self.source / "srcs/protobuf"
        self.proto.mkdir(parents=True)
        for level in ("high", "low"):
            (self.proto / f"daphneV3_{level}_level_confs.proto").write_text(f"// {level} fixture\n")
        self.header = self.root / "output header.hpp"

    def run_command(self, *args, cwd=None, good=True):
        result = subprocess.run(args, cwd=cwd, text=True, capture_output=True, timeout=45)
        if good:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
        return result

    def git(self, *args):
        return self.run_command("git", "-C", str(self.repo), *args).stdout.strip()

    def initialize(self):
        self.git("init", "-q")
        self.git("config", "user.name", "Metadata Test")
        self.git("config", "user.email", "metadata-test@example.invalid")
        self.commit()

    def commit(self):
        self.git("add", "--all")
        self.git("-c", "commit.gpgsign=false", "commit", "-qm", "fixture")

    def generated(self, *extra, good=True):
        self.run_command("cmake", "-DSOURCE_DIR=" + str(self.source),
            "-DOUTPUT_HEADER=" + str(self.header), "-DCOMPILER_ID=GNU", "-DCOMPILER_VERSION=12.2.0",
            "-DTARGET_ARCH=aarch64", "-DPROTOBUF_VERSION=6.30.1", *extra, "-P", str(GENERATOR), good=good)
        return self.fields(self.header) if good else None

    def fields(self, header):
        return dict(re.findall(r'inline constexpr char (\w+)\[\] = "([^"]*)";', header.read_text()))

    def test_gitless_export_has_hashes_but_no_revision(self):
        fields = self.generated()
        self.assertEqual(fields["source_commit"], "")
        self.assertEqual(fields["source_tree"], "")
        self.assertEqual(fields["source_dirty"], "")
        for level in ("high", "low"):
            raw = (self.proto / f"daphneV3_{level}_level_confs.proto").read_bytes()
            self.assertEqual(fields[f"{level}_schema_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertNotIn(str(self.root), self.header.read_text())

    def test_clean_dirty_staged_untracked_and_outside_scope(self):
        self.initialize()
        fields = self.generated()
        self.assertEqual(fields["source_commit"], self.git("rev-parse", "HEAD"))
        self.assertEqual(fields["source_tree"], self.git("rev-parse", "HEAD:server with spaces"))
        self.assertEqual(fields["source_dirty"], "false")
        (self.repo / "outside.txt").write_text("outside server\n")
        self.assertEqual(self.generated()["source_dirty"], "false")
        high = self.proto / "daphneV3_high_level_confs.proto"
        high.write_text("// changed\n")
        self.assertEqual(self.generated()["source_dirty"], "true")
        self.git("add", "--", str(high))
        self.assertEqual(self.generated()["source_dirty"], "true")
        self.commit()
        self.assertEqual(self.generated()["source_dirty"], "false")
        (self.source / "untracked.cpp").write_text("// extra source\n")
        self.assertEqual(self.generated()["source_dirty"], "true")

    def test_untracked_export_does_not_inherit_parent_repository(self):
        (self.repo / "unrelated.txt").write_text("unrelated\n")
        self.git("init", "-q")
        self.git("config", "user.name", "Metadata Test")
        self.git("config", "user.email", "metadata-test@example.invalid")
        self.git("add", "unrelated.txt")
        self.git("-c", "commit.gpgsign=false", "commit", "-qm", "unrelated")
        self.assertEqual(self.generated()["source_commit"], "")

    def test_invalid_toolchain_label_cannot_enter_header(self):
        self.generated("-DCOMPILER_ID=private/value", good=False)
        self.assertFalse(self.header.exists())

    def test_no_change_preserves_header_timestamp(self):
        self.initialize()
        before = self.generated()
        mtime = self.header.stat().st_mtime_ns
        self.assertEqual(self.generated(), before)
        self.assertEqual(self.header.stat().st_mtime_ns, mtime)

    def incremental_target(self, generator):
        # Include the exact target definition used by the production CMakeLists.
        (self.source / "CMakeLists.txt").write_text(
            'cmake_minimum_required(VERSION 3.10)\nproject(metadata_fixture LANGUAGES CXX)\n'
            'set(CMAKE_CXX_STANDARD 17)\nset(Protobuf_VERSION 6.30.1)\n'
            f'include("{TARGET}")\n'
            'add_executable(probe probe.cpp "${DAPHNE_BUILD_INFO_HEADER}")\n'
            'add_dependencies(probe daphne_build_metadata)\n'
            'target_include_directories(probe PRIVATE "${CMAKE_CURRENT_BINARY_DIR}")\n')
        (self.source / "probe.cpp").write_text(
            '#include <iostream>\n#include "server_build_info.generated.hpp"\n'
            'int main() { using namespace daphne_sc::compiled_build;\n'
            'std::cout << source_commit << "\\n" << source_dirty << "\\n" << high_schema_sha256 << "\\n"; }\n')
        self.initialize()
        build = self.root / generator
        self.run_command("cmake", "-G", generator, "-S", str(self.source), "-B", str(build))
        def compiled():
            self.run_command("cmake", "--build", str(build), "--target", "probe", "-j", "2")
            return self.run_command(str(build / "probe")).stdout.splitlines()
        clean = compiled()
        self.assertEqual(clean[:2], [self.git("rev-parse", "HEAD"), "false"])
        high = self.proto / "daphneV3_high_level_confs.proto"
        high.write_text(f"// changed for {generator}\n")
        dirty = compiled()
        self.assertEqual(dirty[:2], [clean[0], "true"])
        self.assertNotEqual(dirty[2], clean[2])
        self.commit()
        final = compiled()
        self.assertNotEqual(final[0], clean[0])
        self.assertEqual(final[1:], ["false", dirty[2]])

    def test_incremental_make_refreshes_compiled_source_and_head(self):
        self.incremental_target("Unix Makefiles")

    @unittest.skipUnless(shutil.which("ninja"), "Ninja backend not installed")
    def test_incremental_ninja_refreshes_compiled_source_and_head(self):
        self.incremental_target("Ninja")


if __name__ == "__main__":
    unittest.main()
