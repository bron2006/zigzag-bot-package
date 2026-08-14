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


class GetSignalOutcomeRowsForBacktestTest(unittest.TestCase):
    """Real-DB test for backtest.py's data source (2026-08-14). SignalOutcome
    has no account_mode-style scoping column (unlike BinomoTrade), so this
    scopes by a pair name distinctive enough to never collide with real
    signals, and purges by that name in setUp/tearDown - same isolation
    principle as the BinomoTrade e2e tests, different mechanism."""

    PAIR = "ZZTESTPAIR"

    def setUp(self):
        self._purge()

    def tearDown(self):
        self._purge()

    def _purge(self):
        with db.get_db() as session:
            if session is None:
                return
            rows = session.query(db.SignalOutcome).filter(db.SignalOutcome.pair == self.PAIR).all()
            for row in rows:
                session.delete(row)
            session.commit()

    def test_only_returns_directional_verdicts_oldest_first(self):
        db.create_signal_outcome(pair=self.PAIR, timeframe="5m", verdict="SELL", score=80, entry_price=2.0, horizon_seconds=300)
        db.create_signal_outcome(pair=self.PAIR, timeframe="5m", verdict="BUY", score=90, entry_price=1.0, horizon_seconds=300)
        db.create_signal_outcome(pair=self.PAIR, timeframe="5m", verdict="NEUTRAL", score=50, entry_price=1.5, horizon_seconds=300)

        rows = db.get_signal_outcome_rows_for_backtest(days=1, pairs=[self.PAIR])

        self.assertEqual([r["verdict"] for r in rows], ["SELL", "BUY"])
        self.assertEqual([r["entry_price"] for r in rows], [2.0, 1.0])

    def test_pairs_filter_excludes_other_pairs(self):
        db.create_signal_outcome(pair=self.PAIR, timeframe="5m", verdict="BUY", score=80, entry_price=1.0, horizon_seconds=300)
        db.create_signal_outcome(pair="EURUSD", timeframe="5m", verdict="BUY", score=80, entry_price=1.1, horizon_seconds=300)

        rows = db.get_signal_outcome_rows_for_backtest(days=1, pairs=[self.PAIR])

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["pair"], self.PAIR)

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
