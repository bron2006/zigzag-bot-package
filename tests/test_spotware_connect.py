import unittest
from unittest.mock import MagicMock, patch

from twisted.internet.defer import Deferred

from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import ProtoMessage
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAAccountAuthReq,
    ProtoOAAccountAuthRes,
    ProtoOAApplicationAuthReq,
    ProtoOAErrorRes,
    ProtoOAGetAccountListByAccessTokenReq,
    ProtoOAGetTrendbarsReq,
)
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOAPayloadType

import config
from spotware_connect import SpotwareConnect


def _wrap(payload_type, payload_message):
    msg = ProtoMessage()
    msg.payloadType = payload_type
    msg.payload = payload_message.SerializeToString()
    return msg


class SpotwareConnectQueueTest(unittest.TestCase):
    """AUDIT FIX (2026-08-17, critical, live finding): ProtoOAGetTrendbarsReq
    (and other data requests) were observed going out before
    ProtoOAAccountAuthRes confirmed the account was authorized, rejected by
    cTrader with "Trading account is not authorized" - 0 bars back, every
    pair falls to WAIT. send() now queues everything except the auth
    handshake itself until self.is_authorized is True, instead of relying
    on every caller correctly checking account_id first."""

    def setUp(self):
        self.sc = SpotwareConnect("client_id", "client_secret")
        self.send_mock = MagicMock(side_effect=lambda *a, **k: Deferred())
        self.sc._client.send = self.send_mock

    def test_data_request_is_queued_before_authorization(self):
        self.assertFalse(self.sc.is_authorized)
        req = ProtoOAGetTrendbarsReq(ctidTraderAccountId=1, symbolId=1)

        outer = self.sc.send(req, responseTimeoutInSeconds=5)

        self.send_mock.assert_not_called()
        self.assertFalse(outer.called)
        self.assertEqual(len(self.sc._pending_data_requests), 1)
        outer.addErrback(lambda failure: None)

    def test_handshake_requests_bypass_the_queue(self):
        handshake_requests = (
            ProtoOAApplicationAuthReq(clientId="x", clientSecret="y"),
            ProtoOAGetAccountListByAccessTokenReq(accessToken="tok"),
            ProtoOAAccountAuthReq(ctidTraderAccountId=1, accessToken="tok"),
        )
        for req in handshake_requests:
            self.send_mock.reset_mock()
            self.sc.send(req)
            self.send_mock.assert_called_once()
            self.assertEqual(self.sc._pending_data_requests, [])

    def test_requests_go_straight_through_once_authorized(self):
        self.sc.is_authorized = True
        req = ProtoOAGetTrendbarsReq(ctidTraderAccountId=1, symbolId=1)

        self.sc.send(req)

        self.send_mock.assert_called_once()
        self.assertEqual(self.sc._pending_data_requests, [])

    def test_account_auth_res_flushes_the_queue(self):
        req = ProtoOAGetTrendbarsReq(ctidTraderAccountId=1, symbolId=1)
        self.sc.send(req)
        self.send_mock.assert_not_called()

        auth_res = ProtoOAAccountAuthRes(ctidTraderAccountId=1)
        self.sc._on_message_received(None, _wrap(ProtoOAPayloadType.PROTO_OA_ACCOUNT_AUTH_RES, auth_res))

        self.assertTrue(self.sc.is_authorized)
        self.send_mock.assert_called_once()
        self.assertEqual(self.sc._pending_data_requests, [])

    def test_already_logged_in_error_also_flushes_the_queue(self):
        req = ProtoOAGetTrendbarsReq(ctidTraderAccountId=1, symbolId=1)
        self.sc.send(req)
        self.send_mock.assert_not_called()

        err = ProtoOAErrorRes(errorCode="ALREADY_LOGGED_IN", description="already")
        self.sc._on_message_received(None, _wrap(ProtoOAPayloadType.PROTO_OA_ERROR_RES, err))

        self.assertTrue(self.sc.is_authorized)
        self.send_mock.assert_called_once()
        self.assertEqual(self.sc._pending_data_requests, [])

    def test_account_auth_res_emits_ready_with_the_client_instance(self):
        # BUG FIX (2026-09-03, live finding): a stale/superseded
        # SpotwareConnect's "ready" used to be indistinguishable from the
        # current one's to ctrader.on_ctrader_ready, which read whatever
        # app_state.client happened to be at that moment - see ctrader.py's
        # own regression test for the actual race this closes. This just
        # proves the client is included on the event so a listener CAN tell.
        handler = MagicMock()
        self.sc.on("ready", handler)

        with patch("spotware_connect.reactor.callFromThread", side_effect=lambda f, *a, **k: f(*a, **k)):
            auth_res = ProtoOAAccountAuthRes(ctidTraderAccountId=1)
            self.sc._on_message_received(None, _wrap(ProtoOAPayloadType.PROTO_OA_ACCOUNT_AUTH_RES, auth_res))

        handler.assert_called_once_with(self.sc)

    def test_already_logged_in_error_emits_ready_with_the_client_instance(self):
        handler = MagicMock()
        self.sc.on("ready", handler)

        with patch("spotware_connect.reactor.callFromThread", side_effect=lambda f, *a, **k: f(*a, **k)):
            err = ProtoOAErrorRes(errorCode="ALREADY_LOGGED_IN", description="already")
            self.sc._on_message_received(None, _wrap(ProtoOAPayloadType.PROTO_OA_ERROR_RES, err))

        handler.assert_called_once_with(self.sc)

    def test_disconnect_fails_pending_queued_requests(self):
        req = ProtoOAGetTrendbarsReq(ctidTraderAccountId=1, symbolId=1)
        outer = self.sc.send(req)

        self.sc._on_disconnected(None, reason="TEST")

        self.assertTrue(outer.called)
        self.assertEqual(self.sc._pending_data_requests, [])
        outer.addErrback(lambda failure: None)

    def test_stop_fails_pending_queued_requests(self):
        req = ProtoOAGetTrendbarsReq(ctidTraderAccountId=1, symbolId=1)
        outer = self.sc.send(req)

        self.sc.stop()

        self.assertTrue(outer.called)
        self.assertEqual(self.sc._pending_data_requests, [])
        outer.addErrback(lambda failure: None)

    def test_queue_has_a_size_cap(self):
        # Defense-in-depth (2026-08-17, per external consultation): each
        # queued item already self-clears via its own timeout, and the
        # queue is already cleared on disconnect/stop/host-switch - this
        # just proves the extra ceiling actually holds.
        for i in range(config.SPOTWARE_MAX_PENDING_DATA_REQUESTS):
            outer = self.sc.send(ProtoOAGetTrendbarsReq(ctidTraderAccountId=1, symbolId=i))
            outer.addErrback(lambda failure: None)
        self.assertEqual(len(self.sc._pending_data_requests), config.SPOTWARE_MAX_PENDING_DATA_REQUESTS)

        overflow = self.sc.send(ProtoOAGetTrendbarsReq(ctidTraderAccountId=1, symbolId=9999))
        overflow.addErrback(lambda failure: None)

        # The overflow request must not have been added to the queue.
        self.assertEqual(len(self.sc._pending_data_requests), config.SPOTWARE_MAX_PENDING_DATA_REQUESTS)


if __name__ == "__main__":
    unittest.main()
