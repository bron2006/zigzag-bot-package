import unittest
from pathlib import Path
import numpy as np
import pandas as pd
from daily_trend import simulate, load_history


def bars(opens, closes, positions):
    return pd.DataFrame({"Open": opens, "Close": closes, "position": positions})


class DailyTrendTest(unittest.TestCase):
    def test_cash_stays_flat(self):
        result, curve = simulate(bars([100,200], [150,300], [0,0]), .001)
        self.assertEqual(result["total_return"], 0)
        self.assertEqual(result["changes"], 0)
        self.assertEqual(curve.tolist(), [1,1])

    def test_fee_charged_for_entry_and_terminal_exit(self):
        result, _ = simulate(bars([100,100], [100,100], [1,1]), .001)
        self.assertAlmostEqual(result["total_return"], .999**2-1)
        self.assertEqual(result["changes"], 2)
        self.assertEqual(result["completed_trades"], 1)

    def test_gap_return_goes_to_existing_holder_before_exit(self):
        result, _ = simulate(bars([100,200], [110,200], [1,0]), 0)
        self.assertAlmostEqual(result["total_return"], 1)

    def test_future_jump_is_not_earned_before_entry(self):
        result, _ = simulate(bars([100,200], [100,200], [0,1]), 0)
        self.assertEqual(result["total_return"], 0)

    def test_buy_hold_control_uses_same_start_and_end(self):
        df = bars([100,200], [150,250], [0,0])
        result, _ = simulate(df, 0, hold=True)
        self.assertEqual(result["total_return"], 1.5)

    def test_drawdown_includes_initial_capital_peak(self):
        result, _ = simulate(bars([100,100], [50,100], [1,1]), 0)
        self.assertEqual(result["max_drawdown"], -.5)

    def test_stress_cost_is_worse_with_unchanged_decisions(self):
        df = bars([100,100,100], [100,100,100], [1,0,1])
        normal, _ = simulate(df, .001)
        stress, _ = simulate(df, .003)
        self.assertLess(stress["total_return"], normal["total_return"])
        self.assertEqual(stress["changes"], normal["changes"])

    def test_real_history_reconciles_with_independent_vectorized_equity(self):
        directory = Path(__file__).with_name("public_daily")
        if not directory.exists():
            self.skipTest("Optional public history snapshot not downloaded")
        for symbol in ("BTCUSDT", "ETHUSDT"):
            full = load_history(directory/f"{symbol}_1d.json")
            for start, end in (("2020-01-01", "2024-01-01"), ("2024-01-01", "2026-10-01")):
                df = full[(full.date >= start) & (full.date < end)]
                for fee in (.001, .003):
                    _, actual = simulate(df, fee)
                    position = df.position.to_numpy()
                    previous_position = np.r_[0, position[:-1]]
                    opens, closes = df.Open.to_numpy(), df.Close.to_numpy()
                    previous_close = np.r_[opens[0], closes[:-1]]
                    overnight = np.where(previous_position == 1, opens/previous_close, 1)
                    intraday = np.where(position == 1, closes/opens, 1)
                    fees = (1-fee)**np.abs(position-previous_position)
                    independent = np.cumprod(overnight*intraday*fees)
                    if position[-1]:
                        independent[-1] *= 1-fee
                    np.testing.assert_allclose(actual, independent, rtol=1e-12, atol=1e-12)

    def test_changing_future_prices_cannot_change_earlier_position(self):
        directory = Path(__file__).with_name("public_daily")
        if not directory.exists():
            self.skipTest("Optional public history snapshot not downloaded")
        df = load_history(directory/"BTCUSDT_1d.json")
        close = df.Close.copy()
        close.iloc[1500:] *= 5
        modified = (close > close.rolling(200, min_periods=200).mean()).astype(int).shift(2).fillna(0)
        np.testing.assert_array_equal(df.position.iloc[:1500], modified.iloc[:1500])
