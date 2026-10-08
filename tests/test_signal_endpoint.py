"""Offline endpoint tests. Run with DATABASE_URL=sqlite:///:memory:."""
import threading
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import db
with patch.object(db, '_ensure_binomo_trade_fk'):
    # The legacy PostgreSQL ALTER helper is unrelated to endpoint tests;
    # SQLite creates its foreign keys with metadata.create_all instead.
    import signal_tracking as tracking
    from state import AppState


def isolated_state():
    # No token/database lookup, connections, pools or services.
    state = AppState.__new__(AppState)
    state._state_lock = threading.RLock()
    state.live_prices = {}
    state._outcome_quotes = {}
    state._outcome_quote_sides = {}
    return state


class QuoteHistoryTest(unittest.TestCase):
    def setUp(self):
        self.state = isolated_state()

    def quote(self, ts, bid=100, ask=102):
        with patch('state.time.time', return_value=max(ts, 2000)):
            self.state.update_live_price('TEST', dict(ts=ts, quote_ts=ts, bid=bid, ask=ask))

    def test_first_full_quote_after_deadline_not_before_or_latest(self):
        self.quote(999)
        self.quote(1001, 104, 106)
        self.quote(1010, 110, 112)
        self.assertEqual(self.state.get_signal_endpoint_quote('TEST', 1000, 1010), dict(ts=1001, mid=105))

    def test_predeadline_only_is_not_endpoint(self):
        self.quote(999)
        self.assertIsNone(self.state.get_signal_endpoint_quote('TEST', 1000, 1005))

    def test_late_quote_is_not_endpoint(self):
        self.quote(1005.01)
        self.assertIsNone(self.state.get_signal_endpoint_quote('TEST', 1000, 1010))

    def test_future_relative_to_resolver_is_not_used(self):
        self.quote(1004)
        self.assertIsNone(self.state.get_signal_endpoint_quote('TEST', 1000, 1003))

    def test_invalid_and_single_sided_quotes_not_measurements(self):
        for bid, ask in [(None, 102), (100, None), (103, 102), (float('nan'), 102), (100, float('inf')), (0, 102)]:
            self.state = isolated_state()
            self.quote(1001, bid, ask)
            self.assertIsNone(self.state.get_signal_endpoint_quote('TEST', 1000, 1005))

    def test_partial_events_assemble_only_fresh_sides(self):
        self.quote(1000, 100, None)
        self.quote(1001, None, 102)
        self.assertEqual(self.state.get_signal_endpoint_quote('TEST', 1000, 1005), dict(ts=1001, mid=101))

    def test_partial_event_cannot_reuse_stale_other_side(self):
        self.quote(990, 100, None)
        self.quote(1001, None, 102)
        self.assertIsNone(self.state.get_signal_endpoint_quote('TEST', 1000, 1005))

    def test_future_wall_clock_quote_rejected(self):
        with patch('state.time.time', return_value=1000):
            self.state.update_live_price('TEST', dict(ts=1004, quote_ts=1004, bid=100, ask=102))
        self.assertIsNone(self.state.get_signal_endpoint_quote('TEST', 1000, 1005))

    def test_out_of_order_quote_not_inserted(self):
        self.quote(1010)
        self.quote(1001)
        self.assertIsNone(self.state.get_signal_endpoint_quote('TEST', 1000, 1010))

    def test_history_bounded_even_for_fast_feed(self):
        for i in range(15000):
            self.quote(1000 + i / 10)
        self.assertLessEqual(len(self.state._outcome_quotes['TEST']), 601)
        self.assertLessEqual(self.state._outcome_quotes['TEST'][-1][0] - self.state._outcome_quotes['TEST'][0][0], 600)

    def test_restart_loses_history_without_guessing_from_live_price(self):
        self.state.live_prices['TEST'] = dict(mid=105, ts=1001)
        self.assertIsNone(self.state.get_signal_endpoint_quote('TEST', 1000, 1005))

    def test_delayed_receipt_does_not_change_broker_quote_time(self):
        with patch('state.time.time', return_value=1001):
            self.state.update_live_price('TEST', dict(ts=1001, quote_ts=990, bid=100, ask=102))
        self.assertIsNone(self.state.get_signal_endpoint_quote('TEST', 1000, 1005))

    def test_missing_broker_timestamp_is_not_guessed(self):
        with patch('state.time.time', return_value=1001):
            self.state.update_live_price('TEST', dict(ts=1001, bid=100, ask=102))
        self.assertIsNone(self.state.get_signal_endpoint_quote('TEST', 1000, 1005))


class ResolveEndpointTest(unittest.TestCase):
    def setUp(self):
        self.state = isolated_state()
        self.entry = datetime(2026, 10, 9, 12)
        self.deadline = (self.entry.replace(tzinfo=timezone.utc) + timedelta(minutes=15)).timestamp()
        self.row = dict(id=1, pair='TEST', verdict='BUY', entry_ts=self.entry, horizon_seconds=900, entry_price=101)

    def quote(self, offset, bid=104, ask=106):
        with patch('state.time.time', return_value=self.deadline + offset):
            self.state.update_live_price('TEST', dict(ts=self.deadline + offset, quote_ts=self.deadline + offset, bid=bid, ask=ask))

    def resolve(self, offset):
        now = datetime.fromtimestamp(self.deadline + offset, timezone.utc).replace(tzinfo=None)
        with patch.object(tracking, 'app_state', self.state), patch.object(tracking, '_utcnow_naive', return_value=now), patch.object(db, 'get_pending_signal_outcomes', return_value=[self.row]), patch.object(db, 'resolve_signal_outcome', return_value=True) as write:
            tracking.resolve_pending_signals()
        return write

    def test_before_deadline_remains_pending(self):
        self.assertFalse(self.resolve(-1).called)

    def test_missing_quote_waits_only_fixed_window(self):
        self.assertFalse(self.resolve(2).called)
        self.resolve(5).assert_called_once_with(1, outcome='unknown', exit_price=None)

    def test_20_hour_late_price_is_unknown(self):
        self.quote(20 * 3600)
        self.resolve(20 * 3600).assert_called_once_with(1, outcome='unknown', exit_price=None)

    def test_retained_endpoint_beats_later_reversed_price(self):
        self.quote(1)
        self.quote(120, bid=94, ask=96)
        self.resolve(120).assert_called_once_with(1, outcome='up_timed', exit_price=105)

    def test_old_quote_is_not_reused(self):
        self.quote(-120)
        self.resolve(120).assert_called_once_with(1, outcome='unknown', exit_price=None)

    def test_timezone_aware_entry_same_deadline(self):
        self.row['entry_ts'] = self.entry.replace(tzinfo=timezone.utc).astimezone(timezone(timedelta(hours=3)))
        self.quote(1)
        self.resolve(120).assert_called_once_with(1, outcome='up_timed', exit_price=105)

    def test_nan_entry_unknown_not_flat(self):
        self.row['entry_price'] = float('nan')
        self.quote(1)
        self.resolve(120).assert_called_once_with(1, outcome='unknown', exit_price=None)

    def test_invalid_horizon_terminal_unknown(self):
        self.row['horizon_seconds'] = -1
        self.resolve(120).assert_called_once_with(1, outcome='unknown', exit_price=None)


class UnknownAggregationTest(unittest.TestCase):
    def test_verified_view_excludes_historical_successes(self):
        rows = [SimpleNamespace(verdict='BUY', outcome='up', entry_price=100, exit_price=101),
                SimpleNamespace(verdict='BUY', outcome='down_timed', entry_price=100, exit_price=99)]
        for aggregate in (db._aggregate_signal_outcomes, db._aggregate_signal_outcomes_binomo_style):
            result = aggregate(rows, verified_only=True)
            self.assertEqual((result['wins'], result['losses'], result['unverified'], result['pending']), (0, 1, 1, 0))
            self.assertEqual(result['win_rate'], 0)

    def test_unknown_not_loss_win_or_pending_in_both_views(self):
        rows = [SimpleNamespace(verdict='BUY', outcome='up', entry_price=100, exit_price=101),
                SimpleNamespace(verdict='BUY', outcome='unknown', entry_price=100, exit_price=101),
                SimpleNamespace(verdict='BUY', outcome='pending', entry_price=100, exit_price=None)]
        for aggregate in (db._aggregate_signal_outcomes, db._aggregate_signal_outcomes_binomo_style):
            result = aggregate(rows)
            self.assertEqual((result['wins'], result['losses'], result['unknown'], result['pending'], result['resolved']), (1, 0, 1, 1, 2))
            self.assertEqual(result['win_rate'], 100)

    def test_all_unknown_has_no_winrate(self):
        rows = [SimpleNamespace(verdict='BUY', outcome='unknown', entry_price=100, exit_price=None)]
        for aggregate in (db._aggregate_signal_outcomes, db._aggregate_signal_outcomes_binomo_style):
            self.assertIsNone(aggregate(rows)['win_rate'])

    def test_sqlite_roundtrip_unknown_removed_from_pending(self):
        # Deliberately cannot run this persistence test on a remote database.
        self.assertEqual(db.engine.url.drivername, 'sqlite')
        self.assertEqual(db.engine.url.database, ':memory:')
        db.Base.metadata.create_all(db.engine)
        identifier = db.create_signal_outcome(pair='ENDPOINTTEST', timeframe='5m', verdict='BUY', score=90, entry_price=101, horizon_seconds=900)
        self.assertTrue(db.resolve_signal_outcome(identifier, outcome='unknown', exit_price=None))
        self.assertFalse(db.resolve_signal_outcome(identifier, outcome='up', exit_price=105))
        self.assertNotIn(identifier, [r['id'] for r in db.get_pending_signal_outcomes()])
        stats = db.get_pair_signal_outcome_stats('ENDPOINTTEST')
        self.assertEqual(stats['unknown'], 1)
        self.assertIsNone(stats['win_rate'])

    def test_public_stats_query_excludes_old_rows_and_includes_timed_rows(self):
        self.assertEqual(db.engine.url.database, ':memory:')
        db.Base.metadata.create_all(db.engine)
        for status, exit_price in [('up', 105), ('down_timed', 95)]:
            identifier = db.create_signal_outcome(pair='TIMEDQUERYTEST', timeframe='5m', verdict='BUY', score=90, entry_price=101, horizon_seconds=900)
            self.assertTrue(db.resolve_signal_outcome(identifier, outcome=status, exit_price=exit_price))
        for style in (True, False):
            report = db.get_signal_outcome_stats(binomo_style=style)
            pair = next(r for r in report['by_pair'] if r['pair'] == 'TIMEDQUERYTEST')
            self.assertEqual((pair['wins'], pair['losses'], pair['unverified'], pair['pending']), (0, 1, 1, 0))
            self.assertEqual(pair['win_rate'], 0)


class BrokerTimestampWiringTest(unittest.TestCase):
    def test_subscription_requests_quote_timestamps(self):
        import ctrader
        from unittest.mock import MagicMock
        client = SimpleNamespace(_client=SimpleNamespace(account_id=1), send=MagicMock())
        symbol = SimpleNamespace(symbolId=2, symbolName='EURUSD')
        with patch.object(ctrader.app_state, 'client', client):
            ctrader._subscribe_symbol_batch([('EURUSD', symbol)])
        self.assertTrue(client.send.call_args.args[0].subscribeToSpotTimestamp)

    def test_spot_handler_preserves_broker_time_separately_from_receipt(self):
        import ctrader
        from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOASpotEvent
        from unittest.mock import MagicMock
        state = SimpleNamespace(symbol_id_map={2:'EURUSD'}, symbol_cache={'EURUSD':SimpleNamespace(digits=5)}, update_live_price=MagicMock(), publish_sse=MagicMock(), publish_price_sse=MagicMock())
        event = ProtoOASpotEvent(ctidTraderAccountId=1, symbolId=2, bid=110000, ask=110020, timestamp=1000000)
        with patch.object(ctrader, 'app_state', state), patch.object(ctrader.time, 'time', return_value=1010):
            ctrader._on_spot_event(event)
        payload = state.update_live_price.call_args.args[1]
        self.assertEqual((payload['ts'], payload['quote_ts']), (1010,1000))
