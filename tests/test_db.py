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


class RuntimeSettingTest(unittest.TestCase):
    """Real-DB round-trip (2026-08-19) for the generic AppRuntimeSetting
    store threshold_advisor.check_trade_count_milestones() uses to avoid
    re-notifying the same crossed milestone every day."""

    KEY = "zztest_runtime_setting"

    def tearDown(self):
        db.set_runtime_setting(self.KEY, None)

    def test_missing_key_returns_none(self):
        self.assertIsNone(db.get_runtime_setting(self.KEY))

    def test_set_then_get_round_trips(self):
        self.assertTrue(db.set_runtime_setting(self.KEY, "1"))
        self.assertEqual(db.get_runtime_setting(self.KEY), "1")

    def test_overwriting_replaces_the_value(self):
        db.set_runtime_setting(self.KEY, "1")
        db.set_runtime_setting(self.KEY, "2")
        self.assertEqual(db.get_runtime_setting(self.KEY), "2")


class CountSettledBinomoTradesTest(unittest.TestCase):
    """Real-DB test (2026-08-19), same isolation principle as the other
    BinomoTrade e2e tests - a distinctive fake account_mode, purged in
    setUp/tearDown, so this can never touch real demo/live trade counts."""

    ACCOUNT_MODE = "zzcount"  # account_mode is VARCHAR(8) in the real schema

    def setUp(self):
        self._purge()

    def tearDown(self):
        self._purge()

    def _purge(self):
        with db.get_db() as session:
            if session is None:
                return
            rows = session.query(db.BinomoTrade).filter(
                db.BinomoTrade.account_mode == self.ACCOUNT_MODE
            ).all()
            for row in rows:
                session.delete(row)
            session.commit()

    def _make_trade(self, result):
        trade_id = db.create_binomo_trade(
            asset="EUR/USD", pair="EURUSD", direction="up", amount=10.0,
            expiry_seconds=300, account_mode=self.ACCOUNT_MODE,
        )
        if result is not None:
            with db.get_db() as session:
                row = session.query(db.BinomoTrade).filter(db.BinomoTrade.id == trade_id).first()
                row.result = result
                session.commit()
        return trade_id

    def test_counts_only_win_and_loss_not_pending(self):
        self._make_trade("win")
        self._make_trade("loss")
        self._make_trade(None)  # stays "pending"

        self.assertEqual(db.count_settled_binomo_trades(self.ACCOUNT_MODE), 2)

    def test_does_not_leak_into_other_account_modes(self):
        self._make_trade("win")
        self.assertEqual(db.count_settled_binomo_trades(self.ACCOUNT_MODE), 1)
        self.assertEqual(db.count_settled_binomo_trades("some-other-mode-entirely"), 0)


if __name__ == "__main__":
    unittest.main()
