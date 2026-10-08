import unittest
import numpy as np
import pandas as pd
from screen import first_signal, outcome, prepare


def session():
    df = pd.DataFrame({"Open": np.ones(96)*100, "High": np.ones(96)*100.2,
                       "Low": np.ones(96)*99.8, "Close": np.ones(96)*100,
                       "atr": np.ones(96)})
    return df


class ExecutionTest(unittest.TestCase):
    def test_signal_cannot_fill_on_signal_or_next_bar(self):
        df = session()
        df.loc[12:13, "Open"] = 50
        result = outcome(df, 12, 1)
        self.assertEqual(result["entry_index"], 14)
        self.assertEqual(result["entry_price"], 100)

    def test_stop_wins_same_bar_ambiguity(self):
        df = session()
        df.loc[14, ["High", "Low"]] = [105, 97]
        self.assertEqual(outcome(df, 12, 1)["gross_r"], -1)

    def test_gap_through_stop_is_not_filled_at_better_price(self):
        df = session()
        df.loc[15, ["Open", "High", "Low", "Close"]] = [95, 96, 94, 95]
        self.assertEqual(outcome(df, 12, 1)["gross_r"], -2.5)

    def test_short_target_and_costs(self):
        df = session()
        df.loc[15, "Low"] = 95
        result = outcome(df, 12, -1)
        self.assertEqual(result["gross_r"], 2)
        self.assertAlmostEqual(result["net_r"], 1.89)
        self.assertAlmostEqual(result["stress_r"], 1.78)

    def test_time_exit_is_one_hour_maximum(self):
        result = outcome(session(), 12, 1)
        self.assertEqual(result["exit_index"], 25)
        self.assertAlmostEqual(result["net_r"], -0.11)

    def test_late_signal_does_not_use_final_bar(self):
        df = session()
        df.loc[83:, "Close"] = 110
        self.assertIsNone(first_signal(df, "opening_breakout"))

    def test_future_changes_do_not_change_an_existing_signal(self):
        df = session()
        df.loc[12, "Close"] = 102
        original = first_signal(df, "hour_momentum")
        df.loc[20:, "Close"] = 500
        self.assertEqual(first_signal(df, "hour_momentum"), original)

    def test_failed_breakout_needs_prior_closed_bar_outside_range(self):
        df = session()
        df.loc[12, "Close"] = 101
        self.assertEqual(first_signal(df, "failed_breakout"), (13, -1))

    def test_impossible_ohlc_rejected(self):
        df = session().iloc[:2].drop(columns="atr")
        df["symbol"], df["Timestamp"], df["Volume"] = "TEST", [0,300], 1
        df.loc[0, "Close"] = 200
        with self.assertRaises(ValueError):
            prepare(df)


if __name__ == "__main__":
    unittest.main()
