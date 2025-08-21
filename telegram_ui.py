import logging
from telegram import Bot
from telegram.ext import Updater, CommandHandler, CallbackContext
from config import TELEGRAM_BOT_TOKEN, CHAT_ID

logger = logging.getLogger(__name__)

class TelegramUI:
    def __init__(self):
        """Ініціалізує та налаштовує Telegram-бота."""
        if not TELEGRAM_BOT_TOKEN:
            logger.error("Telegram bot token not found!")
            raise ValueError("TELEGRAM_BOT_TOKEN is not set")
            
        self.bot = Bot(token=TELEGRAM_BOT_TOKEN)
        self.updater = Updater(token=TELEGRAM_BOT_TOKEN, use_context=True)
        self.dispatcher = self.updater.dispatcher

        # Реєструємо обробники команд
        self._register_handlers()

        # Запускаємо бота в неблокуючому режимі
        self.updater.start_polling()
        logger.info("Telegram bot has started polling.")

    def _register_handlers(self):
        """Реєструє обробники команд для бота."""
        self.dispatcher.add_handler(CommandHandler("start", self.start_command))
        # Тут можна додати інші команди (status, help, etc.)

    def start_command(self, update, context: CallbackContext):
        """Обробник команди /start."""
        user_id = update.effective_chat.id
        logger.info(f"Received /start command from user {user_id}")
        update.message.reply_text("👋 Вітаю! Бот запущено і готовий до роботи.")

    def send_message(self, text):
        """Надсилає повідомлення визначеному користувачу."""
        if not CHAT_ID:
            logger.warning("CHAT_ID is not set, can't send message.")
            return
        try:
            self.bot.send_message(chat_id=CHAT_ID, text=text)
            logger.info(f"Sent message to chat {CHAT_ID}: '{text}'")
        except Exception as e:
            logger.error(f"Failed to send message to chat {CHAT_ID}: {e}")

    def send_startup_message(self, account_id):
        """Надсилає вітальне повідомлення при успішному запуску."""
        message = f"✅ **Бот Онлайн**\n\nУспішно підключено до рахунку cTrader: `{account_id}`"
        self.send_message(message)