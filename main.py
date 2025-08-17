# main.py
import os
import json
import asyncio
import threading
from urllib.parse import parse_qs, unquote
from dotenv import load_dotenv
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

from config import logger, FOREX_SESSIONS, SYMBOL_DATA_CACHE, CACHE_LOCK, APP_PORT, CLIENT_ID, CLIENT_SECRET, ACCESS_TOKEN, ACCOUNT_ID
from db import init_db, get_watchlist, toggle_watch, get_signal_history
import analysis
import telegram_ui

load_dotenv()

HOST = os.getenv("CT_HOST", "demo.ctraderapi.com")
PORT = int(os.getenv("CT_PORT", 5035))

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

        logger.info("Починаю cTrader SSL-підключення...")
        ctxFactory = ssl.optionsForClientTLS(hostname=HOST)
        reactor.connectSSL(HOST, PORT, CTraderFactory(self), ctxFactory)

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
                    with CACHE_LOCK:
                        for symbol in details.symbol:
                            if hasattr(symbol, 'symbolName') and symbol.symbolName:
                                SYMBOL_DATA_CACHE[symbol.symbolName] = {'symbolId': symbol.symbolId, 'digits': symbol.digits}
                    logger.info(f"Кеш символів cTrader тепер містить {len(SYMBOL_DATA_CACHE)} елементів.")
                chunk_size = 70
                for i in range(0, len(all_symbol_ids), chunk_size):
                    chunk = all_symbol_ids[i:i + chunk_size]
                    d = self.send_request(ProtoOASymbolByIdReq(ctidTraderAccountId=ACCOUNT_ID, symbolId=chunk))
                    d.addCallback(on_symbols_details)
            except Exception as e:
                logger.error(f"Помилка при обробці списку символів: {e}")

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
    except Exception as e: logger.warning(f"Не вдалося розпарсити initData: {e}")
    return None

def json_response(request, data):
    request.setHeader('Content-Type', 'application/json; charset=utf-8')
    request.setHeader('Access-Control-Allow-Origin', '*')
    return json.dumps(data, ensure_ascii=False)

@app.route('/health')
def health_check(request):
    logger.info("HTTP /health called")
    return "OK"

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
    if not user_id or not pair: return json_response(request, {"success": False})
    toggle_watch(user_id, pair)
    return json_response(request, {"success": True})

@app.route('/api/signal_history')
def api_signal_history(request):
    user_id = _get_user_id_from_request(request)
    pair = request.args.get(b"pair", [b""])[0].decode()
    if not user_id or not pair: return json_response(request, [])
    history = get_signal_history(user_id, pair)
    return json_response(request, history)

@app.route('/api/signal')
def api_signal(request):
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

@app.route('/api/get_mta')
def api_get_mta(request):
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

@app.route("/", branch=True)
def static_files(request):
    return File("./webapp")

# ----------------- Telegram helpers -----------------
def get_telegram_token():
    # підтримуємо TELEGRAM_BOT_TOKEN або TOKEN (Fly secret)
    return os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TOKEN")

# ----------------- Twisted runner (фон) -----------------
def start_twisted_in_background(port):
    # Ставимо завдання, які Reactor повинен виконати при запуску
    reactor.callWhenRunning(ctrader.connect)

    def _listen():
        endpoint_str = f"tcp:port={port}:interface=0.0.0.0"
        endpoint = endpoints.serverFromString(reactor, endpoint_str)
        endpoint.listen(Site(app.resource()))
        logger.info(f"Klein web scheduled to listen on {port}")

    reactor.callWhenRunning(_listen)

    def _run():
        logger.info("Starting Twisted reactor (background thread)...")
        reactor.run(installSignalHandlers=False)
        logger.info("Twisted reactor stopped.")

    t = threading.Thread(target=_run, name="twisted-reactor", daemon=True)
    t.start()
    return t

# ----------------- Main (PTB in main thread) -----------------
if __name__ == "__main__":
    init_db()

    # Запускаємо Twisted/Klein у фоні
    start_twisted_in_background(APP_PORT)

    # Тепер запускаємо Telegram у головному потоці (asyncio прив'язаний до main thread)
    TELEGRAM_TOKEN = get_telegram_token()
    if not TELEGRAM_TOKEN:
        logger.warning("TELEGRAM token не встановлено — Telegram бот не запущено.")
    else:
        try:
            from telegram import __version__ as ptb_ver
            logger.info(f"python-telegram-bot version: {ptb_ver}")
            from telegram.ext import Application
        except Exception:
            logger.exception("Не вдалося імпортувати PTB Application.")
            raise

        try:
            application = Application.builder().token(TELEGRAM_TOKEN).build()
            # register handlers (синхронна)
            telegram_ui.register_handlers(application)
            logger.info("Запускаю Telegram бот (polling) у головному потоці...")
            application.run_polling()
        except Exception:
            logger.exception("Помилка при запуску Telegram бота.")
