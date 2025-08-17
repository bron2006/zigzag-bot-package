# main.py
import os
import json
from urllib.parse import parse_qs, unquote
from dotenv import load_dotenv

# --- TELEGRAM ІМПОРТИ ---
from telegram import Update
from telegram.ext import CallbackContext

from twisted.internet import reactor, ssl, defer
from twisted.internet.protocol import ClientFactory
from twisted.web.static import File
from klein import Klein

from ctrader_open_api import Protobuf, TcpProtocol
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import ProtoMessage
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAApplicationAuthReq, ProtoOAApplicationAuthRes,
    ProtoOAAccountAuthReq, ProtoOAAccountAuthRes, ProtoOAErrorRes,
    ProtoOASymbolsListReq, ProtoOASymbolsListRes,
    ProtoOASymbolByIdReq, ProtoOASymbolByIdRes,
    ProtoOAGetTrendbarsReq, ProtoOAGetTrendbarsRes
)

# --- ІМПОРТИ ДЛЯ БОТА ---
from config import logger, FOREX_SESSIONS, SYMBOL_DATA_CACHE, CACHE_LOCK, bot, dp, WEBHOOK_SECRET
from db import init_db, get_watchlist, toggle_watch, get_signal_history
import analysis
from telegram_ui import register_handlers

load_dotenv()

# --- НАЛАШТУВАННЯ ---
HOST = "demo.ctraderapi.com"
PORT = 5035
CLIENT_ID = os.getenv("CT_CLIENT_ID")
CLIENT_SECRET = os.getenv("CT_CLIENT_SECRET")
ACCESS_TOKEN = os.getenv("CTRADER_ACCESS_TOKEN")
ACCOUNT_ID = int(os.getenv("DEMO_ACCOUNT_ID", 9541520))
APP_PORT = int(os.getenv("PORT", 8080))
APP_NAME = os.getenv("FLY_APP_NAME", "zigzag-bot-package")

# --- cTRADER ПРОТОКОЛ ---
class CTraderProtocol(TcpProtocol, Protobuf):
    def __init__(self, service):
        super().__init__()
        self.service = service

    def connectionMade(self):
        self.service._on_connected(self)

    def connectionLost(self, reason):
        self.service._on_disconnected(reason)

    def messageReceived(self, message: ProtoMessage):
        self.service._message_received(message)


class CTraderService:
    def __init__(self):
        self._protocol = None
        self._is_authorized = False
        self._ready_deferred = None  # Буде викликано після повної авторизації

    def when_ready(self):
        """Повертає Deferred, який спрацює, коли сервіс буде готовий."""
        if self._is_authorized and self._ready_deferred is None:
            d = defer.Deferred()
            d.callback(None)
            return d
        if self._ready_deferred is None:
            self._ready_deferred = defer.Deferred()
        return self._ready_deferred

    def connect(self):
        class CTraderFactory(ClientFactory):
            def __init__(self, service):
                self.service = service

            def buildProtocol(self, addr):
                return CTraderProtocol(self.service)

            def clientConnectionFailed(self, connector, reason):
                logger.error(f"❌ Не вдалося підключитися до cTrader: {reason.getErrorMessage()}")
                if self.service._ready_deferred:
                    self.service._ready_deferred.errback(Exception("Connection failed"))
                    self.service._ready_deferred = None

        logger.info(f"✅ Спроба підключення до cTrader: {HOST}:{PORT}")
        ctxFactory = ssl.optionsForClientTLS(hostname=HOST)
        reactor.connectSSL(HOST, PORT, CTraderFactory(self), ctxFactory)

    def _on_connected(self, protocol):
        self._protocol = protocol
        logger.info("✅ З'єднання встановлено. Авторизація додатку...")
        request = ProtoOAApplicationAuthReq(clientId=CLIENT_ID, clientSecret=CLIENT_SECRET)
        self._protocol.send(request)

    def _on_disconnected(self, reason):
        logger.warning(f"⚠️ З'єднання втрачено: {reason.getErrorMessage()}")
        self._protocol = None
        self._is_authorized = False
        if self._ready_deferred:
            self._ready_deferred = None  # Перепідключення буде новим

    def _on_connection_failed(self, reason):
        logger.error(f"❌ Підключення не вдалося: {reason.getErrorMessage()}")
        self._protocol = None
        if self._ready_deferred:
            self._ready_deferred.errback(Exception("Connection failed"))
            self._ready_deferred = None

    def _message_received(self, message):
        logger.info(f"📩 Отримано повідомлення cTrader: {type(message).__name__}")

        if isinstance(message, ProtoOAApplicationAuthRes):
            logger.info("✅ Авторизація додатку успішна. Надсилаю запит на авторизацію акаунта...")
            request = ProtoOAAccountAuthReq(ctidTraderAccountId=ACCOUNT_ID, accessToken=ACCESS_TOKEN)
            self._protocol.send(request)

        elif isinstance(message, ProtoOAAccountAuthRes):
            self._is_authorized = True
            logger.info(f"✅ Авторизація акаунта {ACCOUNT_ID} успішна.")
            self._populate_symbol_cache()

            # --- ПОВІДОМЛЯЄМО, ЩО СЕРВІС ГОТОВИЙ ---
            if self._ready_deferred:
                self._ready_deferred.callback(None)
                self._ready_deferred = None

        elif isinstance(message, ProtoOAErrorRes):
            logger.error(f"❌ Помилка cTrader: {message.errorCode}. Опис: {message.description}")
            if "Unauthorized" in message.description and self._ready_deferred:
                self._ready_deferred.errback(Exception(message.description))
                self._ready_deferred = None

        elif self._protocol:
            self._protocol.handle_response(message)

    def _populate_symbol_cache(self):
        def on_symbols_listed(response):
            try:
                symbols_list = ProtoOASymbolsListRes()
                symbols_list.ParseFromString(response.payload)
                all_symbol_ids = [s.symbolId for s in symbols_list.symbol]

                def on_symbols_details(details_response):
                    details = ProtoOASymbolByIdRes()
                    details.ParseFromString(details_response.payload)
                    added = 0
                    with CACHE_LOCK:
                        for symbol in details.symbol:
                            if hasattr(symbol, 'symbolName') and symbol.symbolName:
                                SYMBOL_DATA_CACHE[symbol.symbolName] = {
                                    'symbolId': symbol.symbolId,
                                    'digits': symbol.digits
                                }
                                added += 1
                    logger.info(f"✅ Кеш оновлено: додано {added} символів. Усього: {len(SYMBOL_DATA_CACHE)}")

                chunk_size = 70
                for i in range(0, len(all_symbol_ids), chunk_size):
                    chunk = all_symbol_ids[i:i + chunk_size]
                    d = self.send_request(ProtoOASymbolByIdReq(ctidTraderAccountId=ACCOUNT_ID, symbolId=chunk))
                    d.addCallback(on_symbols_details)

            except Exception as e:
                logger.error(f"❌ Помилка при заповненні кешу символів: {e}")

        logger.info("🔄 Починаю завантаження списку символів...")
        d = self.send_request(ProtoOASymbolsListReq(ctidTraderAccountId=ACCOUNT_ID))
        d.addCallback(on_symbols_listed)
        d.addErrback(lambda f: logger.error(f"❌ Не вдалося отримати список символів: {f.value}"))

    def send_request(self, request, timeout=30):
        if not self._protocol:
            d = defer.Deferred()
            d.errback(Exception("Сервіс не підключений."))
            return d
        return self._protocol.send(request, timeout=timeout)

    def get_trendbars(self, symbol_id, period, from_timestamp, to_timestamp):
        req = ProtoOAGetTrendbarsReq(
            ctidTraderAccountId=ACCOUNT_ID,
            symbolId=symbol_id,
            period=period,
            fromTimestamp=from_timestamp,
            toTimestamp=to_timestamp
        )
        d = self.send_request(req)
        d.addCallback(lambda response: ProtoOAGetTrendbarsRes.FromString(response.payload))
        return d


# --- KLEIN ВЕБ-СЕРВЕР ---
app = Klein()
ctrader = CTraderService()

@app.route(f"/webhook", methods=['POST'])
def webhook(request):
    try:
        if request.getHeader('X-Telegram-Bot-Api-Secret-Token') == WEBHOOK_SECRET:
            update = Update.de_json(json.loads(request.content.read()), bot)
            dp.process_update(update)
            return "OK"
        else:
            logger.warning("❌ Невірний секретний токен вебхука")
            request.setResponseCode(403)
            return "Forbidden"
    except Exception as e:
        logger.error(f"❌ Помилка обробки вебхука: {e}")
        request.setResponseCode(500)
        return "Error"

def _get_user_id_from_request(req):
    init_data = req.args.get(b"initData", [b""])[0].decode()
    if not init_data:
        return None
    try:
        user_json_str = parse_qs(unquote(init_data)).get("user", [None])[0]
        if user_json_str:
            return json.loads(user_json_str).get("id")
    except Exception as e:
        logger.warning(f"⚠️ Не вдалося розпарсити initData: {e}")
    return None

def json_response(request, data):
    request.setHeader('Content-Type', 'application/json; charset=utf-8')
    request.setHeader('Access-Control-Allow-Origin', '*')
    return json.dumps(data, ensure_ascii=False, indent=2)

@app.route('/health')
def health_check(request):
    if ctrader._is_authorized and len(SYMBOL_DATA_CACHE) > 0:
        request.setResponseCode(200)
        return "OK"
    else:
        request.setResponseCode(503)  # Service Unavailable
        return "Service not ready"

@app.route('/')
def root(request):
    request.setResponseCode(200)
    return f"✅ ZigZag Bot запущено. Авторизація cTrader: {'так' if ctrader._is_authorized else 'ні'}. Символів у кеші: {len(SYMBOL_DATA_CACHE)}"

# --- API МАРШРУТИ ---
@app.route('/api/get_ranked_pairs')
def api_get_ranked_pairs(request):
    user_id = _get_user_id_from_request(request)
    watchlist = get_watchlist(user_id) if user_id else []
    data = {
        "watchlist": watchlist,
        "crypto": [],
        "forex": {session: [{'ticker': p, 'active': True} for p in pairs] for session, pairs in FOREX_SESSIONS.items()},
        "stocks": []
    }
    return json_response(request, data)

@app.route('/api/toggle_watchlist')
def toggle_watchlist_route(request):
    user_id = _get_user_id_from_request(request)
    pair = request.args.get(b"pair", [b""])[0].decode()
    if not user_id or not pair:
        return json_response(request, {"success": False})
    toggle_watch(user_id, pair)
    return json_response(request, {"success": True})

@app.route('/api/signal_history')
def api_signal_history(request):
    user_id = _get_user_id_from_request(request)
    pair = request.args.get(b"pair", [b""])[0].decode()
    if not user_id or not pair:
        return json_response(request, [])
    history = get_signal_history(user_id, pair)
    return json_response(request, history)

@app.route('/api/signal')
def api_signal(request):
    pair = request.args.get(b"pair", [b""])[0].decode()
    user_id = _get_user_id_from_request(request)

    if not isinstance(pair, str) or len(pair) < 3:
        return json_response(request, {"error": "Некоректна назва пари"})

    def on_error(failure):
        logger.error(f"❌ Помилка в api_signal для '{pair}': {failure.value}")
        return json_response(request, {"error": str(failure.value)})

    # Чекаємо, поки cTrader буде готовий
    d = ctrader.when_ready()
    d.addCallback(lambda _: analysis.get_api_detailed_signal_data(ctrader, pair, user_id))
    d.addCallback(lambda data: json_response(request, data))
    d.addErrback(on_error)
    return d

@app.route('/api/get_mta')
def api_get_mta(request):
    pair = request.args.get(b"pair", [b""])[0].decode()

    if not isinstance(pair, str) or len(pair) < 3:
        return json_response(request, {"error": "Некоректна назва пари"})

    def on_error(failure):
        logger.error(f"❌ Помилка в api_get_mta для '{pair}': {failure.value}")
        return json_response(request, {"error": str(failure.value)})

    d = ctrader.when_ready()
    d.addCallback(lambda _: analysis.get_api_mta_data(ctrader, pair))
    d.addCallback(lambda data: json_response(request, data))
    d.addErrback(on_error)
    return d

@app.route("/", branch=True)
def static_files(request):
    return File("./webapp")


# --- ГОЛОВНИЙ ЗАПУСК ---
if __name__ == "__main__":
    init_db()
    register_handlers(dp)

    # Встановлюємо вебхук
    WEBHOOK_URL = f"https://{APP_NAME}.fly.dev/webhook"
    success = bot.set_webhook(url=WEBHOOK_URL, secret_token=WEBHOOK_SECRET)
    if success:
        logger.info(f"✅ Webhook встановлено: {WEBHOOK_URL}")
    else:
        logger.error("❌ Не вдалося встановити webhook!")

    # Налаштовуємо HTTP-сервер
    endpoint_str = f"tcp:port={APP_PORT}:interface=0.0.0.0"
    endpoint = reactor.listenTCP(APP_PORT, Site(app.resource()))

    # Запускаємо підключення до cTrader
    reactor.callWhenRunning(ctrader.connect)

    logger.info(f"🚀 Сервер запущено на порту {APP_PORT}. Очікуємо авторизацію cTrader...")
    reactor.run()