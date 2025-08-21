# main.py
import logging
import os
from twisted.internet import reactor
from klein import Klein

import state
from spotware_connect import SpotwareClient
# from telegram_ui import setup_telegram_bot # Закоментовано до повної готовності API

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
            return f.read().encode('utf-8')
    except FileNotFoundError:
        logger.warning("templates/index.html не знайдено.")
        return b"cTrader Bot is running."

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

# --- Основна логіка запуску ---
if __name__ == "__main__":
    logger.info("Запуск cTrader Bot...")
    
    # Ініціалізуємо наш cTrader клієнт
    # Передаємо йому ID та секрет додатку для первинної авторизації
    state.client = SpotwareClient(os.getenv("CT_CLIENT_ID"), os.getenv("CT_CLIENT_SECRET"))
    
    # Додаємо обробники на події готовності та помилок
    d = state.client.isReady()
    d.addCallbacks(on_symbols_loaded, on_client_error)
    
    # Запускаємо процес підключення в фоні
    state.client.connect()

    # Визначаємо порт для веб-сервера
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"Запуск веб-сервера Klein на порту {port}.")
    
    # FIX: Використовуємо app.run() для запуску. Це правильно ініціалізує Twisted reactor.
    app.run(host="0.0.0.0", port=port)