# spotware_connect.py
import logging
from twisted.internet import reactor
from ctrader_open_api.client import Client
from ctrader_open_api.factory import Factory
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import ProtoOAPayloadType
from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoMessage
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import ProtoErrorRes
from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAApplicationAuthReq, ProtoOAAccountAuthReq, ProtoOAGetAccountListByAccessTokenReq
import state

logger = logging.getLogger("spotware_connect")

class SpotwareConnect(Client):
    def __init__(self, client_id, client_secret):
        # --- ПОЧАТОК ЗМІН: Винесено конфігурацію в app.py ---
        # Тепер ці значення будуть встановлюватися з app.py, а не жорстко прописані тут
        self.host = None
        self.port = None
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token = None
        self.account_id = None
        self.listeners = {}
        # Ми більше не викликаємо super().__init__ тут, це буде зроблено в app.py
        # --- КІНЕЦЬ ЗМІН ---

    def start(self, host, port, access_token, account_id):
        # --- ПОЧАТОК ЗМІН: Метод start тепер приймає конфігурацію ---
        self.host = host
        self.port = port
        self.access_token = access_token
        self.account_id = account_id
        super().__init__(self.host, self.port, ssl=True)
        reactor.connectSSL(self.host, self.port, Factory(self))
        logger.info(f"Connecting to {host}:{port}...")
        # --- КІНЕЦЬ ЗМІН ---

    def on(self, event, listener):
        if event not in self.listeners:
            self.listeners[event] = []
        self.listeners[event].append(listener)

    def remove_listener(self, event, listener):
        if event in self.listeners:
            self.listeners[event].remove(listener)

    def emit(self, event, *args):
        if event in self.listeners:
            for listener in self.listeners[event]:
                listener(*args)

    def on_connect(self):
        logger.info("Connection successful. Authorizing application...")
        self.authorize_app()

    def on_error(self, reason):
        logger.error(f"Connection error: {reason.getErrorMessage()}")

    def on_close(self, reason):
        logger.warning(f"Disconnected. Reason: {reason.getErrorMessage()}")

    def on_message(self, message: ProtoMessage):
        if message.payloadType == ProtoOAPayloadType.ERROR_RES:
            error_res = ProtoErrorRes()
            error_res.ParseFromString(message.payload)
            logger.error(f"API Error: {error_res.errorCode} | Description: {error_res.description}")
            return
        
        # --- ПОЧАТОК ЗМІН: Централізований обробник тікових даних ---
        if message.payloadType == ProtoOAPayloadType.PROTO_OA_SPOT_EVENT:
            self.emit("spot_event", message)
        # --- КІНЕЦЬ ЗМІН ---

        if message.clientMsgId:
            self.emit(message.clientMsgId, message)

    def authorize_app(self):
        request = ProtoOAApplicationAuthReq(clientId=self.client_id, clientSecret=self.client_secret)
        deferred = self.send(request)
        deferred.addCallback(self.on_app_authorized)
        
    def on_app_authorized(self, message):
        logger.info("Application authorized. Authorizing account...")
        self.authorize_account()

    def authorize_account(self):
        request = ProtoOAAccountAuthReq(ctidTraderAccountId=self.account_id, accessToken=self.access_token)
        deferred = self.send(request)
        deferred.addCallback(self.on_account_authorized)

    def on_account_authorized(self, message):
        logger.info(f"✅ Account {self.account_id} authorized.")
        self.emit("ready")

# --- ПОЧАТОК ЗМІН: Новий централізований обробник, який кладе ціни в кеш ---
def central_spot_event_handler(message):
    try:
        from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOASpotEvent
        spot_event = ProtoOASpotEvent()
        spot_event.ParseFromString(message.payload)
        
        symbol_id = spot_event.symbolId
        symbol_name = state.symbol_id_to_name_map.get(symbol_id)

        if not symbol_name:
            return # Невідомий символ, ігноруємо

        # Розраховуємо середню ціну
        price = 0
        if spot_event.HasField('bid') and spot_event.HasField('ask'):
            price = (spot_event.bid + spot_event.ask) / 2
        elif spot_event.HasField('bid'):
            price = spot_event.bid
        elif spot_event.HasField('ask'):
            price = spot_event.ask
        
        if price > 0:
            # Важливо: cTrader надсилає ціни як цілі числа, треба ділити на 10^5
            state.live_price_cache[symbol_name] = price / (10**5)

    except Exception:
        logger.exception("Error in central_spot_event_handler")
# --- КІНЕЦЬ ЗМІН ---