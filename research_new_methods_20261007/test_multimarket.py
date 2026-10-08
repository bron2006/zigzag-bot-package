import unittest
import numpy as np
import pandas as pd
from multimarket_test import simulate, model_weights, paired_interval


class MonthlyPilotTest(unittest.TestCase):
    def test_cash_no_profit(self):
        result, _, _ = simulate(np.full((3, 4), .1), np.zeros((3, 4)), .001, .06)
        self.assertEqual(result['total_return'], 0)

    def test_short_loses_when_price_rises(self):
        result, _, _ = simulate(np.array([[.1], [.1]]), np.array([[-.25], [-.25]]), 0, 0)
        self.assertAlmostEqual(result['total_return'], .975**2-1)

    def test_entry_terminal_fees(self):
        result, _, _ = simulate(np.zeros((2, 1)), np.full((2, 1), .25), .001, 0)
        self.assertLess(result['total_return'], -.00049)
        self.assertGreater(result['total_return'], -.00051)

    def test_costs_reduce_equity(self):
        r, w = np.full((12, 4), .01), np.full((12, 4), .1)
        base, _, _ = simulate(r, w, .001, .03)
        stress, _, _ = simulate(r, w, .003, .06)
        self.assertLess(stress['total_return'], base['total_return'])

    def test_leverage_rejected(self):
        with self.assertRaises(ValueError):
            simulate(np.zeros((3, 4)), np.ones((3, 4)), 0, 0)

    def test_two_month_information_lag(self):
        dates = pd.period_range('2010-01', periods=80, freq='M')
        p = pd.DataFrame({'one': 100*np.exp(np.arange(80)*.01+np.sin(np.arange(80))*.05)}, index=dates)
        _, before = model_weights(p)
        p.iloc[60:] *= 3
        _, after = model_weights(p)
        np.testing.assert_allclose(before.iloc[:62], after.iloc[:62], equal_nan=True)

    def test_constant_bootstrap(self):
        np.testing.assert_allclose(paired_interval(np.full(45, .01)), [.12, .12])

    def test_independent_fixed_weight_gross_equity(self):
        r = np.array([[.02, -.03], [-.01, .05], [.1, -.08]])
        w = np.array([[.15, -.2], [.1, .2], [-.25, .1]])
        _, actual, _ = simulate(r, w, 0, 0)
        np.testing.assert_allclose(actual, np.cumprod(1+np.sum(r*w, axis=1)))
