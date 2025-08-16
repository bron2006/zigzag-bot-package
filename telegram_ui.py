# telegram_ui.py
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import CallbackContext, CommandHandler, Dispatcher

# URL вашого розгорнутого веб-додатка
WEB_APP_URL = "https://zigzag-bot-package.fly.dev"

def start(update: Update, context: CallbackContext):
    """Обробник команди /start."""
    
    # Створюємо інформацію про Web App
    web_app_info = WebAppInfo(url=WEB_APP_URL)
    
    # Створюємо кнопку, яка відкриває Web App
    button = InlineKeyboardButton(
        text="📈 Відкрити торговий термінал",
        web_app=web_app_info
    )
    
    # Створюємо клавіатуру з однією кнопкою
    keyboard = InlineKeyboardMarkup([[button]])
    
    # Відправляємо повідомлення користувачу
    update.message.reply_text(
        "👋 Вітаю! Це торговий термінал ZigZag.\n\n"
        "Натисніть кнопку нижче, щоб відкрити термінал та почати аналіз ринку.",
        reply_markup=keyboard
    )

def register_handlers(dp: Dispatcher):
    """Реєструє всі обробники команд для чат-бота."""
    dp.add_handler(CommandHandler("start", start))