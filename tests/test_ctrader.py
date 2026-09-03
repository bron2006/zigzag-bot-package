import unittest
from types import SimpleNamespace
from unittest.mock import patch

import ctrader
from state import app_state


class ResolveBrokerSymbolTest(unittest.TestCase):
    """AUDIT FIX (2026-08-16, high): _resolve_broker_symbol used to be the
    ONLY symbol lookup, and its fuzzy startswith() prefix fallback was
    also used to size/place REAL orders in autotrader.py. A requested pair
    with no exact broker symbol could silently resolve to an unrelated
    symbol that merely shares a prefix. _resolve_broker_symbol_exact was
    split out with no fuzzy fallback, and autotrader.py's order path now
    uses it instead."""

    def setUp(self):
        self._saved_cache = dict(app_state.symbol_cache)
        app_state.symbol_cache.clear()

    def tearDown(self):
        app_state.symbol_cache.clear()
        app_state.symbol_cache.update(self._saved_cache)

    def test_exact_resolver_finds_an_exact_symbol_cache_hit(self):
        symbol = SimpleNamespace(symbolName="EURUSD", symbolId=1)
        app_state.symbol_cache["EURUSD"] = symbol

        self.assertIs(ctrader._resolve_broker_symbol_exact("EURUSD"), symbol)
        self.assertIs(ctrader._resolve_broker_symbol("EURUSD"), symbol)

    def test_exact_resolver_does_not_fuzzy_match_a_prefix(self):
        # A symbol whose name merely starts with the requested pair, with
        # no exact key match anywhere - only the fuzzy fallback should
        # ever return this.
        unrelated = SimpleNamespace(symbolName="EURUSDT", symbolId=2)
        app_state.symbol_cache["EURUSDT"] = unrelated

        self.assertIsNone(ctrader._resolve_broker_symbol_exact("EURUSD"))
        self.assertIs(ctrader._resolve_broker_symbol("EURUSD"), unrelated)

    def test_missing_symbol_returns_none_from_both_resolvers(self):
        self.assertIsNone(ctrader._resolve_broker_symbol_exact("EURUSD"))
        self.assertIsNone(ctrader._resolve_broker_symbol("EURUSD"))


class OnCtraderReadyStalenessTest(unittest.TestCase):
    """BUG FIX (2026-09-03, live finding): a disconnect can leave TWO
    SpotwareConnect instances authenticating in parallel - Twisted's own
    ClientService auto-reconnects the OLD one at the transport layer while
    ctrader.py's _do_reconnect() independently builds a NEW one and
    reassigns app_state.client to it. Both still have on_ctrader_ready
    wired (EventEmitter never unbinds a retired client's listeners), so
    whichever finished auth SECOND used to call _request_symbols() against
    whatever app_state.client happened to be at that moment - often the
    OTHER, not-yet-authorized object, producing "Symbols error: No Account
    ID" and a stuck poll cycle (hit live 2026-09-03, ~7min hang, force-
    killed by the supervisor). on_ctrader_ready now takes the client that
    fired "ready" and ignores it if it's been superseded."""

    def setUp(self):
        self._saved_client = app_state.client

    def tearDown(self):
        app_state.client = self._saved_client

    def test_ready_from_a_superseded_client_is_ignored(self):
        old_client = SimpleNamespace(name="old")
        new_client = SimpleNamespace(name="new")
        app_state.client = new_client  # ctrader._do_reconnect() already moved on

        ctrader._reconnect_attempt = 7

        with patch("ctrader.reactor.callLater") as mock_call_later:
            ctrader.on_ctrader_ready(old_client)  # the stale one finishes auth late

        mock_call_later.assert_not_called()
        self.assertEqual(ctrader._reconnect_attempt, 7, "stale ready must not reset reconnect bookkeeping")

    def test_ready_from_the_current_client_proceeds_normally(self):
        current_client = SimpleNamespace(name="current")
        app_state.client = current_client
        ctrader._reconnect_attempt = 3

        with patch("ctrader.reactor.callLater") as mock_call_later:
            ctrader.on_ctrader_ready(current_client)

        mock_call_later.assert_called_once_with(1.0, ctrader._request_symbols)
        self.assertEqual(ctrader._reconnect_attempt, 0)


if __name__ == "__main__":
    unittest.main()
