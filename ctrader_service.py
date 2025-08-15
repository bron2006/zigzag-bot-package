import threading
import time
import os
from dotenv import load_dotenv
from twisted.internet import reactor
from ctrader_open_api import Client, TcpProtocol
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import ProtoMessage
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAApplicationAuthReq, ProtoOAAccountAuthReq, ProtoOAErrorRes,
    ProtoOASymbolsListReq, ProtoOASymbolsListRes,
    ProtoOASymbolByIdReq, ProtoOASymbolByIdRes,
    ProtoOAGetTrendbarsReq, ProtoOAGetTrendbarsRes
)
from config import logger

load_dotenv()

class CTraderService:
    def __init__(self):
        self._pending_requests = {}
        self._is_authorized = False
        self._client_id = os.getenv("CT_CLIENT_ID")
        self._client_secret = os.getenv("CT_CLIENT_SECRET")
        self._access_token = os.getenv("CTRADER_ACCESS_TOKEN")
        self._account_id = int(os.getenv("DEMO_ACCOUNT_ID", 9541520))
        
        # --- ФІНАЛЬНЕ ВИПРАВЛЕННЯ: Передаємо обробник одразу в конструктор ---
        self._protocol = TcpProtocol(message_handler=self._message_received)
        self._client = Client("demo.ctraderapi.com", 5035, self._protocol)

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
            logger.info("Авторизація акаунту успішна.")
            self._is_authorized = True
        elif message.payloadType == ProtoOAErrorRes.payload_type:
            error_res = ProtoOAErrorRes()
            error_res.ParseFromString(message.payload)
            logger.critical(f"Помилка авторизації: {error_res.errorCode} - {error_res.description}")
            # Зупиняємо реактор, якщо авторизація провалилася
            if reactor.running:
                reactor.stop()

    def _authorize_account(self):
        logger.info("Авторизація акаунту...")
        request = ProtoOAAccountAuthReq(ctidTraderAccountId=self._account_id, accessToken=self._access_token)
        self._client.send(request)

    def _start_reactor(self):
        if not reactor.running:
            logger.info("Запуск реактора Twisted...")
            reactor.run(installSignalHandlers=0)

    def start(self):
        # self._protocol.set_message_handler - Цей рядок видалено
        reactor_thread = threading.Thread(target=self._start_reactor, daemon=True)
        reactor_thread.start()

        def on_connect():
            logger.info("З'єднання встановлено. Авторизація додатку...")
            request = ProtoOAApplicationAuthReq(clientId=self._client_id, clientSecret=self._client_secret)
            self._client.send(request)

        # Використовуємо set_connected_handler, який існує в protocol
        if hasattr(self._protocol, 'set_connected_handler'):
             self._protocol.set_connected_handler(on_connect)
        
        # Використовуємо client.start(), який існує в client
        if hasattr(self._client, 'start'):
            self._client.start()
        
    def _send_request(self, request, timeout=30):
        if not self._is_authorized:
            logger.warning("Сервіс не авторизований. Чекаю на авторизацію (до 15с)...")
            for _ in range(15):
                if self._is_authorized:
                    break
                time.sleep(1)
            else:
                raise Exception("Не вдалося авторизуватися в cTrader. Перевірте ключі доступу.")

        client_msg_id = str(time.time()) # Simple unique ID
        request.clientMsgId = client_msg_id
        
        event = threading.Event()
        result_dict = {"data": None, "error": None}
        self._pending_requests[client_msg_id] = (event, result_dict)

        self._client.send(request)

        if not event.wait(timeout=timeout):
            self._pending_requests.pop(client_msg_id, None) # Очищаємо запит
            raise TimeoutError(f"Таймаут очікування відповіді для запиту {type(request).__name__}")
        
        if result_dict["error"]:
            raise Exception(result_dict["error"])
        
        return result_dict["data"]

    # --- Публічні методи для виклику з інших частин додатку ---
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

    def get_trendbars(self, symbol_id, period, count):
        request = ProtoOAGetTrendbarsReq(ctidTraderAccountId=self._account_id, symbolId=symbol_id, period=period, count=count)
        response_msg = self._send_request(request, timeout=10)
        response = ProtoOAGetTrendbarsRes()
        response.ParseFromString(response_msg.payload)
        return response

# Створюємо єдиний екземпляр сервісу для всього додатку
ctrader_service = CTraderService()