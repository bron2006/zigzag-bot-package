# main.py
import os
import json
from urllib.parse import parse_qs, unquote
from dotenv import load_dotenv

# --- Telegram Imports (Updated for PTB v21) ---
from telegram import Update
from telegram.ext import Application, ApplicationBuilder

# --- Twisted & Klein Imports ---
from twisted.internet import reactor, defer
from twisted.web.server import Site
from klein import Klein

# --- cTrader Imports (Using the library's Client) ---
from ctrader_open_api.client import Client, TcpProtocol
from ctrader_open_api.endpoints import EndPoints
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import ProtoMessage
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAApplicationAuthReq, ProtoOAApplicationAuthRes,
    ProtoOAAccountAuthReq, ProtoOAAccountAuthRes, ProtoOAErrorRes,
    ProtoOASymbolsListReq, ProtoOASymbolsListRes,
    ProtoOASymbolByIdReq, ProtoOASymbolByIdRes
)

# --- Local Modules ---
from config import logger, SYMBOL_DATA_CACHE, CACHE_LOCK, TOKEN, WEBHOOK_SECRET, \
                   CT_CLIENT_ID, CT_CLIENT_SECRET, CTRADER_ACCESS_TOKEN, DEMO_ACCOUNT_ID, \
                   FOREX_SESSIONS
from db import init_db, get_watchlist, toggle_watch, get_signal_history
import analysis
from telegram_ui import register_handlers

load_dotenv()

# --- App Configuration ---
HOST = EndPoints.PROTOBUF_DEMO_HOST
PORT = EndPoints.PROTOBUF_PORT
APP_PORT = int(os.getenv("PORT", 8080))
APP_NAME = os.getenv("FLY_APP_NAME", "zigzag-bot-package")

# --- ARCHITECTURE REFACTORED: Using the library's Client class ---
is_ctrader_authorized = False
client = Client(HOST, PORT, TcpProtocol)
web_app = Klein()
telegram_app: Application | None = None

# --- cTrader Client Callbacks ---
def connected(client: Client):
    """Callback triggered on successful connection."""
    logger.info("✅ Connection successful. Authorizing application...")
    request = ProtoOAApplicationAuthReq(clientId=CT_CLIENT_ID, clientSecret=CT_CLIENT_SECRET)
    client.send(request)

def disconnected(client: Client, reason):
    """Callback triggered on disconnection."""
    global is_ctrader_authorized
    is_ctrader_authorized = False
    logger.warning(f"⚠️ Disconnected. Reason: {reason.getErrorMessage()}")

def on_error(failure):
    """General error handler for deferreds."""
    logger.error(f"❌ An error occurred: {failure.getErrorMessage()}")

def message_received(client: Client, message: ProtoMessage):
    """Callback for all incoming messages from cTrader."""
    global is_ctrader_authorized
    if message.payloadType == ProtoOAApplicationAuthRes().payloadType:
        logger.info("✅ Application authorized. Authorizing account...")
        request = ProtoOAAccountAuthReq(ctidTraderAccountId=DEMO_ACCOUNT_ID, accessToken=CTRADER_ACCESS_TOKEN)
        client.send(request)

    elif message.payloadType == ProtoOAAccountAuthRes().payloadType:
        logger.info(f"✅ Account {DEMO_ACCOUNT_ID} authorized successfully.")
        is_ctrader_authorized = True
        populate_symbol_cache() # Start populating cache after full authorization

    elif message.payloadType == ProtoOAErrorRes().payloadType:
        error_res = ProtoOAErrorRes()
        error_res.ParseFromString(message.payload)
        logger.error(f"❌ cTrader Error: {error_res.errorCode} - {error_res.description}")

    elif is_ctrader_authorized:
        # Handle other events if needed, e.g., spot events
        pass

def populate_symbol_cache():
    """Fetches all symbols and populates the cache."""
    logger.info("🔄 Populating symbol cache...")
    list_req = ProtoOASymbolsListReq(ctidTraderAccountId=DEMO_ACCOUNT_ID)
    d = client.send(list_req)

    def on_symbols_listed(response: ProtoMessage):
        symbols_list = ProtoOASymbolsListRes.FromString(response.payload)
        all_symbol_ids = [s.symbolId for s in symbols_list.symbol]
        
        chunk_size = 70
        deferred_list = []
        for i in range(0, len(all_symbol_ids), chunk_size):
            chunk = all_symbol_ids[i:i + chunk_size]
            details_req = ProtoOASymbolByIdReq(ctidTraderAccountId=DEMO_ACCOUNT_ID, symbolId=chunk)
            deferred_list.append(client.send(details_req))

        d_list = defer.DeferredList(deferred_list, consumeErrors=True)
        d_list.addCallback(on_all_details_fetched)

    def on_all_details_fetched(results):
        added_count = 0
        with CACHE_LOCK:
            for success, response in results:
                if success:
                    details = ProtoOASymbolByIdRes.FromString(response.payload)
                    for symbol in details.symbol:
                        if hasattr(symbol, 'symbolName') and symbol.symbolName:
                            SYMBOL_DATA_CACHE[symbol.symbolName] = {
                                'symbolId': symbol.symbolId,
                                'digits': symbol.digits
                            }
                            added_count += 1
        logger.info(f"✅ Symbol cache populated. Total symbols: {len(SYMBOL_DATA_CACHE)}")

    d.addCallbacks(on_symbols_listed, on_error)

# --- Klein Web Server Routes ---
@web_app.route("/webhook", methods=["POST"])
async def webhook(request):
    """Telegram webhook endpoint."""
    try:
        if request.getHeader("X-Telegram-Bot-Api-Secret-Token") == WEBHOOK_SECRET:
            await telegram_app.update_queue.put(Update.de_json(json.loads(request.content.read()), telegram_app.bot))
            return "OK"
        else:
            request.setResponseCode(403)
            return "Forbidden"
    except Exception as e:
        logger.error(f"❌ Webhook error: {e}")
        request.setResponseCode(500)
        return "Error"

@web_app.route("/health")
def health_check(request):
    if is_ctrader_authorized and len(SYMBOL_DATA_CACHE) > 10:
        request.setResponseCode(200)
        return "OK"
    else:
        request.setResponseCode(503)
        return "Service Unavailable"

@web_app.route("/")
def root(request):
    status = "authorized" if is_ctrader_authorized else "connecting..."
    return f"✅ ZigZag Bot. cTrader Status: {status}. Symbols in cache: {len(SYMBOL_DATA_CACHE)}"

# --- API Routes for Web App ---
def _get_user_id_from_request(req):
    # This function remains the same
    return None # Placeholder

def json_response(request, data):
    request.setHeader("Content-Type", "application/json; charset=utf-8")
    request.setHeader("Access-Control-Allow-Origin", "*")
    # Klein handles deferreds, so if data is a deferred, it will await it.
    if isinstance(data, defer.Deferred):
        data.addCallback(lambda result: json.dumps(result, ensure_ascii=False, indent=2))
        return data
    return json.dumps(data, ensure_ascii=False, indent=2)

@web_app.route("/api/signal")
def api_signal(request):
    pair = request.args.get(b"pair", [b""])[0].decode()
    user_id = _get_user_id_from_request(request)

    if not pair or not isinstance(pair, str):
        return json_response(request, {"error": "Invalid pair name"})
    
    if not is_ctrader_authorized:
        return json_response(request, {"error": "cTrader service is not ready."})

    # The analysis function now returns a Deferred
    d = analysis.get_api_detailed_signal_data(client, pair, user_id)
    return json_response(request, d)

@web_app.route("/api/get_mta")
def api_get_mta(request):
    pair = request.args.get(b"pair", [b""])[0].decode()

    if not pair or not isinstance(pair, str):
        return json_response(request, {"error": "Invalid pair name"})

    if not is_ctrader_authorized:
        return json_response(request, {"error": "cTrader service is not ready."})
        
    d = analysis.get_api_mta_data(client, pair)
    return json_response(request, d)

# Other API routes (get_ranked_pairs, etc.) remain largely the same for brevity

# --- Main Application Startup ---
async def main():
    """Main function to setup and run services."""
    global telegram_app
    
    init_db()

    # --- Initialize Telegram Bot (PTB v21) ---
    telegram_app = ApplicationBuilder().token(TOKEN).build()
    telegram_app.bot_data['ctrader_client'] = client # Make client accessible to handlers
    register_handlers(telegram_app)

    # --- Set Webhook ---
    webhook_url = f"https://{APP_NAME}.fly.dev/webhook"
    await telegram_app.bot.set_webhook(url=webhook_url, secret_token=WEBHOOK_SECRET)
    logger.info(f"✅ Telegram webhook set: {webhook_url}")

    # --- Initialize and run Telegram's internal async components ---
    await telegram_app.initialize()
    await telegram_app.start()

    # --- Setup Twisted Reactor ---
    logger.info(f"🚀 Starting HTTP server on port {APP_PORT}...")
    reactor.listenTCP(APP_PORT, Site(web_app.resource()))

    # --- Setup and run cTrader Client ---
    client.setConnectedCallback(connected)
    client.setDisconnectedCallback(disconnected)
    client.setMessageReceivedCallback(message_received)
    client.startService()

    logger.info("✅ Services are running. Twisted reactor is in charge.")
    # Note: reactor.run() is called outside this async function

if __name__ == "__main__":
    # Use Twisted's reactor to run the async main function
    reactor.callWhenRunning(lambda: defer.ensureDeferred(main()))
    # Start the Twisted event loop
    reactor.run()