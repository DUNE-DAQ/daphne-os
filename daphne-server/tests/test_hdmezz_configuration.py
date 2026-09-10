"""Independent low-level wire validation; no mezzanine hardware is accessed."""
import ast
import contextlib
import io
from pathlib import Path
import sys
import unittest
import daphneV3_low_level_confs_pb2 as low

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from hdmezz_configuration import check_configuration_readback


def fixture():
    r = low.cmd_readHDMezzBlockConfig_response(success=True, afeBlock=2,
        shunt_cal_5V=2000, shunt_cal_3V3=3000, block_enabled=True, driver_configured=True,
        requested_shunt_cal_5V=2000, requested_shunt_cal_3V3=3000,
        calibration_matches_requested=True, calibration_readback_quality=low.HDMEZZ_READBACK_GOOD,
        acquisition_started_monotonic_ns=100, observed_monotonic_ns=200,
        requested_settings_available=True)
    for field in ("r_shunt_5V", "r_shunt_3V3", "max_current_5V_scale", "max_current_3V3_scale",
                  "max_current_5V_shutdown", "max_current_3V3_shutdown", "max_power_5V",
                  "max_power_3V3", "current_lsb_5V", "current_lsb_3V3"):
        setattr(r, field, 0.1)
    return r


class HDMezzConfigurationTests(unittest.TestCase):
    def checked(self, r):
        return check_configuration_readback(type(r).FromString(r.SerializeToString()), low)

    def test_actual_and_requested_are_independent(self):
        r = fixture()
        self.assertTrue(self.checked(r)["calibration_matches_requested"])
        r.shunt_cal_5V = 0
        r.calibration_matches_requested = False
        report = self.checked(r)
        self.assertEqual(report["actual_calibration_5v_ce"], [0, 3000])
        self.assertEqual(report["requested_calibration_5v_ce"], [2000, 3000])
        self.assertFalse(report["calibration_matches_requested"])

    def test_legacy_codes_have_no_readback_provenance(self):
        r = low.cmd_readHDMezzBlockConfig_response(success=True, shunt_cal_5V=1234)
        report = self.checked(r)
        self.assertFalse(report["available"])
        self.assertEqual(report["quality"], "legacy-unqualified")
        self.assertNotIn("actual_calibration_5v_ce", report)

    def test_unavailable_driver_and_failure_do_not_invent_values(self):
        for quality in (low.HDMEZZ_READBACK_UNAVAILABLE, low.HDMEZZ_READBACK_ERROR,
                        low.HDMEZZ_READBACK_INVALID):
            r = low.cmd_readHDMezzBlockConfig_response(calibration_readback_quality=quality)
            report = self.checked(r)
            self.assertFalse(report["available"])
            self.assertIsNone(report["actual_calibration_5v_ce"])
            self.assertIsNone(report["requested_derived_settings"])
            r.shunt_cal_5V = 3
            with self.assertRaises(ValueError): self.checked(r)

    def test_bad_success_time_range_and_comparison_are_rejected(self):
        for field, value in (("success", False), ("block_enabled", False),
                             ("requested_settings_available", False), ("afeBlock", 5),
                             ("acquisition_started_monotonic_ns", 0), ("observed_monotonic_ns", 99),
                             ("observed_monotonic_ns", 100_000_101), ("shunt_cal_5V", -1),
                             ("shunt_cal_3V3", 32768), ("calibration_matches_requested", False),
                             ("r_shunt_5V", float("nan")), ("current_lsb_3V3", 0),
                             ("requested_shunt_cal_5V", 0), ("calibration_readback_quality", 999)):
            with self.subTest(field=field, value=value):
                r = fixture(); setattr(r, field, value)
                with self.assertRaises(ValueError): self.checked(r)
        r = fixture(); r.observed_monotonic_ns = 100_000_100
        self.assertTrue(self.checked(r)["available"])

    def test_cli_labels_readback_and_legacy_unavailability(self):
        # Exercise the real printing function without importing GUI/socket setup.
        source = ast.parse((ROOT / "client/hdmezz_control_v2.py").read_text())
        node = next(n for n in source.body if isinstance(n, ast.FunctionDef) and n.name == "print_config_response")
        namespace = {"pb_low": low, "check_configuration_readback": check_configuration_readback}
        exec(compile(ast.Module(body=[node], type_ignores=[]), "actual_client_renderer", "exec"), namespace)
        for r, expected in ((fixture(), "actual_shunt_cal_5V_CE=[2000, 3000]"),
                            (low.cmd_readHDMezzBlockConfig_response(success=True), "Actual calibration readback unavailable")):
            out = io.StringIO()
            with contextlib.redirect_stdout(out): namespace["print_config_response"](r)
            self.assertIn(expected, out.getvalue())

    def test_actual_handler_uses_one_readback_not_cache_getters(self):
        # Wiring guard, not a simulated whole-Daphne hardware handler execution.
        source = (ROOT / "srcs/server_controller/handlers.cpp").read_text()
        body = source.split("bool readHDMezzBlockConfig(", 1)[1].split("bool setHDMezzPowerStates(", 1)[0]
        self.assertEqual(body.count("readBlockConfiguration(afeBlock)"), 1)
        self.assertIn("fill_hdmezz_configuration(snapshot, response)", body)
        for forbidden in ("getShuntCal", "getRShunt", "enableAfeBlock(", "configureHdMezz", "checkAlertStatus("):
            self.assertNotIn(forbidden, body)


if __name__ == "__main__":
    unittest.main()
