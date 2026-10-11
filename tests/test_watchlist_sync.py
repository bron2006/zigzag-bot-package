import unittest
from unittest.mock import patch

from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import scoped_session, sessionmaker

import api
import db
import scanner
from state import app_state


class DurableWatchlistTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite:///:memory:')
        db.User.__table__.create(self.engine)
        db.UserWatchlist.__table__.create(self.engine)
        self.sessions = scoped_session(sessionmaker(bind=self.engine))
        self.patch = patch.object(db, 'SessionLocal', self.sessions)
        self.patch.start()
        with db.session_scope() as session:
            session.add(db.User(user_id=1))
            session.add(db.User(user_id=2))

    def tearDown(self):
        self.patch.stop()
        self.sessions.remove()
        self.engine.dispose()

    def test_add_retry_and_remove_are_idempotent_and_user_scoped(self):
        self.assertEqual(db.update_watchlist(1, ['BTCUSD', 'ETHUSD'], True), ['BTCUSD', 'ETHUSD'])
        self.assertEqual(db.update_watchlist(1, ['BTCUSD'], True), ['BTCUSD', 'ETHUSD'])
        self.assertEqual(db.update_watchlist(2, ['BTCUSD'], True), ['BTCUSD'])
        self.assertEqual(db.update_watchlist(1, ['BTCUSD'], False), ['ETHUSD'])
        self.assertEqual(db.update_watchlist(1, ['BTCUSD'], False), ['ETHUSD'])
        self.assertEqual(db.get_watchlist(2), ['BTCUSD'])

    def test_commit_failure_is_not_acknowledged_or_cached(self):
        with patch.object(self.sessions.session_factory.class_, 'commit',
                          side_effect=OperationalError('commit', {}, Exception('unavailable'))):
            self.assertIsNone(db.update_watchlist(1, ['BTCUSD'], True))
        self.assertEqual(db.get_watchlist(1), [])

    def test_memory_only_favorites_are_not_reported_as_confirmed(self):
        db._fallback_add_watchlist(1, 'GHOSTUSD')
        self.addCleanup(lambda: db._fallback_watchlists.pop(1, None))
        self.assertEqual(db.get_watchlist(1), [])

    def test_missing_user_or_database_fails_closed(self):
        self.assertIsNone(db.update_watchlist(99, ['BTCUSD'], True))
        with patch.object(db, 'SessionLocal', None):
            self.assertIsNone(db.update_watchlist(1, ['BTCUSD'], True))

    def test_watchlist_scans_crypto_even_when_crypto_category_is_off(self):
        db.update_watchlist(1, ['BTCUSD', 'ETHUSD'], True)
        with patch.object(scanner, 'get_chat_id', return_value=1), \
             patch.object(app_state, 'get_scanner_state', side_effect=lambda c: c == 'watchlist'):
            self.assertEqual(scanner._collect_assets_to_scan(), ['BTCUSD', 'ETHUSD'])


class WatchlistApiTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        api.register_routes(app)
        self.client = app.test_client()

    def test_requires_authentication(self):
        response = self.client.post('/api/watchlist', data={'pair':'BTCUSD', 'enabled':'true'})
        self.assertEqual(response.status_code, 401)

    def request(self, data, result):
        with patch.object(api, 'is_valid_admin_token', return_value=True), \
             patch.object(db, 'update_watchlist', return_value=result) as update, \
             patch.object(api.reactor, 'callFromThread') as schedule:
            response = self.client.post('/api/watchlist?admin_token=test', data=data)
        return response, update, schedule

    def test_returns_server_list_and_schedules_quote_subscription(self):
        response, update, schedule = self.request({'pair':['BTC/USD','ETHUSD'], 'enabled':'true'}, ['BTCUSD','ETHUSD'])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['watchlist'], ['BTCUSD','ETHUSD'])
        self.assertEqual(update.call_args.args[1:], (['BTCUSD','ETHUSD'], True))
        schedule.assert_called_once_with(api.ctrader.start_price_subscriptions)

    def test_db_failure_returns_503_without_success_or_subscription(self):
        response, _, schedule = self.request({'pair':'BTCUSD','enabled':'true'}, None)
        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.json['success'])
        schedule.assert_not_called()

    def test_rejects_bad_pairs_and_ambiguous_enabled(self):
        for data in ({'pair':'GHOSTUSD','enabled':'true'}, {'pair':'BTCUSD','enabled':'yes'}, {'enabled':'true'}):
            response, update, schedule = self.request(data, [])
            self.assertEqual(response.status_code, 400)
            update.assert_not_called()
            schedule.assert_not_called()

    def test_legacy_toggle_failure_is_not_reported_as_success(self):
        with patch.object(api, 'is_valid_admin_token', return_value=True), \
             patch.object(db, 'update_watchlist', return_value=None), \
             patch.object(api.reactor, 'callFromThread') as schedule:
            response = self.client.post('/api/toggle_watchlist?admin_token=test', data={'pair':'BTCUSD'})
        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.json['success'])
        schedule.assert_not_called()


if __name__ == '__main__':
    unittest.main()
