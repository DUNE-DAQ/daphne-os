"""Offline regression checks for error accounting and truthful DMA eye margins."""
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'client'))
from dma_eye_plot import point_rates, measured_margins


def point(tap, failures=None, low=None, boundary=None, boundaries=0):
    return SimpleNamespace(tap=tap, bitslip=3, transitionsPerChannel=99,
        channelFailures=failures or [0] * 8, low_bit_failures=low or [0] * 8,
        boundary_failures=boundary or [0] * 8, boundary_transitions_per_channel=boundaries)


def result(points, tap=8, mask=255):
    return SimpleNamespace(afe=2, bitslip=3, selected_delay=tap,
                           approved_lane_mask=mask, points=points)


class EyePresentationTests(unittest.TestCase):
    def test_single_point_margin_is_zero_and_marked_narrow(self):
        points = [point(t, [int(t != 8)] * 8) for t in (0, 4, 8, 12, 16)]
        _, _, metrics = measured_margins(result(points))
        self.assertEqual(metrics[0]['window_at_selected'], [8, 8])
        self.assertEqual(metrics[0]['sampled_margin_taps'], 0)
        self.assertTrue(metrics[0]['marginal'])

    def test_measure_run_at_selected_not_wider_disconnected_run(self):
        points = [point(t, [int(t in (12, 28))] * 8) for t in range(0, 33, 4)]
        _, _, metrics = measured_margins(result(points, tap=32))
        self.assertEqual(metrics[0]['window_at_selected'], [32, 32])
        self.assertEqual(metrics[0]['coverage_clipped'], ['right'])

    def test_coverage_edges_are_unknown_not_measured_eye_edges(self):
        _, _, metrics = measured_margins(result([point(t) for t in (0, 4, 8, 12, 16)]))
        self.assertEqual(metrics[0]['sampled_margin_taps'], 8)
        self.assertEqual(metrics[0]['coverage_clipped'], ['left', 'right'])
        self.assertFalse(metrics[0]['marginal'])

    def test_low_bits_and_boundary_errors_use_their_own_denominators(self):
        rates = point_rates(point(8, low=[1] + [0] * 7,
                                  boundary=[0, 1] + [0] * 6, boundaries=1))
        self.assertAlmostEqual(rates[0], 1 / 101)
        self.assertEqual(rates[1], 1)
        _, _, metrics = measured_margins(result([point(8, low=[1] + [0] * 7)]))
        self.assertIsNone(metrics[0]['window_at_selected'])

    def test_failed_approval_never_reports_margin_for_default_tap_zero(self):
        _, _, metrics = measured_margins(result([point(0), point(4)], tap=0, mask=0))
        self.assertTrue(all(m['window_at_selected'] is None for m in metrics))

    def test_invalid_boundary_counts_fail_instead_of_showing_pass(self):
        with self.assertRaises(ValueError):
            point_rates(point(8, boundary=[1] + [0] * 7))

    def test_partial_approval_keeps_excluded_channels_explicit(self):
        _, _, metrics = measured_margins(result([point(4), point(8), point(12)], mask=127))
        self.assertTrue(metrics[0]['approved'])
        self.assertFalse(metrics[7]['approved'])
        self.assertEqual(metrics[7]['window_at_selected'], [4, 12])


if __name__ == '__main__':
    unittest.main()
