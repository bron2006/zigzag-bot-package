# main.py
import logging
import os
from twisted.internet import reactor, endpoints
from twisted.web.server import Site
from klein import Klein

import state
from spotware_connect import SpotwareClient
# from telegram_ui import setup_telegram_bot # Закоментовано до повної готовності API

# Налаштування логування
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Створюємо Klein app для веб-частини
app = Klein()

@app.route("/")
def home(request):
    try:
        # Віддаємо статичну сторінку, якщо вона є
        with open("templates/index.html", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "cTrader Bot is running."

def on_symbols_loaded(symbols):
    """Колбек, який викликається, коли символи завантажено."""
    logger.info(f"Завантажено {len(symbols)} символів. Ініціалізую кеш...")
    
    # Створюємо кеш, зберігаючи важливі дані для кожного символу
    for s in symbols:
        # Нормалізуємо ім'я, видаляючи слеш
        normalized_name = s.symbolName.replace("/", "")
        # Зберігаємо symbolId та digits, які потрібні для запитів
        state.symbol_cache[normalized_name] = {'symbolId': s.symbolId, 'digits': s.digits}
        
    state.SYMBOLS_LOADED = True
    logger.info("Кеш символів готовий. Бот повністю функціональний.")
    
    # Тут можна буде розкоментувати запуск Telegram бота
    # state.updater = setup_telegram_bot()
    # logger.info("Telegram Bot запущено.")

def on_client_error(failure):
    """Колбек для критичних помилок клієнта."""
    error_message = failure.getErrorMessage() if hasattr(failure, 'getErrorMessage') else str(failure)
    logger.critical(f"Критична помилка cTrader клієнта: {error_message}. Зупиняю реактор.")
    if reactor.running:
        reactor.stop()

def main():
    logger.info("Запуск cTrader Bot...")
    
    # Ініціалізуємо наш cTrader клієнт
    # Передаємо йому ID та секрет додатку для первинної авторизації
    state.client = SpotwareClient(os.getenv("CT_CLIENT_ID"), os.getenv("CT_CLIENT_SECRET"))
    
    # Додаємо обробники на події готовності та помилок
    d = state.client.isReady()
    d.addCallbacks(on_symbols_loaded, on_client_error)
    
    # Запускаємо процес підключення
    state.client.connect()

    # Налаштовуємо та запускаємо веб-сервер Klein
    port = int(os.environ.get("PORT", 8080))
    endpoint_str = f"tcp:port={port}:interface=0.0.0.0"
    endpoint = endpoints.serverFromString(reactor, endpoint_str)
    endpoint.listen(Site(app.resource()))
    
    logger.info(f"Twisted Reactor запущено. Веб-сервер слухає на порту {port}.")
    
    # Запускаємо головний цикл Twisted
    reactor.run()

if __name__ == "__main__":
    main()