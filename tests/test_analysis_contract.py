import unittest
from types import SimpleNamespace

import pandas as pd

import analysis
import ml_models


class AnalysisContractTest(unittest.TestCase):
    def test_trendbar_to_row_returns_ohlc_columns(self):
        bar = SimpleNamespace(
            low=1000,
            deltaOpen=10,
            deltaHigh=80,
            deltaClose=40,
            volume=123,
            utcTimestampInMinutes=42,
        )

        row = analysis._trendbar_to_row(bar, 100)

        self.assertEqual(row["Open"], 10.10)
        self.assertEqual(row["High"], 10.80)
        self.assertEqual(row["Low"], 10.00)
        self.assertEqual(row["Close"], 10.40)
        self.assertEqual(row["Volume"], 123)
        self.assertEqual(row["Timestamp"], 42 * 60)

    def test_missing_ml_models_returns_wait_instead_of_neutral(self):
        old_model = ml_models.LGBM_MODEL
        old_scaler = ml_models.SCALER
        ml_models.LGBM_MODEL = None
        ml_models.SCALER = None

        try:
            df = pd.DataFrame(
                {
                    "Open": [1.0 + i * 0.001 for i in range(300)],
                    "High": [1.1 + i * 0.001 for i in range(300)],
                    "Low": [0.9 + i * 0.001 for i in range(300)],
                    "Close": [1.05 + i * 0.001 for i in range(300)],
                    "Volume": [100 + i for i in range(300)],
                }
            )

            score, verdict, reason = analysis._run_technical_analysis(df)

            self.assertEqual(score, 50)
            self.assertEqual(verdict, "WAIT")
            self.assertIn("ML", reason)
        finally:
            ml_models.LGBM_MODEL = old_model
            ml_models.SCALER = old_scaler

    def test_analysis_contract_when_client_is_missing(self):
        d = analysis.get_api_detailed_signal_data(None, {}, "EUR/USD", 1, "1m")
        result = []
        d.addCallback(result.append)

        self.assertEqual(len(result), 1)
        payload = result[0]

        self.assertEqual(payload["pair"], "EURUSD")
        self.assertEqual(payload["timeframe"], "1m")
        self.assertEqual(payload["verdict_text"], "WAIT")
        self.assertEqual(payload["score"], 50)
        self.assertFalse(payload["is_trade_allowed"])
        self.assertIsInstance(payload["reasons"], list)


if __name__ == "__main__":
    unittest.main()
