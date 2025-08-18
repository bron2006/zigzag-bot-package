import logging
import os
import json
import queue
import threading
from klein import Klein
from twisted.internet import reactor
from telegram import Update
from telegram.ext import Updater

import state
from telegram_ui import start, button_handler
from spotware_connect import SpotwareClient
from config import (
    get_telegram_token, get_ct_client_id, 
    get_ct_client_secret, get_fly_app_name,
    get_webhook_secret
)

# --- Налаштування логування ---
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Ініціалізація ---
app = Klein()
TOKEN = get_telegram_token()
# Створюємо потоко-безпечну чергу для оновлень від Telegram
updates_queue = queue.Queue(maxsize=1000)

# --- Воркер для обробки оновлень з черги ---
def dispatcher_worker():
    """Ця функція працює у фоновому потоці, бере оновлення з черги і обробляє їх."""
    while True:
        try:
            update_data = updates_queue.get()
            if state.updater:
                update = Update.de_json(update_data, state.updater.bot)
                state.updater.dispatcher.process_update(update)
            updates_queue.task_done()
        except Exception as e:
            logger.exception(f"Помилка в воркері диспетчера: {e}")

# --- Ініціалізація Telegram ---
def init_telegram_bot():
    """Ініціалізує Updater та запускає фонові воркери."""
    state.updater = Updater(TOKEN, use_context=True)
    
    # Реєструємо обробники
    dispatcher = state.updater.dispatcher
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CallbackQueryHandler(button_handler))
    logger.info("✅ Обробники Telegram зареєстровані.")
    
    # Запускаємо наші власні воркери для обробки черги
    for _ in range(4): # Запускаємо 4 фонових потоки
        threading.Thread(target=dispatcher_worker, daemon=True).start()
    logger.info("✅ Воркери для обробки черги Telegram запущені.")

# --- Ініціалізація cTrader ---
def on_symbols_loaded(symbols):
    temp_cache = {}
    for s in symbols:
        if "symbolName" in s:
            normalized_name = s["symbolName"].replace("/", "").strip()
            temp_cache[normalized_name] = s
    state.symbol_cache.update(temp_cache)
    logger.info("✅ Кеш символів заповнено (%s символів)", len(state.symbol_cache))

def init_ctrader_client():
    api_key = get_ct_client_id()
    api_secret = get_ct_client_secret()
    state.client = SpotwareClient(api_key, api_secret)
    state.client.on("symbolsLoaded")(on_symbols_loaded)
    state.client.on("error")(lambda err: logger.error(f"Помилка cTrader: {err}"))
    state.client.connect()
    logger.info("Запущено підключення до cTrader API...")

# --- Веб-ручки (Web Routes) ---

@app.route(f"/{TOKEN}", methods=['POST'])
def webhook_handler(request):
    """Швидка ручка, що лише кладе оновлення в чергу і миттєво відповідає."""
    try:
        # ОБОВ'ЯЗКОВО зчитуємо тіло запиту повністю
        body = request.content.read()
        
        if request.getHeader("X-Telegram-Bot-Api-Secret-Token") != get_webhook_secret():
            logger.warning("Відхилено запит до вебхука з неправильним секретним токеном.")
            request.setResponseCode(403)
            return b"Forbidden"

        update_data = json.loads(body.decode())
        updates_queue.put_nowait(update_data) # Неблокуюче додавання в чергу
        
        request.setResponseCode(200)
        return b"OK"
    except queue.Full:
        logger.warning("Черга оновлень переповнена.")
        request.setResponseCode(503) # Service Unavailable
        return b"Busy"
    except Exception:
        logger.exception("Некоректний запит до вебхука.")
        request.setResponseCode(400) # Bad Request
        return b"Bad Request"

@app.route("/health")
def health_check(request):
    """Ручка для перевірки стану сервісу Fly.io."""
    request.setResponseCode(200)
    return b"OK"

@app.route("/")
def home(request):
    """Сторінка-заглушка."""
    return b"Telegram Bot and Web Service is running"

def setup_webhook():
    """Встановлює вебхук при запуску додатку."""
    app_name = get_fly_app_name()
    if app_name and state.updater:
        webhook_url = f"https://{app_name}.fly.dev/{TOKEN}"
        state.updater.bot.set_webhook(url=webhook_url, secret_token=get_webhook_secret())
        logger.info(f"Вебхук встановлено за адресою: {webhook_url}")
    else:
        logger.warning("Не вдалося встановити вебхук.")

# --- Запуск сервісів ---
init_telegram_bot()
reactor.callWhenRunning(setup_webhook)
reactor.callWhenRunning(init_ctrader_client)