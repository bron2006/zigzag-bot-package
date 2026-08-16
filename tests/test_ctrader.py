import unittest
from types import SimpleNamespace

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


if __name__ == "__main__":
    unittest.main()
