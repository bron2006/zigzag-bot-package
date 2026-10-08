"""Offline failure-injection tests; run with DATABASE_URL=sqlite:///:memory:."""
import threading
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from twisted.internet import defer, task
from twisted.python.failure import Failure

from bounded_io import BoundedIO, BoundedIOTimeout


class BoundedIOTest(unittest.TestCase):
    def test_hung_call_has_deadline_and_no_worker_queue(self):
        clock = task.Clock()
        delivered = []
        finished = threading.Event()
        def dispatch(f, *args):
            delivered.append((f, args))
            finished.set()
        clock.callFromThread = dispatch
        worker = BoundedIO(clock, timeout=10)
        started, release = threading.Event(), threading.Event()
        def hanging():
            started.set()
            release.wait(3)
            return "late"
        pending = worker.call(hanging)
        failures = []
        pending.addErrback(lambda error: failures.append(error.type))
        self.assertTrue(started.wait(1))
        try:
            clock.advance(10)
            self.assertEqual(failures, [BoundedIOTimeout])
            never = Mock()
            rejected = []
            worker.call(never).addErrback(lambda error: rejected.append(error.type))
            self.assertEqual(rejected, [BoundedIOTimeout])
            never.assert_not_called()
        finally:
            release.set()
        self.assertTrue(finished.wait(1))
        for f, args in delivered:
            f(*args)
        self.assertEqual(failures, [BoundedIOTimeout])

    def test_success_and_failure_cancel_timer(self):
        for function, success in [(lambda: 42, True), (lambda: 1/0, False)]:
            clock = task.Clock()
            done, queued = threading.Event(), []
            def dispatch(f, *args):
                queued.append((f, args))
                done.set()
            clock.callFromThread = dispatch
            values = []
            BoundedIO(clock).call(function).addBoth(values.append)
            self.assertTrue(done.wait(1))
            for f, args in queued:
                f(*args)
            if success:
                self.assertEqual(values, [42])
            else:
                self.assertIsInstance(values[0], Failure)
            self.assertFalse(clock.getDelayedCalls())


class BrokerRecoveryTest(unittest.TestCase):
    def test_disconnected_service_is_stopped(self):
        from ctrader_open_api.client import Client
        client = Client.__new__(Client)
        client.running, client.isConnected = True, False
        with patch("ctrader_open_api.client.ClientService.stopService", return_value=defer.succeed(None)) as stop:
            client.stopService()
        stop.assert_called_once_with(client)

    def test_disconnect_fails_pending_requests_immediately(self):
        from ctrader_open_api.client import Client
        client = Client.__new__(Client)
        pending = defer.Deferred()
        values = []
        pending.addErrback(lambda f: values.append(f.type))
        client._responseDeferreds = {"request": pending}
        client._disconnected(None)
        self.assertEqual(values, [ConnectionError])
        self.assertEqual(client._responseDeferreds, {})

    def test_late_connection_failure_after_request_timeout_is_consumed(self):
        from ctrader_open_api.client import Client
        from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAApplicationAuthReq
        client = Client.__new__(Client)
        client._runningReactor = task.Clock()
        client._responseDeferreds = {}
        connection = defer.Deferred()
        with patch.object(client, "whenConnected", return_value=connection):
            response = client.send(ProtoOAApplicationAuthReq(), responseTimeoutInSeconds=5)
        values = []
        response.addErrback(lambda f: values.append(f.type))
        client._runningReactor.advance(5)
        connection.errback(ConnectionError("late failure"))
        self.assertEqual(len(values), 1)
        self.assertIsNone(connection.result)

    def test_handshake_failure_recovers_and_is_consumed(self):
        from spotware_connect import SpotwareConnect
        from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAApplicationAuthReq
        client = SpotwareConnect("id", "secret")
        pending = defer.Deferred()
        with patch.object(client, "send", return_value=pending), patch.object(client, "emit") as emit:
            client._send_handshake(ProtoOAApplicationAuthReq(clientId="id", clientSecret="secret"))
            pending.errback(TimeoutError("no response"))
            emit.assert_called_once_with("error", "AUTH_HANDSHAKE_TIMEOUT")
        self.assertIsNone(pending.result)

    def test_retired_handshake_does_not_restart_successor(self):
        from spotware_connect import SpotwareConnect
        from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAApplicationAuthReq
        client = SpotwareConnect("id", "secret")
        pending = defer.Deferred()
        with patch.object(client, "send", return_value=pending), patch.object(client, "emit") as emit:
            client._send_handshake(ProtoOAApplicationAuthReq(clientId="id", clientSecret="secret"))
            client._stopping = True
            pending.errback(TimeoutError("no response"))
            emit.assert_not_called()

    def test_transport_queues_are_not_shared(self):
        from ctrader_open_api.tcpProtocol import TcpProtocol
        first, second = TcpProtocol(), TcpProtocol()
        first.send(b"old")
        self.assertEqual(len(first._send_queue), 1)
        self.assertEqual(len(second._send_queue), 0)

    def test_intentional_stop_cancels_pending_reconnect(self):
        import ctrader
        clock = task.Clock()
        stub = SimpleNamespace(stop=Mock())
        with patch.object(ctrader, "reactor", clock), \
             patch.object(ctrader, "_reconnect_scheduled", False), \
             patch.object(ctrader, "_reconnect_call", None), \
             patch.object(ctrader.app_state, "client", stub), \
             patch.object(ctrader.app_state, "clear_symbol_state"), \
             patch.object(ctrader.app_state, "clear_live_prices"), \
             patch.object(ctrader, "start_ctrader_client") as start:
            ctrader._schedule_reconnect(30)
            ctrader.stop_ctrader_client()
            clock.advance(31)
            start.assert_not_called()
            stub.stop.assert_called_once()

    def test_oauth_http_has_timeout(self):
        from ctrader_open_api.auth import Auth
        with patch("ctrader_open_api.auth.requests.get") as get:
            Auth("id", "secret", "").refreshToken("test-token")
        self.assertEqual(get.call_args.kwargs["timeout"], (5, 10))

    def test_retired_connection_message_cannot_change_authorization(self):
        from spotware_connect import SpotwareConnect
        from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import ProtoMessage
        from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAAccountAuthRes
        from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOAPayloadType
        client = SpotwareConnect("id", "secret")
        response = ProtoOAAccountAuthRes(ctidTraderAccountId=1)
        message = ProtoMessage(payloadType=ProtoOAPayloadType.PROTO_OA_ACCOUNT_AUTH_RES,
                               payload=response.SerializeToString())
        client._on_message_received(object(), message)
        self.assertFalse(client.is_authorized)

    def test_token_persistence_is_not_called_on_reactor_thread(self):
        from spotware_connect import SpotwareConnect
        client = SpotwareConnect("id", "secret")
        with patch.object(client._token_persistence, "call", return_value=defer.succeed(True)) as worker, \
             patch("spotware_connect.app_state.set_ctrader_tokens") as update, \
             patch("spotware_connect.reactor.callLater"):
            client._on_refresh_success({"accessToken": "fake", "refreshToken": "fake", "expiresIn": 300})
        update.assert_called_once_with(access_token="fake", refresh_token="fake", expires_in=300, persist=False)
        worker.assert_called_once()

    def test_retired_refresh_result_does_not_overwrite_current_tokens(self):
        from spotware_connect import SpotwareConnect
        client = SpotwareConnect("id", "secret")
        client._stopping = True
        with patch("spotware_connect.app_state.set_ctrader_tokens") as update:
            client._on_refresh_success({"accessToken": "fake"})
        update.assert_not_called()


class DatabaseFailureTest(unittest.TestCase):
    def test_unavailable_database_fails_closed(self):
        import db
        with patch.object(db, "SessionLocal", None):
            state = db.get_vwap_executor_runtime_state()
        self.assertFalse(state["runtime_enabled"])
        self.assertTrue(state["read_only"])
        self.assertFalse(state["database_available"])

    def test_missing_runtime_state_is_not_a_successful_poll(self):
        import vwap_executor as v
        with patch.object(v, "VWAP_EXECUTOR_ENABLED", True), \
             patch.object(v.db, "get_vwap_executor_runtime_state", return_value={"database_available": False}):
            with self.assertRaises(BoundedIOTimeout):
                v.is_active()

    def test_postgres_engine_has_connection_and_statement_limits(self):
        import db
        with patch.object(db, "create_engine") as create, patch.object(db.event, "listen") as listen:
            db._build_engine("postgresql://invalid/test")
        kwargs = create.call_args.kwargs
        self.assertEqual(kwargs["pool_timeout"], 10)
        self.assertEqual(kwargs["connect_args"]["connect_timeout"], 8)
        self.assertIn("statement_timeout=8000", kwargs["connect_args"]["options"])
        listen.assert_called_once_with(create.return_value, "begin", db._set_transaction_deadlines)

    def test_deadlines_are_set_inside_each_transaction(self):
        import db
        connection = Mock()
        db._set_transaction_deadlines(connection)
        self.assertEqual(connection.exec_driver_sql.call_count, 2)
        self.assertIn("SET LOCAL statement_timeout", connection.exec_driver_sql.call_args_list[0].args[0])

    def test_db_timeout_keeps_loop_alive_without_fake_heartbeat(self):
        import vwap_executor as v
        values = []
        with patch.object(v, "_poll_all_symbols_inner", return_value=defer.fail(BoundedIOTimeout("hung"))), \
             patch.object(v, "_mark_poll_completed") as heartbeat:
            v._poll_all_symbols().addBoth(values.append)
        self.assertEqual(values, [None])
        heartbeat.assert_not_called()

    def test_unexpected_failure_does_not_stop_looping_call(self):
        import vwap_executor as v
        with patch.object(v, "_poll_all_symbols_inner", return_value=defer.fail(ValueError("bad data"))):
            values = []
            v._poll_all_symbols().addBoth(values.append)
        self.assertEqual(values, [None])

    def test_readonly_emergency_stop_never_sends_orders(self):
        import vwap_executor as v
        client = Mock()
        with patch.object(v, "_db_read", side_effect=lambda f, *a, **kw: defer.maybeDeferred(f, *a, **kw)), \
             patch.object(v, "_is_read_only", return_value=True), \
             patch.object(v.db, "get_open_and_pending_vwap_trades") as load:
            values = []
            v._emergency_stop_all(client, 1).addBoth(values.append)
        self.assertEqual(values, [None])
        load.assert_not_called()
        client.send.assert_not_called()


class ScanFailureTest(unittest.TestCase):
    def setUp(self):
        import vwap_executor as v
        self.v = v
        self.patches = [
            patch.object(v, "_in_weekend_closure", return_value=False),
            patch.object(v, "_current_session_window_utc", return_value=(datetime(2026,10,7,8,tzinfo=timezone.utc), datetime(2026,10,7,16,tzinfo=timezone.utc))),
            patch.object(v.app_state, "client", SimpleNamespace(_client=SimpleNamespace(account_id=1))),
            patch.object(v, "_wait_for_live_client", return_value=defer.succeed(True)),
            patch.object(v, "is_active", return_value=True),
            patch.object(v, "_db_read", side_effect=lambda f, *a, **kw: defer.maybeDeferred(f, *a, **kw)),
            patch.object(v, "SYMBOLS", ["A", "B", "C", "D", "E"]),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def test_three_failures_end_cycle_instead_of_timing_out_every_symbol(self):
        with patch.object(self.v, "_fetch_session_bars", side_effect=lambda *a: defer.succeed(None)) as fetch, \
             patch.object(self.v, "_mark_poll_completed") as mark:
            values = []
            self.v._poll_all_symbols().addBoth(values.append)
        self.assertEqual(values, [None])
        self.assertEqual(fetch.call_count, 3)
        mark.assert_called_once()

    def test_not_ready_client_wait_is_bounded_and_loop_returns(self):
        with patch.object(self.v, "_wait_for_live_client", return_value=defer.succeed(False)) as wait, \
             patch.object(self.v, "_mark_poll_completed") as mark:
            self.v._poll_all_symbols()
        wait.assert_called_once_with(max_wait_seconds=30.0)
        mark.assert_called_once()
