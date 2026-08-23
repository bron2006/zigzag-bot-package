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


class BinomoTradeExpiryMismatchTest(unittest.TestCase):
    """Real-DB test (2026-08-21), same isolation principle as
    CountSettledBinomoTradesTest above - a distinctive fake account_mode,
    purged in setUp/tearDown. Covers the requested_expiry_seconds/
    expiry_mismatch columns added per execution_gap_audit.py's Task 3
    finding: Binomo's expiry stepper doesn't always land on the exact
    requested duration (15/198 real trades), and that used to only be
    mentioned in a transient Telegram message - now a queryable column,
    so future win-rate/calibration analysis can filter or segment on it
    directly instead of re-deriving it via signal matching each time."""

    ACCOUNT_MODE = "zzexpiry"  # account_mode is VARCHAR(8) in the real schema

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

    def _make_trade(self, expiry_seconds=300):
        return db.create_binomo_trade(
            asset="EUR/USD", pair="EURUSD", direction="up", amount=10.0,
            expiry_seconds=expiry_seconds, account_mode=self.ACCOUNT_MODE,
        )

    def test_requested_expiry_seconds_is_captured_at_creation(self):
        trade_id = self._make_trade(expiry_seconds=300)
        trade = db.get_binomo_trade(trade_id)
        self.assertEqual(trade["requested_expiry_seconds"], 300)
        self.assertEqual(trade["expiry_seconds"], 300)
        self.assertFalse(trade["expiry_mismatch"])

    def test_matching_actual_expiry_leaves_mismatch_false(self):
        trade_id = self._make_trade(expiry_seconds=300)
        db.update_binomo_trade_expiry_seconds(trade_id, 300)

        trade = db.get_binomo_trade(trade_id)
        self.assertEqual(trade["requested_expiry_seconds"], 300)
        self.assertEqual(trade["expiry_seconds"], 300)
        self.assertFalse(trade["expiry_mismatch"])

    def test_differing_actual_expiry_sets_mismatch_true_and_preserves_requested(self):
        trade_id = self._make_trade(expiry_seconds=300)
        # Binomo's picker landed on 720s instead of the requested 300s -
        # a real live example from execution_gap_audit.py's Task 3.
        db.update_binomo_trade_expiry_seconds(trade_id, 720)

        trade = db.get_binomo_trade(trade_id)
        self.assertEqual(trade["requested_expiry_seconds"], 300, "original request must not be overwritten")
        self.assertEqual(trade["expiry_seconds"], 720, "actual duration is what due_at math needs")
        self.assertTrue(trade["expiry_mismatch"])


class VwapTradeCrudTest(unittest.TestCase):
    """Real-DB tests (Крок 3.1, 2026-08-22) for the VwapTrade table - same
    isolation principle as the BinomoTrade e2e tests above: a distinctive
    fake account_mode, purged in setUp/tearDown."""

    ACCOUNT_MODE = "zzvwap"  # account_mode is VARCHAR(8) in the real schema

    def setUp(self):
        self._purge()

    def tearDown(self):
        self._purge()

    def _purge(self):
        with db.get_db() as session:
            if session is None:
                return
            rows = session.query(db.VwapTrade).filter(
                db.VwapTrade.account_mode == self.ACCOUNT_MODE
            ).all()
            for row in rows:
                session.delete(row)
            session.commit()

    def _make_trade(self, symbol="EURCHF", session_id="2026-08-24"):
        return db.create_vwap_trade(
            symbol=symbol, session_id=session_id, volume=1000000,
            limit_price=0.9350, stop_price=0.9330, account_mode=self.ACCOUNT_MODE,
        )

    def test_create_and_get_round_trips(self):
        trade_id = self._make_trade()
        trade = db.get_vwap_trade(trade_id)
        self.assertEqual(trade["symbol"], "EURCHF")
        self.assertEqual(trade["session_id"], "2026-08-24")
        self.assertEqual(trade["status"], "pending")
        self.assertEqual(trade["limit_price"], 0.9350)

    def test_mark_open_sets_fill_details(self):
        trade_id = self._make_trade()
        ok = db.mark_vwap_trade_open(
            trade_id, broker_order_id="ord-1", broker_position_id="pos-1",
            entry_price=0.9350, filled_volume=1000000,
        )
        self.assertTrue(ok)

        trade = db.get_vwap_trade(trade_id)
        self.assertEqual(trade["status"], "open")
        self.assertEqual(trade["broker_order_id"], "ord-1")
        self.assertEqual(trade["broker_position_id"], "pos-1")
        self.assertEqual(trade["entry_price"], 0.9350)
        self.assertEqual(trade["filled_volume"], 1000000)

    def test_mark_closing_stashes_reason_and_expected_price_without_closing(self):
        trade_id = self._make_trade()
        db.mark_vwap_trade_open(trade_id, broker_order_id="o", broker_position_id="p", entry_price=0.9350, filled_volume=1000000)

        ok = db.mark_vwap_trade_closing(trade_id, exit_reason="vwap_touch", expected_exit_price=0.9360)

        self.assertTrue(ok)
        trade = db.get_vwap_trade(trade_id)
        self.assertEqual(trade["status"], "open")  # still open - this is staging only
        self.assertEqual(trade["exit_reason"], "vwap_touch")
        self.assertEqual(trade["expected_exit_price"], 0.9360)
        self.assertIsNone(trade["closed_at"])

    def test_mark_closing_only_applies_to_open_trades(self):
        trade_id = self._make_trade()  # still "pending", never opened
        self.assertFalse(db.mark_vwap_trade_closing(trade_id, exit_reason="vwap_touch", expected_exit_price=0.9360))

    def test_mark_closed_computes_signed_slippage(self):
        trade_id = self._make_trade()
        db.mark_vwap_trade_open(trade_id, broker_order_id="o", broker_position_id="p", entry_price=0.9350, filled_volume=1000000)

        db.mark_vwap_trade_closed(
            trade_id, status="closed_target", exit_reason="vwap_touch",
            exit_price=0.9365, expected_exit_price=0.9360, pnl_amount=12.5,
        )

        trade = db.get_vwap_trade(trade_id)
        self.assertEqual(trade["status"], "closed_target")
        self.assertEqual(trade["exit_reason"], "vwap_touch")
        self.assertAlmostEqual(trade["slippage"], 0.0005, places=6)
        self.assertEqual(trade["pnl_amount"], 12.5)
        self.assertIsNotNone(trade["closed_at"])

    def test_mark_expired_only_applies_to_pending(self):
        trade_id = self._make_trade()
        self.assertTrue(db.mark_vwap_trade_expired(trade_id))
        self.assertEqual(db.get_vwap_trade(trade_id)["status"], "expired")

        # Already resolved - a second call must not resurrect/override it.
        trade_id2 = self._make_trade()
        db.mark_vwap_trade_open(trade_id2, broker_order_id="o", broker_position_id="p", entry_price=0.9350, filled_volume=1000000)
        self.assertFalse(db.mark_vwap_trade_expired(trade_id2))
        self.assertEqual(db.get_vwap_trade(trade_id2)["status"], "open")

    def test_mark_error_sets_message_and_closes(self):
        trade_id = self._make_trade()
        db.mark_vwap_trade_error(trade_id, "timeout, order state unknown")
        trade = db.get_vwap_trade(trade_id)
        self.assertEqual(trade["status"], "error")
        self.assertEqual(trade["error_message"], "timeout, order state unknown")
        self.assertIsNotNone(trade["closed_at"])

    def test_find_open_trade_for_session_scopes_by_symbol_and_session(self):
        trade_id = self._make_trade(symbol="EURCHF", session_id="2026-08-24")

        found = db.find_open_vwap_trade_for_session("EURCHF", "2026-08-24", self.ACCOUNT_MODE)
        self.assertIsNotNone(found)
        self.assertEqual(found["id"], trade_id)

        self.assertIsNone(db.find_open_vwap_trade_for_session("EURCHF", "2026-08-25", self.ACCOUNT_MODE))
        self.assertIsNone(db.find_open_vwap_trade_for_session("GBPJPY", "2026-08-24", self.ACCOUNT_MODE))

    def test_find_open_trade_ignores_closed_trades(self):
        trade_id = self._make_trade(symbol="EURCHF", session_id="2026-08-24")
        db.mark_vwap_trade_expired(trade_id)

        self.assertIsNone(db.find_open_vwap_trade_for_session("EURCHF", "2026-08-24", self.ACCOUNT_MODE))

    def test_count_open_vwap_trades(self):
        self._make_trade(symbol="EURCHF")
        t2 = self._make_trade(symbol="GBPJPY")
        db.mark_vwap_trade_expired(t2)

        self.assertEqual(db.count_open_vwap_trades(self.ACCOUNT_MODE), 1)

    def test_get_open_and_pending_returns_both_statuses_not_closed(self):
        pending_id = self._make_trade(symbol="EURCHF")
        open_id = self._make_trade(symbol="GBPJPY")
        db.mark_vwap_trade_open(open_id, broker_order_id="o", broker_position_id="p", entry_price=190.0, filled_volume=1000000)
        closed_id = self._make_trade(symbol="AUDCAD")
        db.mark_vwap_trade_expired(closed_id)

        trades = db.get_open_and_pending_vwap_trades(self.ACCOUNT_MODE)

        ids = {t["id"] for t in trades}
        self.assertEqual(ids, {pending_id, open_id})

    def test_get_daily_vwap_pnl_sums_only_closed_trades_today(self):
        t1 = self._make_trade(symbol="EURCHF")
        db.mark_vwap_trade_open(t1, broker_order_id="o1", broker_position_id="p1", entry_price=0.9350, filled_volume=1000000)
        db.mark_vwap_trade_closed(t1, status="closed_target", exit_reason="vwap_touch", exit_price=0.9365, expected_exit_price=0.9360, pnl_amount=10.0)

        t2 = self._make_trade(symbol="GBPJPY")
        db.mark_vwap_trade_open(t2, broker_order_id="o2", broker_position_id="p2", entry_price=190.0, filled_volume=1000000)
        db.mark_vwap_trade_closed(t2, status="closed_stop", exit_reason="stop_loss", exit_price=189.5, expected_exit_price=189.5, pnl_amount=-5.0)

        self._make_trade(symbol="AUDCAD")  # still pending, must not count

        self.assertEqual(db.get_daily_vwap_pnl(self.ACCOUNT_MODE), 5.0)

    def test_get_consecutive_vwap_losses_stops_at_first_win(self):
        for pnl in (-3.0, -2.0, 4.0, -1.0):  # most recent first once resolved in this order
            t = self._make_trade()
            db.mark_vwap_trade_open(t, broker_order_id="o", broker_position_id="p", entry_price=0.9350, filled_volume=1000000)
            db.mark_vwap_trade_closed(t, status="closed_target" if pnl > 0 else "closed_stop",
                                       exit_reason="vwap_touch" if pnl > 0 else "stop_loss",
                                       exit_price=0.9350, expected_exit_price=0.9350, pnl_amount=pnl)

        # Most recently closed two are losses (-1.0 then -2.0 before it going
        # backwards), the win before that ends the streak.
        self.assertEqual(db.get_consecutive_vwap_losses(self.ACCOUNT_MODE), 1)


class VwapExecutorRuntimeStateTest(unittest.TestCase):
    """Real-DB round-trip (Крок 3.1, 2026-08-22) for the persisted runtime
    flags vwap_executor.py and its Telegram admin commands share - same
    persistence-not-a-module-global rationale as autotrade/binomo's own
    runtime state (2026-08-15 audit fix)."""

    def tearDown(self):
        db.set_vwap_executor_runtime_enabled(True)
        db.set_vwap_executor_read_only(False)
        db.clear_vwap_executor_kill_switch()

    def test_default_state_is_enabled_not_read_only_not_tripped(self):
        state = db.get_vwap_executor_runtime_state()
        self.assertTrue(state["runtime_enabled"])
        self.assertFalse(state["read_only"])
        self.assertFalse(state["kill_switch_tripped"])

    def test_disable_then_enable_round_trips(self):
        db.set_vwap_executor_runtime_enabled(False)
        self.assertFalse(db.get_vwap_executor_runtime_state()["runtime_enabled"])

        db.set_vwap_executor_runtime_enabled(True)
        self.assertTrue(db.get_vwap_executor_runtime_state()["runtime_enabled"])

    def test_read_only_toggle_round_trips(self):
        db.set_vwap_executor_read_only(True)
        self.assertTrue(db.get_vwap_executor_runtime_state()["read_only"])

        db.set_vwap_executor_read_only(False)
        self.assertFalse(db.get_vwap_executor_runtime_state()["read_only"])

    def test_trip_and_clear_kill_switch(self):
        db.trip_vwap_executor_kill_switch("daily pnl breached limit")
        state = db.get_vwap_executor_runtime_state()
        self.assertTrue(state["kill_switch_tripped"])
        self.assertEqual(state["kill_switch_reason"], "daily pnl breached limit")

        db.clear_vwap_executor_kill_switch()
        state = db.get_vwap_executor_runtime_state()
        self.assertFalse(state["kill_switch_tripped"])
        self.assertIsNotNone(state["kill_switch_cleared_at"])


if __name__ == "__main__":
    unittest.main()
