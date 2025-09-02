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
    ProtoOASymbolsListReq,
    ProtoOAErrorRes,
    ProtoOASpotEvent # <-- НОВИЙ ІМПОРТ
)
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOAPayloadType
from config import get_ctrader_access_token, get_demo_account_id

logger = logging.getLogger(__name__)

class EventEmitter:
    def __init__(self): self._events = {}
    def on(self, event, func):
        if event not in self._events: self._events[event] = []
        self._events[event].append(func)
    def emit(self, event, *args, **kwargs):
        if event in self._events:
            for func in self._events[event]: reactor.callFromThread(func, *args, **kwargs)
    # --- ПОЧАТОК ЗМІН: Додаємо метод для видалення слухача ---
    def remove_listener(self, event, func):
        if event in self._events:
            if func in self._events[event]:
                self._events[event].remove(func)
    # --- КІНЕЦЬ ЗМІН ---

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

    def start(self): self._client.startService()

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
                    err_msg = f"Таймаут ({timeout}s) для {type(message).__name__}"
                    logger.error(err_msg)
                    timeout_deferred.errback(Exception(err_msg))
                else: timeout_deferred.errback(failure)
        deferred.addCallbacks(on_success, on_error)
        return timeout_deferred

    def _on_connected(self, client):
        logger.info("Connection successful. Authorizing application...")
        self.send(ProtoOAApplicationAuthReq(clientId=self._client_id, clientSecret=self._client_secret))

    def _on_disconnected(self, client, reason):
        self.is_authorized = False
        logger.warning(f"Disconnected. Reason: {reason.getErrorMessage()}")
        self.emit("error", f"Disconnected: {reason.getErrorMessage()}")

    def _on_message_received(self, client, message: ProtoMessage):
        pt = message.payloadType
        if pt == ProtoOAPayloadType.PROTO_OA_APPLICATION_AUTH_RES:
            logger.info("Application authorized. Authorizing account...")
            self._authorize_account()
        elif pt == ProtoOAPayloadType.PROTO_OA_ACCOUNT_AUTH_RES:
            res = ProtoOAAccountAuthRes(); res.ParseFromString(message.payload)
            self._client.account_id = res.ctidTraderAccountId
            self.is_authorized = True
            logger.info(f"✅ Account {res.ctidTraderAccountId} authorized.")
            self.emit("ready")
        elif pt == ProtoOAPayloadType.PROTO_OA_ERROR_RES:
            res = ProtoOAErrorRes(); res.ParseFromString(message.payload)
            logger.error(f"API Error: {res.errorCode} - {res.description}")
        # --- ПОЧАТОК ЗМІН: Обробляємо спотові події ---
        elif pt == ProtoOAPayloadType.PROTO_OA_SPOT_EVENT:
            spot_event = ProtoOASpotEvent()
            spot_event.ParseFromString(message.payload)
            # Генеруємо унікальну подію для конкретного символу
            event_name = f"spot_event_{spot_event.symbolId}"
            logger.info(f"Spot event received for symbol {spot_event.symbolId}. Emitting '{event_name}'")
            self.emit(event_name, spot_event)
        # --- КІНЕЦЬ ЗМІН ---

    def _authorize_account(self):
        acc_id = get_demo_account_id(); token = get_ctrader_access_token()
        logger.info(f"Authorizing account ID: {acc_id}...")
        if not acc_id or not token:
            logger.error("CRITICAL: Account ID or Access Token is missing."); return
        self.send(ProtoOAAccountAuthReq(ctidTraderAccountId=acc_id, accessToken=token))

    def get_all_symbols(self):
        logger.info("Requesting light symbol list...")
        return self.send(ProtoOASymbolsListReq(ctidTraderAccountId=self._client.account_id))