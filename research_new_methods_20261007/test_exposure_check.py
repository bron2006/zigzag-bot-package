import unittest
import numpy as np
from exposure_check import partial, metrics, log_returns, bootstrap, calibrate
from test_daily_trend import bars


class PartialControlTest(unittest.TestCase):
    def test_zero_fraction_is_cash(self):
        np.testing.assert_array_equal(partial([.5, 2], 0), [1, 1])

    def test_full_fraction_is_original_hold(self):
        np.testing.assert_array_equal(partial([.5, 2], 1), [.5, 2])

    def test_half_fraction(self):
        np.testing.assert_array_equal(partial([.5, 2], .5), [.75, 1.5])

    def test_invalid_fraction_rejected(self):
        for fraction in (-.1, 1.1):
            with self.assertRaises(ValueError):
                partial([1], fraction)

    def test_log_returns_telescope(self):
        self.assertAlmostEqual(log_returns([.9, 1.2, 1.1]).sum(), np.log(1.1))

    def test_metrics_include_initial_peak(self):
        self.assertAlmostEqual(metrics(np.array([.8, .9]))['max_drawdown'], -.2)

    def test_bootstrap_reproducible_and_constant_difference(self):
        values = np.full((100, 2), .001)
        a = bootstrap(values, repetitions=100)
        np.testing.assert_allclose(a, .36525)
        np.testing.assert_array_equal(a, bootstrap(values, repetitions=100))

    def test_calibration_accepts_only_supplied_early_data(self):
        early = bars([100, 110, 90, 120], [105, 95, 115, 125], [0, 1, 1, 0])
        weights = calibrate(early)
        self.assertEqual(weights['exposure'], .5)
        self.assertTrue(0 <= weights['volatility'] <= 1)
