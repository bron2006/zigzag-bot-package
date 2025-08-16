# bot.py
import traceback
import json
import threading
from urllib.parse import parse_qs, unquote
from flask import request, jsonify, send_from_directory
from telegram import Update
import os
import time

from config import dp, bot, app, WEBHOOK_SECRET, logger, FOREX_SESSIONS, SYMBOL_DATA_CACHE, CACHE_LOCK
from db import init_db, get_watchlist, toggle_watch, get_signal_history
from analysis import get_api_detailed_signal_data, get_api_mta_data
from ctrader_service import ctrader_service

def initialize_ctrader_cache():
    """Ця функція виконується у фоновому потоці, не блокуючи запуск."""
    try:
        logger.info("Фонова ініціалізація: Запускаю сервіс cTrader...")
        ctrader_service.start()
        
        # Даємо сервісу час на авторизацію
        for i in range(30):
            if ctrader_service._is_authorized:
                logger.info("Фонова ініціалізація: Сервіс cTrader успішно авторизований.")
                break
            logger.info(f"Фонова ініціалізація: Очікування авторизації cTrader... ({i+1}/30)")
            time.sleep(1)
        else:
            logger.critical("Фонова ініціалізація: Сервіс cTrader не зміг авторизуватися за 30 секунд.")
            return

        logger.info("Фонова ініціалізація: Починаю заповнення кешу символів...")
        symbols_list_res = ctrader_service.get_symbols_list()
        all_symbol_ids = [s.symbolId for s in symbols_list_res.symbol]
        logger.info(f"Фонова ініціалізація: Отримано {len(all_symbol_ids)} ID символів. Завантажую деталі...")

        chunk_size = 70
        for i in range(0, len(all_symbol_ids), chunk_size):
            chunk = all_symbol_ids[i:i + chunk_size]
            details_res = ctrader_service.get_symbols_by_id(chunk)
            with CACHE_LOCK:
                for symbol in details_res.symbol:
                    if hasattr(symbol, 'symbolName') and symbol.symbolName:
                        SYMBOL_DATA_CACHE[symbol.symbolName] = {'symbolId': symbol.symbolId, 'digits': symbol.digits}
            logger.info(f"Фонова ініціалізація: Закешовано {len(details_res.symbol)} символів. Прогрес: {i+len(chunk)}/{len(all_symbol_ids)}")
        
        logger.info(f"Фонова ініціалізація: Кеш символів cTrader успішно заповнено. Завантажено {len(SYMBOL_DATA_CACHE)} унікальних символів.")

    except Exception as e:
        logger.critical(f"Фонова ініціалізація: КРИТИЧНА ПОМИЛКА: {e}", exc_info=True)


def on_startup(worker):
    """Цей хук тепер лише запускає фоновий процес і не блокує сервер."""
    flag_file = f'/tmp/app_initialized_{worker.ppid}.flag'
    if not os.path.exists(flag_file):
        with open(flag_file, 'w') as f:
            f.write(str(worker.pid))
        
        logger.info(f"Воркер {worker.pid} (Мастер: {worker.ppid}): Запускаю фонову ініціалізацію cTrader...")
        # --- КЛЮЧОВА ЗМІНА: Виносимо довгу операцію в окремий потік ---
        initialization_thread = threading.Thread(target=initialize_ctrader_cache, daemon=True)
        initialization_thread.start()
    else:
        logger.info(f"Воркер {worker.pid}: Ініціалізацію для мастера {worker.ppid} вже запущено.")


def _get_user_id_from_request(req):
    init_data = req.args.get("initData")
    if not init_data:
        from config import MY_TELEGRAM_ID
        return int(MY_TELEGRAM_ID) if MY_TELEGRAM_ID else None
    try:
        decoded_init_data = unquote(init_data)
        parsed = parse_qs(decoded_init_data)
        user_json_str = parsed.get("user", [None])[0]
        if user_json_str:
            return json.loads(user_json_str).get("id")
    except Exception as e:
        logger.warning(f"Не вдалося розпарсити initData: {e}")
        from config import MY_TELEGRAM_ID
        return int(MY_TELEGRAM_ID) if MY_TELEGRAM_ID else None


@app.before_request
def log_request():
    if request.path.startswith(('/script.js', '/style.css')) or request.path in ['/health', '/favicon.ico']:
        return
    logger.info(f"[{request.method}] {request.path} (Args: {request.args})")

@app.route(f"/{WEBHOOK_SECRET}", methods=["POST"])
def webhook_handler():
    try:
        update = Update.de_json(request.get_json(force=True), bot)
        dp.process_update(update)
    except Exception as e:
        logger.error(f"Webhook error: {e}\n{traceback.format_exc()}")
    return "OK", 200

@app.route("/api/signal", methods=["GET"])
def api_signal():
    pair = request.args.get("pair")
    user_id = _get_user_id_from_request(request)
    if not pair: return jsonify({"error": "Не вказано параметр 'pair'"}), 400
    if not SYMBOL_DATA_CACHE: return jsonify({"error": "Сервіс ще завантажує дані, спробуйте за хвилину."}), 503
    try:
        data = get_api_detailed_signal_data(pair, user_id=user_id)
        if "error" in data: return jsonify(data), 500
        return jsonify(data)
    except Exception as e:
        logger.error(f"API /api/signal error for pair {pair}: {e}\n{traceback.format_exc()}")
        return jsonify({"error": f"Внутрішня помилка сервера при аналізі {pair}"}), 500

@app.route("/api/get_ranked_pairs", methods=["GET"])
def api_get_ranked_pairs():
    user_id = _get_user_id_from_request(request)
    watchlist = get_watchlist(user_id) if user_id else []
    try:
        ranked_crypto = []
        static_forex = { session: [{'ticker': p, 'active': True} for p in pairs] for session, pairs in FOREX_SESSIONS.items() }
        return jsonify({ "watchlist": watchlist, "crypto": ranked_crypto, "forex": static_forex, "stocks": [] })
    except Exception as e:
        logger.error(f"API /api/get_ranked_pairs error: {e}\n{traceback.format_exc()}")
        return jsonify({ "watchlist": watchlist, "crypto": [], "forex": {session: [{'ticker': p, 'active': True} for p in pairs] for session, pairs in FOREX_SESSIONS.items()}, "stocks": [], "error_message": "Помилка при сортуванні, показано стандартний список." })

@app.route("/api/get_mta", methods=["GET"])
def api_get_mta():
    pair = request.args.get("pair")
    if not pair: return jsonify({"error": "Не вказано параметр 'pair'"}), 400
    if not SYMBOL_DATA_CACHE: return jsonify({"error": "Сервіс ще завантажує дані, спробуйте за хвилину."}), 503
    try:
        mta_data = get_api_mta_data(pair)
        return jsonify(mta_data)
    except Exception as e:
        logger.error(f"API /api/get_mta error for {pair}: {e}\n{traceback.format_exc()}")
        return jsonify({"error": "Помилка при розрахунку MTA"}), 500

@app.route("/api/toggle_watchlist", methods=["GET"])
def toggle_watchlist_route():
    user_id = _get_user_id_from_request(request)
    pair = request.args.get("pair")
    if not user_id or not pair: return jsonify({"success": False, "error": "Відсутні необхідні параметри"}), 400
    try:
        toggle_watch(user_id, pair)
        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"Error in /api/toggle_watchlist: {e}")
        return jsonify({"success": False, "error": "Внутрішня помилка сервера"}), 500

@app.route("/api/signal_history", methods=["GET"])
def api_signal_history():
    user_id = _get_user_id_from_request(request)
    pair = request.args.get("pair")
    if not user_id: return jsonify({"error": "Не авторизовано"}), 401
    if not pair: return jsonify({"error": "Не вказано параметр 'pair'"}), 400
    try:
        history = get_signal_history(user_id, pair)
        return jsonify(history)
    except Exception as e:
        logger.error(f"API /api/signal_history error for {pair}: {e}\n{traceback.format_exc()}")
        return jsonify({"error": "Помилка при отриманні історії"}), 500

@app.route('/health')
def health_check():
    # Цей endpoint тепер завжди відповідає, що дозволяє сервісу пройти перевірку
    return "OK", 200

@app.route('/')
def serve_index():
    return send_from_directory('webapp', 'index.html')

@app.route('/<path:filename>')
def serve_webapp_files(filename):
    return send_from_directory('webapp', filename)

with app.app_context():
    init_db()