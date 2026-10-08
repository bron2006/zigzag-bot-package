import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from twisted.internet import defer

import vwap_executor
from state import app_state


class PollAllSymbolsWeekendGateTest(unittest.TestCase):
    """BUG FIX (2026-09-06, live finding): _poll_all_symbols used to
    unconditionally yield _wait_for_live_client() before ever checking the
    session window, so every poll cycle - including all weekend/overnight
    ones - required a live cTrader connection. Harmless on a normal
    weekday, but when cTrader's demo backend itself was flaky on a real
    weekend (CANT_ROUTE_REQUEST / "Trading account is not authorized"),
    this turned into a reconnect storm that stalled poll cycles past the
    supervisor's stale threshold - 32 forced restarts in one Saturday
    (2026-09-05), for a market that can't possibly be open at all.

    These tests drive _poll_all_symbols with every external dependency
    (session window, DB, cTrader connection helpers) mocked to fire
    synchronously, so the inlineCallbacks generator runs to completion
    without a running reactor."""

    def setUp(self):
        self._saved_client = app_state.client
        # Unit tests deliberately run mocked DB reads synchronously. Separate
        # reliability tests exercise the actual worker/deadline with a clock.
        self._db_patch = patch("vwap_executor._db_read", side_effect=lambda f, *a, **kw: defer.maybeDeferred(f, *a, **kw))
        self._db_patch.start()
        self.addCleanup(self._db_patch.stop)

    def tearDown(self):
        app_state.client = self._saved_client

    def _run(self, coro):
        """Drives an inlineCallbacks-decorated call to completion. With every
        yielded sub-deferred already fired (defer.succeed/patched sync
        mocks below), the generator never actually suspends, so the
        reactor doesn't need to run."""
        result = []
        coro.addCallback(result.append)
        coro.addErrback(lambda f: result.append(f))
        self.assertTrue(result, "coroutine did not complete synchronously - a yield is waiting on something unmocked")
        if isinstance(result[0], object) and hasattr(result[0], "raiseException"):
            result[0].raiseException()
        return result[0]

    def test_weekend_with_nothing_open_never_touches_ctrader(self):
        app_state.client = SimpleNamespace(stop=MagicMock())

        with patch("vwap_executor._in_weekend_closure", return_value=False), \
             patch("vwap_executor._current_session_window_utc", return_value=None), \
             patch("vwap_executor.is_active", return_value=True), \
             patch("vwap_executor.db.get_open_and_pending_vwap_trades") as mock_get_trades, \
             patch("vwap_executor._wait_for_live_client") as mock_wait, \
             patch("vwap_executor._emergency_stop_all") as mock_stop_all, \
             patch("vwap_executor.ctrader.start_ctrader_client") as mock_start, \
             patch("vwap_executor._mark_poll_completed") as mock_mark:
            self._run(vwap_executor._poll_all_symbols())

        # is_active() is True here (nothing tripped/turned off) - the code
        # should stop the live connection without ever asking the DB, since
        # there's no emergency-stop scenario to check for at all.
        mock_get_trades.assert_not_called()
        mock_wait.assert_not_called()
        mock_stop_all.assert_not_called()
        mock_start.assert_not_called()
        mock_mark.assert_called_once()

    def test_weekend_stops_a_live_connection_and_clears_it(self):
        stub_client = SimpleNamespace(stop=MagicMock())
        app_state.client = stub_client

        with patch("vwap_executor._in_weekend_closure", return_value=False), \
             patch("vwap_executor._current_session_window_utc", return_value=None), \
             patch("vwap_executor.is_active", return_value=True), \
             patch("vwap_executor._mark_poll_completed"):
            self._run(vwap_executor._poll_all_symbols())

        stub_client.stop.assert_called_once()
        self.assertIsNone(app_state.client)

    def test_weekend_with_no_client_and_nothing_open_is_a_pure_noop(self):
        app_state.client = None

        with patch("vwap_executor._in_weekend_closure", return_value=False), \
             patch("vwap_executor._current_session_window_utc", return_value=None), \
             patch("vwap_executor.is_active", return_value=True), \
             patch("vwap_executor._wait_for_live_client") as mock_wait, \
             patch("vwap_executor.ctrader.start_ctrader_client") as mock_start, \
             patch("vwap_executor._mark_poll_completed") as mock_mark:
            self._run(vwap_executor._poll_all_symbols())

        mock_wait.assert_not_called()
        mock_start.assert_not_called()
        mock_mark.assert_called_once()

    def test_weekend_with_kill_switch_tripped_but_nothing_open_skips_connection(self):
        app_state.client = SimpleNamespace(stop=MagicMock())

        with patch("vwap_executor._in_weekend_closure", return_value=False), \
             patch("vwap_executor._current_session_window_utc", return_value=None), \
             patch("vwap_executor.is_active", return_value=False), \
             patch("vwap_executor.db.get_open_and_pending_vwap_trades", return_value=[]) as mock_get_trades, \
             patch("vwap_executor._wait_for_live_client") as mock_wait, \
             patch("vwap_executor._emergency_stop_all") as mock_stop_all, \
             patch("vwap_executor._mark_poll_completed") as mock_mark:
            self._run(vwap_executor._poll_all_symbols())

        # Not active AND nothing open - the DB read happens (it's what
        # decides this), but no connection is needed since there's nothing
        # to actually close.
        mock_get_trades.assert_called_once()
        mock_wait.assert_not_called()
        mock_stop_all.assert_not_called()
        mock_mark.assert_called_once()

    def test_weekend_with_kill_switch_tripped_and_something_open_still_connects(self):
        # The one case that MUST still reach for a live connection even on
        # a confirmed-closed weekend: an emergency stop with something
        # real (in DB terms) left open. _emergency_stop_all's own docstring
        # says this must act immediately, not wait for the next session.
        app_state.client = None
        live_client = SimpleNamespace(_client=SimpleNamespace(account_id=42))

        def _fake_wait():
            app_state.client = live_client
            return defer.succeed(True)

        with patch("vwap_executor._in_weekend_closure", return_value=False), \
             patch("vwap_executor._current_session_window_utc", return_value=None), \
             patch("vwap_executor.is_active", return_value=False), \
             patch("vwap_executor.db.get_open_and_pending_vwap_trades", return_value=[{"id": 1}]), \
             patch("vwap_executor._wait_for_live_client", side_effect=_fake_wait) as mock_wait, \
             patch("vwap_executor._emergency_stop_all", return_value=defer.succeed(None)) as mock_stop_all, \
             patch("vwap_executor._mark_poll_completed") as mock_mark:
            self._run(vwap_executor._poll_all_symbols())

        mock_wait.assert_called_once()
        mock_stop_all.assert_called_once_with(live_client, 42)
        mock_mark.assert_called_once()

    def test_session_open_reconnects_when_client_was_stopped(self):
        app_state.client = None
        session_start = datetime(2026, 9, 7, 8, 0, tzinfo=timezone.utc)
        session_end = datetime(2026, 9, 7, 16, 0, tzinfo=timezone.utc)
        new_client = SimpleNamespace(on=MagicMock(), _client=SimpleNamespace(account_id=None))

        with patch("vwap_executor._in_weekend_closure", return_value=False), \
             patch("vwap_executor._current_session_window_utc", return_value=(session_start, session_end)), \
             patch("vwap_executor.ctrader.start_ctrader_client", return_value=new_client) as mock_start, \
             patch("vwap_executor._wait_for_live_client", return_value=defer.succeed(False)), \
             patch("vwap_executor._mark_poll_completed"):
            self._run(vwap_executor._poll_all_symbols())

        mock_start.assert_called_once()
        new_client.on.assert_called_once_with("execution_event", vwap_executor.handle_execution_event)

    def test_session_open_with_existing_client_does_not_reconnect(self):
        session_start = datetime(2026, 9, 7, 8, 0, tzinfo=timezone.utc)
        session_end = datetime(2026, 9, 7, 16, 0, tzinfo=timezone.utc)
        app_state.client = SimpleNamespace(_client=SimpleNamespace(account_id=1))

        with patch("vwap_executor._in_weekend_closure", return_value=False), \
             patch("vwap_executor._current_session_window_utc", return_value=(session_start, session_end)), \
             patch("vwap_executor.ctrader.start_ctrader_client") as mock_start, \
             patch("vwap_executor._wait_for_live_client", return_value=defer.succeed(False)), \
             patch("vwap_executor._mark_poll_completed"):
            self._run(vwap_executor._poll_all_symbols())

        mock_start.assert_not_called()


class InWeekendClosureTest(unittest.TestCase):
    """BUG FIX (2026-09-06, user request + live finding): the per-cycle
    weekend gate (2026-09-05) stops cTrader use off-session but still hits
    the DB every cycle via is_active() - and that DB connection itself
    turned out to be flaky overnight (2026-09-05/06: intermittent Supabase
    "SSL SYSCALL error: Software caused connection abort"), 17 CRITICAL
    stale-poll alerts in one night. _in_weekend_closure defines a coarser,
    Friday-session-end-to-Sunday-evening window where _poll_all_symbols
    skips everything, DB included - see its own module-level comment for
    the full reasoning and the accepted trade-off."""

    def test_friday_before_closure_hour_is_open(self):
        self.assertFalse(vwap_executor._in_weekend_closure(datetime(2026, 9, 4, 21, 59, tzinfo=timezone.utc)))

    def test_friday_at_closure_hour_is_closed(self):
        self.assertTrue(vwap_executor._in_weekend_closure(datetime(2026, 9, 4, 22, 0, tzinfo=timezone.utc)))

    def test_friday_late_night_is_closed(self):
        self.assertTrue(vwap_executor._in_weekend_closure(datetime(2026, 9, 4, 23, 59, tzinfo=timezone.utc)))

    def test_saturday_any_hour_is_closed(self):
        for hour in (0, 8, 12, 16, 23):
            with self.subTest(hour=hour):
                self.assertTrue(vwap_executor._in_weekend_closure(datetime(2026, 9, 5, hour, 0, tzinfo=timezone.utc)))

    def test_sunday_before_resume_hour_is_closed(self):
        self.assertTrue(vwap_executor._in_weekend_closure(datetime(2026, 9, 6, 20, 59, tzinfo=timezone.utc)))

    def test_sunday_at_resume_hour_is_open(self):
        self.assertFalse(vwap_executor._in_weekend_closure(datetime(2026, 9, 6, 21, 0, tzinfo=timezone.utc)))

    def test_sunday_late_evening_is_open(self):
        self.assertFalse(vwap_executor._in_weekend_closure(datetime(2026, 9, 6, 23, 30, tzinfo=timezone.utc)))

    def test_monday_session_hours_are_open(self):
        self.assertFalse(vwap_executor._in_weekend_closure(datetime(2026, 9, 7, 10, 0, tzinfo=timezone.utc)))

    def test_regular_weekday_is_open(self):
        for day in (0, 1, 2, 3):  # Mon-Thu
            for hour in (0, 8, 16, 23):
                with self.subTest(day=day, hour=hour):
                    dt = datetime(2026, 9, 7 + day, hour, 0, tzinfo=timezone.utc)
                    self.assertFalse(vwap_executor._in_weekend_closure(dt))


class PollAllSymbolsWeekendClosureShortCircuitTest(unittest.TestCase):
    def setUp(self):
        self._saved_client = app_state.client
        self._db_patch = patch("vwap_executor._db_read", side_effect=lambda f, *a, **kw: defer.maybeDeferred(f, *a, **kw))
        self._db_patch.start()
        self.addCleanup(self._db_patch.stop)

    def tearDown(self):
        app_state.client = self._saved_client

    def _run(self, coro):
        result = []
        coro.addCallback(result.append)
        coro.addErrback(lambda f: result.append(f))
        self.assertTrue(result, "coroutine did not complete synchronously")
        if hasattr(result[0], "raiseException"):
            result[0].raiseException()
        return result[0]

    def test_closure_window_touches_nothing_when_no_client(self):
        app_state.client = None

        with patch("vwap_executor._in_weekend_closure", return_value=True), \
             patch("vwap_executor.is_active") as mock_is_active, \
             patch("vwap_executor.db.get_open_and_pending_vwap_trades") as mock_get_trades, \
             patch("vwap_executor._wait_for_live_client") as mock_wait, \
             patch("vwap_executor.ctrader.start_ctrader_client") as mock_start, \
             patch("vwap_executor._mark_poll_completed") as mock_mark:
            self._run(vwap_executor._poll_all_symbols())

        # Not even the DB (is_active/open-trades) is touched - this is the
        # coarser gate than the 2026-09-05 one, which still did that much.
        mock_is_active.assert_not_called()
        mock_get_trades.assert_not_called()
        mock_wait.assert_not_called()
        mock_start.assert_not_called()
        mock_mark.assert_called_once()

    def test_closure_window_stops_a_live_connection(self):
        stub_client = SimpleNamespace(stop=MagicMock())
        app_state.client = stub_client

        with patch("vwap_executor._in_weekend_closure", return_value=True), \
             patch("vwap_executor._mark_poll_completed"):
            self._run(vwap_executor._poll_all_symbols())

        stub_client.stop.assert_called_once()
        self.assertIsNone(app_state.client)

    def test_outside_closure_window_falls_through_to_the_narrower_gate(self):
        # Sanity check that the new coarse gate doesn't swallow the
        # existing (2026-09-05) narrower weekend gate's own DB-only
        # emergency-stop check when we're merely off-session, not in the
        # full closure window.
        app_state.client = None

        with patch("vwap_executor._in_weekend_closure", return_value=False), \
             patch("vwap_executor._current_session_window_utc", return_value=None), \
             patch("vwap_executor.is_active", return_value=True), \
             patch("vwap_executor.db.get_open_and_pending_vwap_trades") as mock_get_trades, \
             patch("vwap_executor._mark_poll_completed") as mock_mark:
            self._run(vwap_executor._poll_all_symbols())

        mock_get_trades.assert_not_called()  # is_active() True - nothing to check for
        mock_mark.assert_called_once()


if __name__ == "__main__":
    unittest.main()
