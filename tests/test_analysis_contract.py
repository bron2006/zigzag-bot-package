import unittest
from types import SimpleNamespace

import pandas as pd

import analysis
import config
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
            self.assertIn("модель", reason.lower())
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


class EntryDriftBlockReasonTest(unittest.TestCase):
    """AUDIT FIX (2026-08-15, high): _entry_drift_block_reason used to
    apply ONE flat 0.005% threshold to every instrument (forex, crypto,
    commodities, stocks), silently suppressing far more valid signals for
    volatile instruments than calm ones. Now looks up a per-instrument-
    class threshold via config.entry_drift_percent_for_pair."""

    def test_forex_pair_blocked_only_past_the_tight_forex_threshold(self):
        signal_price = 1.10000
        # A move just under BTC's much wider crypto threshold but past
        # forex's tight one - must still block for a forex pair.
        drift = config.MAX_ENTRY_DRIFT_PERCENT_CRYPTO / 100.0 * 0.5
        live_price = signal_price * (1 - drift - 0.0001)  # a bit past forex's own threshold too

        reason = analysis._entry_drift_block_reason("BUY", signal_price, live_price, "EURUSD")
        self.assertIsNotNone(reason)

    def test_crypto_pair_not_blocked_by_a_move_that_would_block_forex(self):
        # Same relative move that WOULD block a forex pair (comfortably
        # past MAX_ENTRY_DRIFT_PERCENT_FOREX) must NOT block a crypto pair,
        # since crypto's own threshold is deliberately much wider.
        signal_price = 60000.0
        forex_drift = config.MAX_ENTRY_DRIFT_PERCENT_FOREX / 100.0
        live_price = signal_price * (1 - forex_drift * 2)  # well past forex's threshold

        self.assertIsNotNone(analysis._entry_drift_block_reason("BUY", signal_price, live_price, "EURUSD"))
        self.assertIsNone(analysis._entry_drift_block_reason("BUY", signal_price, live_price, "BTCUSD"))

    def test_crypto_pair_blocked_once_past_its_own_wider_threshold(self):
        signal_price = 60000.0
        crypto_drift = config.MAX_ENTRY_DRIFT_PERCENT_CRYPTO / 100.0
        live_price = signal_price * (1 - crypto_drift * 2)

        self.assertIsNotNone(analysis._entry_drift_block_reason("BUY", signal_price, live_price, "BTCUSD"))


if __name__ == "__main__":
    unittest.main()
