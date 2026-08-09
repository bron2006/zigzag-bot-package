import unittest
from types import SimpleNamespace
from unittest.mock import patch

import autotrader


class ComputeTpSlTest(unittest.TestCase):
    def test_buy_tp_above_sl_below_entry(self):
        tp, sl = autotrader._compute_tp_sl("BUY", 100.0, atr=2.0)
        self.assertAlmostEqual(tp, 103.0)  # entry + 1.5x ATR
        self.assertAlmostEqual(sl, 98.0)  # entry - 1.0x ATR

    def test_sell_tp_below_sl_above_entry(self):
        tp, sl = autotrader._compute_tp_sl("SELL", 100.0, atr=2.0)
        self.assertAlmostEqual(tp, 97.0)
        self.assertAlmostEqual(sl, 102.0)

    def test_rejects_non_directional_verdict(self):
        self.assertIsNone(autotrader._compute_tp_sl("NEUTRAL", 100.0, atr=2.0))

    def test_rejects_non_positive_inputs(self):
        self.assertIsNone(autotrader._compute_tp_sl("BUY", 0, atr=2.0))
        self.assertIsNone(autotrader._compute_tp_sl("BUY", 100.0, atr=0))
        self.assertIsNone(autotrader._compute_tp_sl("BUY", 100.0, atr=-1))


class NormalizeVolumeTest(unittest.TestCase):
    def _symbol(self, min_volume=1000, max_volume=5_000_000, step_volume=1000):
        return SimpleNamespace(minVolume=min_volume, maxVolume=max_volume, stepVolume=step_volume, symbolId=1)

    def test_rounds_down_to_step(self):
        with patch.object(autotrader.ctrader, "_resolve_broker_symbol", return_value=self._symbol()):
            volume = autotrader._normalize_volume("EURUSD", raw_units=12.3456)
        # raw_units * 100 = 1234.56 -> int 1234 -> rounded down to nearest 1000 -> 1000
        self.assertEqual(volume, 1000)

    def test_rejects_below_min_volume(self):
        with patch.object(autotrader.ctrader, "_resolve_broker_symbol", return_value=self._symbol(min_volume=10000)):
            volume = autotrader._normalize_volume("EURUSD", raw_units=50.0)
        self.assertIsNone(volume)

    def test_clamps_to_max_volume(self):
        with patch.object(autotrader.ctrader, "_resolve_broker_symbol", return_value=self._symbol(max_volume=100000)):
            volume = autotrader._normalize_volume("EURUSD", raw_units=100000.0)
        self.assertLessEqual(volume, 100000)

    def test_returns_none_when_symbol_missing(self):
        with patch.object(autotrader.ctrader, "_resolve_broker_symbol", return_value=None):
            self.assertIsNone(autotrader._normalize_volume("UNKNOWN", raw_units=10.0))

    def test_returns_none_for_non_positive_units(self):
        with patch.object(autotrader.ctrader, "_resolve_broker_symbol", return_value=self._symbol()):
            self.assertIsNone(autotrader._normalize_volume("EURUSD", raw_units=0))


class ClassifyCloseTest(unittest.TestCase):
    def test_matches_take_profit(self):
        status = autotrader._classify_close(exec_price=1.1050, tp_price=1.1050, sl_price=1.0950)
        self.assertEqual(status, "closed_tp")

    def test_matches_stop_loss(self):
        status = autotrader._classify_close(exec_price=1.0951, tp_price=1.1050, sl_price=1.0950)
        self.assertEqual(status, "closed_sl")

    def test_far_from_both_is_manual(self):
        status = autotrader._classify_close(exec_price=1.1200, tp_price=1.1050, sl_price=1.0950)
        self.assertEqual(status, "closed_manual")

    def test_no_exec_price_is_manual(self):
        self.assertEqual(autotrader._classify_close(None, 1.1050, 1.0950), "closed_manual")


class RuntimeToggleTest(unittest.TestCase):
    def tearDown(self):
        autotrader._runtime_enabled = bool(autotrader.AUTOTRADE_ENABLED)
        autotrader._kill_switch_tripped = False

    def test_enable_is_noop_when_config_disabled(self):
        with patch.object(autotrader, "AUTOTRADE_ENABLED", False):
            ok, _ = autotrader.enable()
        self.assertFalse(ok)
        self.assertFalse(autotrader.is_active())

    def test_enable_clears_kill_switch_when_config_enabled(self):
        autotrader._kill_switch_tripped = True
        with patch.object(autotrader, "AUTOTRADE_ENABLED", True):
            ok, _ = autotrader.enable()
            self.assertTrue(ok)
            self.assertFalse(autotrader._kill_switch_tripped)
            self.assertTrue(autotrader.is_active())

    def test_disable_deactivates_even_when_config_enabled(self):
        with patch.object(autotrader, "AUTOTRADE_ENABLED", True):
            autotrader.enable()
            autotrader.disable()
            self.assertFalse(autotrader.is_active())


if __name__ == "__main__":
    unittest.main()
