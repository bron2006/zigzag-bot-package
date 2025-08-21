import logging
from ctrader_open_api.client import Client
# Виправлено імпорт: ProtoOAPayloadType знаходиться в OpenApiMessages_pb2
from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAPayloadType, ProtoOAApplicationAuthReq, ProtoOAAccountAuthReq, ProtoOASymbolsListReq
from config import CT_CLIENT_ID, CT_CLIENT_SECRET, CTRADER_ACCESS_TOKEN, DEMO_ACCOUNT_ID

# Налаштування логування
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class SpotwareConnect:
    def __init__(self, reactor, client_endpoint, factory, client_id, client_secret, ctid, access_token):
        self.reactor = reactor
        self._client_endpoint = client_endpoint
        self._factory = factory
        self._client_id = client_id
        self._client_secret = client_secret
        self._ctid = ctid
        self._access_token = access_token
        self._client = None
        self._is_authorized = False

        self._factory.setConnectedCallback(self._connected_callback)
        self._factory.setDisconnectedCallback(self._disconnected_callback)
        self._factory.setMessageReceivedCallback(self._message_received_callback)

    def start(self):
        """Запускає процес підключення."""
        self._client_endpoint.connect(self._factory)

    def _connected_callback(self, client: Client):
        """Викликається після успішного встановлення з'єднання."""
        self._client = client
        logger.info("Встановлено з'єднання з cTrader API. Авторизація додатку...")
        self._authorize_application()

    def _disconnected_callback(self, client: Client, reason):
        """Викликається при відключенні."""
        logger.warning(f"Відключено від cTrader API. Причина: {reason}")
        self._is_authorized = False

    def _message_received_callback(self, client: Client, message):
        """Обробляє вхідні повідомлення від сервера."""
        if message.payloadType == ProtoOAPayloadType.PROTO_OA_APPLICATION_AUTH_RES:
            logger.info("Додаток успішно авторизовано. Авторизація торгового рахунку...")
            self._authorize_account()

        elif message.payloadType == ProtoOAPayloadType.PROTO_OA_ACCOUNT_AUTH_RES:
            logger.info(f"Торговий рахунок {self._ctid} успішно авторизовано.")
            self._is_authorized = True
            self._get_all_symbols()

        elif message.payloadType == ProtoOAPayloadType.PROTO_OA_SYMBOLS_LIST_RES:
            logger.info("Отримано повний список символів.")
            symbols = message.payload.symbol
            logger.info(f"Завантажено {len(symbols)} символів. Ініціалізую кеш...")
            # Тут буде подальша логіка обробки символів

        elif message.payloadType == ProtoOAPayloadType.PROTO_OA_ERROR_RES:
            logger.error(f"Помилка від API: {message.payload.description}. Код: {message.payload.errorCode}")

    def _authorize_application(self):
        """Надсилає запит на авторизацію додатку."""
        request = ProtoOAApplicationAuthReq()
        request.clientId = self._client_id
        request.clientSecret = self._client_secret
        self._client.send(request)

    def _authorize_account(self):
        """Надсилає запит на авторизацію торгового рахунку."""
        request = ProtoOAAccountAuthReq()
        request.ctidTraderAccountId = self._ctid
        request.accessToken = self._access_token
        self._client.send(request)

    def _get_all_symbols(self):
        """Запитує список всіх доступних символів."""
        request = ProtoOASymbolsListReq()
        request.ctidTraderAccountId = self._ctid
        self._client.send(request)