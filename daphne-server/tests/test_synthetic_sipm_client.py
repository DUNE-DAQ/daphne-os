import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

try:
    import zmq
except ImportError:
    sys.modules["zmq"] = types.SimpleNamespace(ZMQError=RuntimeError)

CLIENT_DIR = Path(__file__).resolve().parents[1] / "client"
sys.path.insert(0, str(CLIENT_DIR))

import protobuf_loader
import synthetic_sipm as client


class FakeProto:
    SYNTHETIC_SIPM_FBK = 0
    SYNTHETIC_SIPM_HPK = 1
    MT2_CONFIGURE_SYNTHETIC_SIPM_REQ = 332
    MT2_CONFIGURE_SYNTHETIC_SIPM_RESP = 333
    MT2_READ_SYNTHETIC_SIPM_CONFIG_REQ = 334
    MT2_READ_SYNTHETIC_SIPM_CONFIG_RESP = 335
    ConfigureSyntheticSipmRequest = types.SimpleNamespace
    ReadSyntheticSipmConfigRequest = types.SimpleNamespace
    SyntheticSipmConfigResponse = types.SimpleNamespace


class FakeClient:
    def __init__(self, *args, **kwargs):
        self.calls = []
        self.state = dict(amplitude_q8=5760, model=1, enable=True)
        self.error = None
        self.wrong_configuration = False
        self.corrupt_raw = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def rpc(self, request_type, request, response_type, response_class):
        self.calls.append((request_type, request, response_type))
        if isinstance(self.error, Exception):
            raise self.error
        if request_type == FakeProto.MT2_CONFIGURE_SYNTHETIC_SIPM_REQ:
            if not self.wrong_configuration:
                self.state = vars(request).copy()
            assert response_type == FakeProto.MT2_CONFIGURE_SYNTHETIC_SIPM_RESP
        else:
            assert request_type == FakeProto.MT2_READ_SYNTHETIC_SIPM_CONFIG_REQ
            assert response_type == FakeProto.MT2_READ_SYNTHETIC_SIPM_CONFIG_RESP
        raw = self.state["amplitude_q8"] | (self.state["model"] << 22) | (int(self.state["enable"]) << 23)
        return response_class(
            success=self.error is None, message=self.error or "OK",
            raw_register=raw ^ int(self.corrupt_raw), **self.state
        )


class SyntheticSipmClientTests(unittest.TestCase):
    def test_decimal_quantization_and_limits(self):
        for text, expected in (
            ("1", 256), ("10000", 2560000), ("22.5", 5760),
            ("22.501953125", 5761), ("22.50195312499999999999999999999", 5760),
            ("1.00390625", 257), ("1e1", 2560),
        ):
            self.assertEqual(client.amplitude_to_q8(text), expected)
        for text in ("nan", "inf", "-inf", "0", "0.9999", "10000.0001", "text"):
            with self.assertRaises(argparse.ArgumentTypeError):
                client.amplitude_to_q8(text)

    def test_configure_requires_all_fields_and_explicit_enable(self):
        parser = client.build_parser()
        for fields in (
            [], ["--amplitude", "22.5"], ["--amplitude", "22.5", "--model", "fbk"],
            ["--amplitude", "22.5", "--model", "fbk", "--enable", "--disable"],
        ):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                parser.parse_args(["configure", *fields])
        args = parser.parse_args(["configure", "--amplitude", "22.5", "--model", "fbk", "--disable"])
        self.assertEqual(args.amplitude, 5760)
        self.assertFalse(args.enable)

    def test_read_is_read_only_and_configure_checks_returned_fields(self):
        connection = FakeClient()
        snapshot = client.read_configuration(FakeProto, connection)
        self.assertEqual(snapshot["raw_register"], "0x00C01680")
        self.assertEqual(snapshot["amplitude"], 22.5)
        self.assertEqual([c[0] for c in connection.calls], [334])
        for model, enable, raw in (("fbk", True, "0x00801680"), ("hpk", False, "0x00401680")):
            snapshot = client.configure_generator(FakeProto, connection, 5760, model, enable)
            self.assertEqual(snapshot["raw_register"], raw)
            self.assertEqual(vars(connection.calls[-1][1]), dict(amplitude_q8=5760, model=int(model == "hpk"), enable=enable))

    def test_disable_preserves_read_parameters(self):
        connection = FakeClient()
        snapshot = client.disable_generator(FakeProto, connection)
        self.assertEqual([c[0] for c in connection.calls], [334, 332])
        self.assertEqual(snapshot["raw_register"], "0x00401680")
        self.assertFalse(snapshot["enable"])

    def test_errors_and_inconsistent_readback(self):
        connection = FakeClient()
        connection.error = "generator unavailable"
        with self.assertRaisesRegex(RuntimeError, "unavailable"):
            client.disable_generator(FakeProto, connection)
        self.assertEqual(len(connection.calls), 1)  # Failed read must not write
        connection.error = None
        connection.corrupt_raw = True
        with self.assertRaisesRegex(RuntimeError, "raw register"):
            client.read_configuration(FakeProto, connection)
        connection.corrupt_raw = False
        connection.wrong_configuration = True
        with self.assertRaisesRegex(RuntimeError, "differs from requested"):
            client.configure_generator(FakeProto, connection, 256, "fbk", True)
        for amplitude in (0, 255, 2560001):
            with self.assertRaises(ValueError):
                client.configure_generator(FakeProto, connection, amplitude, "fbk", False)

    def test_cli_json_and_timeout_exit(self):
        connection = FakeClient()
        with patch.object(client, "load_protobuf_modules", return_value=(FakeProto, None)), \
                patch.object(client, "V2Client", return_value=connection), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(client.main(["read"]), 0)
        self.assertEqual(json.loads(output.getvalue())["raw_register"], "0x00C01680")
        connection.error = TimeoutError("Timed out waiting for daphneServer")
        with patch.object(client, "load_protobuf_modules", return_value=(FakeProto, None)), \
                patch.object(client, "V2Client", return_value=connection), \
                contextlib.redirect_stderr(io.StringIO()) as error:
            self.assertEqual(client.main(["read"]), 2)
        self.assertIn("Timed out", error.getvalue())

    def test_loader_skips_stale_bindings_before_import(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stale = root / "stale"
            fresh = root / "build" / "srcs" / "protobuf"
            stale.mkdir()
            fresh.mkdir(parents=True)
            high = "daphneV3_high_level_confs_pb2"
            low = "daphneV3_low_level_confs_pb2"
            (stale / f"{high}.py").write_text('raise AssertionError("stale module imported")\n')
            (stale / f"{low}.py").write_text("")
            names = [name for name in vars(FakeProto) if not name.startswith("_")]
            source = "\n".join(f"{name} = 0" for name in names)
            source = source.replace(
                "ConfigureSyntheticSipmRequest = 0",
                "_CONFIGURESYNTHETICSIPMREQUEST = 0\n"
                "globals()['Configure' + 'SyntheticSipmRequest'] = 0",
            )
            (fresh / f"{high}.py").write_text(source)
            (fresh / f"{low}.py").write_text("")
            with patch.dict(os.environ, {
                "DAPHNE_PROTO_PYTHON_DIR": str(stale), "DAPHNE_BUILD_DIR": str(root / "build")
            }):
                pb, _ = protobuf_loader.load_protobuf_modules(require_synthetic_sipm=True)
            self.assertEqual(Path(pb.__file__).parent, fresh)
            sys.modules.pop(high, None)
            sys.modules.pop(low, None)


if __name__ == "__main__":
    unittest.main()
