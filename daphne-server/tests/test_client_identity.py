"""Exercise CLI identities without connecting to hardware or a network socket."""

import argparse
import ast
import importlib.util
import os
from pathlib import Path
import runpy
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from identity_cli import add_identity_argument


class Connected(BaseException):
    """Stop an entry point as soon as it would connect to a server."""


class ClientIdentityTests(unittest.TestCase):
    def run_acquire(self, *options, inherited=None):
        import zmq
        import protobuf_loader
        identities = []

        class Socket:
            def setsockopt(self, option, value):
                if option == zmq.IDENTITY:
                    identities.append(value)

            def connect(self, endpoint):
                raise Connected()

        class Context:
            @classmethod
            def instance(cls):
                return cls()

            def socket(self, kind):
                return Socket()

        protobufs = SimpleNamespace(ControlEnvelope=object)
        argv = ["protobuf_acquire_list_channels.py", "-foldername", "unused",
                "-channel_list", "0", "-N", "1", "-L", "8",
                "--trigger-source", "software", *options]
        with patch.dict(os.environ, {}, clear=True):
            if inherited is not None:
                os.environ["DAPHNE_IDENTITY"] = inherited
            with patch.object(zmq, "Context", Context), \
                    patch.object(protobuf_loader, "load_protobuf_modules", return_value=(protobufs, object())), \
                    patch.object(sys, "argv", argv), self.assertRaises(Connected):
                runpy.run_path(str(ROOT / "client" / argv[0]), run_name="__main__")
        self.assertEqual(len(identities), 1)
        return identities[0]

    @unittest.skipUnless(all(importlib.util.find_spec(name) for name in ("zmq", "numpy", "tqdm")),
                         "Acquisition CLI dependencies are optional on minimal test hosts")
    def test_acquire_identity_reaches_both_backends_through_the_cli(self):
        for backend in ([], ["--dma", "--capture-mode", "persistent"]):
            for flag in ("--identity", "-identity"):
                with self.subTest(backend=backend, flag=flag):
                    self.assertEqual(self.run_acquire(*backend, flag, "operator-A"), b"operator-A")

    @unittest.skipUnless(all(importlib.util.find_spec(name) for name in ("zmq", "numpy", "tqdm")),
                         "Acquisition CLI dependencies are optional on minimal test hosts")
    def test_acquire_defaults_and_inherited_identity(self):
        self.assertEqual(self.run_acquire(), b"client-compat")
        self.assertTrue(self.run_acquire("--dma").startswith(b"dma-acquire-"))
        self.assertEqual(self.run_acquire(inherited="scan"), f"scan-{os.getpid()}".encode())
        self.assertEqual(self.run_acquire("--identity", "explicit", inherited="scan"), b"explicit")

    def test_multibyte_identity_is_validated_by_wire_length(self):
        with patch.dict(os.environ, {}, clear=True):
            parser = argparse.ArgumentParser()
            add_identity_argument(parser)
            self.assertEqual(parser.parse_args(["--identity", "é" * 127]).identity, "é" * 127)
            with patch("sys.stderr"), self.assertRaises(SystemExit):
                parser.parse_args(["--identity", "é" * 128])

    def test_osc_parser_accepts_both_aliases_and_backends_without_qt(self):
        from dma_options import add_dma_capture_arguments
        from trigger_source import add_trigger_source_arguments
        tree = ast.parse((ROOT / "client" / "osc.py").read_text(encoding="utf-8"))
        main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
        parse_index = next(index for index, node in enumerate(main.body)
                           if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
                           and isinstance(node.value.func, ast.Attribute) and node.value.func.attr == "parse_args")
        # Execute the actual parser portion, excluding GUI and hardware setup.
        main.body = main.body[:parse_index + 1] + [ast.Return(value=ast.Name(id="args", ctx=ast.Load()))]
        module = ast.fix_missing_locations(ast.Module(body=[main], type_ignores=[]))
        namespace = dict(argparse=argparse, sys=sys, add_identity_argument=add_identity_argument,
                         add_dma_capture_arguments=add_dma_capture_arguments,
                         add_trigger_source_arguments=add_trigger_source_arguments)
        exec(compile(module, "osc-parser", "exec"), namespace)
        for backend in ([], ["--dma"]):
            for flag in ("--identity", "-identity"):
                with patch.object(sys, "argv", ["osc.py", "-L", "8", *backend, flag, "scope-A"]):
                    self.assertEqual(namespace["main"]().identity, "scope-A")

    def test_legacy_req_connections_derive_unique_identities(self):
        import uuid
        tree = ast.parse((ROOT / "client" / "protobuf_client_spybuffer_dump.py").read_text(encoding="utf-8"))
        factory = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "make_req_socket")
        identities = []
        socket = SimpleNamespace(setsockopt=lambda option, identity: identities.append(identity))
        context = SimpleNamespace(socket=lambda kind: socket)
        namespace = dict(zmq=SimpleNamespace(REQ=1, IDENTITY=2), uuid=uuid)
        exec(compile(ast.Module(body=[factory], type_ignores=[]), "legacy-req-factory", "exec"), namespace)
        for _ in range(2):
            namespace["make_req_socket"](context, "operator-A")
        self.assertEqual(len(set(identities)), 2)
        self.assertTrue(all(identity.startswith(b"operator-A-") for identity in identities))
        namespace["make_req_socket"](context, None)
        self.assertEqual(len(identities), 2)

    @unittest.skipUnless(importlib.util.find_spec("zmq"), "pyzmq is optional on minimal test hosts")
    def test_scan_connections_have_distinct_roles(self):
        import scan_afe_delay_eye
        import zmq
        identities = []

        class Socket:
            def setsockopt(self, option, value):
                if option == zmq.IDENTITY:
                    identities.append(value)

            def connect(self, endpoint):
                pass

        context = SimpleNamespace(socket=lambda kind: Socket())
        roles = ("control", "sweep", "apply", "control")
        for role in roles:
            scan_afe_delay_eye.make_socket(context, "fake", 100, role, identity="scan-A")
        self.assertEqual(len(set(identities)), len(roles))
        for identity, role in zip(identities, roles):
            self.assertTrue(identity.startswith(f"scan-A-{role}-".encode()))

    def test_python_scan_gives_each_child_a_distinct_identity(self):
        sys.path.insert(0, str(ROOT / "client" / "dynamic_range_led"))
        import scan_runtime
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            identities = []
            for index in range(2):
                code, command = scan_runtime.run_acquire(
                    host="fake", port=1, route="mezz/0", raw_dir=base / "raw",
                    channels=[0], waveforms=1, waveform_len=8, timeout_ms=100,
                    software_trigger=True, dry_run=True, log_path=base / f"{index}.log",
                    identity="scan-A",
                )
                self.assertEqual(code, 0)
                identities.append(command[command.index("--identity") + 1])
            self.assertTrue(all(value.startswith("scan-A-") for value in identities))
            self.assertEqual(len(set(identities)), 2)


if __name__ == "__main__":
    unittest.main()
