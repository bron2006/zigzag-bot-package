# app.py
import logging
import os
import json
import time
from queue import Queue

from flask import Flask, jsonify, send_from_directory, Response, request
from gevent.pywsgi import WSGIServer
from gevent.queue import Queue as GeventQueue

# Local imports
import state
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

# This is a simple in-memory queue for SSE
# A more robust solution for multiple workers would be Redis Pub/Sub
signal_queue = GeventQueue()

INTERNAL_API_SECRET = os.getenv("INTERNAL_API_SECRET", "default-secret-for-local-dev")

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
    # Note: Authentication logic might need to be re-verified if it depends on the worker
    user_id = 1 # Dummy user_id for now, as auth context is complex
    watchlist = get_watchlist(user_id) if user_id else []
    forex_data = [{"title": f"{name} {TRADING_HOURS.get(name, '')}".strip(), "pairs": pairs} for name, pairs in FOREX_SESSIONS.items()]
    response_data = {"forex": forex_data, "crypto": CRYPTO_PAIRS, "stocks": STOCK_TICKERS, "commodities": COMMODITIES, "watchlist": watchlist}
    return jsonify(response_data)

# NEW: Internal route for the worker to post signals to
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
            # Wait for a signal from the queue
            signal = signal_queue.get()
            yield f"data: {json.dumps(signal, ensure_ascii=False)}\n\n"

    response = Response(generate(), mimetype='text/event-stream')
    response.headers['Cache-Control'] = 'no-cache'
    return response

# Note: The scanner toggle and other routes that modify state now need
# to communicate with the worker process, e.g., via a database flag or another internal API call.
# This is a simplification for now to get the core functionality working.

if __name__ == '__main__':
    # This is for local development only.
    # In production, Gunicorn will run the app.
    http_server = WSGIServer(('0.0.0.0', 8080), app)
    logger.info("Starting Flask server with Gevent for local development...")
    http_server.serve_forever()