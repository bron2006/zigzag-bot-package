# app.py

# --- GEVENT PATCHING (MUST BE AT THE VERY TOP) ---
from gevent import monkey
monkey.patch_all()

import logging
import os
import json
import time
import itertools
from queue import Queue
from threading import Lock

from flask import Flask, jsonify, send_from_directory, Response, request
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackQueryHandler
import crochet # NEW: To run Twisted in a background thread

# Local imports
import state # We will use it for in-memory state
import telegram_ui
from spotware_connect import SpotwareConnect
from config import *
from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOASymbolsListRes
from analysis import get_api_detailed_signal_data

# --- Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
crochet.setup() # Initialize crochet

app = Flask(__name__)
WEBAPP_DIR = os.path.join(app.root_path, "webapp")

# --- Shared State ---
sse_queue = Queue()
scanner_state = {"forex": False, "crypto": False, "metals": False}
scanner_state_lock = Lock()

DATA_DIR = "/data"
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

# --- Background cTrader/Scanner/Telegram Logic ---

def broadcast_sse_signal(signal_data):
    sse_queue.put(signal_data)

@crochet.run_in_reactor
def scan_assets(asset_type, asset_list):
    with scanner_state_lock:
        is_enabled = scanner_state.get(asset_type, False)
    if not is_enabled: return

    logger.info(f"SCANNER ({asset_type.upper()}): Starting scan...")
    chat_id = get_chat_id()

    @inlineCallbacks
    def process_all_pairs():
        for pair in asset_list:
            norm_pair = pair.replace("/", "")
            try:
                result = yield get_api_detailed_signal_data(state.client, state.symbol_cache, norm_pair, 0, "5m")
                
                # The rest of the analysis logic from your file
                score = result.get('bull_percentage', 50)
                if score >= IDEAL_ENTRY_THRESHOLD or score <= (100 - IDEAL_ENTRY_THRESHOLD):
                    now = time.time()
                    cooldown_key = f"{norm_pair}_{asset_type}"
                    if (now - state.scanner_cooldown_cache.get(cooldown_key, 0)) > SCANNER_COOLDOWN_SECONDS:
                        logger.info(f"SCANNER ({asset_type.upper()}): Ideal entry for {norm_pair}. Notifying.")
                        broadcast_sse_signal(result)
                        if chat_id:
                            message = telegram_ui._format_signal_message(result, "5m")
                            state.updater.bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown')
                        state.scanner_cooldown_cache[cooldown_key] = now
            except Exception as e:
                logger.error(f"SCANNER ({asset_type.upper()}): Error analyzing {norm_pair}: {e}")
        logger.info(f"SCANNER ({asset_type.upper()}): Scan finished.")
    
    process_all_pairs()


@crochet.run_in_reactor
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
    
    # Use Twisted's LoopingCall from within the reactor thread, started via crochet
    @crochet.run_in_reactor
    def start_scanners():
        LoopingCall(scan_assets, "forex", all_forex).start(90)
        LoopingCall(scan_assets, "crypto", CRYPTO_PAIRS).start(60)
        LoopingCall(scan_assets, "metals", COMMODITIES).start(120)

    start_scanners()

# --- Flask Routes ---
@app.route("/")
def home():
    return send_from_directory(WEBAPP_DIR, 'index.html')

@app.route("/<path:filename>")
def static_files(filename):
    return send_from_directory(WEBAPP_DIR, filename)

@app.route("/api/get_pairs")
def get_pairs():
    forex_data = [{"title": f"{name} {TRADING_HOURS.get(name, '')}".strip(), "pairs": pairs} for name, pairs in FOREX_SESSIONS.items()]
    response_data = {"forex": forex_data, "crypto": CRYPTO_PAIRS, "stocks": STOCK_TICKERS, "commodities": COMMODITIES}
    return jsonify(response_data)

@app.route("/api/scanner/status")
def get_scanner_status():
    with scanner_state_lock:
        return jsonify(scanner_state)

@app.route("/api/scanner/toggle", methods=['POST'])
def toggle_scanner():
    scanner_type = request.json.get('type')
    if scanner_type not in scanner_state:
        return jsonify({"error": "Invalid scanner type"}), 400
    with scanner_state_lock:
        scanner_state[scanner_type] = not scanner_state[scanner_type]
        logger.info(f"Toggled scanner '{scanner_type}' to {scanner_state[scanner_type]}")
        return jsonify({"success": True, "newState": scanner_state})

@app.route("/api/signal")
def api_signal():
    pair = request.args.get("pair")
    timeframe = request.args.get("timeframe", "5m")
    if not pair:
        return jsonify({"error": "pair is required"}), 400
    
    logger.info(f"On-demand analysis for {pair}")
    
    # Use crochet.wait_for to call the async function and wait for its result
    @crochet.wait_for(timeout=20.0)
    def run_analysis():
        return get_api_detailed_signal_data(state.client, state.symbol_cache, pair.replace('/',''), 0, timeframe)
    
    try:
        result = run_analysis()
        return jsonify(result)
    except Exception as e:
        logger.error(f"On-demand analysis for {pair} failed: {e}")
        return jsonify({"error": "Analysis failed or timed out."}), 500


@app.route("/api/signal-stream")
def signal_stream():
    def generate():
        while True:
            signal = sse_queue.get()
            yield f"data: {json.dumps(signal, ensure_ascii=False)}\n\n"
    return Response(generate(), mimetype='text/event-stream')

# --- Application Startup ---
def start_background_services():
    logger.info("Starting background services...")
    # 1. Initialize Telegram Bot
    updater = Updater(token=TELEGRAM_BOT_TOKEN, use_context=True)
    state.updater = updater
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", telegram_ui.start))
    dp.add_handler(CallbackQueryHandler(telegram_ui.button_handler))
    
    # Run the bot in a separate, non-blocking thread
    bot_thread = threading.Thread(target=updater.start_polling)
    bot_thread.daemon = True
    bot_thread.start()
    logger.info("Telegram bot has started.")
    
    # 2. Initialize cTrader Client in the Crochet/Twisted background thread
    client = SpotwareConnect(get_ct_client_id(), get_ct_client_secret())
    state.client = client
    client.on("ready", on_ctrader_ready)
    
    @crochet.run_in_reactor
    def start_ctrader_client():
        client.start()
    
    start_ctrader_client()
    logger.info("cTrader client scheduled to start.")


# MODIFIED: Removed @app.before_first_request and call the startup function directly.
# This code runs once when the Gunicorn worker process is initialized.
start_background_services()


if __name__ == '__main__':
    # This block is for local development only and is not used by Gunicorn
    app.run(host='0.0.0.0', port=8080, debug=True)