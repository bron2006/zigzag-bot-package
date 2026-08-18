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

    def test_placeholder_entry_price_is_blocked_even_when_live_mid_agrees(self):
        # PLACEHOLDER GUARD (2026-08-18): confirmed live that the same
        # 1.10000 fingerprint recurred a full day after the fail-closed
        # fix went live - the leading theory is that whatever corrupts
        # entry_price also corrupts (or shares a stale source with)
        # live_mid at that same instant, so the two "agree" and the plain
        # divergence check below finds nothing wrong. A live_mid that
        # matches the placeholder exactly must NOT save it from blocking.
        result = {"price": 1.10000, "data_status": {"price": {"mid": 1.10000}}}
        reason = signal_tracking.price_sanity_reason(result)
        self.assertIsNotNone(reason)
        self.assertIn("1.10000", reason)

    def test_placeholder_1_0_is_blocked_regardless_of_live_mid(self):
        result = {"price": 1.0, "data_status": {"price": {"mid": 1.0}}}
        self.assertIsNotNone(signal_tracking.price_sanity_reason(result))

    def test_placeholder_0_0_is_blocked_not_treated_as_nothing_to_check(self):
        # Previously entry_price<=0 short-circuited to "nothing to check
        # yet" (None) - 0.0 is one of the confirmed placeholder values, so
        # it must now be blocked instead of silently waved through.
        result = {"price": 0.0, "data_status": {"price": {"mid": 0.0}}}
        self.assertIsNotNone(signal_tracking.price_sanity_reason(result))

    def test_a_realistic_price_that_happens_to_be_round_is_not_blocked(self):
        # Only the three confirmed placeholder values are blocked outright
        # - an ordinary plausible price must not get caught by an
        # overzealous "looks round" heuristic.
        result = {"price": 1.15000, "data_status": {"price": {"mid": 1.15010}}}
        self.assertIsNone(signal_tracking.price_sanity_reason(result))


if __name__ == "__main__":
    unittest.main()
