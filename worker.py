# worker.py
import logging
import os
import json
import time
import itertools

from twisted.internet import reactor, threads
from twisted.internet.defer import inlineCallbacks
from twisted.internet.task import LoopingCall
from twisted.web.server import Site, NOT_DONE_YET
from klein import Klein

from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackQueryHandler

import state
import telegram_ui
from spotware_connect import SpotwareConnect
from config import *
from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOASymbolsListRes
from analysis import get_api_detailed_signal_data

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("worker")

DATA_DIR = "/data"
if not os.path.exists(DATA_DIR): os.makedirs(DATA_DIR)

SCANNER_STATE_FILE = os.path.join(DATA_DIR, "scanner_state.json")

def get_scanner_state():
    try:
        with open(SCANNER_STATE_FILE, 'r') as f: return json.load(f)
    except: return {"forex": False, "crypto": False, "metals": False}

def save_scanner_state(state_data):
    with open(SCANNER_STATE_FILE, 'w') as f: json.dump(state_data, f)

save_scanner_state({"forex": False, "crypto": False, "metals": False})

internal_api = Klein()
sse_clients = []

def broadcast_sse_signal(signal_data):
    sse_formatted_data = f"data: {json.dumps(signal_data, ensure_ascii=False)}\n\n".encode('utf-8')
    for client_request in list(sse_clients):
        reactor.callFromThread(client_request.write, sse_formatted_data)

def scan_assets(asset_type, asset_list):
    if not get_scanner_state().get(asset_type, False): return
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
        current_analysis_batch = {}
        for pair in asset_list:
            norm_pair = pair.replace("/", "")
            try:
                result = yield get_api_detailed_signal_data(state.client, state.symbol_cache, norm_pair, 0, "5m")
                if not result.get("error"):
                    current_analysis_batch[norm_pair] = result
                on_analysis_done(result, norm_pair)
            except Exception as e:
                logger.error(f"SCANNER ({asset_type.upper()}): Error analyzing {norm_pair}: {e}")
        
        try:
            with open(os.path.join(DATA_DIR, "analysis_cache.json"), 'w', encoding='utf-8') as f:
                json.dump(current_analysis_batch, f, ensure_ascii=False, indent=4)
            logger.info(f"SCANNER: Successfully updated analysis cache file.")
        except IOError as e:
            logger.error(f"SCANNER: Failed to write to analysis cache file: {e}")

        logger.info(f"SCANNER ({asset_type.upper()}): Scan finished.")
    threads.deferToThread(process_all_pairs)

def on_ctrader_ready():
    logger.info("cTrader client ready. Loading symbols...")
    d = state.client.get_all_symbols()
    d.addCallbacks(on_symbols_loaded, lambda f: logger.error(f"Failed to load symbols: {f}"))

def on_symbols_loaded(raw_message):
    symbols_response = ProtoOASymbolsListRes()
    symbols_response.ParseFromString(raw_message.payload)
    state.symbol_cache = {s.symbolName.replace("/", ""): s for s in symbols_response.symbol}
    logger.info(f"✅ Loaded {len(state.symbol_cache)} symbols.")
    
    all_forex = list(set(itertools.chain.from_iterable(FOREX_SESSIONS.values())))
    LoopingCall(scan_assets, "forex", all_forex).start(90)
    LoopingCall(scan_assets, "crypto", CRYPTO_PAIRS).start(60)
    LoopingCall(scan_assets, "metals", COMMODITIES).start(120)

@internal_api.route("/status", methods=['GET'])
def get_status(request):
    request.setHeader('Content-Type', 'application/json')
    return json.dumps(get_scanner_state())

# MODIFIED: Renamed from /get_assets to /get_pairs
@internal_api.route("/get_pairs", methods=['GET'])
def get_pairs(request):
    request.setHeader('Content-Type', 'application/json')
    # This data is needed by the web UI to build the asset lists
    return json.dumps({
        "forex_sessions": FOREX_SESSIONS, "crypto": CRYPTO_PAIRS,
        "stocks": STOCK_TICKERS, "commodities": COMMODITIES,
        "trading_hours": TRADING_HOURS
    })

@internal_api.route("/toggle_scanner", methods=['POST'])
def toggle_scanner(request):
    content = json.loads(request.content.read())
    scanner_type = content.get('type')
    if scanner_type not in ["forex", "crypto", "metals"]:
        request.setResponseCode(400); return json.dumps({"success": False, "error": "Invalid scanner type"})
    
    current_state = get_scanner_state()
    current_state[scanner_type] = not current_state.get(scanner_type, False)
    save_scanner_state(current_state)
    logger.info(f"Toggled scanner '{scanner_type}' to {current_state[scanner_type]}")
    request.setHeader('Content-Type', 'application/json')
    return json.dumps({"success": True, "newState": current_state})

@internal_api.route("/analyze", methods=['GET'])
@inlineCallbacks
def analyze_on_demand(request):
    pair_list = request.args.get(b"pair")
    pair = pair_list[0].decode('utf-8') if pair_list else None
    timeframe_list = request.args.get(b"timeframe")
    timeframe = timeframe_list[0].decode('utf-8') if timeframe_list else "5m"
    request.setHeader('Content-Type', 'application/json; charset=utf-8')
    if not pair:
        request.setResponseCode(400); return json.dumps({"error": "pair is required"})
    try:
        norm_pair = pair.replace("/", "")
        logger.info(f"On-demand analysis for {norm_pair}")
        result = yield get_api_detailed_signal_data(state.client, state.symbol_cache, norm_pair, 0, timeframe)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        request.setResponseCode(500); return json.dumps({"error": "Internal analysis error"})

@internal_api.route("/signal-stream", methods=['GET'])
def signal_stream(request):
    request.setHeader(b'Content-Type', b'text/event-stream; charset=utf-8')
    request.setHeader(b'Cache-Control', b'no-cache')
    request.setHeader(b'Connection', b'keep-alive')
    sse_clients.append(request)
    request.notifyFinish().addBoth(lambda _: sse_clients.remove(request) if request in sse_clients else None)
    return NOT_DONE_YET

if __name__ == "__main__":
    logger.info("Starting worker process...")
    
    site = Site(internal_api.resource())
    reactor.listenTCP(8081, site, interface="0.0.0.0")
    logger.info("Internal API server listening on port 8081...")

    updater = Updater(token=TELEGRAM_BOT_TOKEN, use_context=True)
    state.updater = updater
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", telegram_ui.start))
    dp.add_handler(CommandHandler("symbols", telegram_ui.symbols_command))
    dp.add_handler(MessageHandler(Filters.text("МЕНЮ"), telegram_ui.menu))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, telegram_ui.reset_ui))
    dp.add_handler(CallbackQueryHandler(telegram_ui.button_handler))

    reactor.callInThread(updater.start_polling)
    logger.info("Telegram bot scheduled to start.")
    
    client = SpotwareConnect(get_ct_client_id(), get_ct_client_secret())
    state.client = client
    client.on("ready", on_ctrader_ready)
    reactor.callWhenRunning(client.start)
    logger.info("cTrader client scheduled to start.")
    
    logger.info("Starting Twisted reactor...")
    reactor.run()