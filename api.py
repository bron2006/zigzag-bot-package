import os
import json
import time
import queue
import logging
from functools import wraps
from flask import jsonify, send_from_directory, Response, request, stream_with_context

from state import app_state
import db
from auth import is_valid_init_data, get_user_id_from_init_data
import analysis as analysis_module
import ml_models
from config import (
    FOREX_SESSIONS, get_fly_app_name, CRYPTO_PAIRS, STOCK_TICKERS,
    COMMODITIES, TRADING_HOURS
)

logger = logging.getLogger("api")
get_api_detailed_signal_data = analysis_module.get_api_detailed_signal_data
WEBAPP_DIR = os.path.join(os.path.dirname(__file__), "webapp")

def register_routes(app):
    
    def protected_route(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            init_data = request.args.get("initData")
            if not is_valid_init_data(init_data):
                logger.warning(f"Unauthorized API access: {request.path}")
                return jsonify({"success": False, "error": "Unauthorized"}), 401
            return f(*args, **kwargs)
        return decorated_function

    @app.route("/")
    def home():
        try:
            index_path = os.path.join(WEBAPP_DIR, "index.html")
            if os.path.exists(index_path):
                with open(index_path, "r", encoding="utf-8") as f:
                    content = f.read()
                app_name = get_fly_app_name() or "zigzag-bot-package"
                api_base_url = f"https://{app_name}.fly.dev"
                content = content.replace("{{API_BASE_URL}}", api_base_url)
                cache_buster = int(time.time())
                content = content.replace("script.js", f"script.js?v={cache_buster}")
                content = content.replace("style.css", f"style.css?v={cache_buster}")
                return Response(content, mimetype='text/html')
            return "Web UI not found", 404
        except Exception:
            logger.exception("Error serving index")
            return "Internal Error", 500

    @app.route("/api/health")
    def health_check():
        status = {
            "status": "ok",
            "ctrader_connected": app_state.client is not None,
            "ml_model_loaded": ml_models.LGBM_MODEL is not None,
            "uptime": int(time.time() - getattr(app_state, 'start_time', time.time()))
        }
        return jsonify(status)

    @app.route("/<path:filename>")
    def static_files(filename):
        return send_from_directory(WEBAPP_DIR, filename)

    @app.route("/api/get_pairs")
    @protected_route
    def get_pairs():
        user_id = get_user_id_from_init_data(request.args.get("initData"))
        watchlist = db.get_watchlist(user_id) if user_id else []
        forex_data = [
            {"title": f"{name} {TRADING_HOURS.get(name, '')}".strip(), "pairs": pairs}
            for name, pairs in FOREX_SESSIONS.items()
        ]
        return jsonify({
            "forex": forex_data, "crypto": CRYPTO_PAIRS, "stocks": STOCK_TICKERS,
            "commodities": COMMODITIES, "watchlist": watchlist
        })

    @app.route("/api/signal")
    @protected_route
    def api_signal():
        pair = request.args.get("pair")
        timeframe = request.args.get("timeframe", "15m")
        if not pair: return jsonify({"error": "No pair"}), 400
        user_id = get_user_id_from_init_data(request.args.get("initData"))
        
        d = get_api_detailed_signal_data(app_state.client, app_state.symbol_cache, pair.replace("/", ""), user_id, timeframe)
        done_q = queue.Queue()
        d.addCallbacks(lambda res: done_q.put(res), lambda f: done_q.put({"error": str(f)}))
        try:
            return jsonify(done_q.get(timeout=30))
        except queue.Empty:
            return jsonify({"error": "Timeout"}), 504

    @app.route("/api/toggle_watchlist")
    @protected_route
    def toggle_watchlist_api():
        pair = request.args.get("pair")
        user_id = get_user_id_from_init_data(request.args.get("initData"))
        success = db.toggle_watchlist(user_id, pair)
        return jsonify({"success": success})

    @app.route("/api/scanner/status")
    @protected_route
    def scanner_status():
        return jsonify(app_state.SCANNER_STATE)

    @app.route("/api/scanner/toggle", methods=['GET', 'POST'])
    @protected_route
    def scanner_toggle():
        category = request.args.get("category")
        if not category or category not in app_state.SCANNER_STATE:
            logger.error(f"Invalid category for toggle: {category}")
            return jsonify({"error": "Invalid category"}), 400
        
        current = app_state.get_scanner_state(category)
        app_state.set_scanner_state(category, not current)
        logger.info(f"Scanner {category} toggled to {not current}")
        return jsonify(app_state.SCANNER_STATE)

    @app.route("/api/signal-stream")
    @protected_route
    def signal_stream():
        def generate():
            while True:
                try:
                    data = app_state.sse_queue.get(timeout=20)
                    yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                except queue.Empty:
                    yield ": ping\n\n"
        return Response(stream_with_context(generate()), mimetype='text/event-stream')
