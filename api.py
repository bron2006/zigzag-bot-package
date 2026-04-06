import os
import json
import time
import queue
import logging
from flask import jsonify, send_from_directory, Response, request
from state import app_state
import db
from auth import get_user_id_from_init_data
import analysis as analysis_module
from config import FOREX_SESSIONS, get_fly_app_name, CRYPTO_PAIRS, STOCK_TICKERS, COMMODITIES
from errors import get_error_stats
import ctrader  # Додали імпорт для перепідписки

logger = logging.getLogger("api")
WEBAPP_DIR = os.path.join(os.path.dirname(__file__), "webapp")

MODULE_MAP = {
    "spot_event": "Потік цін cTrader",
    "scanner_loop": "Цикл сканування",
    "process_asset": "Аналіз активу",
    "handle_analysis_result": "Відправка сигналів",
    "collect_assets": "Збір активів",
    "telegram": "Зв'язок з Telegram"
}

def register_routes(app):
    @app.route("/api/health")
    def health_check():
        prices = app_state.live_prices
        now = time.time()
        stale_count = sum(1 for d in prices.values() if now - d.get("ts", 0) > 300)
        err_stats = get_error_stats()
        rows = ""
        if err_stats:
            for ctx, data in err_stats.items():
                friendly_name = MODULE_MAP.get(ctx, ctx)
                count = data.get("consecutive_errors", 0)
                if count > 0:
                    rows += f"<tr><td>{friendly_name}</td><td style='color:#ef5350;font-weight:bold;'>{count}</td></tr>"
        
        html = f"""<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>ZigZag Health</title><style>body {{ background:#121212; color:#e0e0e0; font-family: -apple-system, sans-serif; padding: 20px; }} .card {{ background:#1e1e1e; border-radius:12px; padding:20px; border:1px solid #333; max-width:500px; margin:auto; box-shadow: 0 4px 15px rgba(0,0,0,0.5); }} h1 {{ color:#3390ec; font-size:22px; margin-top:0; border-bottom:1px solid #333; padding-bottom:10px; }} .stat {{ display:flex; justify-content:space-between; margin: 12px 0; font-size:16px; }} .val {{ font-weight:bold; }} .ok {{ color:#4caf50; }} .err {{ color:#ef5350; }} table {{ width:100%; border-collapse:collapse; margin-top:20px; }} th, td {{ padding:10px; text-align:left; border-bottom:1px solid #333; }} th {{ color:#888; font-size:12px; text-transform:uppercase; }}</style></head><body><div class="card"><h1>📊 Стан Системи ZigZag</h1><div class="stat"><span>cTrader (Символи):</span><span class="val">{'✅ ЗАВАНТАЖЕНО' if app_state.SYMBOLS_LOADED else '❌ ПОМИЛКА'}</span></div><div class="stat"><span>Telegram Бот:</span><span class="val">{'✅ АКТИВНИЙ' if app_state.updater else '❌ ВИМКНЕНО'}</span></div><div class="stat"><span>Цін в ефірі:</span><span class="val">{len(prices)}</span></div><div class="stat"><span>Застарілих цін:</span><span class="val {'err' if stale_count > 0 else 'ok'}">{stale_count}</span></div><table><thead><tr><th>Модуль</th><th>Помилок підряд</th></tr></thead><tbody>{rows if rows else "<tr><td colspan='2' style='color:#4caf50;text-align:center;'>Всі системи працюють стабільно</td></tr>"}</tbody></table><p style="color:#555; font-size:11px; margin-top:20px; text-align:center;">Останнє оновлення: {time.strftime('%H:%M:%S')}</p></div></body></html>"""
        return Response(html, mimetype='text/html')

    @app.route("/api/scanner/toggle")
    def scanner_toggle():
        cat = request.args.get("category")
        if cat in app_state.SCANNER_STATE:
            app_state.set_scanner_state(cat, not app_state.get_scanner_state(cat))
            # ЦЕЙ РЯДОК ВСЕ ВИПРАВЛЯЄ: змушуємо cTrader підписатися на нові ціни
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

    @app.route("/api/watchlist/toggle")
    def toggle_watchlist_api():
        pair = request.args.get("pair")
        uid = get_user_id_from_init_data(request.args.get("initData"))
        if uid and pair: return jsonify({"success": db.toggle_watchlist(uid, pair)})
        return jsonify({"success": False}), 400

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
        return "Не знайдено", 404

    @app.route("/<path:filename>")
    def static_files(filename): return send_from_directory(WEBAPP_DIR, filename)
