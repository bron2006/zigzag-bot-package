import unittest

import signal_tracking


class ComputeTpSlTest(unittest.TestCase):
    def test_buy_tp_above_sl_below_entry(self):
        tp, sl = signal_tracking.compute_tp_sl("BUY", 100.0, atr=2.0)
        self.assertAlmostEqual(tp, 103.0)  # entry + 1.5x ATR
        self.assertAlmostEqual(sl, 98.0)  # entry - 1.0x ATR

    def test_sell_tp_below_sl_above_entry(self):
        tp, sl = signal_tracking.compute_tp_sl("SELL", 100.0, atr=2.0)
        self.assertAlmostEqual(tp, 97.0)
        self.assertAlmostEqual(sl, 102.0)

    def test_rejects_non_directional_verdict(self):
        self.assertIsNone(signal_tracking.compute_tp_sl("NEUTRAL", 100.0, atr=2.0))

    def test_rejects_non_positive_inputs(self):
        self.assertIsNone(signal_tracking.compute_tp_sl("BUY", 0, atr=2.0))
        self.assertIsNone(signal_tracking.compute_tp_sl("BUY", 100.0, atr=0))
        self.assertIsNone(signal_tracking.compute_tp_sl("BUY", 100.0, atr=-1))


class MaybeRecordSignalTest(unittest.TestCase):
    def test_skips_when_trade_not_allowed(self):
        result = {
            "is_trade_allowed": False,
            "verdict_text": "BUY",
            "pair": "EURUSD",
            "price": 1.1,
            "atr": 0.001,
        }
        self.assertIsNone(signal_tracking.maybe_record_signal(result))

    def test_skips_when_verdict_not_directional(self):
        result = {
            "is_trade_allowed": True,
            "verdict_text": "NEUTRAL",
            "pair": "EURUSD",
            "price": 1.1,
            "atr": 0.001,
        }
        self.assertIsNone(signal_tracking.maybe_record_signal(result))

    def test_skips_when_atr_missing(self):
        result = {
            "is_trade_allowed": True,
            "verdict_text": "BUY",
            "pair": "EURUSD",
            "price": 1.1,
            "atr": None,
        }
        self.assertIsNone(signal_tracking.maybe_record_signal(result))


if __name__ == "__main__":
    unittest.main()
