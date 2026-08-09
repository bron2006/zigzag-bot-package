import unittest

import signal_tracking


class ComputeHorizonSecondsTest(unittest.TestCase):
    def test_1m_confirms_against_5m_horizon(self):
        self.assertEqual(signal_tracking.compute_horizon_seconds("1m"), 5 * 60)

    def test_5m_confirms_against_15m_horizon(self):
        self.assertEqual(signal_tracking.compute_horizon_seconds("5m"), 15 * 60)

    def test_15m_confirms_against_15m_horizon(self):
        self.assertEqual(signal_tracking.compute_horizon_seconds("15m"), 15 * 60)

    def test_unknown_timeframe_falls_back_to_default(self):
        self.assertEqual(signal_tracking.compute_horizon_seconds("bogus"), 15 * 60)


class ClassifyMoveTest(unittest.TestCase):
    def test_up_move(self):
        self.assertEqual(signal_tracking._classify_move(100.0, 101.0), "up")

    def test_down_move(self):
        self.assertEqual(signal_tracking._classify_move(100.0, 99.0), "down")

    def test_tiny_move_is_flat(self):
        # 0.001% change, well under the default 0.02% noise threshold.
        self.assertEqual(signal_tracking._classify_move(100.0, 100.001), "flat")

    def test_zero_entry_price_is_flat(self):
        self.assertEqual(signal_tracking._classify_move(0.0, 5.0), "flat")


class MaybeRecordSignalTest(unittest.TestCase):
    def test_skips_when_trade_not_allowed(self):
        result = {
            "is_trade_allowed": False,
            "verdict_text": "BUY",
            "pair": "EURUSD",
            "price": 1.1,
            "timeframe": "1m",
        }
        self.assertIsNone(signal_tracking.maybe_record_signal(result))

    def test_skips_when_verdict_not_directional(self):
        result = {
            "is_trade_allowed": True,
            "verdict_text": "NEUTRAL",
            "pair": "EURUSD",
            "price": 1.1,
            "timeframe": "1m",
        }
        self.assertIsNone(signal_tracking.maybe_record_signal(result))

    def test_skips_when_price_missing(self):
        result = {
            "is_trade_allowed": True,
            "verdict_text": "BUY",
            "pair": "EURUSD",
            "price": None,
            "timeframe": "1m",
        }
        self.assertIsNone(signal_tracking.maybe_record_signal(result))


if __name__ == "__main__":
    unittest.main()
