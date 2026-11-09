"""Check the scan's bias/TRIM RPC ordering without hardware."""

import itertools
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "client"))
import protobuf_vgain_bias as scan


class FakeAfe:
    timeout_ms = 1000

    def __init__(self, high):
        self.high = high
        self.bias = 0
        self.trims = [0] * 8
        self.writes = []
        self.fail_clear = False
        self.fail_channel = None
        self.frozen_monitor = None
        self.fail_monitor = False
        self.bias_readback = None

    def rpc(self, request_type, request, response_type, response_class):
        op = self.high.MessageTypeV2.Name(request_type)
        response = response_class(success=True)
        if op == "MT2_READ_AFE_BIAS_SET_REQ":
            response.biasValue = self.bias if self.bias_readback is None else self.bias_readback
        elif op == "MT2_READ_TRIM_ALL_AFE_REQ":
            response.trimValues.extend(self.trims)
        elif op == "MT2_READ_BIAS_VOLTAGE_MONITOR_REQ":
            if self.fail_monitor:
                raise TimeoutError("monitor timeout")
            response.biasVoltageValue = (round(self.bias * scan.BIAS_MV_PER_CODE)
                                         if self.frozen_monitor is None else self.frozen_monitor)
        elif op == "MT2_WRITE_VBIAS_CONTROL_REQ":
            response.vBiasControlValue = request.vBiasControlValue
        elif op == "MT2_WRITE_AFE_BIAS_SET_REQ":
            self.bias = response.biasValue = request.biasValue
            self.writes.append(("bias", self.bias))
        elif op == "MT2_WRITE_TRIM_ALL_AFE_REQ":
            self.writes.append(("clear", request.trimValue))
            if self.fail_clear:
                raise TimeoutError("TRIM clear timeout")
            self.trims[:] = [request.trimValue] * 8
        elif op == "MT2_WRITE_TRIM_CH_REQ":
            channel = response.trimChannel = request.trimChannel
            self.writes.append(("trim", channel, request.trimValue))
            if self.fail_channel == channel:
                raise TimeoutError("channel TRIM timeout")
            self.trims[channel % 8] = response.trimValue = request.trimValue
        else:
            raise AssertionError(f"unexpected RPC {op}")
        if "afeBlock" in response.DESCRIPTOR.fields_by_name:
            response.afeBlock = request.afeBlock
        return response


class VgainBiasTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.state = Path(temporary.name) / ".bias_trim_state.json"
        self.high, self.low = scan.load_protobuf_modules()
        self.afe = FakeAfe(self.high)
        self.sequence = self.new_sequence()
        sleeper = patch.object(scan.time, "sleep")
        sleeper.start()
        self.addCleanup(sleeper.stop)

    def new_sequence(self, window=(10000, 30000), allow_unmonitored_bias=False):
        return scan.AfeBiasSequence(self.afe, self.high, self.low, 1, window, self.state,
                                    allow_unmonitored_bias=allow_unmonitored_bias)

    def test_bias_precedes_positional_trim_and_dynamic_shutdown(self):
        self.sequence.apply(700, 740, {8: 100, 9: 200, 11: 300, 13: 1500})
        self.assertEqual(self.afe.trims, [100, 200, 0, 300, 0, 1500, 0, 0])
        self.sequence.shutdown()
        self.assertEqual(self.afe.writes, [
            ("clear", 0), ("bias", 700), ("trim", 8, 100), ("trim", 9, 200),
            ("trim", 11, 300), ("trim", 13, 1500), ("bias", 661), ("clear", 0), ("bias", 0),
        ])
        self.assertFalse(self.state.exists())

    def test_timeout_clearing_trim_blocks_bias_zero_and_retry_reuses_target(self):
        self.sequence.apply(700, 740, {8: 1500})
        self.afe.fail_clear = True
        with self.assertRaisesRegex(TimeoutError, "TRIM clear timeout"):
            self.sequence.shutdown()
        self.assertNotIn(("bias", 0), self.afe.writes)
        self.assertTrue(self.state.exists())

        self.afe.fail_clear = False
        self.new_sequence().shutdown()
        self.assertEqual([write[1] for write in self.afe.writes if write[0] == "bias"], [700, 661, 0])

    def test_cleanup_uses_possible_trim_when_write_times_out(self):
        self.afe.fail_channel = 9
        with self.assertRaisesRegex(TimeoutError, "channel TRIM timeout"):
            self.sequence.apply(700, 740, {8: 100, 9: 1500})
        self.assertEqual(max(self.afe.trims), 100)
        self.new_sequence().shutdown()
        self.assertEqual(self.afe.writes[-3:], [("bias", 661), ("clear", 0), ("bias", 0)])

    def test_unsettled_transition_blocks_trim_clear_and_bias_zero(self):
        self.sequence.apply(700, 740, {8: 1500})
        self.afe.frozen_monitor = round(self.afe.bias * scan.BIAS_MV_PER_CODE)
        with patch.object(scan.time, "monotonic", side_effect=itertools.count(step=0.1)):
            with self.assertRaisesRegex(RuntimeError, "did not settle"):
                self.sequence.shutdown()
        self.assertEqual(self.afe.writes[-1], ("bias", 661))
        self.assertEqual(self.afe.trims[0], 1500)

    def test_unsettled_initial_bias_blocks_nonzero_trim(self):
        self.afe.frozen_monitor = 0
        with patch.object(scan.time, "monotonic", side_effect=itertools.count(step=0.1)):
            with self.assertRaisesRegex(RuntimeError, "did not settle"):
                self.sequence.apply(700, 740, {8: 1500})
        self.assertEqual(self.afe.writes, [("clear", 0), ("bias", 700)])
        self.assertFalse(self.state.exists())

    def test_unsafe_bias_plan_fails_before_writing(self):
        with self.assertRaisesRegex(ValueError, "outside the configured window"):
            self.new_sequence(window=(25000, 30000)).apply(700, 740, {8: 1500})
        self.assertEqual(self.afe.writes, [])

    def test_unmonitored_scan_uses_dac_readback_for_bias_and_shutdown(self):
        self.afe.fail_monitor = True
        sequence = self.new_sequence(allow_unmonitored_bias=True)
        sequence.apply(700, 740, {8: 100, 9: 1500})
        self.assertEqual(self.afe.trims, [100, 1500, 0, 0, 0, 0, 0, 0])
        sequence.shutdown()
        self.assertEqual(self.afe.writes[-3:], [("bias", 661), ("clear", 0), ("bias", 0)])

    def test_unmonitored_scan_blocks_trim_on_setpoint_mismatch(self):
        self.afe.fail_monitor = True
        self.afe.bias_readback = 699
        with self.assertRaisesRegex(RuntimeError, "readback did not match DAC 700"):
            self.new_sequence(allow_unmonitored_bias=True).apply(700, 740, {8: 1500})
        self.assertEqual(self.afe.writes, [("clear", 0), ("bias", 700)])


if __name__ == "__main__":
    unittest.main()
