import unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

import autotrader
import db


class ComputeTpSlTest(unittest.TestCase):
    def test_buy_tp_above_sl_below_entry(self):
        tp, sl = autotrader._compute_tp_sl("BUY", 100.0, atr=2.0)
        self.assertAlmostEqual(tp, 103.0)  # entry + 1.5x ATR
        self.assertAlmostEqual(sl, 98.0)  # entry - 1.0x ATR

    def test_sell_tp_below_sl_above_entry(self):
        tp, sl = autotrader._compute_tp_sl("SELL", 100.0, atr=2.0)
        self.assertAlmostEqual(tp, 97.0)
        self.assertAlmostEqual(sl, 102.0)

    def test_rejects_non_directional_verdict(self):
        self.assertIsNone(autotrader._compute_tp_sl("NEUTRAL", 100.0, atr=2.0))

    def test_rejects_non_positive_inputs(self):
        self.assertIsNone(autotrader._compute_tp_sl("BUY", 0, atr=2.0))
        self.assertIsNone(autotrader._compute_tp_sl("BUY", 100.0, atr=0))
        self.assertIsNone(autotrader._compute_tp_sl("BUY", 100.0, atr=-1))


class NormalizeVolumeTest(unittest.TestCase):
    def _symbol(self, min_volume=1000, max_volume=5_000_000, step_volume=1000):
        return SimpleNamespace(minVolume=min_volume, maxVolume=max_volume, stepVolume=step_volume, symbolId=1)

    def test_rounds_down_to_step(self):
        with patch.object(autotrader.ctrader, "_resolve_broker_symbol", return_value=self._symbol()):
            volume = autotrader._normalize_volume("EURUSD", raw_units=12.3456)
        # raw_units * 100 = 1234.56 -> int 1234 -> rounded down to nearest 1000 -> 1000
        self.assertEqual(volume, 1000)

    def test_rejects_below_min_volume(self):
        with patch.object(autotrader.ctrader, "_resolve_broker_symbol", return_value=self._symbol(min_volume=10000)):
            volume = autotrader._normalize_volume("EURUSD", raw_units=50.0)
        self.assertIsNone(volume)

    def test_clamps_to_max_volume(self):
        with patch.object(autotrader.ctrader, "_resolve_broker_symbol", return_value=self._symbol(max_volume=100000)):
            volume = autotrader._normalize_volume("EURUSD", raw_units=100000.0)
        self.assertLessEqual(volume, 100000)

    def test_returns_none_when_symbol_missing(self):
        with patch.object(autotrader.ctrader, "_resolve_broker_symbol", return_value=None):
            self.assertIsNone(autotrader._normalize_volume("UNKNOWN", raw_units=10.0))

    def test_returns_none_for_non_positive_units(self):
        with patch.object(autotrader.ctrader, "_resolve_broker_symbol", return_value=self._symbol()):
            self.assertIsNone(autotrader._normalize_volume("EURUSD", raw_units=0))


class ClassifyCloseTest(unittest.TestCase):
    def test_matches_take_profit(self):
        status = autotrader._classify_close(exec_price=1.1050, tp_price=1.1050, sl_price=1.0950)
        self.assertEqual(status, "closed_tp")

    def test_matches_stop_loss(self):
        status = autotrader._classify_close(exec_price=1.0951, tp_price=1.1050, sl_price=1.0950)
        self.assertEqual(status, "closed_sl")

    def test_far_from_both_is_manual(self):
        status = autotrader._classify_close(exec_price=1.1200, tp_price=1.1050, sl_price=1.0950)
        self.assertEqual(status, "closed_manual")

    def test_no_exec_price_is_manual(self):
        self.assertEqual(autotrader._classify_close(None, 1.1050, 1.0950), "closed_manual")


class PersistExecutionEventCommissionTest(unittest.TestCase):
    """AUDIT FIX (2026-08-15, high): pnl_amount used to be grossProfit+swap
    only, omitting detail.commission entirely - the same "gross instead of
    net" shape already found and fixed for get_daily_binomo_pnl. Uses a
    real ProtoOADeal/ProtoOAClosePositionDetail message (not a hand-built
    fake), so this can't drift from cTrader's actual field names."""

    def test_pnl_amount_includes_commission(self):
        from ctrader_open_api.messages.OpenApiModelMessages_pb2 import (
            ProtoOAClosePositionDetail,
            ProtoOADeal,
        )

        deal = ProtoOADeal(
            dealId=1, positionId=100, executionPrice=1.1050,
            closePositionDetail=ProtoOAClosePositionDetail(
                entryPrice=1.1000, grossProfit=5000, swap=-100, commission=-200, moneyDigits=2,
            ),
        )
        fake_trade = {
            "id": 1, "pair": "EURUSD", "direction": "BUY", "status": "open",
            "tp_price": None, "sl_price": None,
        }

        with patch.object(autotrader.db, "get_auto_trade", return_value=None), \
             patch.object(autotrader.db, "find_auto_trade_by_broker_position_id", return_value=fake_trade), \
             patch.object(autotrader.db, "mark_auto_trade_closed", return_value=True) as mock_close, \
             patch.object(autotrader, "_notify_admin_async"):
            autotrader._persist_execution_event(
                execution_type=None, trade_id_hint=None, broker_order_id=None,
                broker_position_id="100", order=None, deal=deal, prepared=None,
            )

        mock_close.assert_called_once()
        _, kwargs = mock_close.call_args
        # (5000 - 100 - 200) / 100 = 47.00 - before the fix this came back
        # as 49.00 (commission silently dropped).
        self.assertAlmostEqual(kwargs["pnl_amount"], 47.00)


class RuntimeToggleTest(unittest.TestCase):
    """AUDIT FIX (2026-08-15, critical): is_active()/enable()/disable() used
    to read/write bare Python module globals (_runtime_enabled,
    _kill_switch_tripped) - a process restart or Fly.io redeploy silently
    reset both, resuming automated real order placement with zero admin
    action, directly contradicting this module's own docstring promise
    that the kill switch "stays stopped... until an admin explicitly runs
    /autotrade_on again". Runs against the REAL db.py AppRuntimeSetting
    table (same mechanism binomo_executor.py's kill switch already uses),
    not mocks - a mock would only prove the plumbing is wired, not that
    the state actually survives outside the process. setUp/tearDown save
    and restore whatever was really there before, so this can never leave
    the real autotrade runtime state in a dirty condition."""

    def setUp(self):
        self._saved_state = db.get_autotrade_runtime_state()

    def tearDown(self):
        db.set_autotrade_runtime_enabled(self._saved_state["runtime_enabled"])
        if self._saved_state["kill_switch_tripped"]:
            db.trip_autotrade_kill_switch(self._saved_state["kill_switch_reason"] or "restored after RuntimeToggleTest")
        else:
            db.clear_autotrade_kill_switch()

    def test_enable_is_noop_when_config_disabled(self):
        with patch.object(autotrader, "AUTOTRADE_ENABLED", False):
            ok, _ = autotrader.enable()
        self.assertFalse(ok)
        self.assertFalse(autotrader.is_active())

    def test_enable_clears_kill_switch_when_config_enabled(self):
        db.trip_autotrade_kill_switch("test trip")
        with patch.object(autotrader, "AUTOTRADE_ENABLED", True):
            ok, _ = autotrader.enable()
            self.assertTrue(ok)
            self.assertFalse(db.get_autotrade_runtime_state()["kill_switch_tripped"])
            self.assertTrue(autotrader.is_active())

    def test_disable_deactivates_even_when_config_enabled(self):
        with patch.object(autotrader, "AUTOTRADE_ENABLED", True):
            autotrader.enable()
            autotrader.disable()
            self.assertFalse(autotrader.is_active())

    def test_state_is_read_fresh_from_the_db_not_a_process_local_cache(self):
        # Proves the actual fix: nothing in autotrader.py's own namespace
        # holds this state anymore - is_active() must reflect whatever the
        # real DB row says, exactly as a fresh process (post-restart)
        # reading it for the first time would see it.
        with patch.object(autotrader, "AUTOTRADE_ENABLED", True):
            db.set_autotrade_runtime_enabled(True)
            db.clear_autotrade_kill_switch()
            self.assertTrue(autotrader.is_active())

            db.trip_autotrade_kill_switch("simulated trip from another process")
            self.assertFalse(autotrader.is_active())

    def test_trip_kill_switch_persists_the_reason(self):
        # _notify_admin_async stays mocked here for the same reason the
        # Binomo kill-switch tests mock notify_admin: it dispatches via
        # deferToThreadPool, which can actually run and page the real admin
        # even outside a running reactor - confirmed live earlier this
        # session for the Binomo equivalent (duplicate real Telegram
        # alerts from a bare test run).
        with patch.object(autotrader, "_notify_admin_async"):
            autotrader._trip_kill_switch(daily_pnl=-500.0, max_daily_loss=400.0)
        state = db.get_autotrade_runtime_state()
        self.assertTrue(state["kill_switch_tripped"])
        self.assertIn("-500.00", state["kill_switch_reason"])


class GetDailyAutoTradePnlTest(unittest.TestCase):
    """AUDIT FIX (2026-08-15, high): get_daily_auto_trade_pnl had no `since`
    parameter at all - the exact same gap already found and fixed for
    get_daily_binomo_pnl. Without it, clearing autotrader's kill switch
    mid-day couldn't actually let trading resume: the next check would
    still sum the same still-negative day and trip it right back. Runs
    against the real DB, scoped by a distinctive account_mode so it can
    never touch real autotrade history."""

    ACCOUNT_MODE = "e2eauto"  # account_mode is VARCHAR(8) - must fit

    def setUp(self):
        self._purge()

    def tearDown(self):
        self._purge()

    def _purge(self):
        with db.get_db() as session:
            if session is None:
                return
            rows = session.query(db.AutoTrade).filter(db.AutoTrade.account_mode == self.ACCOUNT_MODE).all()
            for row in rows:
                session.delete(row)
            session.commit()

    def _closed_trade(self, *, pnl_amount: float) -> int:
        trade_id = db.create_auto_trade(
            pair="EURUSD", direction="BUY", volume=100000, sl_price=1.09, tp_price=1.11,
            account_mode=self.ACCOUNT_MODE,
        )
        self.assertIsNotNone(trade_id)
        self.assertTrue(db.mark_auto_trade_closed(trade_id, status="closed_sl", pnl_amount=pnl_amount))
        return trade_id

    def test_since_excludes_trades_closed_before_it(self):
        now = db._utcnow()
        earlier_today = now - timedelta(hours=2)
        cutoff = now - timedelta(hours=1)

        old_trade_id = self._closed_trade(pnl_amount=-500.0)  # to be excluded
        with db.get_db() as session:
            row = session.query(db.AutoTrade).filter(db.AutoTrade.id == old_trade_id).one()
            row.closed_at = earlier_today
            session.commit()

        self._closed_trade(pnl_amount=200.0)  # closed "now", after cutoff

        pnl_unfiltered = db.get_daily_auto_trade_pnl(self.ACCOUNT_MODE)
        pnl_since_cutoff = db.get_daily_auto_trade_pnl(self.ACCOUNT_MODE, since=cutoff)

        self.assertAlmostEqual(pnl_unfiltered, -300.0)  # old bug's shape: since ignored
        self.assertAlmostEqual(pnl_since_cutoff, 200.0)  # only the post-cutoff trade counts


class PrepareAndCheckRiskClearedAtTest(unittest.TestCase):
    """Proves the plumbing fix: _prepare_and_check_risk must actually pass
    the kill switch's cleared_at through to get_daily_auto_trade_pnl, not
    just have the parameter exist on the function - same regression shape
    as binomo_executor.py's CheckRiskLimitsTest.test_passes_kill_switch_
    cleared_at_as_since_to_the_loss_query."""

    def test_passes_kill_switch_cleared_at_as_since(self):
        from datetime import datetime

        cleared_at = datetime(2026, 8, 15, 12, 0, 0)
        captured = {}

        def _fake_pnl(mode, since=None):
            captured["since"] = since
            return 0.0

        with patch.object(autotrader, "_get_account_balance", return_value=10000.0), \
             patch.object(autotrader, "MAX_DAILY_LOSS_PERCENT", 1000.0), \
             patch.object(autotrader, "MAX_OPEN_POSITIONS", 1000), \
             patch.object(autotrader.db, "get_daily_auto_trade_pnl", side_effect=_fake_pnl), \
             patch.object(autotrader.db, "get_autotrade_runtime_state", return_value={
                 "runtime_enabled": True, "kill_switch_tripped": False, "kill_switch_reason": None,
                 "kill_switch_cleared_at": cleared_at,
             }), \
             patch.object(autotrader.db, "count_open_auto_trades", return_value=0), \
             patch.object(autotrader, "_compute_tp_sl", return_value=None):
            autotrader._prepare_and_check_risk("EURUSD", "BUY", 1.10, 0.001)

        self.assertEqual(captured["since"], cleared_at)


if __name__ == "__main__":
    unittest.main()
