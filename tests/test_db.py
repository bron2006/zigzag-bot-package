import unittest
from types import SimpleNamespace

import db


def _row(verdict, outcome, entry_price, exit_price=None):
    return SimpleNamespace(verdict=verdict, outcome=outcome, entry_price=entry_price, exit_price=exit_price)


class BinomoStyleDirectionTest(unittest.TestCase):
    """Binomo has no push/flat - any price difference, however small,
    settles as a win or loss. These cover that a row the forex-oriented
    classification calls 'flat' still gets a definite direction here."""

    def test_buy_wins_on_any_upward_move(self):
        row = _row("BUY", "flat", 100.0, 100.00001)
        self.assertTrue(db._binomo_style_direction(row))

    def test_buy_loses_on_any_downward_move(self):
        row = _row("BUY", "flat", 100.0, 99.99999)
        self.assertFalse(db._binomo_style_direction(row))

    def test_sell_wins_on_any_downward_move(self):
        row = _row("SELL", "flat", 100.0, 99.99999)
        self.assertTrue(db._binomo_style_direction(row))

    def test_sell_loses_on_any_upward_move(self):
        row = _row("SELL", "flat", 100.0, 100.00001)
        self.assertFalse(db._binomo_style_direction(row))

    def test_agrees_with_forex_classification_outside_the_noise_band(self):
        # A row already classified 'up'/'down' (moved past the noise
        # threshold) must get the same verdict here, not just flat ones.
        row = _row("BUY", "up", 100.0, 105.0)
        self.assertTrue(db._binomo_style_direction(row))

    def test_pending_row_returns_none(self):
        row = _row("BUY", "pending", 100.0, None)
        self.assertIsNone(db._binomo_style_direction(row))

    def test_legacy_outcome_returns_none(self):
        row = _row("BUY", "timeout", 100.0, 101.0)
        self.assertIsNone(db._binomo_style_direction(row))


class AggregateSignalOutcomesBinomoStyleTest(unittest.TestCase):
    def test_flat_rows_are_split_into_wins_and_losses_not_excluded(self):
        rows = [
            _row("BUY", "flat", 100.0, 100.00001),  # tiny win
            _row("BUY", "flat", 100.0, 99.99999),   # tiny loss
            _row("SELL", "up", 100.0, 90.0),          # already-decided win
        ]
        agg = db._aggregate_signal_outcomes_binomo_style(rows)
        self.assertEqual(agg["wins"], 2)
        self.assertEqual(agg["losses"], 1)
        self.assertEqual(agg["flats"], 0)
        self.assertEqual(agg["win_rate"], round(100.0 * 2 / 3, 1))

    def test_pending_and_legacy_rows_excluded_from_win_rate(self):
        rows = [
            _row("BUY", "pending", 100.0, None),
            _row("BUY", "timeout", 100.0, 101.0),
            _row("BUY", "up", 100.0, 101.0),
        ]
        agg = db._aggregate_signal_outcomes_binomo_style(rows)
        self.assertEqual(agg["wins"], 1)
        self.assertEqual(agg["losses"], 0)
        self.assertEqual(agg["pending"], 1)
        self.assertEqual(agg["win_rate"], 100.0)

    def test_empty_rows_give_none_win_rate(self):
        agg = db._aggregate_signal_outcomes_binomo_style([])
        self.assertIsNone(agg["win_rate"])
        self.assertEqual(agg["total"], 0)


if __name__ == "__main__":
    unittest.main()
