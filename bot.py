# bot.py
import traceback
import json
from urllib.parse import parse_qs, unquote
from flask import request, jsonify, send_from_directory
from telegram import Update
import os
import time

from config import dp, bot, app, WEBHOOK_SECRET, logger, FOREX_SESSIONS, SYMBOL_DATA_CACHE, CACHE_LOCK
from db import init_db, get_watchlist, toggle_watch, get_signal_history
from analysis import get_api_detailed_signal_data, get_api_mta_data
from ctrader_service import ctrader_service

def on_startup(worker):
    # Використовуємо PID мастера, щоб гарантувати єдиний запуск
    flag_file = f'/tmp/app_initialized_{worker.ppid}.flag'
    if not os.path.exists(flag_file):
        try:
            with open(flag_file, 'w') as f:
                f.write(str(worker.pid))
            
            logger.info(f"Воркер {worker.pid} (Мастер: {worker.ppid}): Запускаю сервіс cTrader...")
            ctrader_service.start()
            
            # Даємо сервісу час на авторизацію
            for i in range(30):
                if ctrader_service._is_authorized:
                    logger.info("Сервіс cTrader успішно авторизований.")
                    break
                logger.info(f"Очікування авторизації cTrader... ({i+1}/30)")
                time.sleep(1)
            else:
                # Якщо авторизація не вдалася, це критично
                logger.critical("Сервіс cTrader не зміг авторизуватися за 30 секунд. Зупиняю ініціалізацію.")
                # Можна навіть зупинити gunicorn, якщо це критично
                # worker.halt()
                return

            logger.info("Починаю заповнення кешу символів...")
            symbols_list_res = ctrader_service.get_symbols_list()
            all_symbol_ids = [s.symbolId for s in symbols_list_res.symbol]
            logger.info(f"Отримано {len(all_symbol_ids)} ID символів. Завантажую деталі...")

            chunk_size = 70
            for i in range(0, len(all_symbol_ids), chunk_size):
                chunk = all_symbol_ids[i:i + chunk_size]
                details_res = ctrader_service.get_symbols_by_id(chunk)
                with CACHE_LOCK:
                    for symbol in details_res.symbol:
                        # У API поле називається symbolName, а не name
                        if hasattr(symbol, 'symbolName') and symbol.symbolName:
                            SYMBOL_DATA_CACHE[symbol.symbolName] = {'symbolId': symbol.symbolId, 'digits': symbol.digits}
                logger.info(f"Закешовано деталі для {len(details_res.symbol)} символів. Прогрес: {i+len(chunk)}/{len(all_symbol_ids)}")
            
            logger.info(f"Воркер {worker.pid}: Кеш символів cTrader успішно заповнено. Завантажено {len(SYMBOL_DATA_CACHE)} унікальних символів.")

        except Exception as e:
            logger.critical(f"Воркер {worker.pid}: КРИТИЧНА ПОМИЛКА під час запуску: {e}", exc_info=True)
    else:
        logger.info(f"Воркер {worker.pid}: Ініціалізацію для мастера {worker.ppid} вже виконано.")


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
    # Не логуємо запити до статичних файлів та health-чеків
    if request.path.startswith(('/script.js', '/style.css')) or request.path in ['/health', '/favicon.ico']:
        return
    logger.info(f"[{request.method}] {request.path} (Args: {request.args})")

@app.route(f"/{WEBHOOK_SECRET}", methods=["POST"])
def webhook_handler():
    # Ця функція залишається для майбутнього використання з Telegram UI, зараз вона неактивна
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
        # Логіку ранжування тимчасово вимкнено, повертаємо статичні списки
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
    # Перевірка готовності сервісу: кеш символів заповнений і сервіс cTrader авторизований
    if len(SYMBOL_DATA_CACHE) > 100 and ctrader_service._is_authorized:
        return "OK", 200
    else:
        return f"Cache not ready ({len(SYMBOL_DATA_CACHE)} symbols) or service not authorized ({ctrader_service._is_authorized})", 503

@app.route('/')
def serve_index():
    return send_from_directory('webapp', 'index.html')

@app.route('/<path:filename>')
def serve_webapp_files(filename):
    # Дозволяє віддавати style.css, script.js та інші файли з папки webapp
    return send_from_directory('webapp', filename)

with app.app_context():
    init_db()