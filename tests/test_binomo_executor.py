import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import binomo_executor


class LoadAssetMapTest(unittest.TestCase):
    def test_loads_expected_pairs(self):
        asset_map = binomo_executor.load_asset_map()
        self.assertIn("EURUSD", asset_map)
        self.assertEqual(asset_map["EURUSD"]["binomo_name"], "EUR/USD")


class ParseNumericTextTest(unittest.TestCase):
    def test_ukrainian_locale_balance(self):
        # Comma decimal + space thousands separator, as shown live on the
        # Binomo balance display - a naive comma-strip previously produced
        # 35071200.0 instead of 350712.0 (100x too large).
        self.assertEqual(binomo_executor._parse_numeric_text("350 712,00 ₴"), 350712.0)

    def test_plain_integer_amount_field(self):
        self.assertEqual(binomo_executor._parse_numeric_text("₴4000"), 4000.0)

    def test_full_european_format(self):
        self.assertEqual(binomo_executor._parse_numeric_text("1.234,56"), 1234.56)

    def test_empty_or_unparseable_returns_none(self):
        self.assertIsNone(binomo_executor._parse_numeric_text("₴"))


class ResolveBinomoAssetNameTest(unittest.TestCase):
    _WEEKDAY = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)  # Monday
    _WEEKEND = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)  # Saturday

    def _patched_now(self, when):
        class _FixedDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return when

        return patch.object(binomo_executor, "datetime", _FixedDatetime)

    def test_weekday_prefers_plain_name(self):
        entry = {"binomo_name": "EUR/USD", "otc_name": "EUR/USD (OTC)"}
        with self._patched_now(self._WEEKDAY):
            self.assertEqual(binomo_executor._resolve_binomo_asset_name(entry), "EUR/USD")

    def test_weekend_prefers_otc_name(self):
        entry = {"binomo_name": "EUR/USD", "otc_name": "EUR/USD (OTC)"}
        with self._patched_now(self._WEEKEND):
            self.assertEqual(binomo_executor._resolve_binomo_asset_name(entry), "EUR/USD (OTC)")

    def test_weekend_falls_back_to_plain_name_when_no_otc(self):
        entry = {"binomo_name": "USD/CHF", "otc_name": None}
        with self._patched_now(self._WEEKEND):
            self.assertEqual(binomo_executor._resolve_binomo_asset_name(entry), "USD/CHF")

    def test_crypto_has_no_plain_name_any_day(self):
        entry = {"binomo_name": None, "otc_name": "Bitcoin (OTC)"}
        with self._patched_now(self._WEEKDAY):
            self.assertEqual(binomo_executor._resolve_binomo_asset_name(entry), "Bitcoin (OTC)")


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


class ClassifyOrUnknownTest(unittest.TestCase):
    def test_up_and_down(self):
        self.assertEqual(binomo_executor._classify_or_unknown(100.0, 101.0), "up")
        self.assertEqual(binomo_executor._classify_or_unknown(100.0, 99.0), "down")

    def test_unknown_when_price_missing(self):
        self.assertEqual(binomo_executor._classify_or_unknown(None, 101.0), "unknown")
        self.assertEqual(binomo_executor._classify_or_unknown(100.0, None), "unknown")


class CorrelationLogTest(unittest.TestCase):
    def test_writes_header_once_then_appends(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            log_path = binomo_executor.Path(tmp) / "correlation.csv"
            with patch.object(binomo_executor, "CORRELATION_LOG_PATH", log_path):
                row = {field: "x" for field in binomo_executor.CORRELATION_LOG_FIELDS}
                binomo_executor._append_correlation_log(row)
                binomo_executor._append_correlation_log(row)

            content = log_path.read_text(encoding="utf-8")
            lines = [line for line in content.splitlines() if line]
            self.assertEqual(len(lines), 3)  # header + 2 rows
            self.assertEqual(lines[0].split(",")[0], "logged_at")


if __name__ == "__main__":
    unittest.main()
