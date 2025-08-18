import logging
import os
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler
from twisted.internet import reactor

# Імпортуємо об'єкти спільного стану
import state

# Тепер ці імпорти безпечні, оскільки циклічна залежність розірвана
from telegram_ui import start, button_handler
from spotware_connect import SpotwareClient

# Налаштування логування
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


def register_bot_handlers():
    """Реєструє обробники команд Telegram, використовуючи updater зі спільного стану."""
    if not state.updater:
        logger.error("Помилка: Updater не ініціалізовано перед реєстрацією обробників.")
        return

    dispatcher = state.updater.dispatcher
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CallbackQueryHandler(button_handler))
    logger.info("✅ Обробники Telegram зареєстровані. Бот повністю готовий до роботи.")


def init_client():
    """Ініціалізує cTrader клієнт і зберігає його в спільному стані."""
    api_key = os.getenv("CT_CLIENT_ID")
    api_secret = os.getenv("CT_CLIENT_SECRET")

    if not all([api_key, api_secret]):
        logger.critical("Помилка: CT_CLIENT_ID або CT_CLIENT_SECRET не встановлено.")
        return

    # Ініціалізуємо клієнт і зберігаємо його в state.client
    state.client = SpotwareClient(api_key, api_secret)

    @state.client.on("symbolsLoaded")
    def on_symbols(symbols):
        # Оновлюємо кеш символів у спільному стані
        temp_cache = {}
        for s in symbols:
            if "symbolName" in s:
                normalized_name = s["symbolName"].replace("/", "").strip()
                temp_cache[normalized_name] = s
        state.symbol_cache.update(temp_cache)
        logger.info("✅ Кеш символів заповнено (%s символів)", len(state.symbol_cache))
        
        # Реєструємо обробники тільки після завантаження кешу
        register_bot_handlers()

    @state.client.on("error")
    def on_error(error_message):
        logger.error(f"Помилка від cTrader Client: {error_message}")

    state.client.connect()


def main():
    """Головна функція запуску додатку."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.critical("Помилка: Змінна середовища TELEGRAM_BOT_TOKEN не встановлена.")
        return
    
    # Ініціалізуємо updater і зберігаємо його в state.updater
    state.updater = Updater(token)
    
    init_client()

    state.updater.start_polling()
    logger.info("Бот запущений, очікуємо на ініціалізацію cTrader клієнта...")

    if state.client and not reactor.running:
        reactor.run()


if __name__ == "__main__":
    main()