# worker.py
import logging
import os
import json
import time
import itertools
import requests

# Twisted imports
from twisted.internet import reactor, threads
from twisted.internet.defer import Deferred, inlineCallbacks
from twisted.internet.task import LoopingCall

# Telegram imports
from telegram.ext import Updater, CommandHandler

# Local imports
import state
import telegram_ui
from spotware_connect import SpotwareConnect
from config import (
    TELEGRAM_BOT_TOKEN, get_ct_client_id, get_ct_client_secret,
    CRYPTO_PAIRS, IDEAL_ENTRY_THRESHOLD, SCANNER_COOLDOWN_SECONDS, get_chat_id
)
from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOASymbolsListRes
from analysis import get_api_detailed_signal_data

# --- Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("worker")

INTERNAL_API_URL = "http://localhost:8080/internal/notify_signal"
INTERNAL_API_SECRET = os.getenv("INTERNAL_API_SECRET", "default-secret-for-local-dev")

# NEW: Paths for file-based communication
DATA_DIR = "/data"
SCANNER_ENABLED_FLAG_FILE = os.path.join(DATA_DIR, "scanner.enabled")
ANALYSIS_CACHE_FILE = os.path.join(DATA_DIR, "analysis_cache.json")

# --- Scanner Logic ---
def scan_markets():
    # MODIFIED: State is now checked from the flag file
    is_enabled = os.path.exists(SCANNER_ENABLED_FLAG_FILE)
    
    if not is_enabled:
        logger.info("SCANNER: Scanner is disabled via flag file. Skipping scan.")
        return

    logger.info("SCANNER: Starting sequential market scan...")
    assets_to_scan = CRYPTO_PAIRS
    current_analysis_batch = {}
    chat_id = get_chat_id()
        
    def on_analysis_done(result, pair_name):
        try:
            if not result.get("error"):
                # Store result for batch write
                current_analysis_batch[pair_name] = result

                score = result.get('bull_percentage', 50)
                if score >= IDEAL_ENTRY_THRESHOLD or score <= (100 - IDEAL_ENTRY_THRESHOLD):
                    now = time.time()
                    if (now - state.scanner_cooldown_cache.get(pair_name, 0)) > SCANNER_COOLDOWN_SECONDS:
                        logger.info(f"SCANNER: Ideal entry for {pair_name}. Notifying.")
                        
                        if chat_id:
                            message = telegram_ui._format_signal_message(result, "5m")
                            keyboard = telegram_ui.get_main_menu_kb()
                            state.updater.bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown', reply_markup=keyboard)
                        
                        try:
                            requests.post(INTERNAL_API_URL, json=result, headers={"X-Internal-Secret": INTERNAL_API_SECRET}, timeout=5)
                        except requests.RequestException as e:
                            logger.error(f"Failed to notify web app about signal for {pair_name}: {e}")

                        state.scanner_cooldown_cache[pair_name] = now
        except Exception as e:
            logger.error(f"SCANNER: Error in on_analysis_done for {pair_name}: {e}", exc_info=True)

    @inlineCallbacks
    def process_all_pairs():
        for pair in assets_to_scan:
            norm_pair = pair.replace("/", "")
            try:
                result = yield get_api_detailed_signal_data(state.client, state.symbol_cache, norm_pair, 0, "5m")
                on_analysis_done(result, norm_pair)
            except Exception as e:
                logger.error(f"SCANNER: Error analyzing {norm_pair}: {e}")
        
        # After scanning all pairs, write the results to the cache file
        try:
            with open(ANALYSIS_CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(current_analysis_batch, f, ensure_ascii=False, indent=4)
            logger.info(f"SCANNER: Successfully updated analysis cache file with {len(current_analysis_batch)} pairs.")
        except IOError as e:
            logger.error(f"SCANNER: Failed to write to analysis cache file: {e}")

        logger.info("SCANNER: Sequential scan finished.")

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
        
        scanner_loop = LoopingCall(scan_markets)
        scanner_loop.start(60, now=True)
    except Exception as e:
        logger.error(f"Symbol processing error: {e}", exc_info=True)

def on_symbols_error(failure):
    logger.error(f"Failed to load symbols: {failure.getErrorMessage()}")

# --- Main Worker Startup ---
if __name__ == "__main__":
    logger.info("Starting worker process...")

    # FIX: Ensure data directory exists
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)

    # FIX: Set default scanner state to OFF
    if os.path.exists(SCANNER_ENABLED_FLAG_FILE):
        os.remove(SCANNER_ENABLED_FLAG_FILE)
    logger.info("Set initial scanner state to DISABLED.")
    
    # Initialize an empty cache file on startup
    with open(ANALYSIS_CACHE_FILE, 'w') as f:
        json.dump({}, f)

    updater = Updater(token=TELEGRAM_BOT_TOKEN, use_context=True)
    state.updater = updater
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", telegram_ui.start))
    
    reactor.callInThread(updater.start_polling)
    logger.info("Telegram bot scheduled to start in a background thread.")
    
    client = SpotwareConnect(get_ct_client_id(), get_ct_client_secret())
    state.client = client
    client.on("ready", on_ctrader_ready)
    reactor.callWhenRunning(client.start)
    logger.info("cTrader client scheduled to start.")
    
    logger.info("Starting Twisted reactor for cTrader client and scanner...")
    reactor.run()