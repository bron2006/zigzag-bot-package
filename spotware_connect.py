# spotware_connect.py
import logging
from twisted.internet import reactor
from twisted.internet.defer import Deferred, TimeoutError
from ctrader_open_api.client import Client as SpotwareClientBase
from ctrader_open_api.tcpProtocol import TcpProtocol
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import ProtoMessage
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAApplicationAuthReq, ProtoOAApplicationAuthRes,
    ProtoOAAccountAuthReq, ProtoOAAccountAuthRes,
    ProtoOASymbolsListReq, # Залишаємо для сумісності, хоч і не використовуємо
    ProtoOAGetSymbolsReq, ProtoOAGetSymbolsRes, # <-- Новий, правильний запит
    ProtoOAErrorRes
)
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOAPayloadType
from config import get_ctrader_access_token, get_demo_account_id

logger = logging.getLogger(__name__)

class EventEmitter:
    def __init__(self):
        self._events = {}
    def on(self, event, func):
        if event not in self._events: self._events[event] = []
        self._events[event].append(func)
    def emit(self, event, *args, **kwargs):
        if event in self._events:
            for func in self._events[event]:
                reactor.callFromThread(func, *args, **kwargs)

class SpotwareConnect(EventEmitter):
    def __init__(self, client_id, client_secret):
        super().__init__()
        self.host = "demo.ctraderapi.com"; self.port = 5035
        self._client_id = client_id; self._client_secret = client_secret
        self.is_authorized = False
        self._client = SpotwareClientBase(self.host, self.port, TcpProtocol)
        self._client.setConnectedCallback(self._on_connected)
        self._client.setMessageReceivedCallback(self._on_message_received)
        self._client.setDisconnectedCallback(self._on_disconnected)
        self._client.account_id = None

    def start(self):
        self._client.startService()

    def send(self, message, client_msg_id=None, timeout=30):
        deferred = self._client.send(message, clientMsgId=client_msg_id)
        timeout_deferred = Deferred()
        timeout_call = reactor.callLater(timeout, lambda: deferred.cancel() if not deferred.called else None)
        def on_success(result):
            if not timeout_call.called: timeout_call.cancel()
            if not timeout_deferred.called: timeout_deferred.callback(result)
        def on_error(failure):
            if not timeout_call.called: timeout_call.cancel()
            if not timeout_deferred.called:
                if failure.check(TimeoutError):
                    err_msg = f"Таймаут запиту ({timeout}s) для {type(message).__name__}"
                    logger.error(err_msg)
                    timeout_deferred.errback(Exception(err_msg))
                else:
                    timeout_deferred.errback(failure)
        deferred.addCallbacks(on_success, on_error)
        return timeout_deferred

    def _on_connected(self, client):
        logger.info("Connection successful. Authorizing application...")
        request = ProtoOAApplicationAuthReq(clientId=self._client_id, clientSecret=self._client_secret)
        self.send(request)

    def _on_disconnected(self, client, reason):
        self.is_authorized = False
        logger.warning(f"Disconnected from cTrader API. Reason: {reason.getErrorMessage()}")
        self.emit("error", f"Disconnected: {reason.getErrorMessage()}")

    def _on_message_received(self, client, message: ProtoMessage):
        payload_type = message.payloadType
        if payload_type == ProtoOAPayloadType.PROTO_OA_APPLICATION_AUTH_RES:
            logger.info("Application authorized. Authorizing trading account...")
            self._authorize_account()
        elif payload_type == ProtoOAPayloadType.PROTO_OA_ACCOUNT_AUTH_RES:
            response = ProtoOAAccountAuthRes(); response.ParseFromString(message.payload)
            self._client.account_id = response.ctidTraderAccountId
            self.is_authorized = True
            logger.info(f"✅ Account {self._client.account_id} authorized successfully.")
            self.emit("ready")
        elif payload_type == ProtoOAPayloadType.PROTO_OA_ERROR_RES:
            response = ProtoOAErrorRes(); response.ParseFromString(message.payload)
            logger.error("==================== CTrader API Error ====================")
            logger.error(f"Error Code: {response.errorCode}")
            logger.error(f"Description: {response.description}")
            logger.error("=========================================================")

    def _authorize_account(self):
        account_id = get_demo_account_id(); access_token = get_ctrader_access_token()
        logger.info(f"Attempting to authorize account ID: {account_id}...")
        if not account_id or not access_token:
            logger.error("CRITICAL: Demo Account ID or Access Token is missing.")
            return
        request = ProtoOAAccountAuthReq(ctidTraderAccountId=account_id, accessToken=access_token)
        self.send(request)

    def get_all_symbols_full(self): # <-- НОВИЙ МЕТОД
        """Робить запит на отримання ПОВНОЇ інформації про всі символи."""
        logger.info("Requesting full symbol list...")
        request = ProtoOAGetSymbolsReq(ctidTraderAccountId=self._client.account_id)
        return self.send(request)