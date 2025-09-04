# telegram_ui.py
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import CallbackContext
from twisted.internet import reactor
from telegram.error import BadRequest

import state
from config import FOREX_SESSIONS, CRYPTO_PAIRS, STOCK_TICKERS, COMMODITIES, TRADING_HOURS, get_chat_id, get_fly_app_name
from analysis import get_api_detailed_signal_data
from redis_client import get_redis # --- ПОЧАТОК ЗМІН: Додано імпорт Redis ---

logger = logging.getLogger(__name__)

TIMEFRAMES = ["1m", "5m", "15m"]

def get_reply_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [[KeyboardButton("МЕНЮ")]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# --- ПОЧАТОК ЗМІН: Оновлено логіку для роботи з Redis ---
def get_main_menu_kb() -> InlineKeyboardMarkup:
    # URL для Web App тепер динамічний
    app_name = get_fly_app_name() or "zigzag-bot-package"
    web_app_url = f"https://{app_name}.fly.dev"
    
    keyboard = [
        [InlineKeyboardButton("🚀 Відкрити термінал", web_app={"url": web_app_url})],
        [InlineKeyboardButton("💹 Валютні пари (Forex)", callback_data="category_forex")],
        [InlineKeyboardButton("💎 Криптовалюти", callback_data="category_crypto")],
        [InlineKeyboardButton("📈 Акції/Індекси", callback_data="category_stocks")],
        [InlineKeyboardButton("🥇 Сировина", callback_data="category_commodities")]
    ]
    
    scanner_map = {
        "forex": "💹 Forex",
        "crypto": "💎 Crypto",
        "commodities": "🥇 Сировина"
    }
    
    try:
        r = get_redis()
        for key, text in scanner_map.items():
            # Читаємо стан сканера з Redis
            is_enabled = r.get(f"scanner_state:{key}") == 'true'
            status_icon = "✅" if is_enabled else "❌"
            button_text = f"{status_icon} Сканер {text}"
            callback_data = f"toggle_scanner_{key}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])
    except Exception as e:
        logger.error(f"Could not read scanner state from Redis: {e}")

    return InlineKeyboardMarkup(keyboard)
# --- КІНЕЦЬ ЗМІН ---

def get_timeframe_kb(category: str) -> InlineKeyboardMarkup:
    # ... (цей код залишається без змін) ...

def get_forex_sessions_kb(timeframe: str) -> InlineKeyboardMarkup:
    # ... (цей код залишається без змін) ...

def get_assets_kb(asset_list: list, category: str, timeframe: str) -> InlineKeyboardMarkup:
    # ... (цей код залишається без змін) ...

def start(update: Update, context: CallbackContext) -> None:
    # ... (цей код залишається без змін) ...

def menu(update: Update, context: CallbackContext) -> None:
    # ... (цей код залишається без змін) ...

def reset_ui(update: Update, context: CallbackContext) -> None:
    # ... (цей код залишається без змін) ...

def symbols_command(update: Update, context: CallbackContext):
    # ... (цей код залишається без змін) ...

def _format_signal_message(result: dict, timeframe: str) -> str:
    # ... (цей код залишається без змін) ...

def button_handler(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    query.answer()
    data = query.data
    context.user_data['last_menu_id'] = query.message.message_id

    parts = data.split('_')
    action = parts[0]

    # --- ПОЧАТОК ЗМІН: Оновлено логіку для роботи з Redis ---
    if action == "toggle" and parts[1] == "scanner":
        category_to_toggle = parts[2]
        try:
            r = get_redis()
            key = f"scanner_state:{category_to_toggle}"
            current_state = r.get(key) == 'true'
            new_state = not current_state
            r.set(key, 'true' if new_state else 'false') # Зберігаємо стан в Redis
            
            status_text = "увімкнено" if new_state else "вимкнено"
            logger.info(f"Scanner for '{category_to_toggle}' toggled via BOT to: {new_state}")
            query.answer(text=f"Сканер для '{category_to_toggle}' {status_text}")
            query.edit_message_text("🏠 Головне меню:", reply_markup=get_main_menu_kb())
        except Exception as e:
            logger.error(f"Failed to toggle scanner state in Redis: {e}")
            query.answer(text="Помилка з'єднання з сервісом.", show_alert=True)
        return
    # --- КІНЕЦЬ ЗМІН ---

    if action == "main":
        # ... (цей код залишається без змін) ...
    
    elif action == "category":
        # ... (цей код залишається без змін) ...

    elif action == "tf":
        # ... (цей код залишається без змін) ...

    elif action == "session":
        # ... (цей код залишається без змін) ...

    elif action == "analyze":
        # ... (цей код залишається без змін) ...

# --- ПОЧАТОК ЗМІН: Додано нові функції для сповіщень ---
def _format_scanner_notification(data):
    """Спрощене форматування для сповіщень."""
    pair = data.get('pair')
    verdict = data.get('verdict_text', 'N/A')
    score = data.get('bull_percentage', 50)
    price = data.get('price', 0)
    
    header = f"🚨 *Сигнал Сканера: {pair} (5m)* 🚨"
    main_info = f"*{verdict}* (Рахунок: {score}%)"
    price_info = f"Ціна: `{price:.5f}`"
    
    return f"{header}\n\n{main_info}\n{price_info}"

def send_scanner_notification(bot, data):
    """Надсилає сповіщення від сканера в основний чат."""
    chat_id = get_chat_id()
    if not chat_id:
        logger.warning("CHAT_ID not set, cannot send notification.")
        return
        
    try:
        message = _format_scanner_notification(data)
        app_name = get_fly_app_name() or "zigzag-bot-package"
        web_app_url = f"https://{app_name}.fly.dev"
        kb = [[InlineKeyboardButton("🚀 Відкрити термінал", web_app={"url": web_app_url})]]
        reply_markup = InlineKeyboardMarkup(kb)
        
        bot.send_message(
            chat_id=chat_id,
            text=message,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.exception(f"Failed to send scanner notification: {e}")
# --- КІНЕЦЬ ЗМІН ---