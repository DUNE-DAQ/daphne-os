#!/usr/bin/env python3

from pathlib import Path
import contextlib
import io
import sys
import types
import unittest
from unittest.mock import patch


class _Again(Exception):
    pass


class _ZmqError(Exception):
    pass


sys.modules["zmq"] = types.SimpleNamespace(
    Again=_Again,
    ZMQError=_ZmqError,
    DEALER=1,
    IDENTITY=2,
    LINGER=3,
    RCVTIMEO=4,
    SNDTIMEO=5,
    RCVMORE=6,
)


CLIENT_DIR = Path(__file__).resolve().parents[1] / "client"
sys.path.insert(0, str(CLIENT_DIR))

import protobuf_configure_pedestal_level as pedestal  # noqa: E402
from protobuf_configure_pedestal_level import (  # noqa: E402
    ADC_MAX,
    INITIAL_OFFSET,
    PEDESTAL_WAVEFORMS,
    _read_current_offsets,
    _measure_pedestals,
    _verify_configured_offsets,
    _write_offset,
    build_parser,
    calibrate_pedestals,
    calibrate_pedestals_auto,
    parse_channels,
    pedestal_levels,
)


class _SimulatedHardware:
    def __init__(self, transfer_functions):
        self.transfer_functions = transfer_functions
        self.offsets = {}
        self.writes = {channel: [] for channel in transfer_functions}
        self.measurements = []

    def write_offset(self, channel, offset):
        self.offsets[channel] = offset
        self.writes[channel].append(offset)

    def measure(self, channels):
        self.measurements.append(
            {channel: self.offsets[channel] for channel in channels}
        )
        return {
            channel: self.transfer_functions[channel](self.offsets[channel])
            for channel in channels
        }


class _DumpRequest:
    def __init__(self):
        self.channelList = []
        self.numberOfWaveforms = 0
        self.numberOfSamples = 0
        self.softwareTrigger = False


class _DumpResponse:
    pass


class _FakeHighProto:
    MT2_DUMP_SPYBUFFER_REQ = 100
    MT2_DUMP_SPYBUFFER_RESP = 101
    DumpSpyBuffersRequest = _DumpRequest
    DumpSpyBuffersResponse = _DumpResponse


class _AcquisitionClient:
    def rpc(self, request_type, request, response_type, response_class):
        if request_type != _FakeHighProto.MT2_DUMP_SPYBUFFER_REQ:
            raise AssertionError("unexpected request type")
        if response_type != _FakeHighProto.MT2_DUMP_SPYBUFFER_RESP:
            raise AssertionError("unexpected response type")
        if response_class is not _DumpResponse:
            raise AssertionError("unexpected response class")
        if request.numberOfWaveforms != PEDESTAL_WAVEFORMS:
            raise AssertionError("client did not request exactly 500 waveforms")
        if not request.softwareTrigger:
            raise AssertionError("client did not request software triggers")

        response = _DumpResponse()
        response.success = True
        response.message = "OK"
        response.channelList = list(request.channelList)
        response.numberOfWaveforms = request.numberOfWaveforms
        response.numberOfSamples = request.numberOfSamples
        response.softwareTrigger = request.softwareTrigger
        one_waveform = [100, 100, 200, 300, 400, 400]
        response.data = one_waveform * PEDESTAL_WAVEFORMS
        return response


class _OffsetReadRequest:
    pass


class _OffsetReadResponse:
    pass


class _FakeLowProto:
    cmd_readOffset_allChannels = _OffsetReadRequest
    cmd_readOffset_allChannels_response = _OffsetReadResponse


class _OffsetReadClient:
    def rpc(self, request_type, request, response_type, response_class):
        self.request = request
        self.response_class = response_class
        response = _OffsetReadResponse()
        response.success = True
        response.message = "OK"
        response.offsetValues = [2000 + channel for channel in range(40)]
        return response


class _WriteOffsetRequest:
    def __init__(self, offsetChannel, offsetValue, offsetGain):
        self.offsetChannel = offsetChannel
        self.offsetValue = offsetValue
        self.offsetGain = offsetGain


class _WriteOffsetResponse:
    pass


class _StatefulLowProto:
    cmd_readOffset_allChannels = _OffsetReadRequest
    cmd_readOffset_allChannels_response = _OffsetReadResponse
    cmd_writeOFFSET_singleChannel = _WriteOffsetRequest
    cmd_writeOFFSET_singleChannel_response = _WriteOffsetResponse


class _StatefulHighProto:
    MT2_READ_OFFSET_ALL_CH_REQ = 200
    MT2_READ_OFFSET_ALL_CH_RESP = 201
    MT2_WRITE_OFFSET_CH_REQ = 202
    MT2_WRITE_OFFSET_CH_RESP = 203


class _StatefulOffsetClient:
    def __init__(self):
        self.offsets = [0] * 40

    def rpc(self, request_type, request, response_type, response_class):
        if request_type == _StatefulHighProto.MT2_WRITE_OFFSET_CH_REQ:
            if response_type != _StatefulHighProto.MT2_WRITE_OFFSET_CH_RESP:
                raise AssertionError("unexpected write response type")
            self.offsets[request.offsetChannel] = request.offsetValue
            response = _WriteOffsetResponse()
            response.success = True
            response.message = "OK"
            response.offsetValue = request.offsetValue
            return response
        if request_type == _StatefulHighProto.MT2_READ_OFFSET_ALL_CH_REQ:
            if response_type != _StatefulHighProto.MT2_READ_OFFSET_ALL_CH_RESP:
                raise AssertionError("unexpected read response type")
            response = _OffsetReadResponse()
            response.success = True
            response.message = "OK"
            response.offsetValues = list(self.offsets)
            return response
        raise AssertionError(f"unexpected request type {request_type}")


class PedestalCalibrationTests(unittest.TestCase):
    def test_plateau_margin_preserves_original_target_on_reachable_channels(self):
        for calibrate, settings in (
            (calibrate_pedestals, dict(max_iterations=16, max_offset_step=128, tolerance=1)),
            (calibrate_pedestals_auto, dict(minimum_tolerance=1)),
        ):
            with self.subTest(calibrate=calibrate.__name__):
                hw = _SimulatedHardware({
                    0: lambda offset: max(800, 2 * (offset - 500)),
                    1: lambda offset: 2 * offset,
                })
                initial_offsets = {0: 100, 1: 100}
                hw.offsets.update(initial_offsets)
                fallback, original = calibrate(
                    [0, 1], 500, "regula_falsi", plateau_margin=200,
                    write_offset=hw.write_offset, measure_pedestals=hw.measure,
                    initial_offsets=initial_offsets, report=None, **settings,
                )
                self.assertTrue(fallback.converged)
                self.assertEqual(fallback.plateau_target, 1000)
                self.assertEqual(fallback.pedestal, 1000)
                self.assertEqual(hw.offsets[0], 1000)
                self.assertTrue(original.converged)
                self.assertIsNone(original.plateau_target)
                self.assertEqual(original.pedestal, 500)
                self.assertEqual(hw.offsets[1], 250)

    def test_signed_margin_can_tune_below_an_upper_plateau(self):
        for margin, expected in ((-200, 6800), (200, None)):
            with self.subTest(margin=margin):
                hw = _SimulatedHardware({0: lambda offset: min(7000, 2 * offset)})
                result, = calibrate_pedestals_auto(
                    [0], 8192, "regula_falsi", 1, hw.write_offset, hw.measure,
                    report=None, plateau_margin=margin,
                )
                self.assertEqual(result.converged, expected is not None)
                self.assertEqual(result.plateau_target, expected)
                if expected is not None:
                    self.assertEqual(result.pedestal, expected)
                    self.assertEqual(hw.offsets[0], 3400)

    def test_plateau_margin_does_not_fall_back_on_sloped_response(self):
        hw = _SimulatedHardware({0: lambda offset: 800 + 2 * offset})
        result, = calibrate_pedestals_auto(
            [0], 500, "regula_falsi", 1, hw.write_offset, hw.measure,
            report=None, plateau_margin=200,
        )
        self.assertFalse(result.converged)
        self.assertIsNone(result.plateau_target)
        self.assertEqual(hw.offsets[0], 0)

    def test_plateau_margin_accepts_a_flat_region_with_dac_edge_drift(self):
        # Channel 3 in the ColdBox scan showed edge drift and a minimum
        # inside the DAC range before the pedestal started rising again.
        measurements = {
            0: 2324.984, 32: 2379.770, 64: 2376.764, 142: 2312.976,
            271: 2301.336, 365: 2232.868, 1406: 4819.530, 1407: 4822.238,
        }

        def transfer(offset):
            if offset in measurements:
                return measurements[offset]
            if offset < 365:
                return 2324.984 - offset * (2324.984 - 2232.868) / 365
            return min(ADC_MAX, 2232.868 + 2.485 * (offset - 365))

        hw = _SimulatedHardware({0: transfer})
        hw.offsets[0] = 1407
        result, = calibrate_pedestals_auto(
            [0], 2000, "regula_falsi", 1, hw.write_offset, hw.measure,
            report=None, initial_offsets={0: 1407}, plateau_margin=300,
        )
        self.assertTrue(result.converged)
        self.assertAlmostEqual(result.plateau_target, 2532.868)
        self.assertAlmostEqual(result.pedestal, result.plateau_target, delta=result.tolerance)
        self.assertEqual(hw.transfer_functions[0](hw.offsets[0]), result.pedestal)

    def test_plateau_margin_probes_response_after_search_stays_near_dac_limit(self):
        # ColdBox channel 0, with an interpolated rising branch beyond the log.
        measured = {0: 2444.360, 12: 2433.708, 32: 2435.786, 64: 2433.844,
                    135: 2431.298, 136: 2435.298}

        def transfer(offset):
            if offset in measured:
                return measured[offset]
            return min(ADC_MAX, 2438 + 4 * max(0, offset - 480))

        hw = _SimulatedHardware({0: transfer})
        hw.offsets[0] = 136
        result, = calibrate_pedestals_auto(
            [0], 2000, "regula_falsi", 1, hw.write_offset, hw.measure,
            report=None, initial_offsets={0: 136}, plateau_margin=300,
        )
        self.assertIn({0: pedestal.OFFSET_MAX}, hw.measurements)
        self.assertTrue(result.converged)
        self.assertAlmostEqual(result.plateau_target, 2731.298)
        self.assertAlmostEqual(result.pedestal, result.plateau_target, delta=result.tolerance)

    def test_plateau_margin_keeps_original_target_when_new_probe_brackets_it(self):
        hw = _SimulatedHardware({0: lambda offset: 2 * offset})
        result, = calibrate_pedestals(
            [0], 6000, "regula_falsi", 1, 512, 1, hw.write_offset, hw.measure,
            report=None, plateau_margin=-300,
        )
        self.assertTrue(result.converged)
        self.assertIsNone(result.plateau_target)
        self.assertEqual(result.pedestal, 6000)

    def test_plateau_margin_keeps_target_discovered_by_extra_probes(self):
        hw = _SimulatedHardware({0: lambda offset: 2 * offset})
        result, = calibrate_pedestals(
            [0], 500, "regula_falsi", 1, 512, 1, hw.write_offset, hw.measure,
            report=None, plateau_margin=200,
        )
        self.assertTrue(result.converged)
        self.assertIsNone(result.plateau_target)
        self.assertEqual(result.pedestal, 500)

    def test_dma_flags_are_explicit_and_force_requires_dma(self):
        base = ["-target_pedestal", "8192", "-L", "2048"]
        args = build_parser().parse_args(base)
        self.assertFalse(args.dma)
        self.assertFalse(args.force_acq)
        for flag in ("--force-acq", "--force_acq"):
            args = build_parser().parse_args(base + ["--dma", flag])
            self.assertTrue(args.dma)
            self.assertTrue(args.force_acq)
        with patch.object(pedestal, "load_protobuf_modules") as loader:
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                pedestal.main(base + ["--force-acq"])
            loader.assert_not_called()

    def test_dma_requires_numpy_without_affecting_spybuffer_reduction(self):
        with patch.object(pedestal, "np", None):
            self.assertEqual(pedestal_levels([[[100, 100, 200]]]), [100.0])
            with patch.object(pedestal, "load_protobuf_modules") as loader:
                with contextlib.redirect_stderr(io.StringIO()) as stderr:
                    result = pedestal.main(["--dma", "-target_pedestal", "8192", "-L", "64"])
                self.assertEqual(result, 2)
                self.assertIn("requires numpy", stderr.getvalue())
                loader.assert_not_called()

    def test_main_defaults_to_spybuffer_and_current_offset(self):
        with patch.object(pedestal, "load_protobuf_modules", return_value=(object(), object())) as loader, \
                patch.object(pedestal, "V2Client"), \
                patch.object(pedestal, "configure_trigger_source") as trigger, \
                patch.object(pedestal, "_read_current_offsets", return_value={0: 2200}), \
                patch.object(pedestal, "_measure_pedestals", return_value={0: 8192.0}) as measure, \
                patch.object(pedestal, "_measure_pedestals_dma") as dma_measure, \
                patch.object(pedestal, "_write_offset") as write, \
                patch.object(pedestal, "_verify_configured_offsets", return_value={0: 2200}), \
                contextlib.redirect_stdout(io.StringIO()):
            result = pedestal.main(["--use-current-offset", "-target_pedestal", "8192", "-L", "64"])
        self.assertEqual(result, 0)
        loader.assert_called_once_with(require_trigger_source=True, require_dma=False)
        self.assertEqual(trigger.call_args.args[2], "software")
        self.assertEqual(measure.call_args.args[2:], ([0], 64))
        dma_measure.assert_not_called()
        # An already-correct current OFFSET is retained, with final readback.
        write.assert_not_called()

    @unittest.skipIf(pedestal.np is None, "numpy is required for DMA")
    def test_dma_main_preflights_and_forwards_force_on_every_measurement(self):
        events = []
        transport = types.SimpleNamespace(rpc=lambda *args: None)
        dma = types.SimpleNamespace(
            probe=lambda *args: events.append(("probe", args)) or types.SimpleNamespace(maximum_target_waveforms=500),
            _check_force_acq=lambda force: events.append(("force", force)),
            batch_limit=lambda *args: 8,
        )

        def measure(client, channels, samples, force_acq):
            self.assertIs(client, dma)
            self.assertEqual(samples, 64)
            self.assertTrue(force_acq)
            events.append(("measure", list(channels)))
            return {ch: 8192.0 for ch in channels}

        def calibrate(**kwargs):
            for channels in ([0, 1], [1]):
                kwargs["write_offset"](channels[0], 2275)
                kwargs["measure_pedestals"](channels)
            return [pedestal.CalibrationResult(ch, 2275, 8192, True, 1, "OK") for ch in [0, 1]]

        dma_module = types.SimpleNamespace(DmaClient=lambda *args, **kwargs: dma)
        with patch.dict(sys.modules, {"dma_client": dma_module}), \
                patch.object(pedestal, "load_protobuf_modules", return_value=(object(), object())) as loader, \
                patch.object(pedestal, "V2Client") as connection, \
                patch.object(pedestal, "configure_trigger_source") as spy_trigger, \
                patch.object(pedestal, "_measure_pedestals") as spy_measure, \
                patch.object(pedestal, "_measure_pedestals_dma", side_effect=measure), \
                patch.object(pedestal, "_write_offset", side_effect=lambda *args: events.append(("write", args[-2:]))), \
                patch.object(pedestal, "_verify_configured_offsets", return_value={0: 2275, 1: 2275}), \
                patch.object(pedestal, "calibrate_pedestals_auto", side_effect=calibrate), \
                contextlib.redirect_stdout(io.StringIO()):
            connection.return_value.__enter__.return_value = transport
            result = pedestal.main(["--dma", "--force-acq", "--auto", "-channel", "0", "1",
                                    "-target_pedestal", "8192", "-L", "64"])
        self.assertEqual(result, 0)
        loader.assert_called_once_with(require_trigger_source=False, require_dma=True)
        spy_trigger.assert_not_called()
        spy_measure.assert_not_called()
        self.assertEqual([event[0] for event in events], ["probe", "force", "write", "measure", "write", "measure"])

    @unittest.skipIf(pedestal.np is None, "numpy is required for DMA")
    def test_dma_preflight_rejection_occurs_before_offset_writes(self):
        for failure in ("probe", "force", "target"):
            with self.subTest(failure=failure):
                dma = types.SimpleNamespace(
                    probe=lambda *args: types.SimpleNamespace(maximum_target_waveforms=499 if failure == "target" else 500),
                    _check_force_acq=lambda force: None,
                    batch_limit=lambda *args: 8,
                )
                if failure == "probe":
                    dma.probe = unittest.mock.Mock(side_effect=RuntimeError("PERSISTENT_UNAVAILABLE"))
                if failure == "force":
                    dma._check_force_acq = unittest.mock.Mock(side_effect=RuntimeError("force unsupported"))
                with patch.dict(sys.modules, {"dma_client": types.SimpleNamespace(DmaClient=lambda *args, **kwargs: dma)}), \
                        patch.object(pedestal, "load_protobuf_modules", return_value=(object(), object())), \
                        patch.object(pedestal, "V2Client"), \
                        patch.object(pedestal, "_write_offset") as write, \
                        patch.object(pedestal, "configure_trigger_source") as trigger, \
                        contextlib.redirect_stderr(io.StringIO()):
                    result = pedestal.main(["--dma", "--force-acq", "-target_pedestal", "8192", "-L", "64"])
                self.assertEqual(result, 2)
                write.assert_not_called()
                trigger.assert_not_called()

    def test_cli_accepts_requested_calibration_parameters(self):
        args = build_parser().parse_args(
            [
                "-channel",
                "2",
                "7",
                "-target_pedestal",
                "6000",
                "-method",
                "regula-falsi",
                "-max_iteration_steps",
                "20",
                "-max_iteration_offset",
                "300",
                "-L",
                "64",
            ]
        )
        self.assertEqual(args.channel, ["2", "7"])
        self.assertEqual(args.target_pedestal, 6000)
        self.assertEqual(args.method, "regula_falsi")
        self.assertEqual(args.max_iterations, 20)
        self.assertEqual(args.max_offset_change, 300)

    def test_cli_exposes_auto_and_clear_manual_option_names(self):
        parser = build_parser()
        auto_args = parser.parse_args(
            ["--auto", "-target_pedestal", "8000", "-L", "1024"]
        )
        self.assertTrue(auto_args.auto)
        self.assertIsNone(auto_args.max_iterations)
        self.assertIsNone(auto_args.max_offset_change)

        manual_args = build_parser().parse_args(
            [
                "-target_pedestal",
                "8000",
                "-L",
                "1024",
                "--max-iterations",
                "12",
                "--max-offset-change",
                "50",
            ]
        )
        self.assertEqual(manual_args.max_iterations, 12)
        self.assertEqual(manual_args.max_offset_change, 50)
        help_text = parser.format_help()
        self.assertIn("--max-offset-change", help_text)
        self.assertNotIn("max_iteration_offset", help_text)

    def test_cli_accepts_current_offset_flag_and_suggested_alias(self):
        for flag in (
            "--use-current-offset",
            "--use_current_offset",
            "--use_init_current_pedestal",
        ):
            args = build_parser().parse_args(
                [flag, "-target_pedestal", "8000", "-L", "64"]
            )
            self.assertTrue(args.use_current_offset)

    def test_parses_one_many_comma_separated_and_all_channels(self):
        self.assertEqual(parse_channels(None, False), [0])
        self.assertEqual(parse_channels(["1", "3,5", "3"], False), [1, 3, 5])
        self.assertEqual(parse_channels(None, True), list(range(40)))
        with self.assertRaisesRegex(ValueError, "out of range"):
            parse_channels(["40"], False)

    def test_pedestal_is_mode_of_the_mean_waveform(self):
        waves = [
            [
                [101, 101, 201, 100] if index == 0 else [100, 100, 200, 100],
                [300, 400, 400, 500],
            ]
            for index in range(PEDESTAL_WAVEFORMS)
        ]

        levels = pedestal_levels(waves)

        self.assertAlmostEqual(levels[0], 100.002)
        self.assertEqual(levels[1], 400.0)

    def test_rpc_acquisition_uses_500_software_triggered_waveforms(self):
        levels = _measure_pedestals(
            _FakeHighProto, _AcquisitionClient(), [2, 7], samples=3
        )
        self.assertEqual(levels, {2: 100.0, 7: 400.0})

    def test_reads_current_offsets_for_selected_channels(self):
        class HighProto:
            MT2_READ_OFFSET_ALL_CH_REQ = 200
            MT2_READ_OFFSET_ALL_CH_RESP = 201

        client = _OffsetReadClient()
        offsets = _read_current_offsets(
            HighProto, _FakeLowProto, client, [0, 7, 33]
        )

        self.assertEqual(offsets, {0: 2000, 7: 2007, 33: 2033})
        self.assertIsInstance(client.request, _OffsetReadRequest)
        self.assertIs(client.response_class, _OffsetReadResponse)

    def test_configures_and_reads_back_one_or_multiple_channel_offsets(self):
        cases = (
            {7: 2210},
            {1: 2101, 8: 2208, 33: 2233},
        )
        for expected in cases:
            with self.subTest(channels=list(expected)):
                client = _StatefulOffsetClient()
                for channel, offset in expected.items():
                    _write_offset(
                        _StatefulHighProto,
                        _StatefulLowProto,
                        client,
                        channel,
                        offset,
                    )

                actual = _verify_configured_offsets(
                    _StatefulHighProto,
                    _StatefulLowProto,
                    client,
                    expected,
                )

                self.assertEqual(actual, expected)
                for channel, offset in expected.items():
                    self.assertEqual(client.offsets[channel], offset)

    def test_final_offset_verification_rejects_a_readback_mismatch(self):
        client = _StatefulOffsetClient()
        client.offsets[5] = 2000

        with self.assertRaisesRegex(RuntimeError, "ch5: expected 2100, read 2000"):
            _verify_configured_offsets(
                _StatefulHighProto,
                _StatefulLowProto,
                client,
                {5: 2100},
            )

    def test_bisection_converges_and_obeys_maximum_step(self):
        hardware = _SimulatedHardware({0: lambda offset: 4.0 * offset})

        result = calibrate_pedestals(
            channels=[0],
            target=6000,
            method="bisection",
            max_iterations=12,
            max_offset_step=400,
            tolerance=0.1,
            write_offset=hardware.write_offset,
            measure_pedestals=hardware.measure,
            report=None,
        )[0]

        self.assertTrue(result.converged)
        self.assertEqual(result.offset, 1500)
        self.assertEqual(result.pedestal, 6000)
        self.assertEqual(hardware.writes[0][0], INITIAL_OFFSET)
        for previous, current in zip(hardware.writes[0], hardware.writes[0][1:]):
            self.assertLessEqual(abs(current - previous), 400)

    def test_manual_mode_can_measure_current_offset_without_initial_write(self):
        hardware = _SimulatedHardware({0: lambda offset: 4.0 * offset})
        hardware.offsets[0] = 1800

        result = calibrate_pedestals(
            channels=[0],
            target=7200,
            method="bisection",
            max_iterations=12,
            max_offset_step=400,
            tolerance=1.0,
            write_offset=hardware.write_offset,
            measure_pedestals=hardware.measure,
            report=None,
            initial_offsets={0: 1800},
        )[0]

        self.assertTrue(result.converged)
        self.assertEqual(hardware.measurements[0], {0: 1800})
        self.assertEqual(hardware.writes[0], [])

    def test_regula_falsi_calibrates_channels_independently(self):
        hardware = _SimulatedHardware(
            {
                2: lambda offset: 4.0 * offset,
                7: lambda offset: 2.0 * offset + 2000,
            }
        )

        results = calibrate_pedestals(
            channels=[2, 7],
            target=6000,
            method="regula_falsi",
            max_iterations=12,
            max_offset_step=512,
            tolerance=0.1,
            write_offset=hardware.write_offset,
            measure_pedestals=hardware.measure,
            report=None,
        )

        self.assertEqual([result.channel for result in results], [2, 7])
        self.assertEqual([result.offset for result in results], [1500, 2000])
        self.assertTrue(all(result.converged for result in results))

    def test_auto_mode_derives_sensitivity_tolerance_and_offset_change(self):
        hardware = _SimulatedHardware(
            {33: lambda offset: 20.0 * offset - 36509.0}
        )

        result = calibrate_pedestals_auto(
            channels=[33],
            target=8000,
            method="regula_falsi",
            minimum_tolerance=1.0,
            write_offset=hardware.write_offset,
            measure_pedestals=hardware.measure,
            report=None,
        )[0]

        self.assertTrue(result.converged)
        self.assertEqual(result.offset, 2225)
        self.assertEqual(result.pedestal, 7991)
        self.assertEqual(result.sensitivity, 20)
        self.assertEqual(result.tolerance, 10)
        self.assertEqual(hardware.writes[33][:2], [2275, 2274])
        self.assertGreater(
            abs(hardware.writes[33][2] - hardware.writes[33][1]), 1
        )

    def test_auto_mode_starts_from_current_offset_without_rewriting_it(self):
        hardware = _SimulatedHardware({0: lambda offset: 4.0 * offset})
        hardware.offsets[0] = 2200

        result = calibrate_pedestals_auto(
            channels=[0],
            target=8800,
            method="regula_falsi",
            minimum_tolerance=1.0,
            write_offset=hardware.write_offset,
            measure_pedestals=hardware.measure,
            report=None,
            initial_offsets={0: 2200},
        )[0]

        self.assertTrue(result.converged)
        self.assertEqual(hardware.measurements[0], {0: 2200})
        self.assertEqual(hardware.writes[0][0], 2201)
        self.assertNotIn(INITIAL_OFFSET, hardware.writes[0])

    def test_auto_mode_expands_probe_out_of_low_saturation(self):
        hardware = _SimulatedHardware(
            {0: lambda offset: max(0.0, 10.0 * (offset - 2300))}
        )

        result = calibrate_pedestals_auto(
            channels=[0],
            target=100,
            method="regula_falsi",
            minimum_tolerance=1.0,
            write_offset=hardware.write_offset,
            measure_pedestals=hardware.measure,
            report=None,
        )[0]

        self.assertTrue(result.converged)
        self.assertEqual(result.offset, 2310)
        self.assertEqual(result.pedestal, 100)
        self.assertIn(2307, hardware.writes[0])

    def test_auto_mode_handles_both_14_bit_rails(self):
        low_hardware = _SimulatedHardware(
            {0: lambda offset: max(0.0, 10.0 * (offset - INITIAL_OFFSET))}
        )
        low_result = calibrate_pedestals_auto(
            channels=[0],
            target=0,
            method="bisection",
            minimum_tolerance=1.0,
            write_offset=low_hardware.write_offset,
            measure_pedestals=low_hardware.measure,
            report=None,
        )[0]

        high_hardware = _SimulatedHardware(
            {
                0: lambda offset: min(
                    float(ADC_MAX),
                    ADC_MAX + 10.0 * (offset - INITIAL_OFFSET),
                )
            }
        )
        high_result = calibrate_pedestals_auto(
            channels=[0],
            target=ADC_MAX,
            method="bisection",
            minimum_tolerance=1.0,
            write_offset=high_hardware.write_offset,
            measure_pedestals=high_hardware.measure,
            report=None,
        )[0]

        self.assertTrue(low_result.converged)
        self.assertEqual(low_result.pedestal, 0)
        self.assertTrue(high_result.converged)
        self.assertEqual(high_result.pedestal, ADC_MAX)

    def test_auto_mode_accepts_target_on_a_fully_saturated_rail(self):
        hardware = _SimulatedHardware({0: lambda offset: 0.0})

        result = calibrate_pedestals_auto(
            channels=[0],
            target=0,
            method="regula_falsi",
            minimum_tolerance=1.0,
            write_offset=hardware.write_offset,
            measure_pedestals=hardware.measure,
            report=None,
        )[0]

        self.assertTrue(result.converged)
        self.assertIsNone(result.sensitivity)
        self.assertIn("ADC rail", result.reason)
        self.assertEqual(hardware.offsets[0], INITIAL_OFFSET)

    def test_iteration_limit_does_not_write_an_unmeasured_candidate(self):
        hardware = _SimulatedHardware({0: lambda offset: 4.0 * offset})

        result = calibrate_pedestals(
            channels=[0],
            target=6000,
            method="bisection",
            max_iterations=1,
            max_offset_step=400,
            tolerance=0.1,
            write_offset=hardware.write_offset,
            measure_pedestals=hardware.measure,
            report=None,
        )[0]

        self.assertFalse(result.converged)
        self.assertEqual(result.reason, "maximum iterations reached")
        self.assertEqual(hardware.writes[0], [INITIAL_OFFSET])

    def test_reports_unreachable_saturated_target_and_keeps_best_offset(self):
        hardware = _SimulatedHardware(
            {0: lambda offset: min(8000.0, 2.0 * offset)}
        )

        result = calibrate_pedestals(
            channels=[0],
            target=12000,
            method="regula_falsi",
            max_iterations=10,
            max_offset_step=512,
            tolerance=1.0,
            write_offset=hardware.write_offset,
            measure_pedestals=hardware.measure,
            report=None,
        )[0]

        self.assertFalse(result.converged)
        self.assertEqual(result.pedestal, 8000)
        self.assertIn("upper offset limit", result.reason)
        self.assertEqual(hardware.offsets[0], result.offset)


if __name__ == "__main__":
    unittest.main()
