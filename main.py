# main.py
import os
import json
from urllib.parse import parse_qs, unquote
from dotenv import load_dotenv

from telegram import Update
from telegram.ext import CallbackContext

# --- ВИПРАВЛЕННЯ: Додано 'defer' для механізму очікування ---
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

from config import logger, FOREX_SESSIONS, SYMBOL_DATA_CACHE, CACHE_LOCK, bot, dp, WEBHOOK_SECRET
from db import init_db, get_watchlist, toggle_watch, get_signal_history
import analysis
from telegram_ui import register_handlers

load_dotenv()
HOST = "demo.ctraderapi.com"
PORT = 5035
CLIENT_ID = os.getenv("CT_CLIENT_ID")
CLIENT_SECRET = os.getenv("CT_CLIENT_SECRET")
ACCESS_TOKEN = os.getenv("CTRADER_ACCESS_TOKEN")
ACCOUNT_ID = int(os.getenv("DEMO_ACCOUNT_ID", 9541520))
APP_PORT = int(os.getenv("PORT", 8080))
APP_NAME = os.getenv("FLY_APP_NAME", "zigzag-bot-package")

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
        self._is_ready = False
        # --- ВИПРАВЛЕННЯ: Створюємо "обіцянку" готовності сервісу ---
        self._ready_deferred = defer.Deferred()

    def when_ready(self):
        """Повертає Deferred, який буде виконано, коли сервіс буде готовий."""
        return self._ready_deferred

    def connect(self):
        class CTraderFactory(ClientFactory):
            def __init__(self, service): self.service = service
            def buildProtocol(self, addr): return CTraderProtocol(self.service)
            def clientConnectionFailed(self, connector, reason): self.service._on_connection_failed(reason)
        
        # --- ВИПРАВЛЕННЯ: Прибрано помилкову умову 'if not reactor.running' ---
        logger.info("Ініціація SSL-підключення до cTrader...")
        ctxFactory = ssl.optionsForClientTLS(hostname=HOST)
        reactor.connectSSL(HOST, PORT, CTraderFactory(self), ctxFactory)
            
    def _on_connected(self, protocol):
        self._protocol = protocol
        logger.info("З'єднання встановлено. Авторизація додатку...")
        request = ProtoOAApplicationAuthReq(clientId=CLIENT_ID, clientSecret=CLIENT_SECRET)
        self._protocol.send(request)

    def _on_disconnected(self, reason):
        logger.warning(f"З'єднання втрачено: {reason.getErrorMessage()}")
        self._protocol = None; self._is_ready = False
    
    def _on_connection_failed(self, reason):
        logger.error(f"Не вдалося підключитися: {reason.getErrorMessage()}")
        self._protocol = None; self._is_ready = False
        # --- ВИПРАВЛЕННЯ: Повідомляємо про помилку, якщо сервіс очікував на готовність ---
        if not self._ready_deferred.called:
            self._ready_deferred.errback(reason)

    def _message_received(self, message):
        logger.info(f"Received cTrader message: {type(message).__name__}")

        if isinstance(message, ProtoOAApplicationAuthRes):
            logger.info("Авторизація додатку успішна. Надсилаю запит на авторизацію акаунту...")
            request = ProtoOAAccountAuthReq(ctidTraderAccountId=ACCOUNT_ID, accessToken=ACCESS_TOKEN)
            self._protocol.send(request)
        elif isinstance(message, ProtoOAAccountAuthRes):
            self._is_ready = True
            logger.info(f"Авторизація акаунту {ACCOUNT_ID} успішна.")
            self._populate_symbol_cache()
        elif isinstance(message, ProtoOAErrorRes):
            logger.error(f"Помилка cTrader: {message.errorCode}. Опис: {message.description}")
            if not self._ready_deferred.called:
                self._ready_deferred.errback(Exception(f"{message.errorCode}: {message.description}"))

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
                    # --- ВИПРАВЛЕННЯ: Повідомляємо, що сервіс готовий до роботи ---
                    if not self._ready_deferred.called:
                        self._ready_deferred.callback(self)

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

app = Klein()
ctrader = CTraderService()
dp.bot_data['ctrader_service'] = ctrader

@app.route(f"/webhook", methods=['POST'])
def webhook(request):
    try:
        if request.getHeader('X-Telegram-Bot-Api-Secret-Token') == WEBHOOK_SECRET:
            update = Update.de_json(json.loads(request.content.read()), bot)
            dp.process_update(update)
            return "OK"
        else:
            logger.warning("Invalid webhook secret token received.")
            return "Forbidden", 403
    except Exception as e:
        logger.error(f"Error processing webhook: {e}")
        return "Error", 500

def json_response(request, data):
    request.setHeader('Content-Type', 'application/json; charset=utf-8')
    request.setHeader('Access-Control-Allow-Origin', '*')
    return json.dumps(data, ensure_ascii=False)

@app.route('/health')
def health_check(request):
    request.setResponseCode(200)
    return "OK"

@app.route('/')
def root(request):
    request.setResponseCode(200)
    return "Bot is running. Use /webhook for Telegram."

# --- ВИПРАВЛЕННЯ: Всі ендпоінти тепер чекають на готовність cTrader ---
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

    def on_error(failure):
        logger.error(f"Error in api_signal for pair '{pair}': {failure.value}")
        return json_response(request, {"error": str(failure.value)})

    d = ctrader.when_ready()
    d.addCallback(lambda _: analysis.get_api_detailed_signal_data(ctrader, pair, user_id))
    d.addCallback(lambda data: json_response(request, data))
    d.addErrback(on_error)
    return d

@app.route('/api/get_mta')
def api_get_mta(request):
    pair = request.args.get(b"pair", [b""])[0].decode()
    
    def on_error(failure):
        logger.error(f"Error in api_get_mta for pair '{pair}': {failure.value}")
        return json_response(request, {"error": str(failure.value)})

    d = ctrader.when_ready()
    d.addCallback(lambda _: analysis.get_api_mta_data(ctrader, pair))
    d.addCallback(lambda data: json_response(request, data))
    d.addErrback(on_error)
    return d

@app.route("/", branch=True)
def static_files(request):
    return File("./webapp")

from twisted.internet import endpoints
from twisted.web.server import Site

if __name__ == "__main__":
    init_db()

    WEBHOOK_URL = f"https://{APP_NAME}.fly.dev/webhook"
    bot.set_webhook(url=WEBHOOK_URL, secret_token=WEBHOOK_SECRET)
    register_handlers(dp)
    logger.info(f"Telegram webhook встановлено на {WEBHOOK_URL}")

    endpoint_str = f"tcp:port={APP_PORT}:interface=0.0.0.0"
    endpoint = endpoints.serverFromString(reactor, endpoint_str)
    endpoint.listen(Site(app.resource()))
    
    reactor.callWhenRunning(ctrader.connect)
    
    logger.info("Сервер запущено...")
    reactor.run()