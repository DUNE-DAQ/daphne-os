"""Wire/client/GUI-logic tests with generated bindings and local fakes; no board access."""
import ast
import contextlib
import io
import os
from pathlib import Path
import socket
import subprocess
import sys
from types import SimpleNamespace
import unittest

import zmq
import daphneV3_high_level_confs_pb2 as high
import daphneV3_low_level_confs_pb2 as low

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from hdmezz_status import check_monitoring_status, VALUE_FIELDS
from hdmezz_configuration import check_configuration_readback


def fixture():
    r = low.cmd_readHDMezzStatus_response(success=True, afeBlock=2,
        monitor_quality=low.HDMEZZ_MONITOR_GOOD, driver_state_available=True,
        block_enabled=True, driver_configured=True, acquisition_started_monotonic_ns=100,
        observed_monotonic_ns=200, state_observed_monotonic_ns=300,
        last_good_monotonic_ns=200, sample_attempt=7, active_configuration_verified=True,
        power_requests_off_confirmed=True)
    for name in VALUE_FIELDS:
        setattr(r, name, False if name.startswith("power") else 0)
    r.measured_voltage5V = 5.0; r.measured_voltage3V3 = 3.2; r.measured_current5V = -1.5
    for name, legacy, timestamp in (("alert_history_5V", "alert_5V", 130), ("alert_history_3V3", "alert_3V3", 140)):
        getattr(r, name).CopyFrom(low.HDMezzAlertHistory(mask_enable_raw=0x8001, observed_monotonic_ns=timestamp))
        setattr(r, legacy, False)
    return r


def unavailable(quality=low.HDMEZZ_MONITOR_UNAVAILABLE):
    r = fixture(); r.success = False; r.monitor_quality = quality
    for name in VALUE_FIELDS:
        r.ClearField(name)
    r.active_configuration_verified = r.power_requests_off_confirmed = False
    if quality == low.HDMEZZ_MONITOR_STALE:
        r.state_observed_monotonic_ns = r.observed_monotonic_ns + 5_000_000_001
    else:
        r.observed_monotonic_ns = 0
    r.alert_5V = r.alert_history_5V.software_latched = True
    r.alert_history_5V.mask_enable_raw = 0x8011
    r.protective_action_attempted = True
    return r


def actual_function(name, namespace=None):
    tree = ast.parse((ROOT / "client/hdmezz_control_v2.py").read_text())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    space = {"pb_low": low, "check_monitoring_status": check_monitoring_status,
             "check_configuration_readback": check_configuration_readback}
    space.update(namespace or {})
    exec(compile(ast.Module(body=[node], type_ignores=[]), "actual_client_function", "exec"), space)
    return space[name]


class MonitoringWireTests(unittest.TestCase):
    def checked(self, response, **kwargs):
        return check_monitoring_status(type(response).FromString(response.SerializeToString()), low, **kwargs)

    def test_zero_false_signed_values_and_original_field_contract(self):
        r = fixture(); report = self.checked(r, expected_afe=2)
        self.assertTrue(report["available"])
        self.assertEqual(report["values"]["measured_power5V"], 0)
        self.assertFalse(report["values"]["power5V"])
        self.assertEqual(report["values"]["measured_current5V"], -1.5)
        names = ["success", "message", "afeBlock", *VALUE_FIELDS, "alert_5V", "alert_3V3"]
        for number, name in enumerate(names, 1):
            f = r.DESCRIPTOR.fields_by_name[name]
            self.assertEqual(f.number, number)
            self.assertEqual(f.type, 9 if number == 2 else 13 if number == 3 else 2 if 6 <= number <= 11 else 8)
            if number >= 4: self.assertTrue(f.has_presence)

    def test_every_missing_value_and_bad_number_rejected(self):
        for name in VALUE_FIELDS:
            r = fixture(); r.ClearField(name)
            with self.subTest(missing=name), self.assertRaises(ValueError): self.checked(r)
        for name in VALUE_FIELDS[2:]:
            for value in (float("nan"), float("inf"), -float("inf")):
                r = fixture(); setattr(r, name, value)
                with self.subTest(field=name, value=value), self.assertRaises(ValueError): self.checked(r)
            if "current" not in name:
                r = fixture(); setattr(r, name, -1)
                with self.assertRaises(ValueError): self.checked(r)

    def test_failed_and_stale_samples_retain_history_not_values(self):
        for quality in (low.HDMEZZ_MONITOR_UNAVAILABLE, low.HDMEZZ_MONITOR_ERROR,
                        low.HDMEZZ_MONITOR_INVALID, low.HDMEZZ_MONITOR_STALE):
            r = unavailable(quality); report = self.checked(r)
            self.assertFalse(report["available"]); self.assertIsNone(report["values"])
            self.assertTrue(report["alerts"][0]["latched"])
            self.assertEqual(report["alerts"][0]["observed_monotonic_ns"], 130)
            for name in VALUE_FIELDS:
                bad = type(r)(); bad.CopyFrom(r); setattr(bad, name, 0)
                with self.subTest(quality=quality, field=name), self.assertRaises(ValueError): self.checked(bad)

    def test_missing_driver_and_legacy_never_produce_measurements(self):
        r = low.cmd_readHDMezzStatus_response(afeBlock=2, monitor_quality=low.HDMEZZ_MONITOR_UNAVAILABLE)
        report = self.checked(r)
        self.assertIsNone(report["driver_state"]); self.assertEqual(report["alerts"], [None, None])
        for name in ("block_enabled", "driver_configured", "state_observed_monotonic_ns"):
            bad = type(r)(); bad.CopyFrom(r); setattr(bad, name, 1)
            with self.assertRaises(ValueError): self.checked(bad)
        old = low.cmd_readHDMezzStatus_response(success=True, measured_voltage5V=5)
        self.assertEqual(self.checked(old)["quality"], "legacy-unqualified")
        self.assertIsNone(self.checked(old)["values"])

    def test_timestamp_state_success_and_quality_invariants(self):
        for field, value in (("success", False), ("monitor_quality", 999), ("afeBlock", 5),
                ("driver_state_available", False), ("block_enabled", False), ("driver_configured", False),
                ("sample_attempt", 0), ("acquisition_started_monotonic_ns", 0),
                ("observed_monotonic_ns", 99), ("observed_monotonic_ns", 100_000_101),
                ("last_good_monotonic_ns", 199), ("state_observed_monotonic_ns", 0),
                ("state_observed_monotonic_ns", 199), ("state_observed_monotonic_ns", 5_000_000_201),
                ("active_configuration_verified", False), ("power_requests_off_confirmed", False),
                ("protective_action_attempted", True)):
            r = fixture(); setattr(r, field, value)
            with self.subTest(field=field), self.assertRaises(ValueError): self.checked(r)
        with self.assertRaises(ValueError): self.checked(fixture(), expected_afe=1)
        r = unavailable(low.HDMEZZ_MONITOR_ERROR); r.observed_monotonic_ns = 200
        with self.assertRaises(ValueError): self.checked(r)
        r = unavailable(low.HDMEZZ_MONITOR_STALE); r.state_observed_monotonic_ns -= 1
        with self.assertRaises(ValueError): self.checked(r)

    def test_alert_presence_time_flags_and_retention(self):
        for fault in range(8):
            r = fixture()
            if fault == 0: r.ClearField("alert_5V")
            if fault == 1: r.ClearField("alert_history_5V")
            if fault == 2: r.alert_history_5V.mask_enable_raw = 0x10000
            if fault == 3: r.alert_history_5V.observed_monotonic_ns = 99
            if fault == 4: r.alert_history_3V3.observed_monotonic_ns = 120
            if fault == 5: r.alert_history_5V.mask_enable_raw |= 0x20
            if fault == 6: r.alert_history_5V.mask_enable_raw |= 0x10
            if fault == 7: r.alert_5V = True
            with self.subTest(fault=fault), self.assertRaises(ValueError): self.checked(r)
        r = unavailable(low.HDMEZZ_MONITOR_ERROR)
        r.alert_history_5V.observed_monotonic_ns = 0
        r.ClearField("alert_history_3V3"); r.ClearField("alert_3V3")
        report = self.checked(r)
        self.assertTrue(report["alerts"][0]["latched"]); self.assertIsNone(report["alerts"][1])
        r.alert_history_5V.mask_enable_raw = 0x8001 # A later explicit read may retain the software latch.
        self.assertTrue(self.checked(r)["alerts"][0]["latched"])

    def test_fresh_alert_requires_attempt_and_off_request_readback(self):
        r = fixture(); r.alert_5V = r.alert_history_5V.software_latched = True
        r.alert_history_5V.mask_enable_raw = 0x8011; r.protective_action_attempted = True
        self.assertTrue(self.checked(r)["available"])
        r.power5V = True; r.power_requests_off_confirmed = False
        with self.assertRaises(ValueError): self.checked(r)

    def test_inclusive_boundaries_and_conservative_network_age(self):
        r = fixture(); r.observed_monotonic_ns = r.last_good_monotonic_ns = 100_000_100
        r.state_observed_monotonic_ns = r.observed_monotonic_ns + 5_000_000_000
        self.assertTrue(self.checked(r)["available"])
        report = self.checked(r, roundtrip_ns=1)
        self.assertFalse(report["available"]); self.assertIsNone(report["values"])
        self.assertEqual(report["quality"], "CLIENT_STALE")
        for duration in (-1, 0.1):
            with self.assertRaises(ValueError): self.checked(r, roundtrip_ns=duration)

    def test_actual_cli_renderer_does_not_print_unqualified_values(self):
        render = actual_function("print_status_response")
        for r, accepted in ((fixture(), True), (unavailable(), False),
                            (unavailable(low.HDMEZZ_MONITOR_STALE), False),
                            (low.cmd_readHDMezzStatus_response(success=True, afeBlock=2), False)):
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream): result = render(r, expected_afe=2)
            self.assertEqual(result, accepted)
            if accepted:
                self.assertIn("measured_current5V=-1.500000 mA", stream.getvalue())
            else:
                self.assertNotIn("measured_voltage", stream.getvalue())
                self.assertNotIn("requested_power", stream.getvalue())
        r = fixture(); r.measured_power5V = float("nan")
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream): self.assertFalse(render(r))
        self.assertIn("rejected", stream.getvalue()); self.assertNotIn("measured_voltage", stream.getvalue())

    def test_config_renderer_masks_missing_settings_and_bad_readback(self):
        render = actual_function("print_config_response")
        r = low.cmd_readHDMezzBlockConfig_response(calibration_readback_quality=low.HDMEZZ_READBACK_UNAVAILABLE)
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream): self.assertFalse(render(r))
        self.assertIn("settings unavailable", stream.getvalue())
        self.assertNotIn("r_shunt_", stream.getvalue())
        self.assertNotIn("current_lsb_", stream.getvalue())

    def test_source_wiring_uses_cache_and_retains_protective_runtime_invalidation(self):
        # Source guard complements executed driver/protobuf tests; not whole-Daphne hardware execution.
        handlers = (ROOT / "srcs/server_controller/handlers.cpp").read_text()
        body = handlers.split("bool readHDMezzStatus(", 1)[1].split("bool clearHDMezzAlertFlag(", 1)[0]
        self.assertEqual(body.count("monitoringSnapshot(afeBlock)"), 1)
        self.assertIn("fill_hdmezz_status(snapshot, response)", body)
        for forbidden in ("I2C2BusGuard", "pollMonitoring(", "readRail", "checkAlertStatus(", "setPowerRequests("):
            self.assertNotIn(forbidden, body)
        monitor = (ROOT / "srcs/server_controller/monitoring.cpp").read_text()
        body = monitor.split("void i2c_2_monitor_thread(", 1)[1].split("void i2c_1_monitor_thread(", 1)[0]
        self.assertIn("hd->pollMonitoring(i)", body)
        self.assertIn('runtime->invalidate("Mezzanine alert observed;', body)
        self.assertNotIn("setPowerRequests(", body)
        for path in ("srcs/Daphne.hpp", "srcs/Daphne.cpp", "srcs/server_controller/handlers.cpp", "srcs/server_controller/monitoring.cpp"):
            self.assertNotIn("HDMezz_5V_voltage", (ROOT / path).read_text())
        clear = handlers.split("bool clearHDMezzAlertFlag(", 1)[1].split("template <", 1)[0]
        self.assertIn("clearCachedAlerts(afeBlock)", clear)


class Widget:
    def __init__(self): self.value = None; self.text = ""; self.samples = []; self.tooltip = ""
    def set_value(self, value): self.value = value
    def set_on(self, value): self.value = value
    def setText(self, value): self.text = value
    def setToolTip(self, value): self.tooltip = value
    def append_values(self, values): self.samples.append(values)
    def clear_values(self): self.samples.clear()


class MonitoringGuiLogicTests(unittest.TestCase):
    def panel(self):
        # Execute the actual GUI methods with recording widgets; no Qt event-loop/rendering claim.
        tree = ast.parse((ROOT / "client/hdmezz_control_v2.py").read_text())
        visual = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run_visual")
        panel = next(n for n in visual.body if isinstance(n, ast.ClassDef) and n.name == "AFEPanel")
        selected = [n for n in panel.body if isinstance(n, ast.FunctionDef) and n.name in
                    ("_clear_measurements", "_show_status_report", "_expire_display", "read_status",
                     "_run", "apply_enable", "apply_power")]
        self.clock = SimpleNamespace(value=1.0)
        space = {"time": SimpleNamespace(monotonic=lambda: self.clock.value),
                 "check_monitoring_status": check_monitoring_status, "pb_low": low,
                 "QtWidgets": SimpleNamespace(QApplication=SimpleNamespace(
                     setOverrideCursor=lambda _: None, restoreOverrideCursor=lambda: None)),
                 "QtCore": SimpleNamespace(Qt=SimpleNamespace(CursorShape=SimpleNamespace(BusyCursor=0)))}
        exec(compile(ast.Module(body=selected, type_ignores=[]), "actual_gui_methods", "exec"), space)
        p = SimpleNamespace(last_sample_key=None, sample_expires_at=None, afe=2, log=lambda _: None,
                            client=SimpleNamespace(last_status_roundtrip_ns=0))
        for name in ("power_5v_lamp", "power_3v3_lamp", "alert_5v_lamp", "alert_3v3_lamp", "v5_display",
                     "v3_display", "i5_display", "i3_display", "p5_display", "p3_display",
                     "voltage_graph", "current_graph", "power_graph", "sample_quality_label"):
            setattr(p, name, Widget())
        for node in selected: setattr(p, node.name, lambda *a, _fn=space[node.name], **kw: _fn(p, *a, **kw))
        return p

    def test_success_failure_stale_and_history_do_not_change_commands(self):
        p = self.panel() # No command checkboxes/client mutators exist: touching them fails the test.
        p._show_status_report(check_monitoring_status(fixture(), low))
        self.assertEqual(p.v5_display.value, 5)
        self.assertEqual(len(p.voltage_graph.samples), 1)
        p._show_status_report(check_monitoring_status(fixture(), low))
        self.assertEqual(len(p.voltage_graph.samples), 1, "cached sample was graphed as a new acquisition")
        p._show_status_report(check_monitoring_status(unavailable(low.HDMEZZ_MONITOR_ERROR), low))
        self.assertIsNone(p.v5_display.value); self.assertIsNone(p.power_5v_lamp.value)
        self.assertTrue(p.alert_5v_lamp.value); self.assertIn("130", p.alert_5v_lamp.tooltip)
        self.assertEqual(p.voltage_graph.samples, [])
        p._show_status_report(None)
        self.assertIsNone(p.alert_5v_lamp.value); self.assertIsNone(p.i3_display.value)

    def test_local_expiry_clears_measurements_not_history_without_rpc(self):
        p = self.panel(); r = fixture()
        r.state_observed_monotonic_ns = r.observed_monotonic_ns + 4_000_000_000
        p._show_status_report(check_monitoring_status(r, low))
        self.assertEqual(p.sample_expires_at, 2.0)
        self.clock.value = 2.0; p._expire_display()
        self.assertEqual(p.v5_display.value, 5)
        self.clock.value = 2.001; p._expire_display()
        self.assertIsNone(p.v5_display.value); self.assertIn("LOCAL_STALE", p.sample_quality_label.text)
        self.assertFalse(p.alert_5v_lamp.value)

    def test_actual_poll_rejects_bad_reply_and_transport_loss(self):
        p = self.panel(); p._show_status_report(check_monitoring_status(fixture(), low))
        r = fixture(); r.ClearField("measured_voltage5V")
        p._read_status_silent = lambda: r
        p.read_status(log_result=False)
        self.assertIsNone(p.v5_display.value)
        p._read_status_silent = lambda: None
        p.read_status(log_result=False)
        self.assertIsNone(p.power_5v_lamp.value)

    def test_failed_commands_invalidate_display_without_overwriting_pending_values(self):
        p = self.panel()
        changes = []
        control = lambda: SimpleNamespace(isChecked=lambda: True, setChecked=changes.append)
        p.enable_check = control(); p.power_5v = control(); p.power_3v3 = control()
        calls = []
        def fail_enable(afe, enable):
            self.assertIsNone(p.v5_display.value) # Cleared before the command could mutate hardware.
            calls.append((afe, enable))
            return low.cmd_setHDMezzBlockEnable_response(success=False, afeBlock=afe)
        def fail_power(afe, **kwargs):
            self.assertIsNone(p.v5_display.value)
            calls.append((afe, kwargs))
            return low.cmd_setHDMezzPowerStates_response(success=False, afeBlock=afe)
        p.client.set_block_enable = fail_enable; p.client.set_power_states = fail_power
        p._show_status_report(check_monitoring_status(fixture(), low)); p.apply_enable()
        p._show_status_report(check_monitoring_status(fixture(), low)); p.apply_power()
        self.assertEqual(len(calls), 2); self.assertEqual(changes, [])


class MonitoringCliTests(unittest.TestCase):
    def exercise(self, response):
        context = zmq.Context(); router = context.socket(zmq.ROUTER)
        router.setsockopt(zmq.LINGER, 0); router.setsockopt(zmq.RCVTIMEO, 4500)
        port = router.bind_to_random_port("tcp://127.0.0.1")
        env = {**os.environ, "DAPHNE_BUILD_DIR": str(Path(low.__file__).resolve().parents[2])}
        child = subprocess.Popen([sys.executable, str(ROOT / "client/hdmezz_control_v2.py"),
            "read-status", "--afe", "2", "--port", str(port), "--timeout", "3000"],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            peer, raw = router.recv_multipart()
            request = high.ControlEnvelopeV2.FromString(raw)
            self.assertEqual(request.type, high.MT2_READ_HDMEZZ_STATUS_REQ)
            self.assertEqual(low.cmd_readHDMezzStatus.FromString(request.payload).afeBlock, 2)
            reply = high.ControlEnvelopeV2(version=2, dir=high.DIR_RESPONSE,
                type=high.MT2_READ_HDMEZZ_STATUS_RESP, correl_id=request.msg_id,
                payload=response.SerializeToString())
            router.send_multipart([peer, reply.SerializeToString()])
            out, err = child.communicate(timeout=10)
            self.assertFalse(err, err)
            router.setsockopt(zmq.RCVTIMEO, 30)
            with self.assertRaises(zmq.Again): router.recv_multipart() # No fallback enable/configuration/write.
            return child.returncode, out
        finally:
            if child.poll() is None: child.kill(); child.communicate(timeout=5)
            router.close(); context.term()

    def test_cli_good_signed_and_zero_values(self):
        code, output = self.exercise(fixture())
        self.assertEqual(code, 0, output)
        self.assertIn("measured_current5V=-1.500000 mA", output)
        self.assertIn("requested_power5V=0", output)

    def test_cli_unavailable_stale_legacy_and_inconsistent_are_nonzero(self):
        bad = fixture(); bad.ClearField("power5V")
        wrong_block = fixture(); wrong_block.afeBlock = 1
        for r in (unavailable(), unavailable(low.HDMEZZ_MONITOR_STALE), bad, wrong_block,
                  low.cmd_readHDMezzStatus_response(success=True, afeBlock=2)):
            code, output = self.exercise(r)
            self.assertEqual(code, 2, output)
            self.assertNotIn("measured_voltage", output); self.assertNotIn("requested_power", output)

    def test_cli_timeout_never_prints_measurements(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0)); listener.listen(1)
            result = subprocess.run([sys.executable, str(ROOT / "client/hdmezz_control_v2.py"),
                "read-status", "--afe", "2", "--port", str(listener.getsockname()[1]), "--timeout", "50"],
                env={**os.environ, "DAPHNE_BUILD_DIR": str(Path(low.__file__).resolve().parents[2])},
                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("[timeout]", result.stdout); self.assertNotIn("measured_", result.stdout)


if __name__ == "__main__":
    unittest.main()
