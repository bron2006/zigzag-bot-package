import unittest
from unittest.mock import patch

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

    def test_skips_and_alerts_on_implausible_price(self):
        # HOTFIX (2026-08-17): reproduces the active incident - EURUSD BUY
        # signals recorded with entry_price stuck at 1.10000 while the
        # live tick was ~1.158 (a ~4.3% gap). Must skip recording and
        # alert the admin, not write a poisoned SignalOutcome row.
        result = {
            "is_trade_allowed": True,
            "verdict_text": "BUY",
            "pair": "EURUSD",
            "price": 1.10000,
            "timeframe": "5m",
            "data_status": {"price": {"mid": 1.15800}},
        }
        with patch.object(signal_tracking, "notify_admin") as mock_notify:
            self.assertIsNone(signal_tracking.maybe_record_signal(result))
        mock_notify.assert_called_once()


class PriceSanityReasonTest(unittest.TestCase):
    def test_matching_prices_are_plausible(self):
        result = {"price": 1.15800, "data_status": {"price": {"mid": 1.15810}}}
        self.assertIsNone(signal_tracking.price_sanity_reason(result))

    def test_reproduces_the_eurusd_incident(self):
        result = {"price": 1.10000, "data_status": {"price": {"mid": 1.15800}}}
        reason = signal_tracking.price_sanity_reason(result)
        self.assertIsNotNone(reason)
        self.assertIn("1.10000", reason)

    def test_missing_live_mid_is_fail_closed_not_nothing_to_compare(self):
        # FAIL-CLOSED (2026-08-17, same-day follow-up): the original
        # fail-open version of this check let 7 more corrupted EURUSD
        # signals through after the hotfix deployed, all with
        # data_status.price.mid unavailable - this must now block, not
        # silently allow through.
        result = {"price": 1.10000, "data_status": {"price": {"mid": None}}}
        reason = signal_tracking.price_sanity_reason(result)
        self.assertIsNotNone(reason)
        self.assertIn("1.10000", reason)

    def test_missing_data_status_is_fail_closed_not_nothing_to_compare(self):
        reason = signal_tracking.price_sanity_reason({"price": 1.10000})
        self.assertIsNotNone(reason)
        self.assertIn("1.10000", reason)

    def test_missing_entry_price_has_nothing_to_check_yet(self):
        # Distinct from a missing live_mid: with no entry_price at all,
        # there's nothing to sanity-check - that's maybe_record_signal's/
        # scanner.py's own gating to handle, not this function's job.
        result = {"price": None, "data_status": {"price": {"mid": 1.15800}}}
        self.assertIsNone(signal_tracking.price_sanity_reason(result))

    def test_small_divergence_is_within_tolerance(self):
        # A few hundredths of a percent - normal instant timing/bid-ask
        # noise between the trendbar close and the live tick.
        result = {"price": 1.15800, "data_status": {"price": {"mid": 1.15850}}}
        self.assertIsNone(signal_tracking.price_sanity_reason(result))


if __name__ == "__main__":
    unittest.main()
