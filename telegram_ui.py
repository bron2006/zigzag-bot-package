# telegram_ui.py

import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackContext

# Імпортуємо глобальний стан, який вже ініціалізовано в main.py
import state

logger = logging.getLogger(__name__)

# --- Клавіатури ---

def get_main_menu_keyboard():
    """Створює головну клавіатуру меню."""
    keyboard = [
        [InlineKeyboardButton("📈 Статус підключення", callback_data='status')],
        [InlineKeyboardButton("📂 Список рахунків", callback_data='accounts')],
        [InlineKeyboardButton("⚙️ Налаштування", callback_data='settings')],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_accounts_keyboard():
    """Створює клавіатуру для списку рахунків."""
    # У майбутньому тут буде динамічне отримання рахунків з state.client
    keyboard = [
        [InlineKeyboardButton("Рахунок Demo 12345", callback_data='acc_details_12345')],
        [InlineKeyboardButton("Рахунок Live 67890", callback_data='acc_details_67890')],
        [InlineKeyboardButton("⬅️ Назад", callback_data='main_menu')],
    ]
    return InlineKeyboardMarkup(keyboard)

# --- Обробники команд (викликаються з main.py) ---

def start(update: Update, context: CallbackContext) -> None:
    """Обробник команди /start."""
    user = update.effective_user
    update.message.reply_html(
        f"👋 Привіт, {user.mention_html()}!\n\n"
        "Я ваш торговий асистент для cTrader. Оберіть опцію нижче:",
        reply_markup=get_main_menu_keyboard()
    )

def menu(update: Update, context: CallbackContext) -> None:
    """Обробник текстового повідомлення 'МЕНЮ'."""
    update.message.reply_text(
        "Головне меню:",
        reply_markup=get_main_menu_keyboard()
    )

def reset_ui(update: Update, context: CallbackContext) -> None:
    """Скидає будь-який ввід і показує меню."""
    update.message.reply_text(
        f"Невідома команда: '{update.message.text}'.\n"
        "Будь ласка, використовуйте кнопки меню.",
        reply_markup=get_main_menu_keyboard()
    )

# --- Обробник кнопок (CallbackQueryHandler) ---

def button_handler(update: Update, context: CallbackContext) -> None:
    """Центральний обробник для всіх натискань на inline-кнопки."""
    query = update.callback_query
    query.answer()  # Обов'язково відповідаємо на запит
    data = query.data

    if data == 'main_menu':
        query.edit_message_text(text="Головне меню:", reply_markup=get_main_menu_keyboard())

    elif data == 'status':
        if state.client and state.client.is_authorized:
            status_text = "✅ Авторизовано та підключено."
        else:
            status_text = "❌ Відключено або в процесі підключення."
        query.edit_message_text(text=f"Статус підключення до cTrader:\n\n{status_text}", reply_markup=get_main_menu_keyboard())

    elif data == 'accounts':
        query.edit_message_text(text="Оберіть рахунок:", reply_markup=get_accounts_keyboard())
    
    elif data.startswith('acc_details_'):
        account_id = data.replace('acc_details_', '')
        # Тут буде логіка отримання реальних даних
        details_text = f"Детальна інформація по рахунку {account_id}:\n\n- Баланс: ...\n- кредитне плече: ..."
        query.edit_message_text(text=details_text, reply_markup=get_accounts_keyboard())

    elif data == 'settings':
        query.edit_message_text(text="Розділ налаштувань наразі в розробці.", reply_markup=get_main_menu_keyboard())