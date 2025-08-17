# main.py (ОНОВЛЕНО)
import os
import json
from urllib.parse import parse_qs, unquote
import threading
import asyncio
import traceback

from twisted.internet import reactor, ssl, endpoints
from twisted.internet.protocol import ClientFactory
from twisted.web.server import Site
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

from config import logger, FOREX_SESSIONS, SYMBOL_DATA_CACHE, CACHE_LOCK, get_telegram_token
from db import init_db, get_watchlist, toggle_watch, get_signal_history
import analysis

# Telegram (v20)
from telegram.ext import Application
import telegram_ui

HOST = "demo.ctraderapi.com"
PORT = 5035
CLIENT_ID = os.environ.get("CT_CLIENT_ID")
CLIENT_SECRET = os.environ.get("CT_CLIENT_SECRET")
ACCESS_TOKEN = os.environ.get("CTRADER_ACCESS_TOKEN")
ACCOUNT_ID = int(os.environ.get("DEMO_ACCOUNT_ID", "9541520"))
APP_PORT = int(os.environ.get("PORT", "8080"))

# ----------------- cTrader -----------------
class CTraderProtocol(TcpProtocol, Protobuf):
    def __init__(self, service):
        super().__init__()
        self.service = service
    def connectionMade(self): self.service._on_connected(self)
    def connectionLost(self, reason): self.service._on_disconnected(reason)
    def messageReceived(self, message: ProtoMessage): self.service._message_received(message)

class CTraderService:
    def __init__(self):
        self._protocol = None
        self._is_authorized = False

    def connect(self):
        class CTraderFactory(ClientFactory):
            def __init__(self, service): self.service = service
            def buildProtocol(self, addr): return CTraderProtocol(self.service)
            def clientConnectionFailed(self, connector, reason): self.service._on_connection_failed(reason)

        logger.info("Запуск Twisted з SSL-підключенням до cTrader...")
        try:
            ctxFactory = ssl.optionsForClientTLS(hostname=HOST)
            reactor.connectSSL(HOST, PORT, CTraderFactory(self), ctxFactory)
        except Exception as e:
            logger.exception("Не вдалося запустити SSL підключення до cTrader:")

    def _on_connected(self, protocol):
        self._protocol = protocol
        logger.info("З'єднання встановлено. Авторизація додатку...")
        request = ProtoOAApplicationAuthReq(clientId=CLIENT_ID, clientSecret=CLIENT_SECRET)
        self._protocol.send(request)

    def _on_disconnected(self, reason):
        try:
            msg = reason.getErrorMessage()
        except Exception:
            msg = str(reason)
        logger.warning(f"З'єднання втрачено: {msg}")
        self._protocol = None; self._is_authorized = False

    def _on_connection_failed(self, reason):
        try:
            msg = reason.getErrorMessage()
        except Exception:
            msg = str(reason)
        logger.error(f"Не вдалося підключитися: {msg}")
        self._protocol = None; self._is_authorized = False

    def _message_received(self, message):
        logger.info(f"Received cTrader message: {type(message).__name__}")
        if isinstance(message, ProtoOAApplicationAuthRes):
            logger.info("Авторизація додатку успішна. Надсилаю запит на авторизацію акаунту...")
            request = ProtoOAAccountAuthReq(ctidTraderAccountId=ACCOUNT_ID, accessToken=ACCESS_TOKEN)
            self._protocol.send(request)
        elif isinstance(message, ProtoOAAccountAuthRes):
            self._is_authorized = True
            logger.info(f"Авторизація акаунту {ACCOUNT_ID} успішна.")
            self._populate_symbol_cache()
        elif isinstance(message, ProtoOAErrorRes):
            logger.error(f"Помилка cTrader: {message.errorCode}. Опис: {message.description}")
        elif self._protocol:
            try:
                self._protocol.handle_response(message)
            except Exception:
                logger.exception("Помилка при обробці повідомлення від cTrader:")

    def _populate_symbol_cache(self):
        def on_symbols_listed(response):
            try:
                symbols_list = ProtoOASymbolsListRes()
                symbols_list.ParseFromString(response.payload)
                all_symbol_ids = [s.symbolId for s in symbols_list.symbol]
                def on_symbols_details(details_response):
                    try:
                        details = ProtoOASymbolByIdRes()
                        details.ParseFromString(details_response.payload)
                        with CACHE_LOCK:
                            for symbol in details.symbol:
                                if hasattr(symbol, 'symbolName') and symbol.symbolName:
                                    SYMBOL_DATA_CACHE[symbol.symbolName] = {'symbolId': symbol.symbolId, 'digits': symbol.digits}
                        logger.info(f"Кеш символів cTrader тепер містить {len(SYMBOL_DATA_CACHE)} елементів.")
                    except Exception:
                        logger.exception("Помилка при обробці деталей символів:")
                chunk_size = 70
                for i in range(0, len(all_symbol_ids), chunk_size):
                    chunk = all_symbol_ids[i:i + chunk_size]
                    d = self.send_request(ProtoOASymbolByIdReq(ctidTraderAccountId=ACCOUNT_ID, symbolId=chunk))
                    d.addCallback(on_symbols_details)
            except Exception:
                logger.exception("Помилка при обробці списку символів:")

        logger.info("Починаю заповнення кешу символів cTrader...")
        d = self.send_request(ProtoOASymbolsListReq(ctidTraderAccountId=ACCOUNT_ID))
        d.addCallback(on_symbols_listed)

    def send_request(self, request, timeout=30):
        if not self._protocol:
            d = reactor.defer.Deferred()
            d.errback(Exception("Сервіс не підключений."))
            return d
        return self._protocol.send(request, timeout=timeout)

    def get_trendbars(self, symbol_id, period, from_timestamp, to_timestamp):
        req = ProtoOAGetTrendbarsReq(ctidTraderAccountId=ACCOUNT_ID, symbolId=symbol_id,
                                     period=period, fromTimestamp=from_timestamp, toTimestamp=to_timestamp)
        d = self.send_request(req)
        d.addCallback(lambda response: ProtoOAGetTrendbarsRes.FromString(response.payload))
        return d

# ----------------- Klein Web -----------------
app = Klein()
ctrader = CTraderService()

def _get_user_id_from_request(req):
    init_data = req.args.get(b"initData", [b""])[0].decode()
    if not init_data: return None
    try:
        user_json_str = parse_qs(unquote(init_data)).get("user", [None])[0]
        if user_json_str: return json.loads(user_json_str).get("id")
    except Exception as e:
        logger.warning(f"Не вдалося розпарсити initData: {e}")
    return None

def json_response(request, data):
    request.setHeader('Content-Type', 'application/json; charset=utf-8')
    request.setHeader('Access-Control-Allow-Origin', '*')
    return json.dumps(data, ensure_ascii=False)

# ЛОГУЄМО кожен вхідний запит у кінці ендпоінта для діагностики
@app.route('/health')
def health_check(request):
    logger.info("HTTP /health called")
    return "OK"

@app.route('/api/get_ranked_pairs')
def api_get_ranked_pairs(request):
    try:
        logger.info(f"HTTP /api/get_ranked_pairs args={dict(request.args)}")
        user_id = _get_user_id_from_request(request)
        watchlist = get_watchlist(user_id) if user_id else []
        data = {
            "watchlist": watchlist,
            "crypto": [],
            "forex": {session: [{'ticker': p, 'active': True} for p in pairs] for session, pairs in FOREX_SESSIONS.items()},
            "stocks": []
        }
        return json_response(request, data)
    except Exception:
        logger.exception("Error in /api/get_ranked_pairs")
        return json_response(request, {"error": "internal"})

@app.route('/api/toggle_watchlist')
def toggle_watchlist_route(request):
    try:
        logger.info(f"HTTP /api/toggle_watchlist args={dict(request.args)}")
        user_id = _get_user_id_from_request(request)
        pair = request.args.get(b"pair", [b""])[0].decode()
        if not user_id or not pair:
            return json_response(request, {"success": False})
        toggle_watch(user_id, pair)
        return json_response(request, {"success": True})
    except Exception:
        logger.exception("Error in /api/toggle_watchlist")
        return json_response(request, {"success": False, "error": "internal"})

@app.route('/api/signal_history')
def api_signal_history(request):
    try:
        logger.info(f"HTTP /api/signal_history args={dict(request.args)}")
        user_id = _get_user_id_from_request(request)
        pair = request.args.get(b"pair", [b""])[0].decode()
        if not user_id or not pair: return json_response(request, [])
        history = get_signal_history(user_id, pair)
        return json_response(request, history)
    except Exception:
        logger.exception("Error in /api/signal_history")
        return json_response(request, {"error": "internal"})

@app.route('/api/signal')
def api_signal(request):
    try:
        logger.info(f"HTTP /api/signal args={dict(request.args)}")
        pair = request.args.get(b"pair", [b""])[0].decode()
        user_id = _get_user_id_from_request(request)
        if not SYMBOL_DATA_CACHE:
            return json_response(request, {"error": "Сервіс ще завантажує дані, спробуйте за хвилину."})

        def on_error(failure):
            logger.error(f"Error in api_signal for pair '{pair}': {failure.value}")
            return json_response(request, {"error": str(failure.value)})

        d = reactor.defer.maybeDeferred(analysis.get_api_detailed_signal_data, ctrader, pair, user_id)
        d.addCallback(lambda data: json_response(request, data))
        d.addErrback(on_error)
        return d
    except Exception:
        logger.exception("Unhandled error in /api/signal")
        return json_response(request, {"error": "internal"})

@app.route('/api/get_mta')
def api_get_mta(request):
    try:
        logger.info(f"HTTP /api/get_mta args={dict(request.args)}")
        pair = request.args.get(b"pair", [b""])[0].decode()
        if not SYMBOL_DATA_CACHE:
            return json_response(request, {"error": "Сервіс ще завантажує дані, спробуйте за хвилину."})

        def on_error(failure):
            logger.error(f"Error in api_get_mta for pair '{pair}': {failure.value}")
            return json_response(request, {"error": str(failure.value)})

        d = reactor.defer.maybeDeferred(analysis.get_api_mta_data, ctrader, pair)
        d.addCallback(lambda data: json_response(request, data))
        d.addErrback(on_error)
        return d
    except Exception:
        logger.exception("Unhandled error in /api/get_mta")
        return json_response(request, {"error": "internal"})

@app.route("/", branch=True)
def static_files(request):
    logger.info(f"HTTP static request path={request.path} args={dict(request.args)}")
    return File("./webapp")

# ----------------- Telegram Bot -----------------
def start_telegram_bot():
    token = get_telegram_token()
    if not token:
        logger.warning("TELEGRAM token не встановлено — Telegram бот не запущено.")
        return

    # ВАЖЛИВО: створюємо та встановлюємо asyncio loop у цьому потоці
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        logger.info("Asyncio event loop створено у фоні для Telegram.")
    except Exception:
        logger.exception("Не вдалося створити asyncio loop для Telegram потоку.")
        return

    try:
        application = Application.builder().token(token).build()
        telegram_ui.register_handlers(application)
        logger.info("Запускаю Telegram бот (polling) у фоні...")
        application.run_polling()
    except Exception:
        logger.exception("Помилка при запуску Telegram бота:")

# ----------------- Запуск -----------------
if __name__ == "__main__":
    init_db()

    # Запуск Telegram у фоновому потоці (якщо є токен)
    t = threading.Thread(target=start_telegram_bot, daemon=True, name="tg-poller-thread")
    t.start()

    # Запуск cTrader (Twisted) коли реактор запущено
    reactor.callWhenRunning(ctrader.connect)

    # Запуск Klein веб
    endpoint_str = f"tcp:port={APP_PORT}:interface=0.0.0.0"
    endpoint = endpoints.serverFromString(reactor, endpoint_str)
    endpoint.listen(Site(app.resource()))

    logger.info("Starting Twisted reactor...")
    reactor.run()
