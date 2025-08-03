# telegram_ui.py
import math
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import CallbackContext, CommandHandler, MessageHandler, Filters, CallbackQueryHandler
from telegram.error import BadRequest

# Тепер імпортуємо лише константи
from config import CRYPTO_PAIRS_FULL, CRYPTO_CHUNK_SIZE, STOCK_TICKERS, FOREX_SESSIONS, ANALYSIS_TIMEFRAMES
from db import get_watchlist, toggle_watch
from analysis import get_full_mta_verdict, analyze_pair # Імпортуємо потрібні функції

# Глобальні змінні, які будуть ініціалізовані в bot.py
bot = None
dp = None

# --- ПОЧАТОК ЗМІН: Відновлено та об'єднано весь функціонал ---

# --- Клавіатури ---

def build_main_menu_keyboard():
    """Створює головне меню."""
    keyboard = [
        [InlineKeyboardButton("💎 Криптовалюта", callback_data='show_crypto_0')],
        [InlineKeyboardButton("💵 Форекс", callback_data='show_forex')],
        [InlineKeyboardButton("📈 Акції", callback_data='show_stocks')],
        [InlineKeyboardButton("⭐ Обране", callback_data='show_watchlist')]
    ]
    return InlineKeyboardMarkup(keyboard)

def build_crypto_keyboard(page=0):
    """Створює клавіатуру для криптовалют з пагінацією."""
    start_index = page * CRYPTO_CHUNK_SIZE
    end_index = start_index + CRYPTO_CHUNK_SIZE
    pairs_chunk = CRYPTO_PAIRS_FULL[start_index:end_index]
    
    keyboard = [
        [InlineKeyboardButton(pair, callback_data=f'analyze_{pair}')] for pair in pairs_chunk
    ]
    
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Назад", callback_data=f'show_crypto_{page-1}'))
    if end_index < len(CRYPTO_PAIRS_FULL):
        nav_buttons.append(InlineKeyboardButton("Вперед ➡️", callback_data=f'show_crypto_{page+1}'))
    
    keyboard.append(nav_buttons)
    keyboard.append([InlineKeyboardButton("🔙 Головне меню", callback_data='main_menu')])
    return InlineKeyboardMarkup(keyboard)

def build_forex_keyboard():
    """Створює клавіатуру для Форекс пар."""
    keyboard = []
    for session, pairs in FOREX_SESSIONS.items():
        keyboard.append([InlineKeyboardButton(f"--- {session} ---", callback_data='noop')])
        for pair in pairs:
            keyboard.append([InlineKeyboardButton(pair, callback_data=f'analyze_{pair}')])
    keyboard.append([InlineKeyboardButton("🔙 Головне меню", callback_data='main_menu')])
    return InlineKeyboardMarkup(keyboard)

def build_stocks_keyboard():
    """Створює клавіатуру для акцій."""
    keyboard = [
        [InlineKeyboardButton(ticker, callback_data=f'analyze_{ticker}')] for ticker in STOCK_TICKERS
    ]
    keyboard.append([InlineKeyboardButton("🔙 Головне меню", callback_data='main_menu')])
    return InlineKeyboardMarkup(keyboard)

def build_watchlist_keyboard(user_id):
    """Створює клавіатуру зі списку обраного."""
    watchlist = get_watchlist(user_id)
    if not watchlist:
        keyboard = [
            [InlineKeyboardButton("Список порожній. Додайте активи.", callback_data='noop')],
            [InlineKeyboardButton("🔙 Головне меню", callback_data='main_menu')]
        ]
        return InlineKeyboardMarkup(keyboard)
        
    keyboard = [
        [InlineKeyboardButton(pair, callback_data=f'analyze_{pair}')] for pair in watchlist
    ]
    keyboard.append([InlineKeyboardButton("🔙 Головне меню", callback_data='main_menu')])
    return InlineKeyboardMarkup(keyboard)

# --- Обробники команд ---

def start(update: Update, context: CallbackContext) -> None:
    """Обробник команди /start."""
    reply_markup = build_main_menu_keyboard()
    update.message.reply_text(
        "Привіт! Я бот для аналізу ринків. Оберіть категорію активів:",
        reply_markup=reply_markup
    )

def menu(update: Update, context: CallbackContext) -> None:
    """Повертає користувача в головне меню."""
    query = update.callback_query
    if query:
        query.answer()
        reply_markup = build_main_menu_keyboard()
        try:
            query.edit_message_text(
                "Головне меню. Оберіть категорію активів:",
                reply_markup=reply_markup
            )
        except BadRequest: # Повідомлення не змінилося
            pass
    elif update.message:
        reply_markup = build_main_menu_keyboard()
        update.message.reply_text(
            "Головне меню. Оберіть категорію активів:",
            reply_markup=reply_markup
        )

def analysis_worker(context: CallbackContext):
    """Фоновий воркер для надсилання аналізу."""
    job_data = context.job.context
    chat_id = job_data['chat_id']
    pair = job_data['pair']
    message_id = job_data['message_id']

    results = [analyze_pair(pair, tf) for tf in ANALYSIS_TIMEFRAMES]
    
    verdict = get_signal_strength_verdict(results)
    
    mta_table = "Мульти-таймфрейм аналіз:\n"
    for res in results:
        tf = res.get('timeframe', 'N/A')
        signal = res.get('signal', 'N/A')
        mta_table += f"{tf}: {signal}\n"

    final_text = f"Аналіз для *{pair}*:\n\n{verdict}\n\n`{mta_table}`"

    context.bot.edit_message_text(
        chat_id=chat_id,
        message_id=message_id,
        text=final_text,
        parse_mode='Markdown'
    )

# --- Обробник кнопок ---

def button_handler(update: Update, context: CallbackContext) -> None:
    """Обробляє натискання на всі inline-кнопки."""
    query = update.callback_query
    query.answer()
    data = query.data
    user_id = query.from_user.id

    if data.startswith('show_crypto_'):
        page = int(data.split('_')[2])
        reply_markup = build_crypto_keyboard(page)
        query.edit_message_text("Оберіть криптовалютну пару:", reply_markup=reply_markup)
        
    elif data == 'show_forex':
        reply_markup = build_forex_keyboard()
        query.edit_message_text("Оберіть валютну пару:", reply_markup=reply_markup)

    elif data == 'show_stocks':
        reply_markup = build_stocks_keyboard()
        query.edit_message_text("Оберіть акцію:", reply_markup=reply_markup)
        
    elif data == 'show_watchlist':
        reply_markup = build_watchlist_keyboard(user_id)
        query.edit_message_text("Ваш список обраного:", reply_markup=reply_markup)

    elif data.startswith('analyze_'):
        pair = data.split('_', 1)[1]
        
        # Використовуємо get_full_mta_verdict для отримання швидкого аналізу
        # Оскільки ANALYSIS_TIMEFRAMES - це список, ми візьмемо перший (наприклад, '15min') для швидкого огляду
        timeframe_for_quick_look = ANALYSIS_TIMEFRAMES[0] if ANALYSIS_TIMEFRAMES else '1h'
        verdict_text = get_full_mta_verdict([pair], timeframe_for_quick_look)
        
        query.edit_message_text(f"Аналіз для {pair}:\n\n{verdict_text}")

    elif data == 'main_menu':
        menu(update, context)

    elif data == 'noop':
        # Нічого не робимо, кнопка лише для інформації
        pass

# --- Реєстрація обробників ---

def register_handlers(dispatcher):
    """Реєструє всі обробники команд та кнопок."""
    global dp, bot
    dp = dispatcher
    bot = dp.bot

    # Реєстрація всіх ваших обробників
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("menu", menu))
    # dp.add_handler(MessageHandler(Filters.regex(r'^МЕНЮ$'), menu)) # Можна видалити, якщо використовуєте лише inline
    dp.add_handler(CallbackQueryHandler(button_handler))

# --- КІНЕЦЬ ЗМІН ---