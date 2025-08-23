# telegram_ui.py
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import CallbackContext
from twisted.internet import reactor
from telegram.error import BadRequest

import state
# --- ПОЧАТОК ЗМІН: Імпортуємо новий список ---
from config import FOREX_SESSIONS, CRYPTO_PAIRS, STOCK_TICKERS, COMMODITIES
# --- КІНЕЦЬ ЗМІН ---
from analysis import get_api_detailed_signal_data

logger = logging.getLogger(__name__)

def get_reply_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [[KeyboardButton("МЕНЮ")]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# --- ПОЧАТОК ЗМІН: Додаємо нові кнопки в меню ---
def get_main_menu_kb() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("💹 Валютні пари (Forex)", callback_data="menu_forex")],
        [InlineKeyboardButton("💎 Криптовалюти", callback_data="menu_crypto")],
        [InlineKeyboardButton("📈 Акції", callback_data="menu_stocks")],
        [InlineKeyboardButton("🥇 Сировина", callback_data="menu_commodities")]
    ]
    return InlineKeyboardMarkup(keyboard)
# --- КІНЕЦЬ ЗМІН ---

def get_forex_sessions_kb() -> InlineKeyboardMarkup:
    keyboard = []
    for session in FOREX_SESSIONS:
        keyboard.append([InlineKeyboardButton(f"--- {session} сесія ---", callback_data=f"session_{session}")])
    keyboard.append([InlineKeyboardButton("⬅️ Назад до меню", callback_data="main_menu")])
    return InlineKeyboardMarkup(keyboard)

# --- ПОЧАТОК ЗМІН: Універсальна функція для побудови клавіатури ---
def get_assets_kb(asset_list: list, back_callback: str) -> InlineKeyboardMarkup:
    """Універсальна функція для створення клавіатури зі списку активів."""
    keyboard = []
    row = []
    for asset in asset_list:
        # Нормалізуємо назву для callback_data
        callback_data = asset.replace("/", "")
        row.append(InlineKeyboardButton(asset, callback_data=callback_data))
        if len(row) == 2:  # Робимо по 2 кнопки в ряд для кращого вигляду
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("⬅️ Назад до меню", callback_data=back_callback)])
    return InlineKeyboardMarkup(keyboard)
# --- КІНЕЦЬ ЗМІН ---

def start(update: Update, context: CallbackContext) -> None:
    update.message.reply_text(
        "👋 Вітаю! Натисніть «МЕНЮ» для вибору активів.",
        reply_markup=get_reply_keyboard()
    )

def menu(update: Update, context: CallbackContext) -> None:
    if 'last_menu_id' in context.user_data:
        try: context.bot.delete_message(chat_id=update.message.chat_id, message_id=context.user_data['last_menu_id'])
        except BadRequest: pass
    sent_message = update.message.reply_text("🏠 Головне меню:", reply_markup=get_main_menu_kb())
    context.user_data['last_menu_id'] = sent_message.message_id

def reset_ui(update: Update, context: CallbackContext) -> None:
    update.message.reply_text(f"Невідома команда: '{update.message.text}'. Використовуйте кнопки.", reply_markup=get_reply_keyboard())

def _format_signal_message(result: dict) -> str:
    # ... (код без змін) ...
    if result.get("error"): return f"❌ Помилка аналізу: {result['error']}"
    pair = result.get('pair', 'N/A')
    price = result.get('price', 0)
    verdict = result.get('verdict_text', 'Не вдалося визначити.')
    support = result.get('support')
    resistance = result.get('resistance')
    reasons = result.get('reasons', [])
    price_str = f"{price:.5f}" if price else "N/A"
    message = f"📈 **Аналіз для {pair}**\n\n"
    message += f"**Сигнал:** {verdict}\n"
    message += f"**Поточна ціна:** `{price_str}`\n\n"
    if support or resistance:
        message += "🔑 **Ключові рівні:**\n"
        if support: message += f"    - Підтримка: `{support:.5f}`\n"
        if resistance: message += f"    - Опір: `{resistance:.5f}`\n"
        message += "\n"
    if reasons:
        message += "📑 **Фактори аналізу:**\n"
        for reason in reasons: message += f"    - {reason}\n"
    return message

# --- ПОЧАТОК ЗМІН: Додаємо обробку нових меню ---
def button_handler(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    query.answer()
    data = query.data
    context.user_data['last_menu_id'] = query.message.message_id

    if data == "main_menu":
        query.edit_message_text("🏠 Головне меню:", reply_markup=get_main_menu_kb())
    elif data == "menu_forex":
        query.edit_message_text("💹 Виберіть торгову сесію:", reply_markup=get_forex_sessions_kb())
    elif data.startswith("session_"):
        session_name = data.split("_")[1]
        pairs = FOREX_SESSIONS.get(session_name, [])
        query.edit_message_text(f"Виберіть пару для сесії '{session_name}':", reply_markup=get_assets_kb(pairs, 'main_menu'))
    elif data == "menu_crypto":
        query.edit_message_text("💎 Виберіть криптовалюту:", reply_markup=get_assets_kb(CRYPTO_PAIRS, 'main_menu'))
    elif data == "menu_stocks":
        query.edit_message_text("📈 Виберіть акцію:", reply_markup=get_assets_kb(STOCK_TICKERS, 'main_menu'))
    elif data == "menu_commodities":
        query.edit_message_text("🥇 Виберіть сировину:", reply_markup=get_assets_kb(COMMODITIES, 'main_menu'))
    else:
        symbol = data
        # ... (решта логіки аналізу без змін) ...
        if not state.client or not state.client.is_authorized:
            query.answer(text="❌ З'єднання з cTrader ще не встановлено.", show_alert=True); return
        if not state.SYMBOLS_LOADED or symbol not in state.symbol_cache:
            query.answer(text=f"⚠️ Символи ще завантажуються або {symbol} не знайдено.", show_alert=True); return
        
        query.edit_message_text(text=f"⏳ Обрано {symbol}. Роблю запит до API...")
        
        def on_success(result):
            message_text = _format_signal_message(result)
            query.edit_message_text(text=message_text, parse_mode='Markdown', reply_markup=get_main_menu_kb())

        def on_error(failure):
            error_message = failure.getErrorMessage() if hasattr(failure, 'getErrorMessage') else str(failure)
            logger.error(f"❌ Помилка при отриманні сигналу для {symbol}: {error_message}")
            query.edit_message_text(text=f"❌ Виникла помилка під час аналізу {symbol}: {error_message}", reply_markup=get_main_menu_kb())

        def do_analysis():
            deferred = get_api_detailed_signal_data(state.client, state.symbol_cache, symbol, query.from_user.id)
            deferred.addCallbacks(on_success, on_error)
            
        reactor.callFromThread(do_analysis)
# --- КІНЕЦЬ ЗМІН ---