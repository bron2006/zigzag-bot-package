# worker.py
import logging
import os
import json
import time
import itertools

from twisted.internet import reactor, threads
from twisted.internet.defer import Deferred, inlineCallbacks
from twisted.internet.task import LoopingCall
from twisted.web.server import Site, NOT_DONE_YET
from klein import Klein

from telegram.ext import Updater, CommandHandler

import state
import telegram_ui
from spotware_connect import SpotwareConnect
from config import (
    TELEGRAM_BOT_TOKEN, get_ct_client_id, get_ct_client_secret,
    CRYPTO_PAIRS, FOREX_SESSIONS, COMMODITIES,
    IDEAL_ENTRY_THRESHOLD, SCANNER_COOLDOWN_SECONDS, get_chat_id
)
from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOASymbolsListRes
from analysis import get_api_detailed_signal_data

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("worker")

DATA_DIR = "/data"
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

# --- State Management ---
SCANNER_STATE_FILE = os.path.join(DATA_DIR, "scanner_state.json")

def get_scanner_state():
    try:
        with open(SCANNER_STATE_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"forex": False, "crypto": False, "metals": False}

def save_scanner_state(state_data):
    with open(SCANNER_STATE_FILE, 'w') as f:
        json.dump(state_data, f)

# Set initial state to OFF
save_scanner_state({"forex": False, "crypto": False, "metals": False})


# --- Internal API (Klein) ---
internal_api = Klein()
sse_clients = []

def broadcast_sse_signal(signal_data):
    sse_formatted_data = f"data: {json.dumps(signal_data, ensure_ascii=False)}\n\n".encode('utf-8')
    for client_request in list(sse_clients):
        reactor.callFromThread(client_request.write, sse_formatted_data)

# --- Scanner Logic ---
def scan_assets(asset_type, asset_list):
    state_data = get_scanner_state()
    if not state_data.get(asset_type, False):
        return
        
    logger.info(f"SCANNER ({asset_type.upper()}): Starting scan...")
    chat_id = get_chat_id()

    def on_analysis_done(result, pair_name):
        try:
            if not result.get("error"):
                score = result.get('bull_percentage', 50)
                if score >= IDEAL_ENTRY_THRESHOLD or score <= (100 - IDEAL_ENTRY_THRESHOLD):
                    now = time.time()
                    cooldown_key = f"{pair_name}_{asset_type}"
                    if (now - state.scanner_cooldown_cache.get(cooldown_key, 0)) > SCANNER_COOLDOWN_SECONDS:
                        logger.info(f"SCANNER ({asset_type.upper()}): Ideal entry for {pair_name}. Notifying.")
                        broadcast_sse_signal(result)
                        if chat_id:
                            message = telegram_ui._format_signal_message(result, "5m")
                            state.updater.bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown')
                        state.scanner_cooldown_cache[cooldown_key] = now
        except Exception as e:
            logger.error(f"SCANNER ({asset_type.upper()}): Error in on_analysis_done for {pair_name}: {e}", exc_info=True)

    @inlineCallbacks
    def process_all_pairs():
        for pair in asset_list:
            norm_pair = pair.replace("/", "")
            try:
                result = yield get_api_detailed_signal_data(state.client, state.symbol_cache, norm_pair, 0, "5m")
                on_analysis_done(result, norm_pair)
            except Exception as e:
                logger.error(f"SCANNER ({asset_type.upper()}): Error analyzing {norm_pair}: {e}")
        logger.info(f"SCANNER ({asset_type.upper()}): Scan finished.")

    threads.deferToThread(process_all_pairs)

# --- cTrader Event Handlers ---
def on_ctrader_ready():
    logger.info("cTrader client is ready. Loading symbols...")
    d = state.client.get_all_symbols()
    d.addCallbacks(on_symbols_loaded, on_symbols_error)

def on_symbols_loaded(raw_message):
    try:
        symbols_response = ProtoOASymbolsListRes()
        symbols_response.ParseFromString(raw_message.payload)
        state.symbol_cache = {s.symbolName.replace("/", ""): s for s in symbols_response.symbol}
        state.SYMBOLS_LOADED = True
        logger.info(f"✅ Successfully loaded {len(state.symbol_cache)} light symbols.")
        
        # Start separate scanner loops
        all_forex = list(set(itertools.chain.from_iterable(FOREX_SESSIONS.values())))
        LoopingCall(scan_assets, "forex", all_forex).start(90)
        LoopingCall(scan_assets, "crypto", CRYPTO_PAIRS).start(60)
        LoopingCall(scan_assets, "metals", COMMODITIES).start(120)

    except Exception as e:
        logger.error(f"Symbol processing error: {e}", exc_info=True)

def on_symbols_error(failure):
    logger.error(f"Failed to load symbols: {failure.getErrorMessage()}")

# --- Internal API Routes ---
@internal_api.route("/status", methods=['GET'])
def get_status(request):
    request.setHeader('Content-Type', 'application/json')
    return json.dumps(get_scanner_state())

@internal_api.route("/toggle_scanner", methods=['POST'])
def toggle_scanner(request):
    try:
        content = json.loads(request.content.read())
        scanner_type = content.get('type')
        if scanner_type not in ["forex", "crypto", "metals"]:
            request.setResponseCode(400)
            return json.dumps({"success": False, "error": "Invalid scanner type"})
        
        current_state = get_scanner_state()
        current_state[scanner_type] = not current_state.get(scanner_type, False)
        save_scanner_state(current_state)
        
        logger.info(f"Toggled scanner '{scanner_type}' to {current_state[scanner_type]}")
        request.setHeader('Content-Type', 'application/json')
        return json.dumps({"success": True, "newState": current_state})
    except Exception as e:
        request.setResponseCode(500)
        return json.dumps({"success": False, "error": str(e)})

@internal_api.route("/analyze", methods=['GET'])
@inlineCallbacks
def analyze_on_demand(request):
    pair_list = request.args.get(b"pair")
    pair = pair_list[0].decode('utf-8') if pair_list else None
    
    request.setHeader('Content-Type', 'application/json; charset=utf-8')
    if not pair:
        request.setResponseCode(400)
        return json.dumps({"error": "pair is required"})

    try:
        norm_pair = pair.replace("/", "")
        logger.info(f"On-demand analysis requested for {norm_pair}")
        result = yield get_api_detailed_signal_data(state.client, state.symbol_cache, norm_pair, 0, "5m")
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error during on-demand analysis for {pair}: {e}", exc_info=True)
        request.setResponseCode(500)
        return json.dumps({"error": "Internal analysis error"})

@internal_api.route("/signal-stream", methods=['GET'])
def signal_stream(request):
    request.setHeader(b'Content-Type', b'text/event-stream; charset=utf-8')
    request.setHeader(b'Cache-Control', b'no-cache')
    request.setHeader(b'Connection', b'keep-alive')
    
    sse_clients.append(request)
    logger.info(f"SSE client connected. Total clients: {len(sse_clients)}")

    def on_disconnect(_):
        if request in sse_clients:
            sse_clients.remove(request)
        logger.info(f"SSE client disconnected. Total clients: {len(sse_clients)}")

    request.notifyFinish().addErrback(on_disconnect)
    return NOT_DONE_YET

# --- Main Worker Startup ---
if __name__ == "__main__":
    logger.info("Starting worker process...")
    
    # 1. Start internal API server
    site = Site(internal_api.resource())
    reactor.listenTCP(8081, site, interface="0.0.0.0")
    logger.info("Internal API server listening on port 8081...")

    # 2. Initialize and start Telegram Bot
    updater = Updater(token=TELEGRAM_BOT_TOKEN, use_context=True)
    state.updater = updater
    # ... Add your Telegram handlers here ...
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", telegram_ui.start)) # Example
    
    reactor.callInThread(updater.start_polling)
    logger.info("Telegram bot scheduled to start.")
    
    # 3. Initialize and start cTrader Client
    client = SpotwareConnect(get_ct_client_id(), get_ct_client_secret())
    state.client = client
    client.on("ready", on_ctrader_ready)
    reactor.callWhenRunning(client.start)
    logger.info("cTrader client scheduled to start.")
    
    # 4. Start the main event loop
    logger.info("Starting Twisted reactor...")
    reactor.run()