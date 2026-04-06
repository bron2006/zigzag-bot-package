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

# --- СИСТЕМА РОЗСИЛКИ (Broadcaster) ---
# Дозволяє отримувати сигнали одночасно в декількох вкладках (Веб + Адмінка)
_listeners = []
_listeners_lock = threading.Lock()

def _broadcaster():
    """Фоновий потік, який копіює сигнал з черги усім активним браузерам"""
    logger.info("SSE Broadcaster запущено: очікування сигналів...")
    while True:
        try:
            # Чекаємо сигнал від сканера
            signal_data = app_state.sse_queue.get()
            
            with _listeners_lock:
                if not _listeners:
                    continue
                
                # Формуємо SSE повідомлення
                msg = f"data: {json.dumps(signal_data)}\n\n"
                
                # Розсилаємо копію кожній відкритій вкладці
                for q in _listeners[:]:
                    try:
                        q.put_nowait(msg)
                    except queue.Full:
                        # Якщо черга вкладки переповнена, видаляємо старе повідомлення
                        try:
                            q.get_nowait()
                            q.put_nowait(msg)
                        except: pass
        except Exception as e:
            logger.error(f"Помилка в потоці Broadcaster: {e}")
            time.sleep(1)

# Запуск розсилки при старті модуля
threading.Thread(target=_broadcaster, daemon=True).start()

def register_routes(app):
    
    @app.route("/api/events")
    def sse_events():
        """Ендпоінт, до якого підключається Веб-панель для отримання сигналів"""
        q = queue.Queue(maxsize=100)
        with _listeners_lock:
            _listeners.append(q)
            logger.info(f"Нове підключення до потоку подій. Активних вкладок: {len(_listeners)}")
        
        def stream():
            try:
                while True:
                    # Віддаємо дані, як тільки вони з'являться в персональній черзі вкладки
                    yield q.get()
            except GeneratorExit:
                # Видаляємо вкладку зі списку розсилки при закритті сторінки
                with _listeners_lock:
                    if q in _listeners:
                        _listeners.remove(q)
                logger.info(f"Вкладка закрита. Залишилось підключень: {len(_listeners)}")

        return Response(stream(), mimetype='text/event-stream')

    @app.route("/api/health")
    def health_check():
        """Красива адмін-панель моніторингу стану бота"""
        prices = app_state.live_prices
        now = time.time()
        stale_count = sum(1 for d in prices.values() if now - d.get("ts", 0) > 300)
        err_stats = get_error_stats()
        
        # Генерація рядків таблиці помилок
        rows = ""
        MODULE_MAP = {
            "process_asset": "Аналіз активу",
            "spot_event": "Потік цін cTrader",
            "scanner_loop": "Цикл сканування",
            "handle_analysis_result": "Відправка сигналів",
            "collect_assets": "Збір активів"
        }
        
        if err_stats:
            for ctx, data in err_stats.items():
                count = data.get("consecutive_errors", 0)
                if count > 0:
                    friendly_name = MODULE_MAP.get(ctx, ctx)
                    rows += f"<tr><td>{friendly_name}</td><td style='color:#ef5350;font-weight:bold;'>{count}</td></tr>"

        html = f"""
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>ZigZag Health Dashboard</title>
            <style>
                body {{ background: #0f0f0f; color: #e0e0e0; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; padding: 20px; display: flex; justify-content: center; }}
                .card {{ background: #1a1a1a; border-radius: 16px; padding: 24px; border: 1px solid #333; width: 100%; max-width: 480px; box-shadow: 0 10px 30px rgba(0,0,0,0.6); }}
                h1 {{ color: #3390ec; font-size: 24px; margin-bottom: 20px; text-align: center; border-bottom: 1px solid #333; padding-bottom: 15px; }}
                .stat-group {{ margin-bottom: 20px; }}
                .stat {{ display: flex; justify-content: space-between; padding: 10px 0; border-bottom: 1px solid #252525; font-size: 16px; }}
                .label {{ color: #aaa; }}
                .val {{ font-weight: bold; color: #fff; }}
                .status-ok {{ color: #4caf50; }}
                .status-err {{ color: #ef5350; }}
                .status-info {{ color: #3390ec; }}
                table {{ width: 100%; border-collapse: collapse; margin-top: 20px; background: #222; border-radius: 8px; overflow: hidden; }}
                th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #333; }}
                th {{ background: #2c2c2c; color: #888; font-size: 12px; text-transform: uppercase; letter-spacing: 1px; }}
                .footer {{ text-align: center; color: #555; font-size: 11px; margin-top: 20px; }}
            </style>
        </head>
        <body>
            <div class="card">
                <h1>📊 Стан Системи ZigZag</h1>
                
                <div class="stat-group">
                    <div class="stat">
                        <span class="label">Зв'язок cTrader:</span>
                        <span class="val {'status-ok' if app_state.SYMBOLS_LOADED else 'status-err'}">
                            {'✅ ПІДКЛЮЧЕНО' if app_state.SYMBOLS_LOADED else '❌ ПОМИЛКА'}
                        </span>
                    </div>
                    <div class="stat">
                        <span class="label">Активних вкладок Веб:</span>
                        <span class="val status-info">{len(_listeners)}</span>
                    </div>
                    <div class="stat">
                        <span class="label">Цін в ефірі:</span>
                        <span class="val">{len(prices)}</span>
                    </div>
                    <div class="stat">
                        <span class="label">Застарілих котирувань:</span>
                        <span class="val {'status-err' if stale_count > 0 else 'status-ok'}">{stale_count}</span>
                    </div>
                </div>

                <table>
                    <thead>
                        <tr><th>Модуль</th><th>Помилки підряд</th></tr>
                    </thead>
                    <tbody>
                        {rows if rows else "<tr><td colspan='2' style='color:#4caf50;text-align:center;padding:20px;'>Усі модулі працюють стабільно</td></tr>"}
                    </tbody>
                </table>
                
                <div class="footer">
                    Останнє оновлення сторінки: {time.strftime('%H:%M:%S')}
                </div>
            </div>
        </body>
        </html>
        """
        return Response(html, mimetype='text/html')

    @app.route("/api/scanner/toggle")
    def scanner_toggle():
        """Вмикання/вимикання категорій сканування"""
        cat = request.args.get("category")
        if cat in app_state.SCANNER_STATE:
            app_state.set_scanner_state(cat, not app_state.get_scanner_state(cat))
            # ПЕРЕПІДПИСКА: Змушуємо cTrader відразу підписатися на ціни нових активів
            from twisted.internet import reactor
            reactor.callLater(0.5, ctrader.start_price_subscriptions)
        return jsonify(app_state.SCANNER_STATE)

    @app.route("/api/signal")
    def api_signal():
        """Ручний аналіз конкретної пари"""
        pair = request.args.get("pair")
        tf = request.args.get("timeframe", "15m")
        uid = get_user_id_from_init_data(request.args.get("initData"))
        d = analysis_module.get_api_detailed_signal_data(app_state.client, app_state.symbol_cache, pair.replace("/", ""), uid, tf)
        q = queue.Queue()
        d.addBoth(q.put)
        return jsonify(q.get(timeout=30))

    @app.route("/api/watchlist/toggle")
    def toggle_watchlist_api():
        """Додавання пари в обране"""
        pair = request.args.get("pair")
        uid = get_user_id_from_init_data(request.args.get("initData"))
        if uid and pair:
            return jsonify({"success": db.toggle_watchlist(uid, pair)})
        return jsonify({"success": False}), 400

    @app.route("/api/get_pairs")
    def get_pairs():
        """Отримання списку доступних активів для інтерфейсу"""
        uid = get_user_id_from_init_data(request.args.get("initData"))
        watchlist = db.get_watchlist(uid) if uid else []
        return jsonify({
            "forex": [{"title": k, "pairs": v} for k, v in FOREX_SESSIONS.items()],
            "crypto": CRYPTO_PAIRS,
            "stocks": STOCK_TICKERS,
            "commodities": COMMODITIES,
            "watchlist": watchlist
        })

    @app.route("/api/scanner/status")
    def scanner_status():
        """Поточний статус ввімкнених сканерів"""
        return jsonify(app_state.SCANNER_STATE)

    @app.route("/")
    def home():
        """Головна сторінка веб-панелі"""
        idx = os.path.join(WEBAPP_DIR, "index.html")
        if os.path.exists(idx):
            with open(idx, "r", encoding="utf-8") as f:
                content = f.read().replace("{{API_BASE_URL}}", f"https://{get_fly_app_name()}.fly.dev")
                return Response(content, mimetype='text/html')
        return "Файл index.html не знайдено в папці webapp", 404

    @app.route("/<path:filename>")
    def static_files(filename):
        """Роздача статичних файлів інтерфейсу (js, css, png)"""
        return send_from_directory(WEBAPP_DIR, filename)
