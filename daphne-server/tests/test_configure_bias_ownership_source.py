"""Source-wiring guards, not a simulated or physical Configure qualification.

The server's legacy Daphne/Dac constructors map hardware. These checks pin the
small ownership change at its real call site; live preservation is checked by
verify_aggregate_zero_bias against quality-checked AFE register observations.
"""
from pathlib import Path
import re
import unittest


class ConfigureBiasOwnershipSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (Path(__file__).resolve().parents[1] / "srcs" /
                      "server_controller" / "handlers.cpp").read_text()

    def body(self, start, end):
        self.assertEqual(self.source.count(start), 1)
        self.assertEqual(self.source.count(end), 1)
        body = self.source.split(start, 1)[1].split(end, 1)[0]
        self.assertTrue(body.strip().endswith("}"))
        # Strip comments, so the explanatory ownership comment is not a call.
        return re.sub(r"//[^\n]*|/\*.*?\*/", "", body, flags=re.DOTALL)

    def test_configure_programs_target_but_has_no_enable_access(self):
        body = self.body("bool configureDaphne(", "bool writeAFERegister(")
        self.assertEqual(body.count("setDacHvBias(ctrl, false, false)"), 1)
        self.assertIn("const uint32_t ctrl = requested_cfg.biasctrl();", body)
        self.assertIn("setBiasControlDictValue(ctrl)", body)
        for forbidden in ("setBiasEnable(", "biasEnable\"", "0x9400000C", "0x9400000c"):
            self.assertNotIn(forbidden, body)
        self.assertIn("BiasEnable not written (SC-owned)", body)
        self.assertNotIn("and Enable:", body)

    def test_explicit_enable_command_is_not_removed_or_forced(self):
        body = self.body("bool writeBiasVoltageControl(", "bool readAFEReg(")
        self.assertIn("const bool bias_enable = request.enable();", body)
        self.assertEqual(body.count("setBiasEnable(bias_enable)"), 1)
        self.assertNotIn("setBiasEnable(true)", body)
        self.assertNotIn("setBiasEnable(false)", body)


if __name__ == "__main__":
    unittest.main()
