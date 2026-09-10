import contextlib
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "extract_oks_identity.py"
spec = importlib.util.spec_from_file_location("extract_oks_identity", SCRIPT)
identity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(identity)


def obj(root, cls, name, attrs=(), rels=()):
    element = ET.SubElement(root, "obj", {"class": cls, "id": name})
    for key, value in attrs:
        attr = ET.SubElement(element, "attr", {"name": key, "type": "u32" if isinstance(value, int) else "string"})
        if isinstance(value, list):
            for item in value:
                ET.SubElement(attr, "data", {"val": str(item)})
        else:
            attr.set("val", str(value))
    for key, refs in rels:
        if isinstance(refs, tuple):
            ET.SubElement(element, "rel", {"name": key, "class": refs[0], "id": refs[1]})
        else:
            rel = ET.SubElement(element, "rel", {"name": key})
            for cls, name in refs:
                ET.SubElement(rel, "ref", {"class": cls, "id": name})
    return element


class OksIdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.files = ["segment.xml", "connections.xml", "senders.xml"]
        self.docs = [ET.Element("oks-data") for _ in self.files]
        self.app = obj(self.docs[0], "DaphneApplication", "app", rels=[
            ("configuration", ("DaphneConf", "config")),
            ("detector_connections", [("NetworkDetectorToDaqConnection", "connection")])])
        self.config = obj(self.docs[0], "DaphneConf", "config", rels=[
            ("boards", [("DaphneMapEntry", "entry")])])
        self.entry = obj(self.docs[0], "DaphneMapEntry", "entry", [("key", "8.4.1")], [
            ("conf", ("DaphneV2BoardConf", "board"))])
        self.board = obj(self.docs[0], "DaphneV2BoardConf", "board", [
            ("crate_id", 4), ("slot_id", 1), ("detector_id", 8), ("address", "board.example"),
            ("bias_ctrl", 4095), ("tp_conf", 17881857)])
        self.connection = obj(self.docs[1], "NetworkDetectorToDaqConnection", "connection", rels=[
            ("net_senders", [("HermesDataSender", "sender")])])
        self.sender = obj(self.docs[2], "HermesDataSender", "sender", [("control_host", "alias.example")], [
            ("uses", ("NetworkInterface", "interface")),
            ("streams", [("DetectorStream", "stream0"), ("DetectorStream", "stream1")])])
        self.geos = []
        for n in range(2):
            obj(self.docs[2], "DetectorStream", f"stream{n}", [("source_id", 800 + n)], [
                ("geo_id", ("GeoId", f"geo{n}"))])
            self.geos.append(obj(self.docs[2], "GeoId", f"geo{n}", [
                ("crate_id", 4), ("slot_id", 1), ("detector_id", 8)]))
        self.interface = obj(self.docs[2], "NetworkInterface", "interface", [
            ("mac_address", "02:AA:BB:00:00:15"), ("ip_address", ["192.0.2.15"])])

    def save(self):
        for filename, document in zip(self.files, self.docs):
            (self.root / filename).write_bytes(ET.tostring(document))

    def extract(self):
        self.save()
        return identity.extract_identity(self.root, self.files, "app", "board")

    def attr(self, element, name):
        return next(item for item in element.findall("attr") if item.get("name") == name)

    def test_explicit_assignments_and_unknowns(self):
        data = self.extract()
        self.assertEqual(data["placement"]["crate_id"]["value"], 4)
        self.assertEqual(data["placement"]["slot_id"]["value"], 1)
        self.assertEqual(data["placement"]["detector_id"]["value"], 8)
        self.assertIsNone(data["timing_endpoint_address"])
        self.assertIsNone(data["management_mac_address"])
        link, = data["hermes_interfaces"]
        self.assertEqual(link["mac_address"]["value"], "02:aa:bb:00:00:15")
        self.assertEqual(link["ip_addresses"]["value"], ["192.0.2.15"])
        self.assertIsNone(link["hermes_link_id"])
        self.assertIsNone(link["physical_connector"])
        self.assertNotIn("bias_ctrl", json.dumps(data))
        self.assertNotIn("17881857", json.dumps(data))

    def test_digests_track_actual_bytes_and_order_is_stable(self):
        first = self.extract()
        self.assertEqual(first, identity.extract_identity(self.root, list(reversed(self.files)), "app", "board"))
        source = first["placement"]["crate_id"]["source"]
        self.assertEqual(source["sha256"], hashlib.sha256((self.root / source["file"]).read_bytes()).hexdigest())
        with (self.root / self.files[0]).open("ab") as output:
            output.write(b"\n")
        second = identity.extract_identity(self.root, self.files, "app", "board")
        self.assertNotEqual(first["source_revision_sha256"], second["source_revision_sha256"])

    def test_wrong_or_unreferenced_board_rejected(self):
        obj(self.docs[0], "DaphneV2BoardConf", "unreferenced", [("crate_id", 4)])
        self.save()
        for name in ("wrong", "unreferenced"):
            with self.subTest(name=name), self.assertRaises(identity.IdentityError):
                identity.extract_identity(self.root, self.files, "app", name)

    def test_map_key_and_geo_placement_must_agree(self):
        for element, name, value in ((self.entry, "key", "8.3.1"), (self.geos[0], "slot_id", "2")):
            attr = self.attr(element, name)
            original = attr.get("val")
            attr.set("val", value)
            with self.subTest(name=name), self.assertRaises(identity.IdentityError):
                self.extract()
            attr.set("val", original)

    def test_all_sender_streams_with_wrong_placement_rejected(self):
        for geo in self.geos:
            self.attr(geo, "crate_id").set("val", "7")
        with self.assertRaises(identity.IdentityError):
            self.extract()

    def test_explicit_zero_is_not_missing(self):
        for element in [self.board, *self.geos]:
            self.attr(element, "slot_id").set("val", "0")
        self.attr(self.entry, "key").set("val", "8.4.0")
        self.assertEqual(self.extract()["placement"]["slot_id"]["value"], 0)

    def test_bad_uint_missing_and_duplicate_attributes(self):
        attr = self.attr(self.board, "crate_id")
        for value in ("-1", "4294967296", "1.0", "04", "", " 4", "0x4"):
            attr.set("val", value)
            with self.subTest(value=value), self.assertRaises(identity.IdentityError):
                self.extract()
        attr.set("val", "4")
        self.board.append(copy.deepcopy(attr))
        with self.assertRaises(identity.IdentityError):
            self.extract()
        self.board.remove(attr)
        self.board.remove(self.attr(self.board, "crate_id"))
        with self.assertRaises(identity.IdentityError):
            self.extract()

    def test_duplicate_objects_and_paths_rejected(self):
        self.docs[1].append(copy.deepcopy(self.board))
        with self.assertRaises(identity.IdentityError):
            self.extract()
        self.docs[1].remove(self.docs[1][-1])
        self.save()
        with self.assertRaises(identity.IdentityError):
            identity.ExplicitOks(self.root, self.files + [self.files[0]])

    def test_explicit_types_are_checked_without_schema_defaults(self):
        attr = self.attr(self.board, "crate_id")
        attr.set("type", "bool")
        with self.assertRaises(identity.IdentityError):
            self.extract()
        attr.set("type", "u8")
        attr.set("val", "256")
        with self.assertRaises(identity.IdentityError):
            self.extract()
        attr.set("type", "u16")
        attr.set("val", "4")
        self.extract()

    def test_bad_relationship_shapes(self):
        rel = self.sender.find("rel")
        for cls in ("Unknown", ""):
            rel.set("class", cls)
            with self.subTest(cls=cls), self.assertRaises(identity.IdentityError):
                self.extract()
        rel.set("class", "NetworkInterface")
        ET.SubElement(rel, "ref", {"class": "NetworkInterface", "id": "interface"})
        with self.assertRaises(identity.IdentityError):
            self.extract()

    def test_duplicate_stream_reference_rejected(self):
        streams = list(self.sender.findall("rel"))[1]
        streams.append(copy.deepcopy(streams[0]))
        with self.assertRaises(identity.IdentityError):
            self.extract()

    def test_mac_validation_and_error_redaction(self):
        attr = self.attr(self.interface, "mac_address")
        for value in ("secret-invalid", "00:00:00:00:00:00", "01:00:00:00:00:01", "ff:ff:ff:ff:ff:ff"):
            attr.set("val", value)
            with self.subTest(value=value), self.assertRaises(identity.IdentityError) as error:
                self.extract()
            self.assertNotIn(value, str(error.exception))

    def test_ipv4_validation_duplicates_and_list_shape(self):
        attr = self.attr(self.interface, "ip_address")
        for value in ("secret", "0.0.0.0", "224.0.0.1", "127.0.0.1", "255.255.255.255", "192.0.2.15/24", "2001:db8::15"):
            attr[0].set("val", value)
            with self.subTest(value=value), self.assertRaises(identity.IdentityError):
                self.extract()
        attr[0].set("val", "192.0.2.15")
        attr.append(copy.deepcopy(attr[0]))
        with self.assertRaises(identity.IdentityError):
            self.extract()
        attr.remove(attr[-1])
        attr.set("val", "192.0.2.15")
        with self.assertRaises(identity.IdentityError):
            self.extract()

    def test_multiple_ip_assignments_are_retained_not_guessed(self):
        ET.SubElement(self.attr(self.interface, "ip_address"), "data", {"val": "192.0.2.16"})
        values = self.extract()["hermes_interfaces"][0]["ip_addresses"]["value"]
        self.assertEqual(values, ["192.0.2.15", "192.0.2.16"])

    def test_management_hosts_reject_url_and_shell_syntax(self):
        attr = self.attr(self.board, "address")
        for value in ("tcp://board.example:40001", "board;echo-secret", "board.example/", "board.example..", "192.000.2.1"):
            attr.set("val", value)
            with self.subTest(value=value), self.assertRaises(identity.IdentityError):
                self.extract()

    def test_target_match_is_separate_dns_observation(self):
        data = self.extract()
        self.assertEqual(data["target_check"]["status"], "not_checked")
        identity.verify_target(data, "expected.example", lambda host: "192.0.2.22")
        self.assertEqual(data["target_check"]["status"], "matched")
        self.assertGreater(data["target_check"]["observed_host_unix_ns"], 0)
        self.assertEqual(data["management_address"]["value"], "board.example")
        with self.assertRaises(identity.IdentityError):
            identity.verify_target(data, "wrong.example", lambda host: "192.0.2.23" if host == "wrong.example" else "192.0.2.22")
        self.assertEqual(data["target_check"]["status"], "not_checked")

    def test_dns_errors_ambiguity_and_redaction(self):
        with patch.object(identity.socket, "getaddrinfo", side_effect=OSError("secret")):
            with self.assertRaises(identity.IdentityError) as error:
                identity.resolve_one_ipv4("board.example")
            self.assertNotIn("secret", str(error.exception))
        with patch.object(identity.socket, "getaddrinfo", return_value=[(0, 0, 0, 0, ("192.0.2.1", 0)), (0, 0, 0, 0, ("192.0.2.2", 0))]):
            with self.assertRaises(identity.IdentityError):
                identity.resolve_one_ipv4("board.example")

    def test_entities_invalid_xml_and_alternate_encoding_rejected(self):
        self.save()
        for content in (b"<!DOCTYPE oks-data [<!ENTITY x 'secret'>]><oks-data/>",
                        b"<invalid", "<oks-data/>".encode("utf-16"), b"<oks-schema/>"):
            (self.root / self.files[0]).write_bytes(content)
            with self.subTest(content=content), self.assertRaises(identity.IdentityError):
                identity.ExplicitOks(self.root, self.files)

    def test_size_limit_and_no_include_traversal(self):
        include = ET.SubElement(self.docs[0], "include")
        ET.SubElement(include, "file", {"path": "/must-not-read/schema.xml"})
        self.extract()  # Explicit-only: no external file access.
        with patch.object(identity, "MAX_FILE_BYTES", 32):
            with self.assertRaises(identity.IdentityError):
                identity.ExplicitOks(self.root, self.files)

    def test_path_escape_and_symlink_escape_rejected(self):
        self.save()
        with tempfile.TemporaryDirectory() as outside:
            path = Path(outside) / "outside.xml"
            path.write_text("<oks-data/>")
            (self.root / "escape.xml").symlink_to(path)
            for file in (str(path), "escape.xml"):
                with self.subTest(file=file), self.assertRaises(identity.IdentityError):
                    identity.ExplicitOks(self.root, [file])

    def test_private_output_is_exclusive_0600_and_cli_redacts(self):
        self.save()
        output = self.root / "identity.json"
        args = ["--root", str(self.root), "--segment-file", self.files[0],
                "--connections-file", self.files[1], "--senders-file", self.files[2],
                "--application-id", "app", "--board-object-id", "board", "--private-output", str(output)]
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            self.assertEqual(identity.main(args), 0)
        self.assertNotIn("192.0.2.15", stdout.getvalue())
        self.assertNotIn("02:aa:bb", stdout.getvalue())
        self.assertNotIn("board.example", stdout.getvalue())
        self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
        saved = output.read_bytes()
        with contextlib.redirect_stderr(stderr):
            self.assertEqual(identity.main(args), 1)
        self.assertEqual(output.read_bytes(), saved)
        self.assertNotIn(str(output), stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
