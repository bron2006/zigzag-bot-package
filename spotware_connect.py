# spotware_connect.py
import logging
from twisted.internet import reactor, defer
from ctrader_open_api import Client as SpotwareClientBase, TcpProtocol, Protobuf
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import ProtoMessage
# FIX: Правильний шлях до ProtoOAPayloadType згідно з вашими ж файлами
from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAPayloadType
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAApplicationAuthReq, ProtoOAAccountAuthReq,
    ProtoOASymbolsListReq, ProtoOASymbolsListRes
)
# FIX: Імпортуємо глобальні змінні
from config import CT_CLIENT_ID, CT_CLIENT_SECRET, CTRADER_ACCESS_TOKEN, DEMO_ACCOUNT_ID

logger = logging.getLogger(__name__)

class EventEmitter:
    # ... (код EventEmitter залишається без змін) ...
    def __init__(self):
        self._events = {}
    def on(self, event, func):
        if event not in self._events: self._events[event] = []
        self._events[event].append(func)
    def emit(self, event, *args, **kwargs):
        if event in self._events:
            for func in self._events[event]: reactor.callFromThread(func, *args, **kwargs)

class SpotwareClient(EventEmitter):
    # FIX: Конструктор не приймає аргументів, він бере їх з конфігу
    def __init__(self):
        super().__init__()
        self.host = "demo.ctraderapi.com"
        self.port = 5035
        self._is_ready = defer.Deferred()
        self._client = SpotwareClientBase(self.host, self.port, TcpProtocol)
        self._client.setConnectedCallback(self._on_connected)
        self._client.setMessageReceivedCallback(self._on_message_received)
        self._client.setDisconnectedCallback(self._on_disconnected)

    def isReady(self):
        return self._is_ready

    def connect(self):
        self._client.startService()

    def send(self, message, client_msg_id=None):
        return self._client.send(message, clientMsgId=client_msg_id, responseTimeoutInSeconds=30)

    def _on_connected(self, client):
        logger.info("Встановлено з'єднання з cTrader API. Авторизація додатку...")
        request = ProtoOAApplicationAuthReq(clientId=CT_CLIENT_ID, clientSecret=CT_CLIENT_SECRET)
        self.send(request).addErrback(lambda err: self.emit("error", f"Помилка авторизації додатку: {err.getErrorMessage()}"))

    def _on_disconnected(self, client, reason):
        error_msg = reason.getErrorMessage()
        logger.warning(f"Відключено від cTrader API. Причина: {error_msg}")
        self.emit("error", f"Відключено: {error_msg}")

    def _on_message_received(self, client, message: ProtoMessage):
        payload_type = message.payloadType
        if payload_type == ProtoOAPayloadType.PROTO_OA_APPLICATION_AUTH_RES:
            logger.info("Додаток успішно авторизовано. Авторизація торгового рахунку...")
            self._authorize_account()
        elif payload_type == ProtoOAPayloadType.PROTO_OA_ACCOUNT_AUTH_RES:
            response = Protobuf.extract(message)
            logger.info(f"Торговий рахунок {response.ctidTraderAccountId} успішно авторизовано.")
            self._request_symbols()
        elif payload_type == ProtoOAPayloadType.PROTO_OA_SYMBOLS_LIST_RES:
            response = Protobuf.extract(message)
            logger.info("Отримано повний список символів.")
            if not self._is_ready.called:
                self._is_ready.callback(response.symbol)
        elif payload_type == ProtoOAPayloadType.PROTO_OA_ERROR_RES:
            response = Protobuf.extract(message)
            error_message = f"Помилка від cTrader: {response.errorCode} - {response.description}"
            logger.error(error_message)
            if not self._is_ready.called: self._is_ready.errback(Exception(error_message))
            self.emit("error", error_message)

    def _authorize_account(self):
        request = ProtoOAAccountAuthReq(ctidTraderAccountId=DEMO_ACCOUNT_ID, accessToken=CTRADER_ACCESS_TOKEN)
        self.send(request).addErrback(lambda err: self.emit("error", f"Помилка авторизації рахунку: {err.getErrorMessage()}"))

    def _request_symbols(self):
        request = ProtoOASymbolsListReq(ctidTraderAccountId=DEMO_ACCOUNT_ID)
        self.send(request).addErrback(lambda err: self.emit("error", f"Помилка запиту символів: {err.getErrorMessage()}"))