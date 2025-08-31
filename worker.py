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
from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackQueryHandler, CallbackContext

# Local imports
import state
import telegram_ui
from spotware_connect import SpotwareConnect
from config import (
    TELEGRAM_BOT_TOKEN, get_ct_client_id, get_ct_client_secret,
    FOREX_SESSIONS, CRYPTO_PAIRS,
    IDEAL_ENTRY_THRESHOLD, SCANNER_COOLDOWN_SECONDS, get_chat_id
)
from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOASymbolsListRes
from analysis import get_api_detailed_signal_data

# --- Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("worker")

INTERNAL_API_URL = "http://localhost:8080/internal/notify_signal"
INTERNAL_API_SECRET = os.getenv("INTERNAL_API_SECRET", "default-secret-for-local-dev")


# --- Scanner Logic ---
def scan_markets():
    with state.scanner_lock:
        is_enabled = state.SCANNER_ENABLED
    
    if not is_enabled:
        return

    logger.info("SCANNER: Starting sequential market scan...")
    assets_to_scan = CRYPTO_PAIRS
    logger.info(f"SCANNER: Weekend mode. Scanning crypto pairs: {assets_to_scan}")
    
    chat_id = get_chat_id()
        
    def on_analysis_done(result, pair_name):
        try:
            if not result.get("error"):
                score = result.get('bull_percentage', 50)
                if score >= IDEAL_ENTRY_THRESHOLD or score <= (100 - IDEAL_ENTRY_THRESHOLD):
                    now = time.time()
                    if (now - state.scanner_cooldown_cache.get(pair_name, 0)) > SCANNER_COOLDOWN_SECONDS:
                        logger.info(f"SCANNER: Ideal entry for {pair_name}. Notifying.")
                        
                        # 1. Send to Telegram
                        if chat_id:
                            message = telegram_ui._format_signal_message(result, "5m")
                            keyboard = telegram_ui.get_main_menu_kb()
                            state.updater.bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown', reply_markup=keyboard)
                        
                        # 2. Send to Web App via internal HTTP request
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
                # Pass a dummy user_id (0) for scanner-generated signals
                result = yield get_api_detailed_signal_data(state.client, state.symbol_cache, norm_pair, 0, "5m")
                on_analysis_done(result, norm_pair)
            except Exception as e:
                logger.error(f"SCANNER: Error analyzing {norm_pair}: {e}")
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
    # 1. Initialize Telegram Bot
    updater = Updater(token=TELEGRAM_BOT_TOKEN, use_context=True)
    state.updater = updater
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", telegram_ui.start))
    # Add other handlers if they need to work in the worker
    
    reactor.callInThread(updater.start_polling)
    logger.info("Telegram bot scheduled to start in a background thread.")
    
    # 2. Initialize cTrader Client
    client = SpotwareConnect(get_ct_client_id(), get_ct_client_secret())
    state.client = client
    client.on("ready", on_ctrader_ready)
    reactor.callWhenRunning(client.start)
    logger.info("cTrader client scheduled to start.")
    
    # 3. Start the Twisted reactor
    logger.info("Starting Twisted reactor for cTrader client and scanner...")
    reactor.run()