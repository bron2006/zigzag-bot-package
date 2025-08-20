# main.py
import logging
from twisted.internet import reactor, endpoints
from twisted.web.server import Site
from klein import Klein

import state
from spotware_connect import SpotwareClient
from telegram_ui import setup_telegram_bot # Уявімо, що ця функція налаштовує бота

# Налаштування логування
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Створюємо Klein app для веб-частини (наприклад, для вебхуків Telegram)
app = Klein()

@app.route("/")
def home(request):
    return "cTrader Bot is running."

def on_symbols_loaded(symbols):
    """Колбек, який викликається, коли символи завантажено."""
    logger.info(f"Завантажено {len(symbols)} символів. Ініціалізую кеш...")
    state.symbol_cache = {s.symbolName.replace("/", ""): {'symbolId': s.symbolId, 'digits': s.digits} for s in symbols}
    state.SYMBOLS_LOADED = True
    logger.info("Кеш символів готовий. Бот повністю функціональний.")
    
    # Тут можна запустити Telegram бота, коли ми впевнені, що API готове
    # state.updater = setup_telegram_bot()
    # logger.info("Telegram Bot запущено.")

def on_client_error(failure):
    """Колбек для критичних помилок клієнта."""
    logger.critical(f"Критична помилка cTrader клієнта: {failure.getErrorMessage()}. Зупиняю реактор.")
    if reactor.running:
        reactor.stop()

def main():
    logger.info("Запуск cTrader Bot...")
    
    # Ініціалізуємо наш cTrader клієнт
    state.client = SpotwareClient()
    
    # Додаємо обробники на події готовності та помилок
    d = state.client.isReady()
    d.addCallbacks(on_symbols_loaded, on_client_error)
    
    # Запускаємо процес підключення
    state.client.connect()

    # Налаштовуємо та запускаємо веб-сервер Klein
    endpoint_str = "tcp:port=8080:interface=0.0.0.0"
    endpoint = endpoints.serverFromString(reactor, endpoint_str)
    endpoint.listen(Site(app.resource()))
    
    logger.info("Twisted Reactor запущено. Веб-сервер слухає на порту 8080.")
    
    # Запускаємо головний цикл Twisted
    reactor.run()

if __name__ == "__main__":
    main()