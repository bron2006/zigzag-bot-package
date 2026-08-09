import unittest
from unittest.mock import patch

import binomo_executor


class LoadAssetMapTest(unittest.TestCase):
    def test_loads_expected_pairs(self):
        asset_map = binomo_executor.load_asset_map()
        self.assertIn("EURUSD", asset_map)
        self.assertEqual(asset_map["EURUSD"]["binomo_name"], "EUR/USD")


class IsActiveTest(unittest.TestCase):
    def test_false_when_config_disabled(self):
        with patch.object(binomo_executor.config, "BINOMO_EXECUTOR_ENABLED", False):
            self.assertFalse(binomo_executor.is_active())

    def test_false_when_kill_switch_tripped(self):
        with patch.object(binomo_executor.config, "BINOMO_EXECUTOR_ENABLED", True), \
             patch.object(binomo_executor.db, "get_binomo_runtime_state", return_value={
                 "runtime_enabled": True, "kill_switch_tripped": True, "kill_switch_reason": "x",
             }):
            self.assertFalse(binomo_executor.is_active())

    def test_true_when_enabled_and_not_tripped(self):
        with patch.object(binomo_executor.config, "BINOMO_EXECUTOR_ENABLED", True), \
             patch.object(binomo_executor.db, "get_binomo_runtime_state", return_value={
                 "runtime_enabled": True, "kill_switch_tripped": False, "kill_switch_reason": None,
             }):
            self.assertTrue(binomo_executor.is_active())


class CheckRiskLimitsTest(unittest.TestCase):
    def _patch_db(self, *, trades_today=0, consecutive_losses=0, daily_pnl=0.0):
        return patch.multiple(
            binomo_executor.db,
            count_binomo_trades_today=lambda mode: trades_today,
            get_consecutive_binomo_losses=lambda mode: consecutive_losses,
            get_daily_binomo_pnl=lambda mode: daily_pnl,
        )

    def test_blocks_on_max_trades_per_day(self):
        with patch.object(binomo_executor.config, "BINOMO_MAX_TRADES_PER_DAY", 5), \
             self._patch_db(trades_today=5):
            reason = binomo_executor._check_risk_limits(balance=1000.0)
        self.assertIsNotNone(reason)
        self.assertIn("MAX_TRADES_PER_DAY", reason)

    def test_blocks_and_trips_on_consecutive_losses(self):
        with patch.object(binomo_executor.config, "BINOMO_MAX_TRADES_PER_DAY", 100), \
             patch.object(binomo_executor.config, "BINOMO_MAX_CONSECUTIVE_LOSSES", 3), \
             patch.object(binomo_executor, "_trip_kill_switch") as trip, \
             self._patch_db(consecutive_losses=3):
            reason = binomo_executor._check_risk_limits(balance=1000.0)
        self.assertIsNotNone(reason)
        trip.assert_called_once()

    def test_blocks_and_trips_on_daily_loss(self):
        with patch.object(binomo_executor.config, "BINOMO_MAX_TRADES_PER_DAY", 100), \
             patch.object(binomo_executor.config, "BINOMO_MAX_CONSECUTIVE_LOSSES", 100), \
             patch.object(binomo_executor.config, "BINOMO_MAX_DAILY_LOSS_PERCENT", 5.0), \
             patch.object(binomo_executor, "_trip_kill_switch") as trip, \
             self._patch_db(daily_pnl=-60.0):
            reason = binomo_executor._check_risk_limits(balance=1000.0)  # 5% of 1000 = 50
        self.assertIsNotNone(reason)
        trip.assert_called_once()

    def test_allows_when_within_limits(self):
        with patch.object(binomo_executor.config, "BINOMO_MAX_TRADES_PER_DAY", 100), \
             patch.object(binomo_executor.config, "BINOMO_MAX_CONSECUTIVE_LOSSES", 100), \
             patch.object(binomo_executor.config, "BINOMO_MAX_DAILY_LOSS_PERCENT", 5.0), \
             self._patch_db(trades_today=1, consecutive_losses=0, daily_pnl=10.0):
            reason = binomo_executor._check_risk_limits(balance=1000.0)
        self.assertIsNone(reason)


class SignalStreamUrlTest(unittest.TestCase):
    def test_raises_without_admin_token(self):
        with patch.object(binomo_executor.config, "get_admin_access_token", return_value=None):
            with self.assertRaises(RuntimeError):
                binomo_executor._signal_stream_url()

    def test_builds_url_with_token(self):
        with patch.object(binomo_executor.config, "get_admin_access_token", return_value="tok123"), \
             patch.object(binomo_executor.config, "get_public_base_url", return_value="https://example.fly.dev"):
            url = binomo_executor._signal_stream_url()
        self.assertEqual(url, "https://example.fly.dev/api/signal-stream?admin_token=tok123")


if __name__ == "__main__":
    unittest.main()
