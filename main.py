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

# --- Globals ---
is_ctrader_authorized = False
client = Client(HOST, PORT, TcpProtocol)
web_app = Klein()

# --- Callbacks ---
def connected(client: Client):
    logger.info("✅ cTrader Client Connected. Authorizing application...")
    request = ProtoOAApplicationAuthReq(clientId=CT_CLIENT_ID, clientSecret=CT_CLIENT_SECRET)
    client.send(request)

def disconnected(client: Client, reason):
    global is_ctrader_authorized
    is_ctrader_authorized = False
    try:
        reason_msg = reason.getErrorMessage()
    except Exception:
        reason_msg = str(reason)
    logger.warning(f"⚠️ cTrader Client Disconnected. Reason: {reason_msg}")

def on_error(failure):
    logger.error(f"❌ A cTrader deferred error occurred: {failure}")

def message_received(client: Client, message: ProtoMessage):
    global is_ctrader_authorized
    if message.payloadType == ProtoOAApplicationAuthRes().payloadType:
        logger.info("✅ Application authorized. Authorizing account...")
        request = ProtoOAAccountAuthReq(ctidTraderAccountId=DEMO_ACCOUNT_ID, accessToken=CTRADER_ACCESS_TOKEN)
        client.send(request)
    elif message.payloadType == ProtoOAAccountAuthRes().payloadType:
        is_ctrader_authorized = True
        logger.info(f"✅ Account {DEMO_ACCOUNT_ID} authorized. Populating symbol cache...")
        populate_symbol_cache()
    elif message.payloadType == ProtoOAErrorRes().payloadType:
        error_res = ProtoOAErrorRes.FromString(message.payload)
        logger.error(f"❌ cTrader Error: {error_res.errorCode} - {error_res.description}")

# --- Symbol cache population (двокроковий) ---
def populate_symbol_cache():
    logger.info("🔄 Populating symbol cache...")
    id_to_name_map = {}

    def on_symbols_listed(response: ProtoMessage):
        try:
            symbols_list = ProtoOASymbolsListRes.FromString(response.payload)
        except Exception as e:
            logger.error(f"Failed to parse SymbolsListRes: {e}")
            return

        all_symbol_ids = []
        for symbol in symbols_list.symbol:
            id_to_name_map[symbol.symbolId] = symbol.symbolName
            all_symbol_ids.append(symbol.symbolId)

        logger.info(f"Step 1: Received {len(all_symbol_ids)} symbols. Created ID-to-Name map.")

        if not all_symbol_ids:
            return

        chunk_size = 70
        deferred_list = [
            client.send(ProtoOASymbolByIdReq(ctidTraderAccountId=DEMO_ACCOUNT_ID, symbolId=all_symbol_ids[i:i + chunk_size]))
            for i in range(0, len(all_symbol_ids), chunk_size)
        ]
        d_list = defer.DeferredList(deferred_list, consumeErrors=True)
        d_list.addCallback(on_all_details_fetched)

    def on_all_details_fetched(results):
        temp_cache = {}
        for success, response_or_failure in results:
            if success:
                try:
                    details = ProtoOASymbolByIdRes.FromString(response_or_failure.payload)
                except Exception:
                    continue
                for symbol in details.symbol:
                    symbol_name = id_to_name_map.get(symbol.symbolId)
                    if symbol_name:
                        # normalize name to match UI (remove slash if any)
                        key = symbol_name.replace("/", "").upper()
                        temp_cache[key] = {'symbolId': symbol.symbolId, 'digits': symbol.digits}
        with CACHE_LOCK:
            SYMBOL_DATA_CACHE.clear()
            SYMBOL_DATA_CACHE.update(temp_cache)
        logger.info(f"Step 2: Symbol cache populated. Total symbols: {len(SYMBOL_DATA_CACHE)}")

    list_req = ProtoOASymbolsListReq(ctidTraderAccountId=DEMO_ACCOUNT_ID)
    d = client.send(list_req)
    d.addCallbacks(on_symbols_listed, on_error)

# --- Web Server routes ---
@web_app.route("/")
def root(request):
    request.setHeader("Content-Type", "text/plain; charset=utf-8")
    status = "authorized" if is_ctrader_authorized else "connecting..."
    return f"✅ ZigZag Bot. cTrader Status: {status}. Symbols in cache: {len(SYMBOL_DATA_CACHE)}"

@web_app.route("/webhook", methods=["POST"])
def webhook(request):
    try:
        if request.getHeader("X-Telegram-Bot-Api-Secret-Token") == WEBHOOK_SECRET:
            update = Update.de_json(json.loads(request.content.read()), bot)
            dp.process_update(update)
            return "OK"
        return "Forbidden"
    except Exception as e:
        logger.error(f"❌ Webhook error: {e}")
        return "Error"

@web_app.route("/health")
def health_check(request):
    if is_ctrader_authorized and len(SYMBOL_DATA_CACHE) > 100:
        return "OK"
    return "Service Unavailable"

# --- Main Startup ---
if __name__ == "__main__":
    init_db()

    webhook_url = f"https://{APP_NAME}.fly.dev/webhook"
    try:
        if bot.set_webhook(url=webhook_url, secret_token=WEBHOOK_SECRET):
            logger.info(f"✅ Telegram webhook set: {webhook_url}")
        else:
            logger.error("❌ Failed to set Telegram webhook!")
    except Exception as e:
        logger.error(f"Webhook setup error: {e}")

    register_handlers(dp, client)

    client.setConnectedCallback(connected)
    client.setDisconnectedCallback(disconnected)
    client.setMessageReceivedCallback(message_received)
    client.startService()

    logger.info(f"🚀 Starting HTTP server on port {APP_PORT}...")
    reactor.listenTCP(APP_PORT, Site(web_app.resource()))

    logger.info("✅ All services configured. Starting Twisted reactor...")
    reactor.run()
