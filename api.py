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
    """Фоновий потік: бере сигнал з черги і розсилає КОПІЇ всім підключеним клієнтам"""
    logger.info("SSE Broadcaster запущено. Очікування сигналів для Вебу...")
    while True:
        try:
            # Блокуюче отримання сигналу від сканера
            signal_data = app_state.sse_queue.get()
            
            with _listeners_lock:
                if not _listeners:
                    continue
                
                # Формуємо SSE повідомлення (ensure_ascii=False для кирилиці)
                msg = f"data: {json.dumps(signal_data, ensure_ascii=False)}\n\n"
                
                for q in _listeners[:]:
                    try:
                        q.put_nowait(msg)
                    except queue.Full:
                        # Якщо черга переповнена, звільняємо місце
                        try:
                            q.get_nowait()
                            q.put_nowait(msg)
                        except: pass
        except Exception as e:
            logger.error(f"Помилка в Broadcaster: {e}")
            time.sleep(1)

# Запускаємо розсилку один раз при старті
threading.Thread(target=_broadcaster, daemon=True).start()

def register_routes(app):
    
    # Декоратор для захисту роутів (як у старому коді)
    def protected_route(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            init_data = request.args.get("initData")
            if not is_valid_init_data(init_data):
                logger.warning(f"Unauthorized API access. Path: {request.path}")
                return jsonify({"success": False, "error": "Unauthorized"}), 401
            return f(*args, **kwargs)
        return decorated_function

    @app.route("/api/signal-stream")
    @protected_route
    def signal_stream():
        """Відновлений шлях для сигналів з усіма заголовками Fly.io"""
        q = queue.Queue(maxsize=100)
        with _listeners_lock:
            _listeners.append(q)
            logger.info(f"Веб-клієнт підключився до SSE. Активних вкладок: {len(_listeners)}")
        
        def generate():
            try:
                # Відправляємо початковий пінг для встановлення зв'язку
                yield ": ping\n\n"
                while True:
                    try:
                        # Чекаємо дані з персональної черги вкладки (з таймаутом для пінгу)
                        data = q.get(timeout=20)
                        yield data
                    except queue.Empty:
                        yield ": ping\n\n"
            except GeneratorExit:
                with _listeners_lock:
                    if q in _listeners:
                        _listeners.remove(q)
                logger.info(f"Веб-клієнт відключився. Залишилось: {len(_listeners)}")

        response = Response(stream_with_context(generate()), mimetype='text/event-stream')
        # Критичні заголовки для Fly.io, щоб стрім не "замерзав"
        response.headers['Cache-Control'] = 'no-cache'
        response.headers['Connection'] = 'keep-alive'
        response.headers['X-Accel-Buffering'] = 'no'
        return response

    @app.route("/api/health")
    def health_check():
        """Преміальна адмінка (яка тобі подобається)"""
        prices = app_state.live_prices
        now = time.time()
        stale_count = sum(1 for d in prices.values() if now - d.get("ts", 0) > 300)
        err_stats = get_error_stats()
        
        rows = ""
        MOD_MAP = {"process_asset": "Аналіз", "spot_event": "Ціни", "scanner_loop": "Сканер"}
        if err_stats:
            for ctx, data in err_stats.items():
                count = data.get("consecutive_errors", 0)
                if count > 0:
                    rows += f"<tr><td>{MOD_MAP.get(ctx, ctx)}</td><td style='color:#ef5350;font-weight:bold;'>{count}</td></tr>"

        html = f"""
        <html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {{ background:#0f0f0f; color:#e0e0e0; font-family:sans-serif; padding:20px; display:flex; justify-content:center; }}
            .card {{ background:#1a1a1a; border-radius:16px; padding:24px; border:1px solid #333; width:100%; max-width:450px; }}
            h1 {{ color:#3390ec; border-bottom:1px solid #333; padding-bottom:10px; font-size:22px; }}
            .stat {{ display:flex; justify-content:space-between; padding:10px 0; border-bottom:1px solid #252525; }}
            .ok {{ color:#4caf50; }} .err {{ color:#ef5350; }} .info {{ color:#3390ec; }}
            table {{ width:100%; margin-top:15px; border-collapse:collapse; }}
            th, td {{ padding:10px; text-align:left; border-bottom:1px solid #333; font-size:14px; }}
        </style></head>
        <body><div class="card">
            <h1>📊 Стан ZigZag</h1>
            <div class="stat"><span>cTrader:</span><span class="val {'ok' if app_state.SYMBOLS_LOADED else 'err'}">{'✅ OK' if app_state.SYMBOLS_LOADED else '❌ ERROR'}</span></div>
            <div class="stat"><span>Вкладок Веб:</span><span class="val info">{len(_listeners)}</span></div>
            <div class="stat"><span>Цін в ефірі:</span><span class="val">{len(prices)}</span></div>
            <div class="stat"><span>Застарілих:</span><span class="val {'err' if stale_count > 0 else 'ok'}">{stale_count}</span></div>
            <table><thead><tr><th>Модуль</th><th>Помилки</th></tr></thead><tbody>
            {rows if rows else "<tr><td colspan='2' style='color:#4caf50;text-align:center;'>Система працює стабільно</td></tr>"}
            </tbody></table>
            <p style='text-align:center;color:#555;font-size:11px;margin-top:20px;'>Оновлено: {time.strftime('%H:%M:%S')}</p>
        </div></body></html>"""
        return Response(html, mimetype='text/html')

    @app.route("/api/get_pairs")
    @protected_route
    def get_pairs():
        user_id = get_user_id_from_init_data(request.args.get("initData"))
        watchlist = db.get_watchlist(user_id) if user_id else []
        forex_data = [{"title": f"{k} {TRADING_HOURS.get(k, '')}".strip(), "pairs": v} for k, v in FOREX_SESSIONS.items()]
        return jsonify({"forex": forex_data, "crypto": CRYPTO_PAIRS, "stocks": STOCK_TICKERS, "commodities": COMMODITIES, "watchlist": watchlist})

    @app.route("/api/scanner/toggle", methods=['GET', 'POST'])
    @protected_route
    def scanner_toggle():
        category = request.args.get("category")
        if category in app_state.SCANNER_STATE:
            app_state.set_scanner_state(category, not app_state.get_scanner_state(category))
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

    @app.route("/api/scanner/status")
    @protected_route
    def scanner_status():
        return jsonify(app_state.SCANNER_STATE)

    @app.route("/")
    def home():
        idx = os.path.join(WEBAPP_DIR, "index.html")
        if os.path.exists(idx):
            with open(idx, "r", encoding="utf-8") as f:
                content = f.read().replace("{{API_BASE_URL}}", f"https://{get_fly_app_name()}.fly.dev")
                return Response(content, mimetype='text/html')
        return "Web UI not found", 404

    @app.route("/<path:filename>")
    def static_files(filename):
        return send_from_directory(WEBAPP_DIR, filename)
