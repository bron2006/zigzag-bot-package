import logging
import os
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler
from twisted.internet import reactor # <-- ВАЖЛИВО: Імпортуємо Twisted reactor

# Припускаємо, що spotware_connect.py існує і містить SpotwareClient
# Якщо цього файлу немає, його потрібно створити на основі прикладу KleinWebAppSample
try:
    from spotware_connect import SpotwareClient
except ImportError:
    print("FATAL: Файл spotware_connect.py не знайдено. Будь ласка, створіть його.")
    exit(1)
    
from telegram_ui import start, button_handler

# Налаштування логування
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Глобальні змінні для керування станом ---
client: SpotwareClient = None
symbol_cache = {}
# Updater створюється в main(), але потрібен глобально для реєстрації обробників
updater: Updater = None 

def register_bot_handlers():
    """
    Реєструє обробники Telegram.
    Ця функція викликається ТІЛЬКИ ПІСЛЯ того, як кеш символів буде заповнений.
    """
    if not updater:
        logger.error("Помилка: Updater не ініціалізовано перед реєстрацією обробників.")
        return

    dispatcher = updater.dispatcher
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CallbackQueryHandler(button_handler))
    logger.info("✅ Обробники Telegram зареєстровані. Бот повністю готовий до роботи.")

def init_client():
    """Ініціалізує клієнт cTrader та встановлює обробники подій."""
    global client
    api_key = os.getenv("CT_CLIENT_ID")
    api_secret = os.getenv("CT_CLIENT_SECRET")

    if not all([api_key, api_secret]):
        logger.critical("Помилка: CT_CLIENT_ID або CT_CLIENT_SECRET не встановлено в .env")
        return

    client = SpotwareClient(api_key, api_secret)

    @client.on("symbolsLoaded")
    def on_symbols(symbols):
        global symbol_cache
        # ВИПРАВЛЕННЯ БАГУ: Ключем кешу має бути назва символу, а не ID.
        # Веб-інтерфейс та UI бота використовують імена (напр. "EURUSD").
        temp_cache = {}
        for s in symbols:
            if "symbolName" in s:
                # Нормалізуємо ім'я до формату "EURUSD"
                normalized_name = s["symbolName"].replace("/", "").strip()
                temp_cache[normalized_name] = s
        
        symbol_cache.update(temp_cache)
        logger.info("✅ Кеш символів заповнено (%s символів)", len(symbol_cache))
        
        # Тепер, коли кеш готовий, ми можемо безпечно зареєструвати обробники команд.
        register_bot_handlers()

    @client.on("error")
    def on_error(error_message):
        logger.error(f"Помилка від cTrader Client: {error_message}")

    # Запускаємо процес підключення. Це асинхронна операція.
    client.connect()


def main():
    """Головна функція запуску програми."""
    global updater
    
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.critical("Помилка: Змінна середовища TELEGRAM_BOT_TOKEN не встановлена.")
        return
        
    # Ініціалізуємо Updater, але ще не реєструємо обробники.
    updater = Updater(token)
    
    # Запускаємо клієнт cTrader. Він у фоні підключиться і викличе on_symbols.
    init_client()

    # Запускаємо отримання оновлень від Telegram в окремому потоці (неблокуючий виклик).
    updater.start_polling()
    logger.info("Бот запущений, очікуємо на ініціалізацію cTrader клієнта...")

    # Запускаємо головний цикл подій Twisted. 
    # Це блокуючий виклик, який підтримуватиме роботу cTrader клієнта.
    # Він замінює собою updater.idle().
    if client and not reactor.running:
        reactor.run()

if __name__ == "__main__":
    main()