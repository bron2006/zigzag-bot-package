import unittest
from types import SimpleNamespace
from unittest.mock import patch

import autotrader
import db


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
    """AUDIT FIX (2026-08-15, critical): is_active()/enable()/disable() used
    to read/write bare Python module globals (_runtime_enabled,
    _kill_switch_tripped) - a process restart or Fly.io redeploy silently
    reset both, resuming automated real order placement with zero admin
    action, directly contradicting this module's own docstring promise
    that the kill switch "stays stopped... until an admin explicitly runs
    /autotrade_on again". Runs against the REAL db.py AppRuntimeSetting
    table (same mechanism binomo_executor.py's kill switch already uses),
    not mocks - a mock would only prove the plumbing is wired, not that
    the state actually survives outside the process. setUp/tearDown save
    and restore whatever was really there before, so this can never leave
    the real autotrade runtime state in a dirty condition."""

    def setUp(self):
        self._saved_state = db.get_autotrade_runtime_state()

    def tearDown(self):
        db.set_autotrade_runtime_enabled(self._saved_state["runtime_enabled"])
        if self._saved_state["kill_switch_tripped"]:
            db.trip_autotrade_kill_switch(self._saved_state["kill_switch_reason"] or "restored after RuntimeToggleTest")
        else:
            db.clear_autotrade_kill_switch()

    def test_enable_is_noop_when_config_disabled(self):
        with patch.object(autotrader, "AUTOTRADE_ENABLED", False):
            ok, _ = autotrader.enable()
        self.assertFalse(ok)
        self.assertFalse(autotrader.is_active())

    def test_enable_clears_kill_switch_when_config_enabled(self):
        db.trip_autotrade_kill_switch("test trip")
        with patch.object(autotrader, "AUTOTRADE_ENABLED", True):
            ok, _ = autotrader.enable()
            self.assertTrue(ok)
            self.assertFalse(db.get_autotrade_runtime_state()["kill_switch_tripped"])
            self.assertTrue(autotrader.is_active())

    def test_disable_deactivates_even_when_config_enabled(self):
        with patch.object(autotrader, "AUTOTRADE_ENABLED", True):
            autotrader.enable()
            autotrader.disable()
            self.assertFalse(autotrader.is_active())

    def test_state_is_read_fresh_from_the_db_not_a_process_local_cache(self):
        # Proves the actual fix: nothing in autotrader.py's own namespace
        # holds this state anymore - is_active() must reflect whatever the
        # real DB row says, exactly as a fresh process (post-restart)
        # reading it for the first time would see it.
        with patch.object(autotrader, "AUTOTRADE_ENABLED", True):
            db.set_autotrade_runtime_enabled(True)
            db.clear_autotrade_kill_switch()
            self.assertTrue(autotrader.is_active())

            db.trip_autotrade_kill_switch("simulated trip from another process")
            self.assertFalse(autotrader.is_active())

    def test_trip_kill_switch_persists_the_reason(self):
        # _notify_admin_async stays mocked here for the same reason the
        # Binomo kill-switch tests mock notify_admin: it dispatches via
        # deferToThreadPool, which can actually run and page the real admin
        # even outside a running reactor - confirmed live earlier this
        # session for the Binomo equivalent (duplicate real Telegram
        # alerts from a bare test run).
        with patch.object(autotrader, "_notify_admin_async"):
            autotrader._trip_kill_switch(daily_pnl=-500.0, max_daily_loss=400.0)
        state = db.get_autotrade_runtime_state()
        self.assertTrue(state["kill_switch_tripped"])
        self.assertIn("-500.00", state["kill_switch_reason"])


if __name__ == "__main__":
    unittest.main()
