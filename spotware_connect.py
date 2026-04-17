# spotware_connect.py
import logging

from twisted.internet import reactor
from twisted.internet.defer import Deferred

from ctrader_open_api.client import Client as SpotwareClientBase
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import ProtoMessage
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAAccountAuthReq,
    ProtoOAAccountAuthRes,
    ProtoOAApplicationAuthReq,
    ProtoOAErrorRes,
    ProtoOASpotEvent,
    ProtoOASymbolsListReq,
)
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOAPayloadType
from ctrader_open_api.tcpProtocol import TcpProtocol

from config import get_demo_account_id
from state import app_state

logger = logging.getLogger(__name__)


class EventEmitter:
    def __init__(self):
        self._events = {}

    def on(self, event, func):
        self._events.setdefault(event, []).append(func)

    def emit(self, event, *args, **kwargs):
        handlers = list(self._events.get(event, []))

        def _run_handler(handler):
            try:
                handler(*args, **kwargs)
            except Exception:
                logger.exception("Event handler failed for '%s'", event)

        for handler in handlers:
            reactor.callFromThread(_run_handler, handler)


class SpotwareConnect(EventEmitter):
    def __init__(self, client_id, client_secret):
        super().__init__()

        self.host = "demo.ctraderapi.com"
        self.port = 5035
        self._client_id = client_id
        self._client_secret = client_secret
        self.is_authorized = False
        self._stopping = False

        self._client = SpotwareClientBase(self.host, self.port, TcpProtocol)
        self._client.setConnectedCallback(self._on_connected)
        self._client.setMessageReceivedCallback(self._on_message_received)
        self._client.setDisconnectedCallback(self._on_disconnected)
        self._client.account_id = None

    def start(self):
        self._stopping = False
        self._client.startService()

    def stop(self):
        self._stopping = True
        self.is_authorized = False

        try:
            stop_method = getattr(self._client, "stopService", None)
            if callable(stop_method):
                stop_method()
        except Exception:
            logger.exception("Failed to stop Spotware client")

    def send(self, message, clientMsgId=None, responseTimeoutInSeconds=5, **params):
        timeout_alias = params.pop("timeout", None)
        if timeout_alias is not None:
            responseTimeoutInSeconds = timeout_alias

        return self._client.send(
            message,
            clientMsgId=clientMsgId,
            responseTimeoutInSeconds=responseTimeoutInSeconds,
            **params,
        )

    def _on_connected(self, client):
        logger.info("Connected to cTrader. Waiting 2s before Application Auth...")
        reactor.callLater(2.0, self._send_app_auth)

    def _on_disconnected(self, client, reason=None):
        self.is_authorized = False
        self._client.account_id = None

        if self._stopping:
            logger.info("cTrader disconnected during intentional stop")
            return

        logger.warning("cTrader disconnected: %s", reason)
        self.emit("error", "DISCONNECTED")

    def _send_app_auth(self):
        if not self._client_id or not self._client_secret:
            logger.error("Missing cTrader client id/secret")
            self.emit("error", "MISSING_APP_CREDENTIALS")
            return

        logger.info("Step 1: Sending Application Auth...")
        req = ProtoOAApplicationAuthReq(
            clientId=self._client_id,
            clientSecret=self._client_secret,
        )
        self.send(req, responseTimeoutInSeconds=15)

    def _authorize_account(self):
        acc_id = get_demo_account_id()
        token = app_state.access_token

        if not acc_id or not token:
            logger.error("Missing cTrader Account ID or access token")
            self.emit("error", "MISSING_ACCOUNT_CREDENTIALS")
            return

        logger.info("Step 2: Sending Account Auth...")
        req = ProtoOAAccountAuthReq(
            ctidTraderAccountId=acc_id,
            accessToken=token,
        )
        self.send(req, responseTimeoutInSeconds=15)

    def _on_message_received(self, client, message: ProtoMessage):
        pt = message.payloadType

        if pt == ProtoOAPayloadType.PROTO_OA_APPLICATION_AUTH_RES:
            logger.info("Step 1 OK. Waiting 2s before Account Auth...")
            reactor.callLater(2.0, self._authorize_account)
            return

        if pt == ProtoOAPayloadType.PROTO_OA_ACCOUNT_AUTH_RES:
            res = ProtoOAAccountAuthRes()
            res.ParseFromString(message.payload)

            self._client.account_id = res.ctidTraderAccountId
            self.is_authorized = True

            logger.info("Step 2 OK. Account %s authorized.", res.ctidTraderAccountId)
            self.emit("ready")
            return

        if pt == ProtoOAPayloadType.PROTO_OA_ERROR_RES:
            self._handle_api_error(message)
            return

        if pt == ProtoOAPayloadType.PROTO_OA_SPOT_EVENT:
            spot_event = ProtoOASpotEvent()
            spot_event.ParseFromString(message.payload)
            self.emit("spot_event", spot_event)
            return

    def _handle_api_error(self, message: ProtoMessage):
        res = ProtoOAErrorRes()
        res.ParseFromString(message.payload)

        if res.errorCode == "ALREADY_LOGGED_IN":
            account_id = get_demo_account_id()
            if account_id:
                self._client.account_id = account_id

            self.is_authorized = True
            logger.info("Account already authorized. Marking as ready.")
            self.emit("ready")
            return

        if res.errorCode == "BLOCKED_PAYLOAD_TYPE":
            logger.critical("cTrader rate limit. Waiting before reconnect.")
            self.emit("error", "RATE_LIMIT_BLOCKED")
            return

        logger.error("cTrader API Error: %s - %s", res.errorCode, res.description)
        self.emit("error", res.errorCode)

    def get_all_symbols(self):
        if not getattr(self._client, "account_id", None):
            d = Deferred()
            reactor.callLater(0, d.errback, Exception("No Account ID"))
            return d

        req = ProtoOASymbolsListReq(ctidTraderAccountId=self._client.account_id)
        return self.send(req, responseTimeoutInSeconds=20)
