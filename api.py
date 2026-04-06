import os
import json
import time
import queue
import logging
import threading
from flask import jsonify, send_from_directory, Response, request
from state import app_state
import db
from auth import get_user_id_from_init_data
import analysis as analysis_module
from config import FOREX_SESSIONS, get_fly_app_name, CRYPTO_PAIRS, STOCK_TICKERS, COMMODITIES
from errors import get_error_stats
import ctrader

logger = logging.getLogger("api")
WEBAPP_DIR = os.path.join(os.path.dirname(__file__), "webapp")

# Список активних підключень (браузерів)
_listeners = []
_listeners_lock = threading.Lock()

def _broadcaster():
    """Фоновий потік: бере сигнал з черги і розсилає КОПІЇ всім відкритим вкладкам"""
    logger.info("Broadcaster запущенний: очікування сигналів для Вебу...")
    while True:
        try:
            # Чекаємо сигнал від сканера (блокуюче отримання)
            signal_data = app_state.sse_queue.get()
            
            with _listeners_lock:
                if not _listeners:
                    continue
                
                # Розсилаємо всім, хто зараз тримає відкриту сторінку
                msg = f"data: {json.dumps(signal_data)}\n\n"
                for q in _listeners[:]:
                    try:
                        q.put_nowait(msg)
                    except queue.Full:
                        pass
        except Exception as e:
            logger.error(f"Помилка в Broadcaster: {e}")
            time.sleep(1)

# Запускаємо розсилку в окремому потоці один раз при імпорті
threading.Thread(target=_broadcaster, daemon=True).start()

def register_routes(app):
    @app.route("/api/events")
    def sse_events():
        """Точка підключення браузера до потоку живих сигналів"""
        q = queue.Queue(maxsize=50)
        with _listeners_lock:
            _listeners.append(q)
            logger.info(f"Нове підключення до Веб-панелі. Активних вкладок: {len(_listeners)}")
        
        def stream():
            try:
                while True:
                    yield q.get() # Віддаємо сигнал у браузер
            except GeneratorExit:
                with _listeners_lock:
                    if q in _listeners:
                        _listeners.remove(q)
                logger.info(f"Вкладка закрита. Активних вкладок: {len(_listeners)}")

        return Response(stream(), mimetype='text/event-stream')

    @app.route("/api/health")
    def health_check():
        prices = app_state.live_prices
        now = time.time()
        stale_count = sum(1 for d in prices.values() if now - d.get("ts", 0) > 300)
        err_stats = get_error_stats()
        rows = "".join([f"<tr><td>{ctx}</td><td>{d.get('consecutive_errors', 0)}</td></tr>" for ctx, d in err_stats.items() if d.get('consecutive_errors', 0) > 0])
        
        html = f"""<html><head><meta charset="UTF-8"></head><body style='background:#121212;color:#eee;font-family:sans-serif;'>
            <div style='max-width:400px;margin:20px auto;padding:20px;border:1px solid #333;border-radius:10px;'>
            <h2>📊 Стан Системи ZigZag</h2>
            <p>Цін в ефірі: <b>{len(prices)}</b></p>
            <p>Активних вкладок Веб: <b>{len(_listeners)}</b></p>
            <p>cTrader: <b>{'✅ OK' if app_state.SYMBOLS_LOADED else '❌ ERROR'}</b></p>
            <hr>
            <table style='width:100%;'><tr><th style='text-align:left'>Модуль</th><th style='text-align:left'>Помилок</th></tr>{rows if rows else "<tr><td colspan='2'>Помилок немає</td></tr>"}</table>
            </div></body></html>"""
        return Response(html, mimetype='text/html')

    @app.route("/api/scanner/toggle")
    def scanner_toggle():
        cat = request.args.get("category")
        if cat in app_state.SCANNER_STATE:
            app_state.set_scanner_state(cat, not app_state.get_scanner_state(cat))
            from twisted.internet import reactor
            reactor.callLater(0.5, ctrader.start_price_subscriptions)
        return jsonify(app_state.SCANNER_STATE)

    @app.route("/api/signal")
    def api_signal():
        pair = request.args.get("pair")
        tf = request.args.get("timeframe", "15m")
        uid = get_user_id_from_init_data(request.args.get("initData"))
        d = analysis_module.get_api_detailed_signal_data(app_state.client, app_state.symbol_cache, pair.replace("/", ""), uid, tf)
        q = queue.Queue(); d.addBoth(q.put)
        return jsonify(q.get(timeout=30))

    @app.route("/api/get_pairs")
    def get_pairs():
        uid = get_user_id_from_init_data(request.args.get("initData"))
        watchlist = db.get_watchlist(uid) if uid else []
        return jsonify({"forex": [{"title": k, "pairs": v} for k, v in FOREX_SESSIONS.items()], "crypto": CRYPTO_PAIRS, "stocks": STOCK_TICKERS, "commodities": COMMODITIES, "watchlist": watchlist})

    @app.route("/api/scanner/status")
    def scanner_status(): return jsonify(app_state.SCANNER_STATE)

    @app.route("/")
    def home():
        idx = os.path.join(WEBAPP_DIR, "index.html")
        if os.path.exists(idx):
            with open(idx, "r", encoding="utf-8") as f:
                return Response(f.read().replace("{{API_BASE_URL}}", f"https://{get_fly_app_name()}.fly.dev"), mimetype='text/html')
        return "Not found", 404

    @app.route("/<path:filename>")
    def static_files(filename): return send_from_directory(WEBAPP_DIR, filename)
