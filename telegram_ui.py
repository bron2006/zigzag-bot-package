# telegram_ui.py
import logging
from telegram import Bot, ReplyKeyboardMarkup, Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
from config import TELEGRAM_BOT_TOKEN, CHAT_ID
from state import AppState

logger = logging.getLogger(__name__)

class TelegramUI:
    def __init__(self, app_state: AppState):
        if not TELEGRAM_BOT_TOKEN:
            raise ValueError("TELEGRAM_BOT_TOKEN не встановлено!")
            
        self.state = app_state
        self.bot = Bot(token=TELEGRAM_BOT_TOKEN)
        self.updater = Updater(token=TELEGRAM_BOT_TOKEN, use_context=True)
        self.dispatcher = self.updater.dispatcher

        self._register_handlers()
        self.updater.start_polling()
        logger.info("Telegram bot запущено.")

    def _register_handlers(self):
        """Реєструє обробники команд та кнопок."""
        self.dispatcher.add_handler(CommandHandler("start", self.start_command))
        self.dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, self.handle_menu))

    def _get_main_menu(self):
        """Створює клавіатуру головного меню."""
        keyboard = [["📋 Список пар"]]
        return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    def start_command(self, update: Update, context: CallbackContext):
        """Обробник команди /start."""
        update.message.reply_text(
            "👋 Вітаю! Бот готовий до роботи. Оберіть дію з меню:",
            reply_markup=self._get_main_menu()
        )

    def handle_menu(self, update: Update, context: CallbackContext):
        """Обробляє натискання кнопок."""
        if update.message.text == "📋 Список пар":
            self.list_symbols_command(update)

    def list_symbols_command(self, update: Update):
        """Надсилає користувачу список торгових пар."""
        symbols = self.state.get_symbols()
        if symbols:
            message_text = "📈 **Доступні торгові пари:**\n\n`" + "`, `".join(symbols) + "`"
            update.message.reply_text(message_text, parse_mode='Markdown')
        else:
            update.message.reply_text("Список символів ще завантажується, зачекайте...")

    def send_message(self, text, parse_mode=None):
        """Централізований метод для надсилання повідомлень."""
        try:
            self.bot.send_message(chat_id=CHAT_ID, text=text, parse_mode=parse_mode)
        except Exception as e:
            logger.error(f"Не вдалося надіслати повідомлення: {e}")

    def send_startup_message(self, account_id):
        """Надсилає повідомлення про успішний запуск."""
        message = f"✅ **Бот Онлайн**\n\nПідключено до рахунку cTrader: `{account_id}`"
        self.send_message(message, parse_mode='Markdown')