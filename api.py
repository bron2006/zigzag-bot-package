import os
import json
import time
import queue
import logging
import threading
from functools import wraps
from flask import jsonify, send_from_directory, Response, request, stream_with_context

from state import app_state
import db
from auth import is_valid_init_data, get_user_id_from_init_data
import analysis as analysis_module
from config import (
    FOREX_SESSIONS, get_fly_app_name, CRYPTO_PAIRS, STOCK_TICKERS,
    COMMODITIES, TRADING_HOURS
)
import ctrader

logger = logging.getLogger("api")
WEBAPP_DIR = os.path.join(os.path.dirname(__file__), "webapp")

# --- СИСТЕМА РОЗСИЛКИ (Broadcaster) ---
_listeners = []
_listeners_lock = threading.Lock()

def _broadcaster():
    """Фоновий потік для розсилки сигналів на всі вкладки"""
    while True:
        try:
            signal_data = app_state.sse_queue.get()
            with _listeners_lock:
                if not _listeners: continue
                msg = f"data: {json.dumps(signal_data, ensure_ascii=False)}\n\n"
                for q in _listeners[:]:
                    try:
                        q.put_nowait(msg)
                    except queue.Full:
                        try: q.get_nowait(); q.put_nowait(msg)
                        except: pass
        except Exception as e:
            time.sleep(1)

threading.Thread(target=_broadcaster, daemon=True).start()

def register_routes(app):
    
    def protected_route(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            init_data = request.args.get("initData")
            if not is_valid_init_data(init_data):
                return jsonify({"success": False, "error": "Unauthorized"}), 401
            return f(*args, **kwargs)
        return decorated_function

    @app.route("/api/signal-stream")
    @protected_route
    def signal_stream():
        """SSE потік для Вебу"""
        q = queue.Queue(maxsize=100)
        with _listeners_lock:
            _listeners.append(q)
        
        def generate():
            try:
                yield ": ping\n\n"
                while True:
                    yield q.get(timeout=25)
            except (GeneratorExit, queue.Empty):
                with _listeners_lock:
                    if q in _listeners: _listeners.remove(q)

        resp = Response(stream_with_context(generate()), mimetype='text/event-stream')
        resp.headers.update({'Cache-Control': 'no-cache', 'Connection': 'keep-alive', 'X-Accel-Buffering': 'no'})
        return resp

    @app.route("/api/health")
    def health_check():
        """Адмінка (виправлено 500 помилку)"""
        try:
            prices = app_state.live_prices
            stale_count = sum(1 for d in prices.values() if time.time() - d.get("ts", 0) > 300)
            
            html = f"""
            <html><head><meta charset="UTF-8"><style>
                body {{ background:#0f0f0f; color:#e0e0e0; font-family:sans-serif; padding:20px; display:flex; justify-content:center; }}
                .card {{ background:#1a1a1a; border-radius:16px; padding:24px; border:1px solid #333; width:450px; }}
                h1 {{ color:#3390ec; border-bottom:1px solid #333; padding-bottom:10px; font-size:22px; }}
                .stat {{ display:flex; justify-content:space-between; padding:10px 0; border-bottom:1px solid #252525; }}
                .val {{ font-weight:bold; color:#fff; }}
                .ok {{ color:#4caf50; }} .info {{ color:#3390ec; }}
            </style></head>
            <body><div class="card">
                <h1>📊 Стан ZigZag</h1>
                <div class="stat"><span>cTrader:</span><span class="val {'ok' if app_state.SYMBOLS_LOADED else ''}">{'✅ OK' if app_state.SYMBOLS_LOADED else '❌ ERROR'}</span></div>
                <div class="stat"><span>Активних вкладок:</span><span class="val info">{len(_listeners)}</span></div>
                <div class="stat"><span>Цін в ефірі:</span><span class="val">{len(prices)}</span></div>
                <div class="stat"><span>Застарілих:</span><span class="val">{stale_count}</span></div>
                <p style='text-align:center;color:#555;font-size:11px;margin-top:20px;'>Оновлено: {time.strftime('%H:%M:%S')}</p>
            </div></body></html>"""
            return Response(html, mimetype='text/html')
        except Exception as e:
            return f"Error: {str(e)}", 500

    @app.route("/api/get_pairs")
    @protected_route
    def get_pairs():
        uid = get_user_id_from_init_data(request.args.get("initData"))
        watchlist = db.get_watchlist(uid) if uid else []
        forex_data = [{"title": f"{k} {TRADING_HOURS.get(k, '')}".strip(), "pairs": v} for k, v in FOREX_SESSIONS.items()]
        return jsonify({"forex": forex_data, "crypto": CRYPTO_PAIRS, "stocks": STOCK_TICKERS, "commodities": COMMODITIES, "watchlist": watchlist})

    @app.route("/api/scanner/toggle", methods=['GET', 'POST'])
    @protected_route
    def scanner_toggle():
        cat = request.args.get("category")
        if cat in app_state.SCANNER_STATE:
            app_state.set_scanner_state(cat, not app_state.get_scanner_state(cat))
            from twisted.internet import reactor
            reactor.callLater(0.5, ctrader.start_price_subscriptions)
        return jsonify(app_state.SCANNER_STATE)

    @app.route("/api/signal")
    @protected_route
    def api_signal():
        pair = request.args.get("pair")
        tf = request.args.get("timeframe", "15m")
        uid = get_user_id_from_init_data(request.args.get("initData"))
        d = analysis_module.get_api_detailed_signal_data(app_state.client, app_state.symbol_cache, pair.replace("/", ""), uid, tf)
        q = queue.Queue(); d.addBoth(q.put)
        return jsonify(q.get(timeout=30))

    @app.route("/")
    def home():
        idx = os.path.join(WEBAPP_DIR, "index.html")
        if os.path.exists(idx):
            with open(idx, "r", encoding="utf-8") as f:
                content = f.read().replace("{{API_BASE_URL}}", f"https://{get_fly_app_name()}.fly.dev")
                v = int(time.time())
                return Response(content.replace(".js", f".js?v={v}").replace(".css", f".css?v={v}"), mimetype='text/html')
        return "Not found", 404

    @app.route("/<path:filename>")
    def static_files(filename): return send_from_directory(WEBAPP_DIR, filename)
