# spotware_connect.py
import logging
from twisted.internet import reactor, defer
# FIX 1: Імпортуємо TcpProtocol напряму, як вказано в __init__.py
from ctrader_open_api import Client as SpotwareClientBase, TcpProtocol, Protobuf
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import ProtoMessage
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOAPayloadType
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAApplicationAuthReq, ProtoOAAccountAuthReq,
    ProtoOASymbolsListReq, ProtoOASymbolsListRes, ProtoOAErrorRes
)
# FIX 2: Імпортуємо функції конфігурації, як це було зроблено у вас
from config import get_ct_client_id, get_ct_client_secret, get_ctrader_access_token, get_demo_account_id

logger = logging.getLogger(__name__)

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
                # Використовуємо callFromThread для безпечної взаємодії з Twisted
                reactor.callFromThread(func, *args, **kwargs)

class SpotwareClient(EventEmitter):
    def __init__(self):
        super().__init__()
        self.host = "demo.ctraderapi.com"
        self.port = 5035
        self._is_ready = defer.Deferred() # Deferred для відстеження готовності
        
        # FIX 3: Правильна ініціалізація клієнта згідно з вашим client.py
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
        request = ProtoOAApplicationAuthReq(clientId=get_ct_client_id(), clientSecret=get_ct_client_secret())
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
            # Сигналізуємо, що клієнт готовий до роботи
            if not self._is_ready.called:
                self._is_ready.callback(response.symbol)
        elif payload_type == ProtoOAPayloadType.PROTO_OA_ERROR_RES:
            response = Protobuf.extract(message)
            error_message = f"Помилка від cTrader: {response.errorCode} - {response.description}"
            logger.error(error_message)
            # Якщо сталася помилка до готовності, провалюємо Deferred
            if not self._is_ready.called:
                self._is_ready.errback(Exception(error_message))
            self.emit("error", error_message)

    def _authorize_account(self):
        request = ProtoOAAccountAuthReq(
            ctidTraderAccountId=get_demo_account_id(), 
            accessToken=get_ctrader_access_token()
        )
        self.send(request).addErrback(lambda err: self.emit("error", f"Помилка авторизації рахунку: {err.getErrorMessage()}"))

    def _request_symbols(self):
        request = ProtoOASymbolsListReq(ctidTraderAccountId=get_demo_account_id())
        self.send(request).addErrback(lambda err: self.emit("error", f"Помилка запиту символів: {err.getErrorMessage()}"))