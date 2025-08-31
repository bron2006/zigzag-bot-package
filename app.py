# app.py
import logging
import os
import json
import time
from gevent.queue import Queue as GeventQueue

from flask import Flask, jsonify, send_from_directory, Response, request
from gevent.pywsgi import WSGIServer

# Local imports
from auth import is_valid_init_data, get_user_id_from_init_data
from db import get_watchlist, toggle_watchlist
from config import (
    FOREX_SESSIONS, get_fly_app_name, CRYPTO_PAIRS, STOCK_TICKERS,
    COMMODITIES, TRADING_HOURS
)

# --- Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("webapp")

app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False
WEBAPP_DIR = os.path.join(os.path.dirname(__file__), "webapp")

signal_queue = GeventQueue()
INTERNAL_API_SECRET = os.getenv("INTERNAL_API_SECRET", "default-secret-for-local-dev")

# NEW: Paths for file-based communication
DATA_DIR = "/data"
SCANNER_ENABLED_FLAG_FILE = os.path.join(DATA_DIR, "scanner.enabled")
ANALYSIS_CACHE_FILE = os.path.join(DATA_DIR, "analysis_cache.json")

# --- Routes ---

@app.route("/")
def home():
    try:
        filepath = os.path.join(WEBAPP_DIR, 'index.html')
        with open(filepath, "r", encoding="utf-8") as f: content = f.read()
        app_name = get_fly_app_name() or "zigzag-bot-package"
        api_base_url = f"https://{app_name}.fly.dev"
        cache_buster = int(time.time())
        content = content.replace("{{API_BASE_URL}}", api_base_url)
        content = content.replace("script.js", f"script.js?v={cache_buster}")
        content = content.replace("style.css", f"style.css?v={cache_buster}")
        return Response(content, mimetype='text/html')
    except Exception as e:
        logger.error(f"Error serving index.html: {e}", exc_info=True)
        return "Internal Server Error", 500

@app.route("/<path:filename>")
def static_files(filename):
    return send_from_directory(WEBAPP_DIR, filename)

@app.route("/api/get_pairs")
def get_pairs():
    # This remains simplified as auth logic needs deeper integration if required
    user_id = 1 
    watchlist = get_watchlist(user_id) if user_id else []
    forex_data = [{"title": f"{name} {TRADING_HOURS.get(name, '')}".strip(), "pairs": pairs} for name, pairs in FOREX_SESSIONS.items()]
    response_data = {"forex": forex_data, "crypto": CRYPTO_PAIRS, "stocks": STOCK_TICKERS, "commodities": COMMODITIES, "watchlist": watchlist}
    return jsonify(response_data)

@app.route("/internal/notify_signal", methods=['POST'])
def notify_signal():
    if request.headers.get("X-Internal-Secret") != INTERNAL_API_SECRET:
        return "Forbidden", 403
    
    signal_data = request.json
    if signal_data:
        logger.info(f"Received signal from worker: {signal_data.get('pair')}")
        signal_queue.put(signal_data)
    return "OK", 200

@app.route("/api/signal-stream")
def signal_stream():
    def generate():
        while True:
            signal = signal_queue.get()
            yield f"data: {json.dumps(signal, ensure_ascii=False)}\n\n"

    response = Response(generate(), mimetype='text/event-stream')
    response.headers['Cache-Control'] = 'no-cache'
    return response

# RE-IMPLEMENTED: Scanner control and manual signal endpoints
@app.route("/api/scanner/status")
def get_scanner_status():
    is_enabled = os.path.exists(SCANNER_ENABLED_FLAG_FILE)
    return jsonify({"enabled": is_enabled})

@app.route("/api/scanner/toggle")
def toggle_scanner_status():
    is_enabled = os.path.exists(SCANNER_ENABLED_FLAG_FILE)
    try:
        if is_enabled:
            os.remove(SCANNER_ENABLED_FLAG_FILE)
            logger.info("Scanner DISABLED via API.")
            return jsonify({"enabled": False})
        else:
            open(SCANNER_ENABLED_FLAG_FILE, 'a').close()
            logger.info("Scanner ENABLED via API.")
            return jsonify({"enabled": True})
    except IOError as e:
        logger.error(f"Error toggling scanner status file: {e}")
        return jsonify({"error": "Failed to change scanner state"}), 500

@app.route("/api/signal")
def api_signal():
    pair_normalized = (request.args.get("pair") or "").replace("/", "")
    if not pair_normalized:
        return jsonify({"error": "pair is required"}), 400
    
    try:
        with open(ANALYSIS_CACHE_FILE, 'r', encoding='utf-8') as f:
            cache = json.load(f)
        
        signal_data = cache.get(pair_normalized)
        if signal_data:
            return jsonify(signal_data)
        else:
            return jsonify({"error": "Дані для цього активу ще аналізуються сканером. Спробуйте за хвилину."}), 404
    except (IOError, json.JSONDecodeError) as e:
        logger.error(f"Could not read or parse analysis cache file: {e}")
        return jsonify({"error": "Сервіс аналітики тимчасово недоступний."}), 503

if __name__ == '__main__':
    http_server = WSGIServer(('0.0.0.0', 8080), app)
    logger.info("Starting Flask server with Gevent for local development...")
    http_server.serve_forever()