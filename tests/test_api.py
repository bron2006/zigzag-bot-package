import unittest
from unittest.mock import patch

from flask import Flask

import api
from state import app_state


def _make_client():
    app = Flask(__name__)
    api.register_routes(app)
    return app.test_client()


class EndpointAuditTest(unittest.TestCase):
    def setUp(self):
        self.client = _make_client()

    def test_paper_account_requires_admin_and_failure_is_not_zero_balance(self):
        self.assertEqual(self.client.get('/api/stats/paper_stops').status_code,401)
        with patch('api.is_valid_admin_token',return_value=True),patch('api.db.is_admin_user',return_value=False):
            self.assertEqual(self.client.get('/api/stats/paper_stops').status_code,403)
        with patch('api.is_valid_admin_token',return_value=True),patch('api.db.is_admin_user',return_value=True), \
             patch('paper_stop_view.snapshot',return_value={'ok':True,'status':'not_started','balance':None}) as read:
            response=self.client.get('/api/stats/paper_stops')
            self.assertEqual(response.status_code,200)
            self.assertIsNone(response.json['balance'])
            response=self.client.get('/api/stats/paper_stops?before=25')
            self.assertEqual(read.call_args.kwargs['before'],25)
            self.assertEqual(self.client.get('/api/stats/paper_stops?before=-1').status_code,400)
            read.side_effect=ValueError('bad journal')
            response=self.client.get('/api/stats/paper_stops')
            self.assertEqual(response.status_code,503)
            self.assertNotIn('balance',response.json)

    def test_paper_quotes_are_protected_bounded_and_keep_legacy_mid_format(self):
        self.assertEqual(self.client.get('/api/live_price?pairs=EURUSD&format=paper').status_code,401)
        quote=dict(bid=100,ask=101,bid_ts=1000,ask_ts=1001,ts=1001,source='cTrader',sampled=True)
        with patch('api.is_valid_admin_token',return_value=True), \
             patch.object(app_state,'get_paper_quote',return_value=quote), \
             patch.object(app_state,'get_live_prices_snapshot',return_value={'EURUSD':dict(mid=100.5,ts=1001)}):
            paper=self.client.get('/api/live_price?pairs=EURUSD&format=paper')
            self.assertEqual(paper.json['quotes']['EURUSD'],quote)
            legacy=self.client.get('/api/live_price?pairs=EURUSD')
            self.assertEqual(legacy.json['prices']['EURUSD'],dict(mid=100.5,ts=1001))
            self.assertNotIn('quotes',legacy.json)
            self.assertEqual(self.client.get('/api/live_price?pairs=EURUSD&format=bad').status_code,400)
            self.assertEqual(self.client.get('/api/live_price',query_string=dict(pairs=','.join(['EURUSD']*17),format='paper')).status_code,400)

    def test_missing_paper_quote_is_not_midpoint_fallback(self):
        with patch('api.is_valid_admin_token',return_value=True), \
             patch.object(app_state,'get_paper_quote',return_value=None):
            response=self.client.get('/api/live_price?pairs=EURUSD&format=paper')
            self.assertEqual(response.json['quotes'],{})

    def test_primary_valuation_is_explicit_and_invalid_policy_is_rejected(self):
        with patch('api.is_valid_admin_token',return_value=True), \
             patch('api.db.is_admin_user',return_value=True), \
             patch('api.db.get_signal_outcome_stats',return_value={'ok':True}) as read:
            response=self.client.get('/api/stats/signals',query_string={
                'admin_token':'mock','scope':'current_test','valuation':'asof60'})
            self.assertEqual(response.status_code,200)
            self.assertEqual(read.call_args.kwargs['valuation'],'asof60')
            read.reset_mock()
            response=self.client.get('/api/stats/signals',query_string={
                'admin_token':'mock','scope':'history','valuation':'asof60'})
            self.assertEqual(response.status_code,400)
            read.assert_not_called()

    def test_unauthenticated_probe_is_rejected(self):
        with patch('api.db.get_signal_endpoint_audit') as read:
            self.assertEqual(self.client.post('/api/admin/endpoint-audit', data={'id': 1}).status_code, 401)
            read.assert_not_called()

    def test_admin_probe_reads_only_one_row_and_uses_reactor(self):
        row = dict(id=1, pair='BTCUSD', deadline=1000, outcome='unknown', evidence={})
        with patch('api.is_valid_admin_token', return_value=True), \
             patch('api.db.get_signal_endpoint_audit', return_value=row) as read, \
             patch('api.blockingCallFromThread', return_value={'endpoint': None}) as bridge:
            resp = self.client.post('/api/admin/endpoint-audit', data={'id': 1, 'admin_token': 'mock'})
        self.assertEqual(resp.status_code, 200)
        read.assert_called_once_with(1)
        self.assertEqual(bridge.call_args.args[2:], ('BTCUSD', 1000))

    def test_broker_failure_is_bounded_error_not_fake_result(self):
        row = dict(id=1, pair='BTCUSD', deadline=1000, outcome='unknown', evidence={})
        with patch('api.is_valid_admin_token', return_value=True), \
             patch('api.db.get_signal_endpoint_audit', return_value=row), \
             patch('api.blockingCallFromThread', side_effect=TimeoutError):
            resp = self.client.post('/api/admin/endpoint-audit', data={'id': 1})
        self.assertEqual(resp.status_code, 503)

    def test_asof_audit_uses_separate_policy_without_writing(self):
        row = dict(id=1,pair='BTCUSD',deadline=1300,outcome='unknown',evidence={})
        with patch('api.is_valid_admin_token',return_value=True), \
             patch('api.db.get_signal_endpoint_audit',return_value=row), \
             patch('api.blockingCallFromThread',return_value={'endpoint':None}) as bridge, \
             patch('api.db.save_signal_asof_audit') as write:
            resp=self.client.post('/api/admin/endpoint-audit',data={'id':1,'phase':'asof60'})
        self.assertEqual(resp.status_code,200)
        self.assertEqual(bridge.call_args.args[2:],('BTCUSD',1300,'asof60'))
        write.assert_not_called()

    def test_entry_audit_uses_saved_broker_quote_time(self):
        row = dict(id=1,pair='BTCUSD',deadline=1300,outcome='unknown',
                   evidence={'entry_quote': {'ts': 998, 'mid': 100}})
        with patch('api.is_valid_admin_token', return_value=True), \
             patch('api.db.get_signal_endpoint_audit', return_value=row), \
             patch('api.blockingCallFromThread', return_value={'endpoint': None}) as bridge:
            resp = self.client.post('/api/admin/endpoint-audit',data={'id':1,'phase':'entry'})
        self.assertEqual(resp.status_code,200)
        self.assertEqual(bridge.call_args.args[2:],('BTCUSD',998))
        self.assertEqual(resp.json['saved'],row['evidence']['entry_quote'])


class CtraderOauthStartAuthTest(unittest.TestCase):
    """SECURITY FIX (2026-08-15, audit finding): /api/ctrader/oauth/start had
    no auth at all - anyone could start the flow with their OWN cTrader
    account and the callback would unconditionally overwrite this app's
    shared CTRADER_ACCESS_TOKEN/CTRADER_REFRESH_TOKEN. Now admin-only."""

    def setUp(self):
        self.client = _make_client()

    def test_rejects_request_with_no_admin_token(self):
        resp = self.client.get("/api/ctrader/oauth/start")
        self.assertEqual(resp.status_code, 401)

    def test_rejects_request_with_wrong_admin_token(self):
        resp = self.client.get("/api/ctrader/oauth/start?admin_token=not-the-real-one")
        self.assertEqual(resp.status_code, 401)

    def test_allows_request_with_valid_admin_token_and_mints_state(self):
        with patch("api.is_valid_admin_token", return_value=True), \
             patch("api.get_ct_client_id", return_value="id"), \
             patch("api.get_ct_client_secret", return_value="secret"), \
             patch("api.get_ctrader_redirect_uri", return_value="https://example.com/cb"):
            resp = self.client.get("/api/ctrader/oauth/start?admin_token=whatever-since-mocked")

        self.assertEqual(resp.status_code, 302)
        self.assertIn("id.ctrader.com", resp.headers["Location"])
        self.assertIn("state=", resp.headers["Location"])
        # A real, single-use state was actually stored - proven by the next
        # class's tests, which don't go through this route at all.


class CtraderOauthCallbackStateTest(unittest.TestCase):
    """CSRF/state check (2026-08-15): the callback must reject any `code`
    that isn't paired with the exact state /start minted for THIS flow -
    otherwise a crafted callback link could inject an attacker's own OAuth
    code into the shared token state (see AppState.consume_ctrader_oauth_
    pending_state's docstring for the attack this closes)."""

    def setUp(self):
        self.client = _make_client()
        # Clean slate regardless of what an earlier test left pending.
        app_state.consume_ctrader_oauth_pending_state("__drain__")

    def test_rejects_missing_state(self):
        resp = self.client.get("/api/ctrader/oauth/callback?code=abc")
        self.assertEqual(resp.status_code, 403)

    def test_rejects_wrong_state(self):
        app_state.set_ctrader_oauth_pending_state("the-real-state")
        resp = self.client.get("/api/ctrader/oauth/callback?code=abc&state=guessed-wrong")
        self.assertEqual(resp.status_code, 403)

    def _mocked_success_callback(self, url):
        # Mocks everything the success path touches beyond the state check
        # itself, so this stays a side-effect-free unit test: no real
        # network token exchange, no real DB persist, no real env mutation.
        with patch("api._ctrader_oauth_client") as mock_client, \
             patch("api.app_state.set_ctrader_tokens") as mock_set_tokens, \
             patch.dict("os.environ", {}, clear=False), \
             patch("api.reactor"):
            mock_client.return_value.getToken.return_value = {
                "accessToken": "a", "refreshToken": "b", "expiresIn": 3600,
            }
            resp = self.client.get(url)
        return resp, mock_client, mock_set_tokens

    def test_rejects_replayed_state(self):
        app_state.set_ctrader_oauth_pending_state("one-time-state")
        url = "/api/ctrader/oauth/callback?code=abc&state=one-time-state"
        first, _, _ = self._mocked_success_callback(url)
        self.assertEqual(first.status_code, 200)

        second = self.client.get(url)
        self.assertEqual(second.status_code, 403)

    def test_accepts_matching_state_and_proceeds_to_token_exchange(self):
        app_state.set_ctrader_oauth_pending_state("good-state")
        resp, mock_client, mock_set_tokens = self._mocked_success_callback(
            "/api/ctrader/oauth/callback?code=abc&state=good-state"
        )

        self.assertEqual(resp.status_code, 200)
        mock_client.return_value.getToken.assert_called_once_with("abc")
        mock_set_tokens.assert_called_once()


class ConsumeCtraderOauthPendingStateTest(unittest.TestCase):
    """Unit-level coverage of the state.py mechanism itself, independent of
    the Flask routes above."""

    def tearDown(self):
        app_state.consume_ctrader_oauth_pending_state("__drain__")

    def test_consume_fails_when_nothing_was_ever_set(self):
        self.assertFalse(app_state.consume_ctrader_oauth_pending_state("anything"))

    def test_consume_succeeds_once_then_fails_on_replay(self):
        app_state.set_ctrader_oauth_pending_state("s1")
        self.assertTrue(app_state.consume_ctrader_oauth_pending_state("s1"))
        self.assertFalse(app_state.consume_ctrader_oauth_pending_state("s1"))

    def test_consume_fails_after_expiry(self):
        app_state.set_ctrader_oauth_pending_state("s2")
        with patch("state.time.time", return_value=__import__("time").time() + 700):
            self.assertFalse(app_state.consume_ctrader_oauth_pending_state("s2"))


if __name__ == "__main__":
    unittest.main()
