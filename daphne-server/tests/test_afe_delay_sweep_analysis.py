#!/usr/bin/env python3

import json
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import patch


CLIENT_DIR = Path(__file__).resolve().parents[1] / "client"
sys.path.insert(0, str(CLIENT_DIR))

from afe_delay_sweep_analysis import (  # noqa: E402
    best_partial_passing_window,
    longest_passing_window,
    summarize_afe_eye,
)
import scan_afe_delay_eye as scan_client  # noqa: E402
from scan_afe_delay_eye import (  # noqa: E402
    fine_range_from_coarse_result,
    result_has_common_window,
)


class AfeDelaySweepAnalysisTests(unittest.TestCase):
    def test_finds_longest_window_and_midpoint(self):
        window = longest_passing_window(
            [0, 4, 8, 12, 16, 20],
            [2, 0, 0, 0, 3, 0],
            [100] * 6,
        )
        self.assertEqual(window.first_tap, 4)
        self.assertEqual(window.last_tap, 12)
        self.assertEqual(window.point_count, 3)
        self.assertEqual(window.recommended_tap, 8)

    def test_accepts_configured_error_rate(self):
        window = longest_passing_window(
            [0, 1, 2],
            [2, 1, 2],
            [100, 100, 100],
            max_error_rate=0.01,
        )
        self.assertEqual((window.first_tap, window.last_tap), (1, 1))

    def test_reports_no_window(self):
        self.assertIsNone(
            longest_passing_window([0, 1], [1, 1], [100, 100])
        )

    def test_common_window_requires_every_channel(self):
        summary = summarize_afe_eye(
            [0, 4, 8, 12, 16],
            (
                [1, 0, 0, 0, 1],
                [1, 1, 0, 0, 0],
            ),
            [100] * 5,
        )
        self.assertEqual(summary.channel_windows[0].first_tap, 4)
        self.assertEqual(summary.channel_windows[1].last_tap, 16)
        self.assertEqual(summary.common_window.first_tap, 8)
        self.assertEqual(summary.common_window.last_tap, 12)

    def test_partial_window_prioritizes_channel_count_then_width(self):
        candidate = best_partial_passing_window(
            [0, 1, 2, 3, 4],
            (
                [[0, 0, 0, 0, 0]] * 6
                + [[1, 1, 0, 1, 1]]
                + [[1, 1, 1, 1, 1]]
            ),
            [100] * 5,
        )
        self.assertEqual(candidate.passing_lanes, tuple(range(7)))
        self.assertEqual(candidate.excluded_lanes, (7,))
        self.assertEqual(candidate.window.first_tap, 2)
        self.assertEqual(candidate.window.last_tap, 2)
        self.assertEqual(candidate.window.recommended_tap, 2)

    def test_partial_window_supports_a_single_operational_channel(self):
        candidate = best_partial_passing_window(
            [0, 1, 2, 3, 4],
            (
                [[1, 1, 1, 1, 1]] * 5
                + [[1, 0, 0, 0, 1]]
                + [[1, 1, 1, 1, 1]] * 2
            ),
            [100] * 5,
        )
        self.assertEqual(candidate.passing_lanes, (5,))
        self.assertEqual(candidate.window.first_tap, 1)
        self.assertEqual(candidate.window.last_tap, 3)
        self.assertEqual(candidate.window.recommended_tap, 2)

    def test_partial_window_reports_afe_with_no_good_channel(self):
        self.assertIsNone(
            best_partial_passing_window(
                [0, 1],
                [[1, 1]] * 8,
                [100, 100],
            )
        )

    def test_rejects_mismatched_arrays(self):
        with self.assertRaisesRegex(ValueError, "equal size"):
            longest_passing_window([0, 1], [0], [100, 100])

    @staticmethod
    def make_afe_result(taps, failures_by_lane):
        points = []
        for index, tap in enumerate(taps):
            points.append(
                SimpleNamespace(
                    tap=tap,
                    transitionsPerChannel=100,
                    channelFailures=[
                        failures_by_lane[lane][index] for lane in range(8)
                    ],
                )
            )
        return SimpleNamespace(points=points)

    def test_auto_range_covers_every_channel_coarse_pass(self):
        taps = [0, 10, 20, 30, 40, 50]
        failures = (
            [[1, 1, 0, 0, 1, 1]] * 4
            + [[1, 1, 1, 0, 0, 1]] * 4
        )
        result = self.make_afe_result(taps, failures)
        args = SimpleNamespace(
            first_tap=0,
            last_tap=50,
            max_error_rate=0.0,
        )

        first, last, _ = fine_range_from_coarse_result(result, args)

        self.assertEqual((first, last), (10, 50))
        self.assertTrue(result_has_common_window(result, 0.0))

    def test_auto_range_falls_back_if_a_lane_has_no_coarse_pass(self):
        taps = [0, 10, 20, 30]
        failures = [[1, 0, 0, 1] for _ in range(7)]
        failures.append([1, 1, 1, 1])
        result = self.make_afe_result(taps, failures)
        args = SimpleNamespace(
            first_tap=0,
            last_tap=30,
            max_error_rate=0.0,
        )

        first, last, reason = fine_range_from_coarse_result(result, args)

        self.assertEqual((first, last), (0, 30))
        self.assertIn("full-range fallback", reason)

    @staticmethod
    def make_response():
        good_points = []
        bad_points = []
        for tap in range(3):
            passing = tap == 1
            good_points.append(
                SimpleNamespace(
                    tap=tap,
                    transitionsPerChannel=100,
                    channelFailures=[0 if passing else 1] * 8,
                )
            )
            bad_points.append(
                SimpleNamespace(
                    tap=tap,
                    transitionsPerChannel=100,
                    channelFailures=(
                        [0 if passing else 1] * 7 + [1]
                    ),
                )
            )
        return SimpleNamespace(
            success=True,
            message="ok",
            originalVtcEnable=1,
            afes=[
                SimpleNamespace(
                    afe=0,
                    originalDelay=22,
                    bitslip=3,
                    points=good_points,
                ),
                SimpleNamespace(
                    afe=1,
                    originalDelay=33,
                    bitslip=4,
                    points=bad_points,
                ),
            ],
        )

    @staticmethod
    def make_save_args(output_dir, accept_partial_config):
        return SimpleNamespace(
            output_dir=output_dir,
            summary=True,
            max_error_rate=0.0,
            apply_best=True,
            accept_partial_config=accept_partial_config,
            ip="127.0.0.1",
            port=9876,
            route="mezz/0",
            timeout_ms=1000,
            auto=False,
            first_tap=0,
            last_tap=2,
            tap_step=1,
            samples=16,
            waveforms=1,
            settle_us=0,
        )

    def test_partial_config_applies_best_subset_inside_afe(self):
        with tempfile.TemporaryDirectory() as directory:
            args = self.make_save_args(Path(directory), True)
            applied = {
                "success": True,
                "message": "applied",
                "previous_vtc_enable": 1,
                "current_vtc_enable": 0,
                "settings": [
                    {"afe": 0, "delay": 1, "bitslip": 3},
                    {"afe": 1, "delay": 1, "bitslip": 4},
                ],
            }
            with (
                patch.object(scan_client, "plot_heatmap") as plot_mock,
                patch.object(
                    scan_client,
                    "apply_timing_settings",
                    return_value=applied,
                ) as apply_mock,
            ):
                run_dir, all_pass, application_succeeded = (
                    scan_client.save_results(
                        object(),
                        self.make_response(),
                        args,
                        [0, 1],
                        "external",
                        None,
                    )
                )

            self.assertFalse(all_pass)
            self.assertTrue(application_succeeded)
            apply_mock.assert_called_once_with(
                unittest.mock.ANY,
                args,
                [
                    {"afe": 0, "delay": 1, "bitslip": 3},
                    {"afe": 1, "delay": 1, "bitslip": 4},
                ],
            )
            self.assertTrue((run_dir / "delay_sweep.csv").is_file())
            self.assertEqual(plot_mock.call_count, 2)
            summary = json.loads((run_dir / "summary.json").read_text())
            self.assertEqual(summary["result"], "PARTIAL")
            self.assertEqual(
                summary["timing_application"]["skipped_afes"],
                [],
            )
            coverage = summary["timing_application"]["channel_coverage"]
            self.assertEqual(coverage[1]["mode"], "partial")
            self.assertEqual(coverage[1]["passing_lanes"], list(range(7)))

    def test_partial_config_requires_explicit_acceptance(self):
        with tempfile.TemporaryDirectory() as directory:
            args = self.make_save_args(Path(directory), False)
            args.summary = False
            with (
                patch.object(scan_client, "plot_heatmap") as plot_mock,
                patch.object(
                    scan_client,
                    "apply_timing_settings",
                ) as apply_mock,
            ):
                run_dir, all_pass, application_succeeded = (
                    scan_client.save_results(
                        object(),
                        self.make_response(),
                        args,
                        [0, 1],
                        "external",
                        None,
                    )
                )

            self.assertIsNone(run_dir)
            self.assertEqual(list(Path(directory).iterdir()), [])
            self.assertFalse(all_pass)
            self.assertFalse(application_succeeded)
            plot_mock.assert_not_called()
            apply_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
