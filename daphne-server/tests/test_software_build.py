from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import daphneV3_high_level_confs_pb2 as h
from software_build import check_build


def fixture():
    return h.ServerBuildInfo(metadata_format_version=1, component="daphne-server",
        software_version="git:" + "a" * 40, source_git_commit="a" * 40,
        committed_source_tree="b" * 40, source_worktree_dirty=False,
        source_quality=h.MEASUREMENT_GOOD, source_detail="Build metadata, not attestation",
        high_level_schema_sha256="c" * 64, low_level_schema_sha256="d" * 64,
        control_envelope_version=2, compiler_id="GNU", compiler_version="12.2.0",
        target_architecture="aarch64", protobuf_compile_version="6.30.1")


class SoftwareBuildTests(unittest.TestCase):
    def test_clean_source_and_explicit_false_presence(self):
        info = h.ServerBuildInfo.FromString(fixture().SerializeToString())
        report = check_build(info, h, expected_commit="a" * 40, require_clean=True)
        self.assertIs(report["source_worktree_dirty"], False)
        info.ClearField("source_worktree_dirty")
        with self.assertRaises(RuntimeError):
            check_build(info, h)

    def test_dirty_is_visible_not_clean_provenance(self):
        info = fixture()
        info.source_worktree_dirty = True
        info.software_version += "-dirty"
        self.assertTrue(check_build(info, h)["source_worktree_dirty"])
        with self.assertRaises(RuntimeError):
            check_build(info, h, require_clean=True)

    def test_gitless_has_no_fabricated_source_fields(self):
        info = fixture()
        info.source_quality = h.MEASUREMENT_UNAVAILABLE
        for field in ("software_version", "source_git_commit", "committed_source_tree", "source_worktree_dirty"):
            info.ClearField(field)
        self.assertIsNone(check_build(info, h)["source_git_commit"])
        with self.assertRaises(RuntimeError):
            check_build(info, h, expected_commit="a" * 40)
        info.source_worktree_dirty = False
        with self.assertRaises(RuntimeError):
            check_build(info, h)

    def test_malformed_mismatched_and_private_labels_fail_without_echo(self):
        for field, value in (("metadata_format_version", 2), ("component", "hermes"),
                ("source_git_commit", "b" * 40), ("committed_source_tree", "x" * 40),
                ("software_version", "private-secret"), ("compiler_id", "/private-secret"),
                ("high_level_schema_sha256", "unknown"), ("control_envelope_version", 1),
                ("source_quality", h.MEASUREMENT_ERROR), ("target_architecture", "a" * 81)):
            info = fixture()
            setattr(info, field, value)
            with self.assertRaisesRegex(RuntimeError, "details suppressed") as caught:
                check_build(info, h)
            self.assertNotIn("private-secret", str(caught.exception))

    def test_exact_source_hashes_are_independently_compared(self):
        import hashlib
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            proto = root / "srcs/protobuf"
            proto.mkdir(parents=True)
            info = fixture()
            for level in ("high", "low"):
                data = (level + " source bytes\n").encode()
                (proto / f"daphneV3_{level}_level_confs.proto").write_bytes(data)
                setattr(info, f"{level}_level_schema_sha256", hashlib.sha256(data).hexdigest())
            self.assertTrue(check_build(info, h, source_root=root)["schema_source_compared"])
            (proto / "daphneV3_high_level_confs.proto").write_text("changed\n")
            with self.assertRaises(RuntimeError):
                check_build(info, h, source_root=root)

    def test_snapshot_and_bookkeeping_fields_are_additive(self):
        info = fixture()
        for message, field_number in ((h.ServerState, 19), (h.SystemStatusSnapshot, 29)):
            parent = message(success=True, server_build=info)
            decoded = message.FromString(parent.SerializeToString())
            self.assertEqual(decoded.server_build, info)
            self.assertEqual(parent.DESCRIPTOR.fields_by_name["server_build"].number, field_number)
            self.assertFalse(message(success=True).HasField("server_build"))


if __name__ == "__main__":
    unittest.main()
