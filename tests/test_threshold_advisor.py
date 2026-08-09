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


if __name__ == "__main__":
    unittest.main()
