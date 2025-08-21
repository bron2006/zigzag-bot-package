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

    def on(self, event, func):
        if event not in self._events:
            self._events[event] = []
        self._events[event].append(func)

    def emit(self, event, *args, **kwargs):
        if event in self._events:
            for func in self._events[event]:
                reactor.callFromThread(func, *args, **kwargs)

class SpotwareConnect(EventEmitter):
    def __init__(self, client_id, client_secret):
        super().__init__()
        self.host = "demo.ctraderapi.com"
        self.port = 5035
        self._client_id = client_id
        self._client_secret = client_secret
        self.is_authorized = False
        
        self._client = SpotwareClientBase(self.host, self.port, TcpProtocol)
        self._client.setConnectedCallback(self._on_connected)
        self._client.setMessageReceivedCallback(self._on_message_received)
        self._client.setDisconnectedCallback(self._on_disconnected)
        # Рядок, що викликав помилку, видалено. Обробка помилок підключення буде
        # здійснюватися через стандартний механізм перепідключення Twisted.

    def start(self):
        self._client.startService()

    def send(self, message, client_msg_id=None):
        return self._client.send(message, clientMsgId=client_msg_id, responseTimeoutInSeconds=30)

    def _on_connected(self, client):
        logger.info("Connection successful. Authorizing application...")
        request = ProtoOAApplicationAuthReq(clientId=self._client_id, clientSecret=self._client_secret)
        self.send(request)

    def _on_disconnected(self, client, reason):
        self.is_authorized = False
        error_msg = reason.getErrorMessage()
        logger.warning(f"Disconnected from cTrader API. Reason: {error_msg}")
        self.emit("error", f"Disconnected: {error_msg}")

    def _on_message_received(self, client, message: ProtoMessage):
        payload_type = message.payloadType
        
        if payload_type == ProtoOAPayloadType.PROTO_OA_APPLICATION_AUTH_RES:
            ProtoOAApplicationAuthRes().ParseFromString(message.payload)
            logger.info("Application authorized. Authorizing account...")
            self._authorize_account()
        elif payload_type == ProtoOAPayloadType.PROTO_OA_ACCOUNT_AUTH_RES:
            response = ProtoOAAccountAuthRes()
            response.ParseFromString(message.payload)
            logger.info(f"Account {response.ctidTraderAccountId} authorized.")
            self.is_authorized = True
            self.emit("ready")
        elif payload_type == ProtoOAPayloadType.PROTO_OA_SYMBOLS_LIST_RES:
            response = ProtoOASymbolsListRes()
            response.ParseFromString(message.payload)
            self.emit("symbolsLoaded", response)
        elif payload_type == ProtoOAPayloadType.PROTO_OA_ERROR_RES:
            response = ProtoOAErrorRes()
            response.ParseFromString(message.payload)
            error_message = f"cTrader API Error: {response.errorCode} - {response.description}"
            logger.error(error_message)
            self.emit("error", error_message)

    def _authorize_account(self):
        request = ProtoOAAccountAuthReq(
            ctidTraderAccountId=get_demo_account_id(), 
            accessToken=get_ctrader_access_token()
        )
        self.send(request)

    def get_all_symbols(self):
        logger.info("Requesting symbol list...")
        request = ProtoOASymbolsListReq(ctidTraderAccountId=get_demo_account_id())
        return self.send(request)