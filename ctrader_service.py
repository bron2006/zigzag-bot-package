# ctrader_service.py
import threading
import time
import os

from dotenv import load_dotenv
from twisted.internet import reactor
from twisted.internet import task
from ctrader_open_api import Client, TcpProtocol, EndPoints
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import ProtoMessage
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAApplicationAuthReq, ProtoOAAccountAuthReq, ProtoOAErrorRes,
    ProtoOASymbolsListReq, ProtoOASymbolsListRes,
    ProtoOASymbolByIdReq, ProtoOASymbolByIdRes,
    ProtoOAGetTrendbarsReq, ProtoOAGetTrendbarsRes,
    ProtoHeartbeatEvent
)
from config import logger

load_dotenv()


class CTraderService:
    def __init__(self):
        self._pending_requests = {}
        self._is_authorized = False

        self._client = None
        self._hb_loop = None  # LoopingCall for heartbeat

        # Використовуємо офіційні константи ендпоінтів
        self._host = EndPoints.PROTOBUF_DEMO_HOST  # demo.ctraderapi.com
        self._port = EndPoints.PROTOBUF_PORT       # 5035

        self._client_id = os.getenv("CT_CLIENT_ID")
        self._client_secret = os.getenv("CT_CLIENT_SECRET")
        self._access_token = os.getenv("CTRADER_ACCESS_TOKEN")
        self._account_id = int(os.getenv("DEMO_ACCOUNT_ID", "9541520"))

    # ---------- ПУБЛІЧНЕ АПІ ----------

    def start(self):
        """
        Запускає Twisted-реактор в окремому треді та піднімає Client (SSL+TcpProtocol).
        """
        reactor_thread = threading.Thread(target=self._run_reactor, daemon=True)
        reactor_thread.start()

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
        request = ProtoOAGetTrendbarsReq(
            ctidTraderAccountId=self._account_id,
            symbolId=symbol_id,
            period=period,
            fromTimestamp=from_timestamp,
            toTimestamp=to_timestamp,
        )
        response_msg = self._send_request(request, timeout=15)
        response = ProtoOAGetTrendbarsRes()
        response.ParseFromString(response_msg.payload)
        return response

    # ---------- ВНУТРІШНЄ ----------

    def _run_reactor(self):
        logger.info("Запуск реактора Twisted та ініціація підключення...")

        # SDK-клієнт сам робить SSL TCP+TcpProtocol
        self._client = Client(self._host, self._port, TcpProtocol)

        # Колбеки як у семплах OpenApiPy
        self._client.setConnectedCallback(self._on_connected)
        self._client.setDisconnectedCallback(self._on_disconnected)
        self._client.setMessageReceivedCallback(self._on_message_received)

        # Запускаємо сервіс клієнта і сам реактор
        self._client.startService()
        reactor.run(installSignalHandlers=0)

    def _on_connected(self, client):
        logger.info("З'єднання встановлено. Авторизація додатку...")
        app_req = ProtoOAApplicationAuthReq(clientId=self._client_id, clientSecret=self._client_secret)

        def _ok_app(_res):
            logger.info("Авторизація додатку успішна. Авторизація акаунту...")
            self._authorize_account()

        def _err_app(f):
            logger.critical(f"Авторизація додатку не вдалася: {f.getErrorMessage() if hasattr(f, 'getErrorMessage') else f!r}")

        # send() повертає Deferred — реагуємо колбеками
        d = self._client.send(app_req)
        d.addCallbacks(_ok_app, _err_app)

    def _authorize_account(self):
        acc_req = ProtoOAAccountAuthReq(ctidTraderAccountId=self._account_id, accessToken=self._access_token)

        def _ok_acc(_res):
            self._is_authorized = True
            logger.info(f"Авторизація акаунту {self._account_id} успішна.")
            self._start_heartbeat()

        def _err_acc(f):
            logger.critical(f"Авторизація акаунту не вдалася: {f.getErrorMessage() if hasattr(f, 'getErrorMessage') else f!r}")

        d = self._client.send(acc_req)
        d.addCallbacks(_ok_acc, _err_acc)

    def _start_heartbeat(self):
        # Відповідно до best practices — heartbeat кожні ~10с
        if self._hb_loop and self._hb_loop.running:
            return

        def _beat():
            try:
                # Heartbeat — це event без відповіді, але безпечний для відправки
                self._client.send(ProtoHeartbeatEvent())
            except Exception as e:
                logger.warning(f"Heartbeat помилка: {e}")

        self._hb_loop = task.LoopingCall(_beat)
        self._hb_loop.start(10.0, now=False)

    def _on_disconnected(self, _client, reason):
        self._is_authorized = False
        # reason зазвичай Failure; беремо повідомлення як рядок
        logger.warning(f"З'єднання з сервером cTrader втрачено. Причина: {getattr(reason, 'getErrorMessage', lambda: str(reason))()}")

    def _on_message_received(self, _client, message: ProtoMessage):
        # Загальний хук на всі повідомлення (можна логувати / діагностувати помилки)
        if message.payloadType == ProtoOAErrorRes.payload_type:
            err = ProtoOAErrorRes()
            err.ParseFromString(message.payload)
            logger.error(f"Помилка cTrader: {err.errorCode} - {err.description}")

    def _send_request(self, request, timeout=30):
        """
        Синхронний бар’єр поверх Deferred: блокуємось у фон. треді поки не прилетить відповідь.
        """
        # Дочекаємось авторизації (до 15с), як у твоїй версії
        if not self._is_authorized:
            logger.warning("Сервіс не авторизований. Чекаю (до 15с)...")
            for _ in range(15):
                if self._is_authorized:
                    break
                time.sleep(1)
            else:
                raise Exception("Не вдалося авторизуватися/підключитися в cTrader.")

        event = threading.Event()
        result = {"data": None, "error": None}

        def _ok(res_msg):
            result["data"] = res_msg
            event.set()

        def _err(f):
            result["error"] = f.getErrorMessage() if hasattr(f, "getErrorMessage") else str(f)
            event.set()

        # ВАЖЛИВО: send() треба викликати в треді реактора
        def _send():
            d = self._client.send(request)
            d.addCallbacks(_ok, _err)

        reactor.callFromThread(_send)

        if not event.wait(timeout=timeout):
            raise TimeoutError(f"Таймаут очікування відповіді для запиту {type(request).__name__}")

        if result["error"]:
            raise Exception(result["error"])

        return result["data"]


ctrader_service = CTraderService()
