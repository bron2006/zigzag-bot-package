import logging
from twisted.internet import reactor
from ctrader_open_api.client import Client as SpotwareClientBase
from ctrader_open_api.tcpProtocol import TcpProtocol
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import ProtoMessage
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAApplicationAuthReq, ProtoOAApplicationAuthRes,
    ProtoOAAccountAuthReq, ProtoOAAccountAuthRes,
    ProtoOASymbolsListReq, ProtoOASymbolsListRes,
    ProtoOAErrorRes
)
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOAPayloadType
from config import get_ctrader_access_token, get_demo_account_id

logger = logging.getLogger(__name__)

class EventEmitter:
    def __init__(self):
        self._events = {}

    def on(self, event):
        def decorator(func):
            if event not in self._events:
                self._events[event] = []
            self._events[event].append(func)
            return func
        return decorator

    def emit(self, event, *args, **kwargs):
        if event in self._events:
            for func in self._events[event]:
                func(*args, **kwargs)

class SpotwareClient(EventEmitter):
    def __init__(self, client_id, client_secret):
        super().__init__()
        self.host = "demo.ctraderapi.com"
        self.port = 5035
        self._client_id = client_id
        self._client_secret = client_secret
        self._is_connected = False
        
        self._client = SpotwareClientBase(self.host, self.port, TcpProtocol)
        self._client.setConnectedCallback(self._on_connected)
        self._client.setMessageReceivedCallback(self._on_message_received)
        self._client.setDisconnectedCallback(self._on_disconnected)

    @property
    def isConnected(self):
        return self._is_connected

    def connect(self):
        self._client.startService()

    def send(self, message, client_msg_id=None):
        return self._send_message(message, client_msg_id)

    def _on_connected(self, client):
        logger.info("Встановлено з'єднання з cTrader API. Авторизація додатку...")
        request = ProtoOAApplicationAuthReq(clientId=self._client_id, clientSecret=self._client_secret)
        self._send_message(request)

    def _on_disconnected(self, client, reason):
        self._is_connected = False
        error_msg = reason.getErrorMessage()
        logger.warning(f"Відключено від cTrader API. Причина: {error_msg}")
        self.emit("error", f"Відключено: {error_msg}")

    def _on_message_received(self, client, message: ProtoMessage):
        payload_type = message.payloadType
        
        if payload_type == ProtoOAPayloadType.PROTO_OA_APPLICATION_AUTH_RES:
            ProtoOAApplicationAuthRes().ParseFromString(message.payload)
            logger.info("Додаток успішно авторизовано. Авторизація торгового рахунку...")
            self._authorize_account()
        elif payload_type == ProtoOAPayloadType.PROTO_OA_ACCOUNT_AUTH_RES:
            response = ProtoOAAccountAuthRes()
            response.ParseFromString(message.payload)
            logger.info(f"Торговий рахунок {response.ctidTraderAccountId} успішно авторизовано.")
            self._is_connected = True
            self._request_symbols()
        elif payload_type == ProtoOAPayloadType.PROTO_OA_SYMBOLS_LIST_RES:
            response = ProtoOASymbolsListRes()
            response.ParseFromString(message.payload)
            logger.info("Отримано список символів.")
            symbols_data = [{"symbolId": s.symbolId, "symbolName": s.symbolName} for s in response.symbol]
            self.emit("symbolsLoaded", symbols_data)
        elif payload_type == ProtoOAPayloadType.PROTO_OA_ERROR_RES:
            response = ProtoOAErrorRes()
            response.ParseFromString(message.payload)
            error_message = f"Помилка від cTrader: {response.errorCode} - {response.description}"
            logger.error(error_message)
            self.emit("error", error_message)

    def _authorize_account(self):
        request = ProtoOAAccountAuthReq(
            ctidTraderAccountId=get_demo_account_id(), 
            accessToken=get_ctrader_access_token()
        )
        self._send_message(request)

    def _request_symbols(self):
        logger.info("Надсилаю запит на отримання списку символів...")
        request = ProtoOASymbolsListReq(ctidTraderAccountId=get_demo_account_id())
        self._send_message(request)

    def _send_message(self, message, client_msg_id=None):
        deferred = self._client.send(message, clientMsgId=client_msg_id)
        deferred.addErrback(self._on_send_error)
        return deferred

    def _on_send_error(self, failure):
        error_message = f"Не вдалося надіслати повідомлення: {failure.getErrorMessage()}"
        logger.error(error_message)
        self.emit("error", error_message)