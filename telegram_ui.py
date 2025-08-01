# telegram_ui.py
import math
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import CallbackContext, CommandHandler, MessageHandler, Filters, CallbackQueryHandler
from telegram.error import BadRequest

from config import dp, CRYPTO_PAIRS_FULL, CRYPTO_CHUNK_SIZE, STOCK_TICKERS, FOREX_SESSIONS, FOREX_PAIRS_MAP
from db import get_watchlist, toggle_watch
from analysis import get_signal_strength_verdict, get_full_mta_verdict

# --- ПОЧАТОК ЗМІН: Нова функція-воркер для асинхронного аналізу ---
def analysis_worker(context: CallbackContext):
    """Ця функція виконує повільний аналіз у фоні."""
    # Отримуємо дані, передані з основного потоку
    job_context = context.job.context
    query = job_context['query']
    asset = job_context['asset']
    ticker_safe = job_context['ticker_safe']
    display_safe = job_context['display_safe']
    chunk_idx_str = job_context['chunk_idx_str']
    is_refresh = job_context['is_refresh']
    user_id = query.from_user.id
    ticker, display = ticker_safe.replace('~', '/'), display_safe.replace('~', '/')

    # Виконуємо повільний запит
    msg, analysis_data = get_signal_strength_verdict(ticker, display, asset, user_id=user_id, force_refresh=is_refresh)

    # Зберігаємо результат для майбутніх кнопок
    if analysis_data:
        context.user_data[f"analysis_{ticker_safe}"] = analysis_data

    # Готуємо клавіатуру для фінального повідомлення
    watchlist = get_watchlist(user_id)
    watch_text = "🌟 В обраному" if ticker in watchlist else "⭐ В обране"
    
    if asset == 'crypto': back_button_cb = f'menu_crypto_{chunk_idx_str}'
    elif asset == 'forex': back_button_cb = f'session_{next((s for s, p in FOREX_SESSIONS.items() if display in p), "Азіатська")}'
    else: back_button_cb = 'menu_stocks'

    refresh_callback = f'refresh_{asset}_{ticker_safe}_{display_safe}_{chunk_idx_str}'
    details_callback = f'details_{asset}_{ticker_safe}_{display_safe}_{chunk_idx_str}'
    mta_callback = f'fullmta_{asset}_{ticker_safe}_{display_safe}_{chunk_idx_str}'
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Оновити", callback_data=refresh_callback)],
        [InlineKeyboardButton("📊 Детальний огляд (MTA)", callback_data=mta_callback)],
        [InlineKeyboardButton("📝 Деталі вердикту", callback_data=details_callback)],
        [InlineKeyboardButton(watch_text, callback_data=f'togglewatch_{asset}_{ticker_safe}_{display_safe}_{chunk_idx_str}')],
        [InlineKeyboardButton("⬅️ Назад до списку", callback_data=back_button_cb)]
    ])

    # Оновлюємо повідомлення з фінальним результатом
    query.edit_message_text(text=msg, parse_mode='Markdown', reply_markup=kb)
# --- КІНЕЦЬ ЗМІН ---


# ------------------- KEYBOARDS -------------------
def main_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📈 Криптовалюти", callback_data='menu_crypto_0')],
        [InlineKeyboardButton("💹 Валютні пари", callback_data='menu_forex')],
        [InlineKeyboardButton("🏢 Акції", callback_data='menu_stocks')]
    ])

def forex_session_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🗾 Азіатська", callback_data="session_Азіатська")],
        [InlineKeyboardButton("🏦 Європейська", callback_data="session_Європейська")],
        [InlineKeyboardButton("💵 Американська", callback_data="session_Американська")],
        [InlineKeyboardButton("⬅️ НАЗАД", callback_data="main_menu")]
    ])

def asset_list_kb(asset_type, pairs, chunk_index=0):
    keyboard = []
    for pair_name in pairs:
        ticker = FOREX_PAIRS_MAP.get(pair_name, pair_name) if asset_type == 'forex' else pair_name
        callback_data = f'analyze_{asset_type}_{ticker.replace("/", "~")}_{pair_name.replace("/", "~")}_{chunk_index}'
        keyboard.append([InlineKeyboardButton(pair_name, callback_data=callback_data)])
    
    if asset_type == 'forex':
        keyboard.append([InlineKeyboardButton("⬅️ НАЗАД", callback_data='menu_forex')])
    elif asset_type == 'stocks':
        keyboard.append([InlineKeyboardButton("⬅️ НАЗАД", callback_data='main_menu')])
    else: # crypto
        nav_row = []
        total_chunks = math.ceil(len(CRYPTO_PAIRS_FULL) / CRYPTO_CHUNK_SIZE)
        if chunk_index > 0:
            nav_row.append(InlineKeyboardButton("⬅️ Назад", callback_data=f'menu_crypto_{chunk_index - 1}'))
        if chunk_index < total_chunks - 1:
            nav_row.append(InlineKeyboardButton("➡️ Далі", callback_data=f'menu_crypto_{chunk_index + 1}'))
        if nav_row:
            keyboard.append(nav_row)
        keyboard.append([InlineKeyboardButton("🏠 Головне меню", callback_data='main_menu')])
        
    return InlineKeyboardMarkup(keyboard)

# ------------------- HANDLERS -------------------
def start(update: Update, context: CallbackContext):
    keyboard = [["МЕНЮ"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)
    update.message.reply_text("👋 Вітаю! Натисніть «МЕНЮ» нижче.", reply_markup=reply_markup)

def menu(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id
    try:
        context.bot.delete_message(chat_id=chat_id, message_id=update.message.message_id)
    except BadRequest:
        pass
    if 'last_menu_id' in context.user_data:
        try:
            context.bot.delete_message(chat_id=chat_id, message_id=context.user_data['last_menu_id'])
        except BadRequest:
            pass
    sent_message = context.bot.send_message(chat_id=chat_id, text="🏠 Головне меню:", reply_markup=main_kb())
    context.user_data['last_menu_id'] = sent_message.message_id

def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    # --- ПОЧАТОК ЗМІН: Відповідаємо на запит одразу, якщо це можливо ---
    # query.answer() буде викликано або тут, або в `analyze_` блоці
    # --- КІНЕЦЬ ЗМІН ---
    data = query.data
    context.user_data['last_menu_id'] = query.message.message_id
    
    if data == 'main_menu':
        query.answer()
        query.edit_message_text("🏠 Головне меню:", reply_markup=main_kb())

    elif data.startswith('menu_crypto_'):
        query.answer()
        chunk_index = int(data.split('_')[-1])
        start_pos = chunk_index * CRYPTO_CHUNK_SIZE
        end_pos = start_pos + CRYPTO_CHUNK_SIZE
        pairs_chunk = CRYPTO_PAIRS_FULL[start_pos:end_pos]
        
        query.edit_message_text(
            f"📈 Криптовалюти (Сторінка {chunk_index + 1}):", 
            reply_markup=asset_list_kb('crypto', pairs_chunk, chunk_index)
        )

    elif data == 'menu_forex':
        query.answer()
        query.edit_message_text("💹 Виберіть сесію:", reply_markup=forex_session_kb())

    elif data == 'menu_stocks':
        query.answer()
        query.edit_message_text("🏢 Виберіть акцію:", reply_markup=asset_list_kb('stocks', STOCK_TICKERS))

    elif data.startswith('session_'):
        query.answer()
        session = data.split('_')[1]
        pairs = FOREX_SESSIONS.get(session, [])
        query.edit_message_text(f"📊 Пари сесії {session}:", reply_markup=asset_list_kb('forex', pairs))

    # --- ПОЧАТОК ЗМІН: Запускаємо аналіз асинхронно ---
    elif data.startswith('analyze_') or data.startswith('refresh_'):
        query.answer() # Миттєво відповідаємо Telegram
        
        is_refresh = data.startswith('refresh_')
        action, asset, ticker_safe, display_safe, chunk_idx_str = data.split('_', 4)
        
        # Миттєво оновлюємо повідомлення, щоб користувач бачив, що процес почався
        query.edit_message_text(f"⏳ {'Примусово оновлюю' if is_refresh else 'Аналізую'} {display_safe.replace('~', '/')}...")
        
        # Збираємо всі необхідні дані в один словник
        job_context = {
            'query': query, 'asset': asset, 'ticker_safe': ticker_safe,
            'display_safe': display_safe, 'chunk_idx_str': chunk_idx_str,
            'is_refresh': is_refresh
        }
        # Запускаємо нашу повільну функцію у фоновому потоці
        context.job_queue.run_once(analysis_worker, 0, context=job_context, name=f"analysis_{query.id}")
    # --- КІНЕЦЬ ЗМІН ---

    elif data.startswith('details_'):
        query.answer()
        _, asset, ticker_safe, display_safe, chunk_idx_str = data.split('_', 4)
        
        analysis_data = context.user_data.get(f"analysis_{ticker_safe}")
        if not analysis_data:
            query.answer("Дані для деталей застаріли, будь ласка, оновіть сигнал.", show_alert=True)
            return

        reasons = analysis_data.get('reasons', [])
        support = analysis_data.get('support')
        resistance = analysis_data.get('resistance')
        candle = analysis_data.get('candle_pattern')
        volume = analysis_data.get('volume_info')
        
        details_text = "*Ключові фактори:*\n"
        if reasons:
            details_text += "\n".join([f"• _{r}_" for r in reasons])
        else:
            details_text += "_Немає виражених факторів._"
            
        details_text += "\n\n*Додаткова інформація:*\n"
        if candle:
            details_text += f"🕯️ Патерн: *{candle['text']}*\n"
        if support and isinstance(support, (int, float)):
            details_text += f"📉 Підтримка: `{support:.4f}`\n"
        if resistance and isinstance(resistance, (int, float)):
            details_text += f"📈 Опір: `{resistance:.4f}`\n"
        if volume:
             details_text += f"📊 Об'єм: *{volume}*"

        back_callback = f"refresh_{asset}_{ticker_safe}_{display_safe}_{chunk_idx_str}"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад до вердикту", callback_data=back_callback)]])

        query.edit_message_text(text=details_text, parse_mode='Markdown', reply_markup=kb)

    elif data.startswith('togglewatch_'):
        query.answer()
        _, asset, ticker_safe, display_safe, chunk_idx_str = data.split('_', 4)
        ticker, display = ticker_safe.replace('~', '/'), display_safe.replace('~', '/')
        user_id = query.from_user.id
        toggle_watch(user_id, ticker)
        query.answer(text=f"{display} оновлено в списку спостереження!")
        
        # Щоб оновити кнопку, потрібно відтворити всю клавіатуру
        watchlist = get_watchlist(user_id)
        watch_text = "🌟 В обраному" if ticker in watchlist else "⭐ В обране"
        refresh_callback = f'refresh_{asset}_{ticker_safe}_{display_safe}_{chunk_idx_str}'
        mta_callback = f'fullmta_{asset}_{ticker_safe}_{display_safe}_{chunk_idx_str}'
        details_callback = f'details_{asset}_{ticker_safe}_{display_safe}_{chunk_idx_str}'
        if asset == 'crypto': back_button_cb = f'menu_crypto_{chunk_idx_str}'
        elif asset == 'forex': back_button_cb = f'session_{next((s for s, p in FOREX_SESSIONS.items() if display in p), "Азіатська")}'
        else: back_button_cb = 'menu_stocks'
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Оновити", callback_data=refresh_callback)],
            [InlineKeyboardButton("📊 Детальний огляд (MTA)", callback_data=mta_callback)],
            [InlineKeyboardButton("📝 Деталі вердикту", callback_data=details_callback)],
            [InlineKeyboardButton(watch_text, callback_data=data)],
            [InlineKeyboardButton("⬅️ Назад до списку", callback_data=back_button_cb)]
        ])
        query.edit_message_reply_markup(reply_markup=kb)

    elif data.startswith('fullmta_'):
        query.answer()
        parts = data.split('_')
        force_refresh = parts[-1] == 'refresh'
        asset, ticker_safe, display_safe, chunk_idx_str = parts[1], parts[2], parts[3], parts[4]
        ticker, display = ticker_safe.replace('~', '/'), display_safe.replace('~', '/')
        query.edit_message_text(f"⏳ Збираю MTF для {display}...")
        msg = get_full_mta_verdict(ticker, display, asset, force_refresh=force_refresh)
        back_callback = f"{'refresh' if force_refresh else 'analyze'}_{asset}_{ticker_safe}_{display_safe}_{chunk_idx_str}"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад до індексу", callback_data=back_callback)]])
        query.edit_message_text(text=msg, parse_mode='Markdown', reply_markup=kb)

# --- ПОЧАТОК ЗМІН: Потрібно додати job_queue в Updater ---
# Цю зміну потрібно зробити у файлі config.py
# updater = Updater(bot=bot, use_context=True, job_queue=JobQueue())
# Але оскільки ми не можемо редагувати config.py звідси,
# ми додамо job_queue до існуючого updater'а тут.
# В ідеалі, це має бути зроблено при ініціалізації.
from telegram.ext import JobQueue
if not dp.job_queue:
    dp.job_queue = JobQueue()
    dp.job_queue.set_dispatcher(dp)
    dp.job_queue.start()
# --- КІНЕЦЬ ЗМІН ---


dp.add_handler(CommandHandler("start", start))
dp.add_handler(CommandHandler("menu", menu))
dp.add_handler(MessageHandler(Filters.text("МЕНЮ"), menu))
dp.add_handler(CallbackQueryHandler(button_handler))