import unittest
from unittest.mock import patch

import scanner
from state import app_state


class HandleAnalysisResultPriceSanityTest(unittest.TestCase):
    """HOTFIX (2026-08-17, critical, active incident): confirmed live -
    EURUSD BUY signals on 5m kept firing with entry_price stuck at exactly
    1.10000 (~4.3% off the real live price), and scanner.py published that
    same result to the SSE stream binomo_executor.py --run consumes
    BEFORE recording it. These tests prove the price-sanity guard blocks
    both the SSE publish and the outcome-tracking write for an implausible
    price, without touching the DB (deferToThreadPool is mocked out - it's
    never reached on this path anyway)."""

    def setUp(self):
        self._saved_threshold = app_state.IDEAL_ENTRY_THRESHOLD
        app_state.IDEAL_ENTRY_THRESHOLD = 78

    def tearDown(self):
        app_state.IDEAL_ENTRY_THRESHOLD = self._saved_threshold
        app_state.scanner_cooldown_cache.pop("EURUSD", None)

    def _signal_result(self, price: float, live_mid: float) -> dict:
        # verdict/score chosen only to clear is_signal's own gate (SELL +
        # score >= threshold) - the price-sanity guard is what's under
        # test, not the verdict/score mapping itself.
        return {
            "verdict_text": "SELL",
            "score": 90,
            "sentiment": "GO",
            "is_trade_allowed": True,
            "price": price,
            "data_status": {"price": {"mid": live_mid}},
            "timeframe": "5m",
        }

    def test_implausible_price_is_not_published_or_recorded(self):
        result = self._signal_result(price=1.10000, live_mid=1.15800)

        with patch.object(app_state, "publish_signal_sse") as mock_publish, \
             patch.object(scanner, "notify_admin") as mock_notify, \
             patch.object(scanner, "deferToThreadPool") as mock_defer:
            d = scanner._handle_analysis_result("EURUSD", result)

        self.assertTrue(d.called)
        self.assertIsNone(d.result)
        mock_publish.assert_not_called()
        mock_defer.assert_not_called()
        mock_notify.assert_called_once()

    def test_plausible_price_is_published_normally(self):
        result = self._signal_result(price=1.15800, live_mid=1.15810)

        with patch.object(app_state, "publish_signal_sse") as mock_publish, \
             patch.object(scanner, "notify_admin") as mock_notify, \
             patch.object(scanner, "deferToThreadPool") as mock_defer:
            scanner._handle_analysis_result("EURUSD", result)

        mock_publish.assert_called_once()
        mock_notify.assert_not_called()
        # deferToThreadPool fires for both maybe_record_signal and the
        # Telegram send_signal call - the sanity guard isn't blocking
        # either, unlike the implausible-price case above.
        self.assertTrue(mock_defer.called)


if __name__ == "__main__":
    unittest.main()
