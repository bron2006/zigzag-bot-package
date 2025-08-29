import logging
import os
import json
import time
import traceback
import itertools
import queue
from functools import wraps
from flask import Flask, jsonify, send_from_directory, Response, request, stream_with_context
from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackQueryHandler, CallbackContext

import crochet
crochet.setup()

import state
from auth import is_valid_init_data, get_user_id_from_init_data
from db import get_watchlist, toggle_watchlist
from spotware_connect import SpotwareConnect
from config import (
    TELEGRAM_BOT_TOKEN, get_ct_client_id, get_ct_client_secret,
    FOREX_SESSIONS, get_fly_app_name, CRYPTO_PAIRS, STOCK_TICKERS,
    COMMODITIES, TRADING_HOURS, IDEAL_ENTRY_THRESHOLD, SCANNER_COOLDOWN_SECONDS, get_chat_id
)
from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOASymbolsListRes

from twisted.internet import reactor
from twisted.internet.defer import Deferred
from twisted.internet.task import LoopingCall
import telegram_ui

from analysis import get_api_detailed_signal_data, PERIOD_MAP

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False

WEBAPP_DIR = os.path.join(os.path.dirname(__file__), "webapp")

_client_ready_deferred = None

def set_client_ready_deferred(d):
    global _client_ready_deferred
    _client_ready_deferred = d

def wait_client_ready():
    from twisted.internet.defer import succeed
    return _client_ready_deferred if _client_ready_deferred is not None else succeed(True)


def protected_route(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        init_data = request.args.get("initData")
        if not is_valid_init_data(init_data):
            logger.warning(f"Unauthorized API access attempt. Path: {request.path}")
            return jsonify({"success": False, "error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated_function

def scan_markets_wrapper():
    try:
        scan_markets()
    except Exception as e:
        logger.critical(f"SCANNER: CRITICAL FAILURE IN SCAN WRAPPER: {e}", exc_info=True)

@crochet.run_in_reactor
def scan_markets():
    if not state.SCANNER_ENABLED:
        return

    logger.info("SCANNER: Starting sequential market scan...")
    all_forex_pairs = list(set(itertools.chain.from_iterable(FOREX_SESSIONS.values())))
    chat_id = get_chat_id()

    if not chat_id:
        logger.warning("SCANNER: CHAT_ID is not set. Scanner will not send notifications.")
        
    def on_analysis_done(result, pair_name):
        try:
            if result.get("error"):
                return
            state.latest_analysis_cache[pair_name] = result
            score = result.get('bull_percentage', 50)
            if score >= IDEAL_ENTRY_THRESHOLD or score <= (100 - IDEAL_ENTRY_THRESHOLD):
                now = time.time()
                if (now - state.scanner_cooldown_cache.get(pair_name, 0)) > SCANNER_COOLDOWN_SECONDS:
                    logger.info(f"SCANNER: Ideal entry for {pair_name}. Notifying.")
                    state.sse_queue.put(result)
                    message = telegram_ui._format_signal_message(result, "5m")
                    keyboard = telegram_ui.get_main_menu_kb()
                    if chat_id:
                        state.updater.bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown', reply_markup=keyboard)
                    state.scanner_cooldown_cache[pair_name] = now
        except Exception as e:
            logger.error(f"SCANNER: Error processing result for {pair_name}: {e}", exc_info=True)

    def process_next_pair(result, pairs_to_scan):
        if not pairs_to_scan:
            logger.info("SCANNER: Sequential scan finished.")
            return
        
        pair = pairs_to_scan.pop(0)
        norm_pair = pair.replace("/", "")
        
        d = get_api_detailed_signal_data(state.client, state.symbol_cache, norm_pair, 0, "5m")
        d.addCallback(on_analysis_done, pair_name=norm_pair)
        d.addBoth(process_next_pair, pairs_to_scan=pairs_to_scan)
        return d

    process_next_pair(None, all_forex_pairs.copy())

# ... (решта коду до /api/signal-stream без змін) ...

@app.route("/api/signal")
@protected_route
def api_signal():
    pair = request.args.get("pair")
    if not pair:
        return jsonify({"error": "pair is required"}), 400
    
    pair_normalized = pair.replace("/", "")
    cached_result = state.latest_analysis_cache.get(pair_normalized)
    
    if cached_result:
        return jsonify(cached_result)
    else:
        return jsonify({
            "error": "Дані для цього активу ще аналізуються сканером. Спробуйте за хвилину."
        }), 404

@app.route("/api/scanner/status")
@protected_route
def get_scanner_status():
    return jsonify({"enabled": state.SCANNER_ENABLED})

@app.route("/api/scanner/toggle")
@protected_route
def toggle_scanner_status():
    state.SCANNER_ENABLED = not state.SCANNER_ENABLED
    logger.info(f"Scanner status toggled via API. New status: {state.SCANNER_ENABLED}")
    return jsonify({"enabled": state.SCANNER_ENABLED})


# --- ПОЧАТОК ЗМІН: Повністю переписаний signal_stream згідно з рекомендаціями експерта ---
@app.route("/api/signal-stream")
@protected_route
def signal_stream():
    def generate():
        while True:
            try:
                # Очікуємо на новий сигнал, але не довше 20 секунд
                signal_data = state.sse_queue.get(timeout=20)
                sse_data = f"data: {json.dumps(signal_data, ensure_ascii=False)}\n\n"
                yield sse_data
            except queue.Empty:
                # Якщо за 20 секунд нічого не прийшло, надсилаємо "ping", щоб зберегти з'єднання
                yield ": ping\n\n"
            except Exception as e:
                logger.error(f"SSE Stream error: {e}")
                # У разі помилки просто продовжуємо цикл
                continue

    # Створюємо відповідь з правильними заголовками, щоб уникнути буферизації
    response = Response(stream_with_context(generate()), mimetype='text/event-stream')
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['Connection'] = 'keep-alive'
    response.headers['X-Accel-Buffering'] = 'no'
    return response
# --- КІНЕЦЬ ЗМІН ---

if __name__ != "__main__":
    start_background_services()