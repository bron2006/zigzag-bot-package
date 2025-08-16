# ctrader_service.py
import threading
import time
import os
from dotenv import load_dotenv

from twisted.internet import reactor
# --- ВИПРАВЛЕНО: Використовуємо класи напряму, як того вимагає ця версія бібліотеки ---
from ctrader_open_api import Protobuf
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import ProtoMessage
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAApplicationAuthReq, ProtoOAAccountAuthReq, ProtoOAErrorRes,
    ProtoOASymbolsListReq, ProtoOASymbolsListRes,
    ProtoOASymbolByIdReq, ProtoOASymbolByIdRes,
    ProtoOAGetTrendbarsReq, ProtoOAGetTrendbarsRes
)
from config import logger

load_dotenv()

# --- Нова архітектура сервісу ---

class CTraderService:
    def __init__(self):
        self._pending_requests = {}
        self._is_authorized = False
        self._is_connected = False
        self._protocol = None

        # Завантажуємо дані з .env
        self._host = "demo.ctraderapi.com"
        self._port = 5035
        self._client_id = os.getenv("CT_CLIENT_ID")
        self._client_secret = os.getenv("CT_CLIENT_SECRET")
        self._access_token = os.getenv("CTRADER_ACCESS_TOKEN")
        self._account_id = int(os.getenv("DEMO_ACCOUNT_ID", 9541520))

    def start(self):
        """Ініціює підключення та запускає реактор у фоновому потоці."""
        reactor_thread = threading.Thread(target=self._run_reactor, daemon=True)
        reactor_thread.start()

    def _run_reactor(self):
        # Створюємо кастомний протокол, який наслідує Protobuf з бібліотеки
        # Це дозволяє нам додати власну логіку на події підключення/відключення
        class CustomCtraderProtocol(Protobuf):
            # Використовуємо 'outer' для доступу до екземпляру CTraderService
            outer = self

            def connectionMade(self):
                self.outer._on_connected(self)
                
            def connectionLost(self, reason):
                self.outer._on_disconnected(reason)

            def messageReceived(self, message: ProtoMessage):
                self.outer._message_received(message)
        
        # Створюємо фабрику, яка буде генерувати наш протокол
        class CTraderFactory(object):
            def buildProtocol(self, addr):
                return CustomCtraderProtocol()

        if not reactor.running:
            logger.info("Запуск реактора Twisted та ініціація підключення...")
            reactor.connectTCP(self._host, self._port, CTraderFactory())
            reactor.run(installSignalHandlers=0)

    def _on_connected(self, protocol_instance):
        logger.info("З'єднання встановлено. Авторизація додатку...")
        self._is_connected = True
        self._protocol = protocol_instance # Зберігаємо екземпляр протоколу для відправки повідомлень
        request = ProtoOAApplicationAuthReq(clientId=self._client_id, clientSecret=self._client_secret)
        self._protocol.send(request)

    def _on_disconnected(self, reason):
        logger.warning(f"З'єднання з сервером cTrader втрачено. Причина: {reason.getErrorMessage()}")
        self._is_connected = False
        self._is_authorized = False
        self._protocol = None

    def _authorize_account(self):
        logger.info(f"Авторизація акаунту {self._account_id}...")
        request = ProtoOAAccountAuthReq(ctidTraderAccountId=self._account_id, accessToken=self._access_token)
        self._protocol.send(request)
        
    def _message_received(self, message: ProtoMessage):
        if message.clientMsgId and message.clientMsgId in self._pending_requests:
            event, result_dict = self._pending_requests.pop(message.clientMsgId)
            
            if message.payloadType == ProtoOAErrorRes.payload_type:
                error_res = ProtoOAErrorRes()
                error_res.ParseFromString(message.payload)
                result_dict["error"] = f"API Error: {error_res.errorCode} - {error_res.description}"
            else:
                result_dict["data"] = message
            
            event.set()
        
        elif message.payloadType == 2101: # ProtoOAApplicationAuthRes
            logger.info("Авторизація додатку успішна.")
            self._authorize_account()
        elif message.payloadType == 2103: # ProtoOAAccountAuthRes
            logger.info(f"Авторизація акаунту {self._account_id} успішна.")
            self._is_authorized = True
        elif message.payloadType == ProtoOAErrorRes.payload_type:
            error_res = ProtoOAErrorRes()
            error_res.ParseFromString(message.payload)
            logger.critical(f"Помилка cTrader: {error_res.errorCode} - {error_res.description}")
        
    def _send_request(self, request, timeout=30):
        if not self._is_authorized or not self._protocol:
            logger.warning("Сервіс не авторизований або не підключений. Чекаю (до 15с)...")
            for _ in range(15):
                if self._is_authorized and self._protocol:
                    break
                time.sleep(1)
            else:
                raise Exception("Не вдалося авторизуватися/підключитися в cTrader.")

        client_msg_id = f"{type(request).__name__}_{time.time()}"
        request.clientMsgId = client_msg_id
        
        event = threading.Event()
        result_dict = {"data": None, "error": None}
        self._pending_requests[client_msg_id] = (event, result_dict)

        reactor.callFromThread(self._protocol.send, request)

        if not event.wait(timeout=timeout):
            self._pending_requests.pop(client_msg_id, None) 
            raise TimeoutError(f"Таймаут очікування відповіді для запиту {type(request).__name__}")
        
        if result_dict["error"]:
            raise Exception(result_dict["error"])
        
        return result_dict["data"]

    def get_symbols_list(self):
        request = ProtoOASymbolsListReq(ctidTraderAccountId=self._account_id)
        response_msg = self._send_request(request)
        response = ProtoOASymbolsListRes()
        response.ParseFromString(response_msg.payload)
        return response

    def get_symbols_by_id(self, ids):
        request = ProtoOASymbolByIdReq(ctidTraderAccountId=self._account_id, symbolId=ids)
        response_msg = self._send_request(request)
        response = ProtoOASymbolByIdRes()
        response.ParseFromString(response_msg.payload)
        return response

    def get_trendbars(self, symbol_id, period, from_timestamp, to_timestamp):
        request = ProtoOAGetTrendbarsReq(ctidTraderAccountId=self._account_id, symbolId=symbol_id, period=period, fromTimestamp=from_timestamp, toTimestamp=to_timestamp)
        response_msg = self._send_request(request, timeout=10)
        response = ProtoOAGetTrendbarsRes()
        response.ParseFromString(response_msg.payload)
        return response

# Створюємо єдиний екземпляр сервісу для всього додатку
ctrader_service = CTraderService()