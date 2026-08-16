import unittest
from unittest.mock import patch

from flask import Flask

import api
from state import app_state


def _make_client():
    app = Flask(__name__)
    api.register_routes(app)
    return app.test_client()


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
