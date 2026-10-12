"""Reject old DMA descriptors before they pollute protobuf's global pool."""
import ast
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from google.protobuf import descriptor_pb2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
import protobuf_loader


class DmaBindingLoaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pb, _ = protobuf_loader.load_protobuf_modules(require_dma=True)
        cls.fresh = Path(pb.__file__).parent
        cls.source = Path(pb.__file__).read_text(encoding="utf-8")
        call = next(n for n in ast.walk(ast.parse(cls.source))
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "AddSerializedFile")
        cls.descriptor = ast.literal_eval(call.args[0])

    def stale_bindings(self, directory):
        directory.mkdir(parents=True)
        descriptor = descriptor_pb2.FileDescriptorProto.FromString(self.descriptor)
        for message in descriptor.message_type:
            required = protobuf_loader.DMA_FIELDS.get(message.name, set())
            retained = [f for f in message.field if f.name not in required]
            del message.field[:]
            message.field.extend(retained)
        source = (
            "# DmaAcquireRequest DmaReadResponse AcquisitionCapabilitiesResponse MT2_DMA_SCAN_REQ\n"
            "raise AssertionError('old DMA module imported')\n"
            "from google.protobuf import descriptor_pool\n"
            f"DESCRIPTOR = descriptor_pool.Default().AddSerializedFile({descriptor.SerializeToString()!r})\n"
        )
        (directory / "daphneV3_high_level_confs_pb2.py").write_text(source, encoding="utf-8")
        (directory / "daphneV3_low_level_confs_pb2.py").write_text("", encoding="utf-8")

    def fresh_bindings(self, directory):
        directory.mkdir(parents=True)
        for name in ("daphneV3_high_level_confs_pb2.py", "daphneV3_low_level_confs_pb2.py"):
            shutil.copyfile(self.fresh / name, directory / name)

    def run_loader(self, root, configured, expected):
        env = dict(os.environ, DAPHNE_PROTO_PYTHON_DIR=str(configured),
                   DAPHNE_BUILD_DIR=str(root / "absent-build"))
        script = (
            "import sys; from pathlib import Path; "
            f"sys.path.insert(0, {str(ROOT / 'client')!r}); "
            "import protobuf_loader as loader; "
            "loader.REPO_ROOT = Path(sys.argv[1]); "
            "p, _ = loader.load_protobuf_modules(require_dma=True); "
            "assert Path(p.__file__).parent == Path(sys.argv[2]); "
            "assert 'skip_ramp_verification' in p.AfeDelaySweepRequest.DESCRIPTOR.fields_by_name; "
            "assert 'force_acquisition_supported' in p.AcquisitionCapabilitiesResponse.DESCRIPTOR.fields_by_name"
        )
        return subprocess.run([sys.executable, "-c", script, str(root), str(expected)],
                              env=env, capture_output=True, text=True)

    def test_stale_environment_override_falls_back_before_import(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stale, fresh = root / "old", root / "srcs" / "protobuf"
            self.stale_bindings(stale)
            self.fresh_bindings(fresh)
            result = self.run_loader(root, stale, fresh)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_stale_server_build_falls_back_before_import(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.stale_bindings(root / "build-petalinux" / "srcs" / "protobuf")
            fresh = root / "srcs" / "protobuf"
            self.fresh_bindings(fresh)
            result = self.run_loader(root, root / "absent", fresh)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_only_stale_bindings_reports_local_schema_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.stale_bindings(root / "old")
            result = self.run_loader(root, root / "old", root / "absent")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("DMA schema lacks force acquisition/ramp verification fields", result.stderr)
            self.assertNotIn("old DMA module imported", result.stderr)


if __name__ == "__main__":
    unittest.main()
