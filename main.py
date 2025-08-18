# main.py
import os
import json
from dotenv import load_dotenv

from telegram import Update
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

from config import logger, SYMBOL_DATA_CACHE, CACHE_LOCK, WEBHOOK_SECRET, \
                   CT_CLIENT_ID, CT_CLIENT_SECRET, CTRADER_ACCESS_TOKEN, DEMO_ACCOUNT_ID, \
                   bot, dp
from db import init_db
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

# --- cTrader Client Callbacks ---
def connected(client: Client):
    logger.info("✅ cTrader Client Connected. Authorizing application...")
    request = ProtoOAApplicationAuthReq(clientId=CT_CLIENT_ID, clientSecret=CT_CLIENT_SECRET)
    client.send(request)

def disconnected(client: Client, reason):
    global is_ctrader_authorized
    is_ctrader_authorized = False
    logger.warning(f"⚠️ cTrader Client Disconnected. Reason: {reason.getErrorMessage()}")

def on_error(failure):
    logger.error(f"❌ A cTrader deferred error occurred: {failure.getErrorMessage()}")

def message_received(client: Client, message: ProtoMessage):
    global is_ctrader_authorized
    if message.payloadType == ProtoOAApplicationAuthRes().payloadType:
        logger.info("✅ Application authorized. Authorizing account...")
        request = ProtoOAAccountAuthReq(ctidTraderAccountId=DEMO_ACCOUNT_ID, accessToken=CTRADER_ACCESS_TOKEN)
        client.send(request)
    elif message.payloadType == ProtoOAAccountAuthRes().payloadType:
        is_ctrader_authorized = True
        logger.info(f"✅ Account {DEMO_ACCOUNT_ID} authorized successfully. Populating symbol cache...")
        populate_symbol_cache()
    elif message.payloadType == ProtoOAErrorRes().payloadType:
        error_res = ProtoOAErrorRes.FromString(message.payload)
        logger.error(f"❌ cTrader Error: {error_res.errorCode} - {error_res.description}")

# --- ЗМІНЕНО: Повністю переписано на послідовні запити, як в офіційному прикладі ---
def populate_symbol_cache():
    logger.info("🔄 Populating symbol cache...")
    
    def on_symbols_listed(response: ProtoMessage):
        symbols_list = ProtoOASymbolsListRes.FromString(response.payload)
        all_symbol_ids = [s.symbolId for s in symbols_list.symbol if s.symbolId]
        logger.info(f"DIAGNOSTIC: Received {len(all_symbol_ids)} symbol IDs. Fetching details sequentially...")

        if not all_symbol_ids:
            logger.warning("⚠️ Symbol list is empty. Aborting cache population.")
            return

        # Створюємо тимчасовий кеш для збору результатів
        temp_cache = {}
        
        # Створюємо ланцюжок послідовних запитів
        d = defer.succeed(None)
        chunk_size = 70
        
        def process_chunk(result, chunk):
            # Коли попередній запит завершився, відправляємо наступний
            details_req = ProtoOASymbolByIdReq(ctidTraderAccountId=DEMO_ACCOUNT_ID, symbolId=chunk)
            return client.send(details_req)

        def on_chunk_details(response: ProtoMessage):
            # Обробляємо результат поточного запиту
            details = ProtoOASymbolByIdRes.FromString(response.payload)
            for symbol in details.symbol:
                if hasattr(symbol, 'symbolName') and symbol.symbolName:
                    temp_cache[symbol.symbolName] = {'symbolId': symbol.symbolId, 'digits': symbol.digits}
            logger.info(f"DIAGNOSTIC: Processed chunk, current temp cache size: {len(temp_cache)}")

        # Формуємо ланцюжок
        for i in range(0, len(all_symbol_ids), chunk_size):
            chunk = all_symbol_ids[i:i + chunk_size]
            d.addCallback(process_chunk, chunk)
            d.addCallback(on_chunk_details)

        def on_all_done(result):
            # Коли всі запити в ланцюжку виконано
            with CACHE_LOCK:
                SYMBOL_DATA_CACHE.clear()
                SYMBOL_DATA_CACHE.update(temp_cache)
            logger.info(f"✅ Symbol cache populated. Total symbols: {len(SYMBOL_DATA_CACHE)}")

        d.addCallback(on_all_done)
        d.addErrback(on_error)

    # Запускаємо початковий запит на список символів
    list_req = ProtoOASymbolsListReq(ctidTraderAccountId=DEMO_ACCOUNT_ID)
    d = client.send(list_req)
    d.addCallbacks(on_symbols_listed, on_error)

# --- Klein Web Server Routes ---
@web_app.route("/")
def root(request):
    request.setHeader("Content-Type", "text/plain; charset=utf-8")
    status = "authorized" if is_ctrader_authorized else "connecting..."
    return f"✅ ZigZag Bot. cTrader Status: {status}. Symbols in cache: {len(SYMBOL_DATA_CACHE)}"

# ... (решта файлу без змін) ...
@web_app.route("/webhook", methods=["POST"])
def webhook(request):
    try:
        if request.getHeader("X-Telegram-Bot-Api-Secret-Token") == WEBHOOK_SECRET:
            update = Update.de_json(json.loads(request.content.read()), bot)
            dp.process_update(update)
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

# --- Main Application Startup ---
if __name__ == "__main__":
    init_db()
    
    webhook_url = f"https://{APP_NAME}.fly.dev/webhook"
    if bot.set_webhook(url=webhook_url, secret_token=WEBHOOK_SECRET):
        logger.info(f"✅ Telegram webhook set: {webhook_url}")
    else:
        logger.error(f"❌ Failed to set Telegram webhook!")
        
    register_handlers(dp, client)
    
    client.setConnectedCallback(connected)
    client.setDisconnectedCallback(disconnected)
    client.setMessageReceivedCallback(message_received)
    client.startService()
    
    logger.info(f"🚀 Starting HTTP server on port {APP_PORT}...")
    reactor.listenTCP(APP_PORT, Site(web_app.resource()))
    
    logger.info("✅ All services configured. Starting Twisted reactor...")
    reactor.run()