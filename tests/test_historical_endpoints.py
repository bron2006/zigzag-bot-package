import unittest
import copy
import math
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from types import SimpleNamespace as Tick
from historical_endpoints import decode_ticks, select_endpoint


def history_fixture(deadline):
    quote = select_endpoint([(deadline + 1, 100)], [(deadline + 1, 102)], deadline)
    return dict(source='cTrader_historical_ticks_v1', complete=True, symbol_id=1,
                from_ms=math.floor((deadline - 5) * 1000), to_ms=math.floor((deadline + 5) * 1000),
                endpoint=quote, sides={'bid': [dict(ts=deadline + 1, price=100)],
                                       'ask': [dict(ts=deadline + 1, price=102)]})


class HistoryTest(unittest.TestCase):
    def test_signed_time_and_price_deltas(self):
        ticks = [Tick(timestamp=1002000, tick=10200000), Tick(timestamp=-1000, tick=-100000)]
        self.assertEqual(decode_ticks(ticks, False, 995000, 1005000), [(1001, 101), (1002, 102)])

    def test_rejects_truncated_invalid_order_and_out_of_bounds(self):
        for ticks, more in [([], True), ([Tick(timestamp=1002000, tick=1), Tick(timestamp=2, tick=1)], False),
                            ([Tick(timestamp=1006000, tick=100)], False), ([Tick(timestamp=1002000, tick=0)], False)]:
            with self.assertRaises(ValueError):
                decode_ticks(ticks, more, 995000, 1005000)

    def test_first_valid_endpoint_with_fresh_sides(self):
        q = select_endpoint([(999, 100), (1002, 104)], [(1001, 102)], 1000)
        self.assertEqual(q["ts"], 1001)
        self.assertEqual(q["mid"], 101)

    def test_no_invented_endpoint(self):
        for bids, asks in [([(990, 100)], [(1001, 102)]), ([], [(1001, 102)]),
                           ([(1006, 100)], [(1006, 102)]), ([(1001, 103)], [(1001, 102)])]:
            self.assertIsNone(select_endpoint(bids, asks, 1000))

    def test_same_timestamp_assembles_both_sides(self):
        self.assertEqual(select_endpoint([(1001, 100)], [(1001, 102)], 1000)["mid"], 101)

    def test_validates_proof_and_rejects_tampering(self):
        from historical_endpoints import validate_recovery
        history = history_fixture(1000)
        self.assertTrue(validate_recovery(history, 1000))
        for field, value in [('mid', 900), ('bid_ts', 990), ('ts', 1006), ('ask', float('nan'))]:
            invalid = copy.deepcopy(history)
            invalid['endpoint'][field] = value
            self.assertFalse(validate_recovery(invalid, 1000))
        history['complete'] = False
        self.assertFalse(validate_recovery(history, 1000))


class RecoveryDatabaseTest(unittest.TestCase):
    def setUp(self):
        import db
        self.db = db
        self.assertEqual(db.engine.url.drivername, 'sqlite')
        self.assertEqual(db.engine.url.database, ':memory:')
        db.Base.metadata.create_all(db.engine)
        self.entry = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=960)
        self.deadline = self.entry.replace(tzinfo=timezone.utc).timestamp() + 900
        self.history = history_fixture(self.deadline)
        self.identifier = db.create_signal_outcome(pair='ZZRECOVERY', timeframe='5m', verdict='BUY', score=90,
            entry_price=100, horizon_seconds=900, entry_ts=self.entry,
            evidence={'version': 'live_mid_v1', 'reason': 'no_valid_quote_in_5s_window', 'checked_at': 'original'})

    def test_unknown_recovery_preserves_audit_and_is_idempotent(self):
        db = self.db
        self.assertTrue(db.resolve_signal_outcome(self.identifier, outcome='unknown', exit_price=None))
        self.assertTrue(db.recover_signal_endpoint(self.identifier, self.history))
        self.assertFalse(db.recover_signal_endpoint(self.identifier, self.history))
        row = db.get_signal_endpoint_audit(self.identifier)
        self.assertEqual(row['outcome'], 'up_timed')
        self.assertEqual(row['evidence']['recovery']['original_reason'], 'no_valid_quote_in_5s_window')
        self.assertEqual(row['evidence']['recovery']['original_checked_at'], 'original')

    def test_pending_or_known_cannot_be_rewritten(self):
        self.assertFalse(self.db.recover_signal_endpoint(self.identifier, self.history))
        self.db.resolve_signal_outcome(self.identifier, outcome='down_timed', exit_price=99)
        self.assertFalse(self.db.recover_signal_endpoint(self.identifier, self.history))

    def test_invalid_history_keeps_unknown(self):
        self.db.resolve_signal_outcome(self.identifier, outcome='unknown', exit_price=None)
        self.history['endpoint']['mid'] = 999
        self.assertFalse(self.db.recover_signal_endpoint(self.identifier, self.history))
        self.assertEqual(self.db.get_signal_endpoint_audit(self.identifier)['outcome'], 'unknown')

    def test_cancelled_publication_is_not_recovered(self):
        self.db.resolve_signal_outcome(self.identifier, outcome='unknown', exit_price=None,
            evidence={'version': 'live_mid_v1', 'reason': 'publication_cancelled_db_delay'})
        self.assertFalse(self.db.recover_signal_endpoint(self.identifier, self.history))

    def test_unsuccessful_check_is_durable_without_changing_result(self):
        self.db.resolve_signal_outcome(self.identifier, outcome='unknown', exit_price=None)
        history = dict(self.history, endpoint=None, counts=[0, 0], ranges=[None, None])
        self.assertTrue(self.db.record_signal_history_check(self.identifier, history))
        self.assertFalse(self.db.record_signal_history_check(self.identifier, history))
        row = self.db.get_signal_endpoint_audit(self.identifier)
        self.assertEqual(row['outcome'], 'unknown')
        self.assertEqual(row['evidence']['history_check']['counts'], [0, 0])
        self.assertNotIn(self.identifier, self.db.get_recoverable_signal_ids())


class ReactorHistoryTest(unittest.TestCase):
    def exercise(self, mode):
        import historical_endpoints as history
        import analysis
        import ctrader
        from state import app_state
        from twisted.internet import defer
        from twisted.internet.task import Clock
        from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAGetTickDataRes
        clock = Clock()
        client = Tick(_client=Tick(account_id=1), is_authorized=True)
        values, errors = [], []
        calls = []
        def send(client_arg, req, response_timeout):
            calls.append(req)
            if mode == 'timeout':
                return defer.Deferred()
            response = ProtoOAGetTickDataRes(ctidTraderAccountId=2 if mode == 'account' else 1, hasMore=False)
            response.tickData.add(timestamp=1001000, tick=10000000 if req.type == 1 else 10200000)
            return defer.succeed(Tick(payloadType=response.payloadType, payload=response.SerializeToString()))
        with patch('twisted.internet.reactor', clock), patch.object(history, '_busy', False), \
             patch.object(history, '_last_started', 0), patch.object(history.time, 'time', return_value=1020), \
             patch.object(history.time, 'monotonic', return_value=1000), \
             patch.object(app_state, 'client', client), \
             patch.object(ctrader, '_resolve_broker_symbol_exact', return_value=Tick(symbolId=2)), \
             patch.object(analysis, '_send_market_data_request', side_effect=send):
            d = history.fetch_on_reactor('TEST', 1000)
            d.addCallbacks(values.append, lambda failure: errors.append(failure.value))
            if mode == 'retired':
                app_state.client = Tick()
            clock.advance(15)
            self.assertFalse(history._busy)
        return values, errors, calls

    def test_both_sides_requested_on_shared_market_data_limiter(self):
        values, errors, calls = self.exercise('ok')
        self.assertFalse(errors)
        self.assertEqual([x.type for x in calls], [1, 2])
        self.assertEqual(values[0]['endpoint']['mid'], 101)
        self.assertTrue(values[0]['complete'])

    def test_timeout_does_not_hang(self):
        values, errors, calls = self.exercise('timeout')
        self.assertFalse(values)
        self.assertEqual(len(errors), 1)

    def test_account_and_retired_transport_rejected(self):
        for mode in ('account', 'retired'):
            values, errors, calls = self.exercise(mode)
            self.assertFalse(values)
            self.assertEqual(len(errors), 1)


class RecoveryWorkerTest(unittest.TestCase):
    def test_bounded_cycle_and_failure_isolation(self):
        import db
        import historical_endpoints as history
        from twisted.internet import reactor
        row = dict(pair='TEST', deadline=1000, evidence={'reason': 'no_valid_quote_in_5s_window'})
        result = dict(endpoint=None, counts=[0, 0])
        with patch.object(history, '_attempted', {}), patch.object(history.time, 'time', return_value=1020), \
             patch.object(history.time, 'monotonic', return_value=1000), patch.object(reactor, 'running', True), \
             patch.object(db, 'get_recoverable_signal_ids', return_value=[1, 2, 3]), \
             patch.object(db, 'get_signal_endpoint_audit', return_value=row), \
             patch('twisted.internet.threads.blockingCallFromThread', side_effect=[TimeoutError, result]) as bridge, \
             patch.object(db, 'record_signal_history_check', return_value=True) as audit:
            history.recover_missing_endpoints()
        self.assertEqual(bridge.call_count, 2)
        audit.assert_called_once_with(2, result)
