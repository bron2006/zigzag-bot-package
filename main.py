# main.py
# --- ЗМІНЕНО: Встановлення asyncio-реактора для Twisted. Це має бути на самому початку! ---
import asyncio
from twisted.internet import asyncioreactor
try:
    asyncioreactor.install(asyncio.get_event_loop())
except Exception:
    # Ігноруємо помилку, якщо реактор вже встановлено (для деяких середовищ)
    pass
# --- КІНЕЦЬ ЗМІН ---

import os
import json
from urllib.parse import parse_qs, unquote
from dotenv import load_dotenv

from telegram import Update
from telegram.ext import Application, ApplicationBuilder

# --- ЗМІНЕНО: reactor тепер імпортується ПІСЛЯ встановлення asyncioreactor ---
from twisted.internet import reactor, defer
from twisted.web.server import Site
from klein import Klein

from ctrader_open_api.client import Client
from ctrader_open_api.tcpProtocol import TcpProtocol
from ctrader_open_api.endpoints import EndPoints
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import ProtoMessage
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAApplicationAuthReq, ProtoOAApplicationAuthRes,
    ProtoOAAccountAuthReq, ProtoOAAccountAuthRes, ProtoOAErrorRes,
    ProtoOASymbolsListReq, ProtoOASymbolsListRes,
    ProtoOASymbolByIdReq, ProtoOASymbolByIdRes
)

from config import logger, SYMBOL_DATA_CACHE, CACHE_LOCK, TOKEN, WEBHOOK_SECRET, \
                   CT_CLIENT_ID, CT_CLIENT_SECRET, CTRADER_ACCESS_TOKEN, DEMO_ACCOUNT_ID
from db import init_db
import analysis
from telegram_ui import register_handlers

load_dotenv()

# --- App Configuration ---
HOST = EndPoints.PROTOBUF_DEMO_HOST
PORT = EndPoints.PROTOBUF_PORT
APP_PORT = int(os.getenv("PORT", 8080))
APP_NAME = os.getenv("FLY_APP_NAME", "zigzag-bot-package")

# --- Globals for services ---
is_ctrader_authorized = False
client = Client(HOST, PORT, TcpProtocol)
web_app = Klein()
telegram_app: Application | None = None

# --- cTrader Client Callbacks (залишаються без змін) ---
def connected(client: Client):
    logger.info("✅ Connection successful. Authorizing application...")
    request = ProtoOAApplicationAuthReq(clientId=CT_CLIENT_ID, clientSecret=CT_CLIENT_SECRET)
    client.send(request)

def disconnected(client: Client, reason):
    global is_ctrader_authorized
    is_ctrader_authorized = False
    logger.warning(f"⚠️ Disconnected. Reason: {reason.getErrorMessage()}")

def on_error(failure):
    logger.error(f"❌ An error occurred: {failure.getErrorMessage()}")

def message_received(client: Client, message: ProtoMessage):
    global is_ctrader_authorized
    if message.payloadType == ProtoOAApplicationAuthRes().payloadType:
        logger.info("✅ Application authorized. Authorizing account...")
        request = ProtoOAAccountAuthReq(ctidTraderAccountId=DEMO_ACCOUNT_ID, accessToken=CTRADER_ACCESS_TOKEN)
        client.send(request)
    elif message.payloadType == ProtoOAAccountAuthRes().payloadType:
        logger.info(f"✅ Account {DEMO_ACCOUNT_ID} authorized successfully.")
        is_ctrader_authorized = True
        populate_symbol_cache()
    elif message.payloadType == ProtoOAErrorRes().payloadType:
        error_res = ProtoOAErrorRes.FromString(message.payload)
        logger.error(f"❌ cTrader Error: {error_res.errorCode} - {error_res.description}")

def populate_symbol_cache():
    # Ця функція залишається без змін
    logger.info("🔄 Populating symbol cache...")
    list_req = ProtoOASymbolsListReq(ctidTraderAccountId=DEMO_ACCOUNT_ID)
    d = client.send(list_req)

    def on_symbols_listed(response: ProtoMessage):
        symbols_list = ProtoOASymbolsListRes.FromString(response.payload)
        all_symbol_ids = [s.symbolId for s in symbols_list.symbol]
        chunk_size = 70
        deferred_list = [
            client.send(ProtoOASymbolByIdReq(ctidTraderAccountId=DEMO_ACCOUNT_ID, symbolId=all_symbol_ids[i:i + chunk_size]))
            for i in range(0, len(all_symbol_ids), chunk_size)
        ]
        d_list = defer.DeferredList(deferred_list, consumeErrors=True)
        d_list.addCallback(on_all_details_fetched)

    def on_all_details_fetched(results):
        with CACHE_LOCK:
            SYMBOL_DATA_CACHE.clear()
            for success, response in results:
                if success:
                    details = ProtoOASymbolByIdRes.FromString(response.payload)
                    for symbol in details.symbol:
                        if hasattr(symbol, 'symbolName') and symbol.symbolName:
                            SYMBOL_DATA_CACHE[symbol.symbolName] = {'symbolId': symbol.symbolId, 'digits': symbol.digits}
        logger.info(f"✅ Symbol cache populated. Total symbols: {len(SYMBOL_DATA_CACHE)}")

    d.addCallbacks(on_symbols_listed, on_error)

# --- Klein Web Server Routes (залишаються без змін) ---
@web_app.route("/webhook", methods=["POST"])
async def webhook(request):
    try:
        if request.getHeader("X-Telegram-Bot-Api-Secret-Token") == WEBHOOK_SECRET:
            update_json = json.loads(request.content.read())
            update = Update.de_json(update_json, telegram_app.bot)
            await telegram_app.process_update(update)
            return "OK"
        request.setResponseCode(403)
        return "Forbidden"
    except Exception as e:
        logger.error(f"❌ Webhook error: {e}")
        request.setResponseCode(500)
        return "Error"

@web_app.route("/health")
def health_check(request):
    if is_ctrader_authorized and len(SYMBOL_DATA_CACHE) > 10:
        return "OK"
    request.setResponseCode(503)
    return "Service Unavailable"

@web_app.route("/")
def root(request):
    status = "authorized" if is_ctrader_authorized else "connecting..."
    return f"✅ ZigZag Bot. cTrader Status: {status}. Symbols in cache: {len(SYMBOL_DATA_CACHE)}"

# --- ЗМІНЕНО: Логіка запуску ---
def main():
    """Синхронна функція для налаштування всіх сервісів перед запуском реактора."""
    global telegram_app
    init_db()

    # 1. Налаштовуємо Telegram, але не запускаємо його блокуючим методом
    telegram_app = ApplicationBuilder().token(TOKEN).build()
    telegram_app.bot_data['ctrader_client'] = client
    register_handlers(telegram_app)
    
    # Використовуємо `run_webhook` в неблокуючому режимі, керованому Twisted
    async def setup_telegram():
        await telegram_app.initialize()
        webhook_url = f"https://{APP_NAME}.fly.dev/webhook"
        await telegram_app.bot.set_webhook(url=webhook_url, secret_token=WEBHOOK_SECRET)
        logger.info(f"✅ Telegram webhook set: {webhook_url}")

    # 2. Налаштовуємо cTrader клієнт
    client.setConnectedCallback(connected)
    client.setDisconnectedCallback(disconnected)
    client.setMessageReceivedCallback(message_received)

    # 3. Додаємо всі задачі в реактор Twisted
    reactor.callWhenRunning(client.startService)
    reactor.callWhenRunning(lambda: defer.ensureDeferred(setup_telegram()))

    # 4. Налаштовуємо веб-сервер Klein
    logger.info(f"🚀 Starting HTTP server on port {APP_PORT}...")
    reactor.listenTCP(APP_PORT, Site(web_app.resource()))
    logger.info("✅ All services configured. Starting Twisted reactor...")

if __name__ == "__main__":
    main()
    reactor.run()