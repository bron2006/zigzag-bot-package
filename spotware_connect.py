# spotware_connect.py
import logging
import requests

from twisted.internet import reactor
from twisted.internet.defer import Deferred, TimeoutError

from ctrader_open_api.client import Client as SpotwareClientBase
from ctrader_open_api.tcpProtocol import TcpProtocol
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import ProtoMessage
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAApplicationAuthReq,
    ProtoOAAccountAuthReq,
    ProtoOAAccountAuthRes,
    ProtoOASymbolsListReq,
    ProtoOASymbolsListRes,
    ProtoOAErrorRes,
    ProtoOASpotEvent,
)
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOAPayloadType

from config import get_demo_account_id, get_ctrader_refresh_token
from state import app_state

logger = logging.getLogger(__name__)

TOKEN_REFRESH_URL = "https://connect.spotware.com/apps/token"


class EventEmitter:
    def __init__(self):
        self._events = {}

    def on(self, event, func):
        if event not in self._events:
            self._events[event] = []
        self._events[event].append(func)

    def emit(self, event, *args, **kwargs):
        if event in self._events:
            for func in self._events[event]:
                reactor.callFromThread(func, *args, **kwargs)

    def remove_listener(self, event, func):
        if event in self._events and func in self._events[event]:
            self._events[event].remove(func)


class SpotwareConnect(EventEmitter):
    def __init__(self, client_id, client_secret):
        super().__init__()
        self.host = "demo.ctraderapi.com"
        self.port = 5035
        self._client_id = client_id
        self._client_secret = client_secret
        self.is_authorized = False
        self.is_refreshing_token = False

        self._client = SpotwareClientBase(self.host, self.port, TcpProtocol)
        self._client.setConnectedCallback(self._on_connected)
        self._client.setMessageReceivedCallback(self._on_message_received)
        self._client.setDisconnectedCallback(self._on_disconnected)
        self._client.account_id = None

        self.symbol_map = {}

    def start(self):
        self._client.startService()

    def stop(self):
        try:
            self.is_authorized = False
            stop_method = getattr(self._client, "stopService", None)
            if callable(stop_method):
                stop_method()
        except Exception:
            logger.exception("Failed to stop Spotware client")

    def send(self, message, client_msg_id=None, timeout=30):
        # ФІКС: Більше не передаємо timeout у саму бібліотеку (вона його не знає)
        deferred = self._client.send(message, clientMsgId=client_msg_id)
        timeout_deferred = Deferred()

        timeout_call = reactor.callLater(
            timeout,
            lambda: deferred.cancel() if not deferred.called else None,
        )

        def on_success(result):
            if timeout_call.active():
                timeout_call.cancel()
            if not timeout_deferred.called:
                timeout_deferred.callback(result)
            return None

        def on_error(failure):
            if timeout_call.active():
                timeout_call.cancel()
            if not timeout_deferred.called:
                timeout_deferred.errback(failure)
            return None

        deferred.addCallbacks(on_success, on_error)
        return timeout_deferred

    def _refresh_access_token(self):
        if self.is_refreshing_token:
            return

        self.is_refreshing_token = True
        logger.info("Refreshing access token...")
        refresh_token = get_ctrader_refresh_token()
        if not refresh_token:
            logger.error("CTRADER_REFRESH_TOKEN is missing")
            self.is_refreshing_token = False
            return

        try:
            params = {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            }
            response = requests.post(TOKEN_REFRESH_URL, data=params, timeout=20)
            response.raise_for_status()
            app_state.access_token = response.json().get("accessToken")
            logger.info("✅ Token refreshed.")
            self._authorize_account()
        except Exception as e:
            logger.error(f"Refresh failed: {e}")
        finally:
            self.is_refreshing_token = False

    def _on_connected(self, client):
        logger.info("Connection successful. Authorizing application...")
        self._client.send(
            ProtoOAApplicationAuthReq(
                clientId=self._client_id,
                clientSecret=self._client_secret,
            )
        )

    def _on_disconnected(self, client, reason):
        self.is_authorized = False
        msg = reason.getErrorMessage() if hasattr(reason, "getErrorMessage") else str(reason)
        logger.warning(f"Disconnected: {msg}")
        self.emit("error", msg)

    def _on_message_received(self, client, message: ProtoMessage):
        pt = message.payloadType

        if pt == ProtoOAPayloadType.PROTO_OA_APPLICATION_AUTH_RES:
            logger.info("App authorized. Authorizing account...")
            self._authorize_account()
            return

        elif pt == ProtoOAPayloadType.PROTO_OA_ACCOUNT_AUTH_RES:
            res = ProtoOAAccountAuthRes()
            res.ParseFromString(message.payload)
            self._client.account_id = res.ctidTraderAccountId
            self.is_authorized = True
            logger.info(f"✅ Account {res.ctidTraderAccountId} authorized.")
            self.emit("ready")
            return

        elif pt == ProtoOAPayloadType.PROTO_OA_ERROR_RES:
            res = ProtoOAErrorRes()
            res.ParseFromString(message.payload)
            
            # ФІКС: Обробка блокування та повторної авторизації
            if res.errorCode == "ALREADY_LOGGED_IN":
                logger.info("Already authorized. Proceeding...")
                self.is_authorized = True
                self.emit("ready")
                return

            if res.errorCode == "BLOCKED_PAYLOAD_TYPE":
                logger.critical("🚨 cTrader RATE LIMIT! Нам треба відпочити.")
                self.emit("error", "RATE_LIMIT_BLOCKED")
                return

            logger.error(f"API Error: {res.errorCode} - {res.description}")
            self.emit("error", res.errorCode)
            return

        elif pt == ProtoOAPayloadType.PROTO_OA_SPOT_EVENT:
            spot_event = ProtoOASpotEvent()
            spot_event.ParseFromString(message.payload)
            self.emit("spot_event", spot_event)
            self.emit(f"spot_event_{spot_event.symbolId}", spot_event)

    def _authorize_account(self):
        acc_id = get_demo_account_id()
        token = app_state.access_token
        if not acc_id or not token: return
        logger.info(f"Authorizing account {acc_id}...")
        self._client.send(
            ProtoOAAccountAuthReq(
                ctidTraderAccountId=acc_id,
                accessToken=token,
            )
        )

    def get_all_symbols(self):
        if not self._client.account_id:
            d = Deferred()
            reactor.callLater(0, d.errback, Exception("No account ID"))
            return d
        return self.send(ProtoOASymbolsListReq(ctidTraderAccountId=self._client.account_id))