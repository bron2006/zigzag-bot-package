import unittest
from unittest.mock import patch

import threshold_advisor
from state import app_state


class ThresholdAdvisorTest(unittest.TestCase):
    def setUp(self):
        self._orig_threshold = app_state.IDEAL_ENTRY_THRESHOLD
        app_state.IDEAL_ENTRY_THRESHOLD = 75

    def tearDown(self):
        app_state.IDEAL_ENTRY_THRESHOLD = self._orig_threshold

    def test_no_data_returns_none(self):
        with patch.object(threshold_advisor.db, "get_signal_outcome_score_breakdown", return_value=[]):
            self.assertIsNone(threshold_advisor.build_recommendation())

    def test_insufficient_samples_returns_none(self):
        buckets = [{"bucket_start": 75, "wins": 2, "losses": 1, "win_rate": 66.7}]
        with patch.object(threshold_advisor.db, "get_signal_outcome_score_breakdown", return_value=buckets):
            self.assertIsNone(threshold_advisor.build_recommendation())

    def test_recommends_higher_threshold_when_clearly_better(self):
        buckets = [
            {"bucket_start": 75, "wins": 15, "losses": 15, "win_rate": 50.0},
            {"bucket_start": 80, "wins": 20, "losses": 5, "win_rate": 80.0},
            {"bucket_start": 85, "wins": 10, "losses": 2, "win_rate": 83.3},
        ]
        with patch.object(threshold_advisor.db, "get_signal_outcome_score_breakdown", return_value=buckets):
            message = threshold_advisor.build_recommendation()

        self.assertIsNotNone(message)
        self.assertIn("Спробуй поріг 80", message)

    def test_no_recommendation_when_current_is_already_best(self):
        buckets = [
            {"bucket_start": 75, "wins": 25, "losses": 5, "win_rate": 83.3},
        ]
        with patch.object(threshold_advisor.db, "get_signal_outcome_score_breakdown", return_value=buckets):
            message = threshold_advisor.build_recommendation()

        self.assertIsNotNone(message)
        self.assertIn("не знайдено", message)


class CheckTradeCountMilestonesTest(unittest.TestCase):
    """CLAUDE.md threshold-review protocol (2026-08-19): a one-time-per-
    milestone reminder, not a decision-maker - proves it fires exactly
    once per crossed milestone and never repeats once notified."""

    def _run(self, total, already_notified):
        with patch.object(threshold_advisor.db, "count_settled_binomo_trades", return_value=total), \
             patch.object(threshold_advisor.db, "get_runtime_setting",
                           side_effect=lambda key: "1" if key in already_notified else None) as mock_get, \
             patch.object(threshold_advisor.db, "set_runtime_setting") as mock_set, \
             patch("notifier.notify_admin") as mock_notify:
            threshold_advisor.check_trade_count_milestones()
        return mock_get, mock_set, mock_notify

    def test_below_every_milestone_notifies_nothing(self):
        _, mock_set, mock_notify = self._run(total=150, already_notified=set())
        mock_notify.assert_not_called()
        mock_set.assert_not_called()

    def test_crossing_300_notifies_once_and_persists_the_flag(self):
        _, mock_set, mock_notify = self._run(total=310, already_notified=set())
        mock_notify.assert_called_once()
        mock_set.assert_called_once_with("threshold_milestone_notified_300", "1")

    def test_already_notified_for_300_does_not_repeat(self):
        _, mock_set, mock_notify = self._run(total=350, already_notified={"threshold_milestone_notified_300"})
        mock_notify.assert_not_called()
        mock_set.assert_not_called()

    def test_crossing_both_milestones_at_once_notifies_both(self):
        _, mock_set, mock_notify = self._run(total=520, already_notified=set())
        self.assertEqual(mock_notify.call_count, 2)
        self.assertEqual(mock_set.call_count, 2)

    def test_only_the_new_milestone_notifies_when_300_already_seen(self):
        _, mock_set, mock_notify = self._run(total=520, already_notified={"threshold_milestone_notified_300"})
        mock_notify.assert_called_once()
        mock_set.assert_called_once_with("threshold_milestone_notified_500", "1")


if __name__ == "__main__":
    unittest.main()
