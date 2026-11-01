"""Hardware-free interlock and real POSIX transport tests using a fake USB tty."""

import contextlib
import io
import os
import threading
import unittest
from unittest.mock import patch

from scripts.remote import rs_pro_ips3303s as rs


class InterlockTests(unittest.TestCase):
    def test_captured_status_and_all_modes(self):
        state = rs.parse_status(b"00011010\r\n")
        self.assertEqual(state["mode"], "independent")
        self.assertFalse(state["output_enabled"])
        self.assertEqual(state["baud"], 9600)
        self.assertTrue(rs.parse_status(b"11011110\r\n")["output_enabled"])
        self.assertEqual(rs.parse_status(b"00111010\r\n")["mode"], "series")
        self.assertEqual(rs.parse_status(b"00101010\r\n")["mode"], "parallel")

    def test_bad_status_fails_closed(self):
        for raw in (b"", b"0001101", b"00011010", b"00011010\n", b"0001101x\r\n",
                    b"00001010\r\n", b"00011000\r\n", b"00011001\r\n", b"\x1a\r\n"):
            with self.subTest(raw=raw), self.assertRaises(rs.SupplyError):
                rs.parse_status(raw)

    def test_on_then_measure_then_off(self):
        fake = rs.SimulatedTransport()
        supply = rs.Supply(fake)
        enabled = supply.run("on")["result"]
        self.assertTrue(enabled["status"]["output_enabled"])
        self.assertEqual(supply.run("measure")["result"]["1"]["voltage_V"], "23.998")
        self.assertEqual(supply.run("measure")["result"]["2"]["current_A"], "0.460")
        self.assertFalse(supply.run("off")["result"]["output_enabled"])
        self.assertEqual([x for x in fake.history if not x.endswith("?")], ["OUT1", "OUT0"])

    def test_each_channel_must_have_exact_setpoints(self):
        for command, unit, bad in (("VSET1?", "V", "23.999"), ("VSET2?", "V", "24.001"),
                                   ("ISET1?", "A", "0.999"), ("ISET2?", "A", "1.001")):
            with self.subTest(command=command):
                fake = rs.SimulatedTransport()
                fake.values[command] = (bad + unit + "\r\n").encode()
                with self.assertRaises(rs.SupplyError):
                    rs.Supply(fake).run("on")
                self.assertNotIn("OUT1", fake.history)
                self.assertFalse(fake.enabled)

    def test_non_independent_modes_block_on(self):
        for mode in ("series", "parallel"):
            with self.subTest(mode=mode):
                fake = rs.SimulatedTransport()
                fake.mode = mode
                with self.assertRaises(rs.SupplyError):
                    rs.Supply(fake).run("on")
                self.assertNotIn("OUT1", fake.history)

    def test_invalid_and_missing_values_block_on(self):
        for reply in (b"", b"NaNV\r\n", b"InfinityV\r\n", b"24.000A\r\n",
                      b"24.000V", b"24.000V\r\n24.000V\r\n", b"-24.000V\r\n"):
            with self.subTest(reply=reply):
                fake = rs.SimulatedTransport()
                fake.values["VSET1?"] = reply
                with self.assertRaises(rs.SupplyError):
                    rs.Supply(fake).run("on")
                self.assertNotIn("OUT1", fake.history)

    def test_wrong_identity_or_firmware_prevents_writes(self):
        for token, replacement in ((b"RS PRO", b"OTHER"), (b"IPS-3303S", b"IPS-3303D"),
                                   (b"V2.10", b"V2.11"), (b"SN:725D240G2", b"SN:000000000")):
            for action in ("on", "off"):
                with self.subTest(replacement=replacement, action=action):
                    fake = rs.SimulatedTransport()
                    original = fake.query
                    def query(command):
                        result = original(command)
                        if command == "*IDN?":
                            return result.replace(token, replacement)
                        return result
                    fake.query = query
                    with self.assertRaises(rs.SupplyError):
                        rs.Supply(fake).run(action)
                    self.assertFalse(any(x in fake.history for x in ("OUT0", "OUT1")))

    def test_read_actions_never_write(self):
        for action in ("config", "status", "measure"):
            with self.subTest(action=action):
                fake = rs.SimulatedTransport()
                rs.Supply(fake).run(action)
                self.assertTrue(all(x.endswith("?") for x in fake.history))

    def test_shutdown_does_not_require_safe_setpoints(self):
        fake = rs.SimulatedTransport()
        fake.enabled = True
        fake.mode = "parallel"
        fake.values["VSET1?"] = b"30.000V\r\n"
        rs.Supply(fake).run("off")
        self.assertFalse(fake.enabled)
        self.assertIn("OUT0", fake.history)
        self.assertNotIn("VSET1?", fake.history)

    def test_changing_settings_in_second_check_blocks_on(self):
        fake = rs.SimulatedTransport()
        original = fake.query
        def query(command):
            if command == "VSET2?" and fake.history.count(command) == 1:
                fake.values[command] = b"30.000V\r\n"
            return original(command)
        fake.query = query
        with self.assertRaises(rs.SupplyError):
            rs.Supply(fake).run("on")
        self.assertNotIn("OUT1", fake.history)

    def test_changing_mode_during_snapshot_aborts(self):
        fake = rs.SimulatedTransport()
        original = fake.query
        def query(command):
            if command == "ISET2?":
                fake.mode = "series"
            return original(command)
        fake.query = query
        with self.assertRaises(rs.SupplyError):
            rs.Supply(fake).run("on")
        self.assertNotIn("OUT1", fake.history)

    def test_failure_after_out1_requests_off_and_never_retries_on(self):
        for failure in ("timeout", "bad-setpoint", "not-enabled", "write-timeout"):
            with self.subTest(failure=failure):
                fake = rs.SimulatedTransport()
                original_query, original_write = fake.query, fake.write_output
                def query(command):
                    if "OUT1" in fake.history:
                        if failure == "timeout":
                            raise rs.SupplyError("timeout")
                        if failure == "bad-setpoint":
                            fake.values["VSET1?"] = b"30.000V\r\n"
                        if failure == "not-enabled":
                            fake.enabled = False
                    return original_query(command)
                def write(enabled):
                    original_write(enabled)
                    if enabled and failure == "write-timeout":
                        raise rs.SupplyError("write timeout")
                fake.query, fake.write_output = query, write
                with self.assertRaises(rs.SupplyError):
                    rs.Supply(fake).run("on")
                self.assertEqual(fake.history.count("OUT1"), 1)
                self.assertEqual(fake.history.count("OUT0"), 1)
                self.assertFalse(fake.enabled)

    def test_off_requires_confirmation(self):
        fake = rs.SimulatedTransport()
        fake.enabled = True
        fake.write_output = lambda enabled: None
        with self.assertRaises(rs.SupplyError):
            rs.Supply(fake).run("off")

    def test_cli_simulation_never_opens_hardware(self):
        for command in ("on", "off", "config", "status", "measure"):
            with self.subTest(command=command), patch.object(rs, "open_serial") as serial:
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(rs.main([command, "--simulate"]), 0)
                serial.assert_not_called()
                self.assertIn('"simulation": true', output.getvalue())

    def test_cli_unsafe_enable_returns_failure(self):
        fake = rs.SimulatedTransport()
        fake.mode = "series"
        with patch.object(rs, "SimulatedTransport", return_value=fake):
            with contextlib.redirect_stderr(io.StringIO()) as error:
                self.assertEqual(rs.main(["on", "--simulate"]), 1)
            self.assertIn("bloqueado", error.getvalue())
        self.assertNotIn("OUT1", fake.history)


@unittest.skipUnless(os.name == "posix", "POSIX pseudo terminals required")
class WireTests(unittest.TestCase):
    def test_production_transport_against_independent_tty_emulator(self):
        import pty
        import select

        master, slave = pty.openpty()
        path = os.ttyname(slave)
        stop = threading.Event()
        wire = []
        errors = []
        enabled = False
        def emulate():
            nonlocal enabled
            buffer = b""
            try:
                while not stop.is_set():
                    if not select.select([master], [], [], 0.05)[0]:
                        continue
                    buffer += os.read(master, 256)
                    while b"\r" in buffer or b"\n" in buffer:
                        end = min(i for i, byte in enumerate(buffer) if byte in (10, 13))
                        command, buffer = buffer[:end + 1], buffer[end + 1:]
                        wire.append(command)
                        if command in (b"OUT1\n", b"OUT0\n"):
                            enabled = command == b"OUT1\n"
                            continue
                        replies = {
                            b"*IDN?\r": b"RS PRO  ,IPS-3303S,SN:725D240G2,V2.10\r\n",
                            b"STATUS?\r": b"11011110\r\n" if enabled else b"00011010\r\n",
                            b"VSET1?\r": b"24.000V\r\n", b"VSET2?\r": b"24.000V\r\n",
                            b"ISET1?\r": b"1.000A\r\n", b"ISET2?\r": b"1.000A\r\n",
                            b"VOUT1?\r": b"23.999V\r\n", b"VOUT2?\r": b"24.001V\r\n",
                            b"IOUT1?\r": b"0.460A\r\n", b"IOUT2?\r": b"0.461A\r\n",
                        }
                        reply = replies[command]
                        # Fragment real reads, including the CRLF delimiter.
                        os.write(master, reply[:-1])
                        os.write(master, reply[-1:])
            except Exception as error:
                errors.append(error)
        worker = threading.Thread(target=emulate, daemon=True)
        worker.start()
        try:
            with rs.open_serial(path) as transport:
                supply = rs.Supply(transport)
                self.assertEqual(supply.run("config")["result"]["status"]["mode"], "independent")
                self.assertTrue(supply.run("on")["result"]["status"]["output_enabled"])
                self.assertEqual(supply.run("measure")["result"]["2"]["voltage_V"], "24.001")
                self.assertFalse(supply.run("off")["result"]["output_enabled"])
                self.assertFalse(supply.run("status")["result"]["output_enabled"])
        finally:
            stop.set()
            worker.join(2)
            os.close(slave)
            os.close(master)
        self.assertFalse(errors, errors)
        self.assertEqual([x for x in wire if not x.endswith(b"?\r")], [b"OUT1\n", b"OUT0\n"])

    def test_partial_reply_times_out_without_retry(self):
        import pty

        master, slave = pty.openpty()
        try:
            with rs.open_serial(os.ttyname(slave)) as transport:
                transport.timeout = 0.1
                os.write(master, b"24.000V")
                with self.assertRaises(rs.SupplyError):
                    transport.query("VSET1?")
                self.assertEqual(os.read(master, 256), b"VSET1?\r")
        finally:
            os.close(slave)
            os.close(master)


if __name__ == "__main__":
    unittest.main()
