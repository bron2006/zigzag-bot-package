import time
import unittest
from unittest.mock import patch

import config
import db
import scanner
import telegram_ui
from state import app_state


class HandleAnalysisResultLanguageTest(unittest.TestCase):
    """AUDIT FIX (2026-08-18): _format_signal_message/get_main_menu_kb both
    default lang="en" and scanner.py used to call them with no lang at all
    - every scanner-pushed signal ignored a user's own /language choice and
    always rendered in English. These prove the user's saved language is
    looked up and passed through for both the message text and the
    keyboard."""

    def setUp(self):
        self._saved_threshold = app_state.IDEAL_ENTRY_THRESHOLD
        app_state.IDEAL_ENTRY_THRESHOLD = 78

    def tearDown(self):
        app_state.IDEAL_ENTRY_THRESHOLD = self._saved_threshold
        app_state.scanner_cooldown_cache.pop("EURUSD", None)

    def _signal_result(self) -> dict:
        return {
            "verdict_text": "SELL",
            "score": 90,
            "sentiment": "GO",
            "is_trade_allowed": True,
            "price": 1.15800,
            "data_status": {"price": {"mid": 1.15810}},
            "timeframe": "5m",
        }

    def test_saved_ukrainian_preference_is_passed_to_message_and_keyboard(self):
        with patch.object(app_state, "publish_signal_sse"), \
             patch.object(scanner, "notify_admin"), \
             patch.object(scanner, "deferToThreadPool"), \
             patch.object(db, "get_user_language", return_value="uk"), \
             patch.object(telegram_ui, "_format_signal_message", return_value="msg") as mock_fmt, \
             patch.object(telegram_ui, "get_main_menu_kb", return_value="kb") as mock_kb:
            scanner._handle_analysis_result("EURUSD", self._signal_result())

        mock_fmt.assert_called_once()
        self.assertEqual(mock_fmt.call_args.args[2], "uk")
        mock_kb.assert_called_once_with("uk")

    def test_no_saved_preference_falls_back_to_default_lang(self):
        with patch.object(app_state, "publish_signal_sse"), \
             patch.object(scanner, "notify_admin"), \
             patch.object(scanner, "deferToThreadPool"), \
             patch.object(db, "get_user_language", return_value=None), \
             patch.object(telegram_ui, "_format_signal_message", return_value="msg") as mock_fmt, \
             patch.object(telegram_ui, "get_main_menu_kb", return_value="kb") as mock_kb:
            scanner._handle_analysis_result("EURUSD", self._signal_result())

        expected_default = telegram_ui.normalize_lang(None)
        self.assertEqual(mock_fmt.call_args.args[2], expected_default)
        mock_kb.assert_called_once_with(expected_default)


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


class TakeBatchTest(unittest.TestCase):
    """_take_batch is the pure helper shared by the main and crypto
    rotations (2026-08-17, per external consultation) - no globals, so it's
    testable directly without touching scanner module state."""

    def test_small_list_returns_everything_and_resets_the_cursor(self):
        batch, cursor = scanner._take_batch(["A", "B"], cursor=5, batch_size=8)
        self.assertEqual(batch, ["A", "B"])
        self.assertEqual(cursor, 0)

    def test_rotates_across_calls_and_wraps_around(self):
        assets = [f"P{i}" for i in range(10)]

        batch1, cursor1 = scanner._take_batch(assets, cursor=0, batch_size=4)
        self.assertEqual(batch1, ["P0", "P1", "P2", "P3"])

        batch2, cursor2 = scanner._take_batch(assets, cursor=cursor1, batch_size=4)
        self.assertEqual(batch2, ["P4", "P5", "P6", "P7"])

        batch3, _ = scanner._take_batch(assets, cursor=cursor2, batch_size=4)
        self.assertEqual(batch3, ["P8", "P9", "P0", "P1"])

    def test_empty_list_returns_empty_batch(self):
        batch, cursor = scanner._take_batch([], cursor=3, batch_size=4)
        self.assertEqual(batch, [])
        self.assertEqual(cursor, 0)


class CollectAssetsCryptoSplitTest(unittest.TestCase):
    """Crypto pairs get a dedicated, faster-cadence loop (2026-08-17, per
    external consultation) instead of sharing the main loop's single
    rotation - _collect_assets_to_scan must never include them, even with
    the crypto toggle on."""

    def setUp(self):
        self._saved_state = dict(app_state.SCANNER_STATE)

    def tearDown(self):
        app_state.SCANNER_STATE.clear()
        app_state.SCANNER_STATE.update(self._saved_state)

    def test_main_collector_excludes_crypto_even_when_enabled(self):
        app_state.SCANNER_STATE["forex"] = False
        app_state.SCANNER_STATE["crypto"] = True
        app_state.SCANNER_STATE["commodities"] = False
        app_state.SCANNER_STATE["watchlist"] = False

        assets = scanner._collect_assets_to_scan()

        crypto_keys = {p.replace("/", "").upper() for p in config.CRYPTO_PAIRS}
        self.assertEqual(set(assets) & crypto_keys, set())

    def test_crypto_collector_is_empty_when_disabled(self):
        app_state.SCANNER_STATE["crypto"] = False
        self.assertEqual(scanner._collect_crypto_assets_to_scan(), [])

    def test_crypto_collector_returns_all_crypto_pairs_when_enabled(self):
        app_state.SCANNER_STATE["crypto"] = True
        assets = scanner._collect_crypto_assets_to_scan()
        self.assertEqual(len(assets), len(config.CRYPTO_PAIRS))


class ScanCryptoOnceTest(unittest.TestCase):
    def setUp(self):
        self._saved_crypto_state = app_state.SCANNER_STATE.get("crypto")
        self._saved_cursor = scanner._crypto_scan_cursor
        self._saved_active = scanner._crypto_scan_active
        self._saved_paused_until = scanner._scanner_paused_until
        scanner._crypto_scan_cursor = 0
        scanner._crypto_scan_active = False
        scanner._scanner_paused_until = 0.0

    def tearDown(self):
        app_state.SCANNER_STATE["crypto"] = self._saved_crypto_state
        scanner._crypto_scan_cursor = self._saved_cursor
        scanner._crypto_scan_active = self._saved_active
        scanner._scanner_paused_until = self._saved_paused_until

    def test_does_nothing_when_crypto_is_disabled(self):
        app_state.SCANNER_STATE["crypto"] = False
        with patch.object(scanner, "_process_one_asset") as mock_process:
            scanner.scan_crypto_once()
        mock_process.assert_not_called()

    def test_processes_a_batch_when_crypto_is_enabled(self):
        from twisted.internet.defer import succeed

        app_state.SCANNER_STATE["crypto"] = True
        with patch.object(scanner, "_process_one_asset", return_value=succeed(None)) as mock_process:
            scanner.scan_crypto_once()

        self.assertTrue(mock_process.called)
        self.assertLessEqual(mock_process.call_count, config.SCANNER_CRYPTO_BATCH_SIZE)

    def test_skips_while_a_previous_cycle_is_still_running(self):
        app_state.SCANNER_STATE["crypto"] = True
        scanner._crypto_scan_active = True

        with patch.object(scanner, "_process_one_asset") as mock_process:
            scanner.scan_crypto_once()

        mock_process.assert_not_called()

    def test_respects_the_shared_rate_limit_pause(self):
        app_state.SCANNER_STATE["crypto"] = True
        scanner._scanner_paused_until = time.time() + 60

        with patch.object(scanner, "_process_one_asset") as mock_process:
            scanner.scan_crypto_once()

        mock_process.assert_not_called()


if __name__ == "__main__":
    unittest.main()
