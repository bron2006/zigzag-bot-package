# main.py
import logging
import os
from twisted.internet import reactor
from klein import Klein

import state
from spotware_connect import SpotwareClient

# Налаштування логування
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Створюємо Klein app
app = Klein()

@app.route("/")
def home(request):
    """Головна сторінка, яка віддає статичний HTML."""
    try:
        with open("templates/index.html", "r", encoding="utf-8") as f:
            # Klein коректно обробляє рядки, кодувати в байти не потрібно
            return f.read()
    except FileNotFoundError:
        logger.warning("templates/index.html не знайдено.")
        return "cTrader Bot is running."

def on_symbols_loaded(symbols):
    """Колбек, який викликається, коли символи завантажено."""
    logger.info(f"Завантажено {len(symbols)} символів. Ініціалізую кеш...")
    for s in symbols:
        normalized_name = s.symbolName.replace("/", "")
        state.symbol_cache[normalized_name] = {'symbolId': s.symbolId, 'digits': s.digits}
    state.SYMBOLS_LOADED = True
    logger.info("Кеш символів готовий. Бот повністю функціональний.")
    
def on_client_error(failure):
    """Колбек для критичних помилок клієнта."""
    error_message = failure.getErrorMessage() if hasattr(failure, 'getErrorMessage') else str(failure)
    logger.critical(f"Критична помилка cTrader клієнта: {error_message}. Зупиняю реактор.")
    if reactor.running:
        reactor.stop()

def start_ctrader_client():
    """Функція, яка ініціалізує та запускає cTrader клієнт."""
    logger.info("Ініціалізація cTrader клієнта...")
    state.client = SpotwareClient()
    d = state.client.isReady()
    d.addCallbacks(on_symbols_loaded, on_client_error)
    state.client.connect()

# --- Запуск логіки при старті реактора ---
# Це гарантує, що клієнт почне підключатися, коли Twisted буде готовий
reactor.callWhenRunning(start_ctrader_client)