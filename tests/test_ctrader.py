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

        mock_call_later.assert_called_once_with(1.0, ctrader._request_symbols, current_client, ctrader._subscription_generation)
        self.assertEqual(ctrader._reconnect_attempt, 0)


class SubscriptionReliabilityTest(unittest.TestCase):
    def setUp(self):
        from unittest.mock import Mock
        self.client = SimpleNamespace(_client=SimpleNamespace(account_id=1), send=Mock(return_value=None))
        self.client_patch = patch.object(app_state, 'client', self.client)
        self.client_patch.start()
        ctrader._reset_spot_subscriptions(self.client)
        self.symbol = SimpleNamespace(symbolId=2, symbolName='TEST')

    def tearDown(self):
        self.client_patch.stop()
        ctrader._reset_spot_subscriptions()

    def test_repeated_and_overlapping_batches_sent_once(self):
        batch = [('TEST', self.symbol)]
        ctrader._subscribe_symbol_batch(batch + batch)
        ctrader._subscribe_symbol_batch(batch)
        self.assertEqual(self.client.send.call_count, 1)
        self.assertEqual(list(self.client.send.call_args.args[0].symbolId), [2])

    def test_retired_connection_batch_ignored(self):
        ctrader._subscribe_symbol_batch([('TEST', self.symbol)], SimpleNamespace())
        self.client.send.assert_not_called()

    def test_new_connection_can_subscribe_same_symbol(self):
        ctrader._subscribe_symbol_batch([('TEST', self.symbol)])
        ctrader._reset_spot_subscriptions(self.client)
        ctrader._subscribe_symbol_batch([('TEST', self.symbol)])
        self.assertEqual(self.client.send.call_count, 2)

    def test_old_transport_generation_batch_ignored(self):
        generation = ctrader._subscription_generation
        ctrader._reset_spot_subscriptions(self.client)
        ctrader._subscribe_symbol_batch([('TEST', self.symbol)], self.client, generation)
        self.client.send.assert_not_called()

    def test_old_symbols_response_ignored(self):
        from twisted.internet.defer import Deferred
        from unittest.mock import Mock
        d = Deferred()
        self.client.get_all_symbols = Mock(return_value=d)
        with patch.object(ctrader, '_on_symbols_loaded') as loaded, patch.object(d, 'addTimeout'):
            ctrader._request_symbols(self.client)
            ctrader._reset_spot_subscriptions(self.client)
            d.callback(object())
        loaded.assert_not_called()

    def test_old_subscription_failure_does_not_clear_new_reservation(self):
        from twisted.internet.defer import Deferred
        d = Deferred()
        self.client.send.return_value = d
        ctrader._subscribe_symbol_batch([('TEST', self.symbol)])
        ctrader._reset_spot_subscriptions(self.client)
        self.client.send.return_value = None
        ctrader._subscribe_symbol_batch([('TEST', self.symbol)])
        d.errback(RuntimeError('old transport'))
        ctrader._subscribe_symbol_batch([('TEST', self.symbol)])
        self.assertEqual(self.client.send.call_count, 2)

    def test_failed_send_can_retry(self):
        self.client.send.side_effect = [RuntimeError('test'), None]
        ctrader._subscribe_symbol_batch([('TEST', self.symbol)])
        ctrader._subscribe_symbol_batch([('TEST', self.symbol)])
        self.assertEqual(self.client.send.call_count, 2)

    def test_deferred_failure_can_retry(self):
        from twisted.internet.defer import Deferred
        d = Deferred()
        self.client.send.return_value = d
        ctrader._subscribe_symbol_batch([('TEST', self.symbol)])
        d.errback(RuntimeError('test'))
        self.client.send.return_value = None
        ctrader._subscribe_symbol_batch([('TEST', self.symbol)])
        self.assertEqual(self.client.send.call_count, 2)

    def test_already_subscribed_does_not_reconnect(self):
        with patch.object(ctrader, '_schedule_reconnect') as retry:
            ctrader._handle_error('ALREADY_SUBSCRIBED')
        retry.assert_not_called()

    def test_other_connection_error_still_reconnects(self):
        with patch.object(ctrader, '_schedule_reconnect') as retry:
            ctrader._handle_error('DISCONNECTED')
        retry.assert_called_once_with(30)


if __name__ == "__main__":
    unittest.main()
