# telegram_ui.py
import math
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import CallbackContext, CommandHandler, MessageHandler, Filters, CallbackQueryHandler
from telegram.error import BadRequest

from config import CRYPTO_PAIRS_FULL, FOREX_SESSIONS, STOCKS_US_SYMBOLS
from db import get_watchlist, toggle_watch
from analysis import get_api_detailed_signal_data, get_api_mta_data

# --- ВИПРАВЛЕННЯ: Функції тепер приймають 'context' ---
def get_signal_strength_verdict(context, ticker, display, asset, user_id=None, force_refresh=False):
    """Адаптер, що викликає основну функцію аналізу і форматує результат."""
    ctrader_service = context.bot_data['ctrader_service']
    # --- ВИПРАВЛЕННЯ: Передаємо ctrader_service першим аргументом ---
    analysis_data = get_api_detailed_signal_data(ctrader_service, ticker, user_id)
    if "error" in analysis_data:
        return f"❌ Помилка для {display}: {analysis_data['error']}", None

    price = analysis_data.get('price', 0)
    verdict_text = analysis_data.get('verdict_text', 'Н/Д')
    msg = f"*{display}* | Ціна: `{price:.5f}`\n\n{verdict_text}"
    return msg, analysis_data

def get_full_mta_verdict(context, ticker, display, asset, user_id=None):
    """Адаптер, що викликає MTA і форматує результат."""
    ctrader_service = context.bot_data['ctrader_service']
    # --- ВИПРАВЛЕННЯ: Передаємо ctrader_service першим аргументом ---
    mta_data = get_api_mta_data(ctrader_service, ticker)
    if not mta_data or "error" in mta_data:
        return f"❌ Помилка MTA для {display}"

    header = f"*Мульти-таймфрейм аналіз для {display}:*\n"
    rows = []
    for item in mta_data:
        signal = item.get('signal', 'N/A')
        tf = item.get('tf', 'N/A')
        emoji = "🔼" if signal == "BUY" else "🔽" if signal == "SELL" else " neutral"
        rows.append(f"`{tf:<5}`: {signal} {emoji}")
    return header + "\n".join(rows)

def main_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⭐ Обране", callback_data='menu_watchlist')],
        [InlineKeyboardButton("💹 Валютні пари", callback_data='menu_forex')],
        [InlineKeyboardButton("💎 Криптовалюти", callback_data='menu_crypto')],
        [InlineKeyboardButton("🏢 Акції США", callback_data='menu_stocks')]
    ])

def forex_session_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🗾 Азіатська", callback_data="session_Азіатська")],
        [InlineKeyboardButton("🏦 Європейська", callback_data="session_Європейська")],
        [InlineKeyboardButton("💵 Американська", callback_data="session_Американська")],
        [InlineKeyboardButton("⬅️ НАЗАД", callback_data="main_menu")]
    ])

def crypto_chunks_kb(pairs, page=0):
    items_per_page = 100
    start_index = page * items_per_page
    end_index = start_index + items_per_page
    
    total_pages = math.ceil(len(pairs) / items_per_page)
    
    buttons = []
    for i in range(start_index, min(end_index, len(pairs)), 10):
        row = []
        for j in range(i, min(i + 10, end_index, len(pairs))):
            chunk_start = pairs[j]
            chunk_end = pairs[min(j + 9, len(pairs)-1)]
            row.append(InlineKeyboardButton(f"{chunk_start[:2]}..-{chunk_end[:2]}..", callback_data=f"crypto_chunk_{j}"))
        buttons.append(row)

    nav_buttons = []
    if page > 0: nav_buttons.append(InlineKeyboardButton("◀️", callback_data=f"crypto_page_{page-1}"))
    nav_buttons.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="noop"))
    if end_index < len(pairs): nav_buttons.append(InlineKeyboardButton("▶️", callback_data=f"crypto_page_{page+1}"))
    buttons.append(nav_buttons)
    buttons.append([InlineKeyboardButton("⬅️ НАЗАД", callback_data="main_menu")])
    return InlineKeyboardMarkup(buttons)

def asset_list_kb(asset_type, pairs, chunk_index=0):
    keyboard = []
    
    if asset_type == 'crypto':
        start = chunk_index
        end = min(start + 10, len(pairs))
        subset_pairs = pairs[start:end]
    else:
        subset_pairs = pairs

    for pair_name in subset_pairs:
        ticker = pair_name
        callback_data = f'analyze_{asset_type}_{ticker.replace("/", "~")}_{pair_name.replace("/", "~")}_{chunk_index}'
        keyboard.append([InlineKeyboardButton(pair_name, callback_data=callback_data)])
    
    back_map = {
        'forex': 'menu_forex',
        'crypto': 'menu_crypto',
        'stocks': 'menu_stocks',
        'watchlist': 'main_menu'
    }
    keyboard.append([InlineKeyboardButton("⬅️ НАЗАД", callback_data=back_map.get(asset_type, 'main_menu'))])
        
    return InlineKeyboardMarkup(keyboard)

def start(update: Update, context: CallbackContext):
    keyboard = [["МЕНЮ"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)
    update.message.reply_text("👋 Вітаю! Я бот для технічного аналізу ринків. Натисніть «МЕНЮ» нижче.", reply_markup=reply_markup)

def menu_command(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id
    if 'last_menu_id' in context.user_data:
        try:
            context.bot.delete_message(chat_id=chat_id, message_id=context.user_data['last_menu_id'])
        except BadRequest:
            pass
    sent_message = context.bot.send_message(chat_id=chat_id, text="🏠 Головне меню:", reply_markup=main_kb())
    context.user_data['last_menu_id'] = sent_message.message_id

def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    data = query.data
    context.user_data['last_menu_id'] = query.message.message_id
    
    if data == 'main_menu':
        query.edit_message_text("🏠 Головне меню:", reply_markup=main_kb())

    elif data == 'menu_forex':
        query.edit_message_text("💹 Виберіть сесію:", reply_markup=forex_session_kb())

    elif data == 'menu_crypto':
        if not CRYPTO_PAIRS_FULL: return query.answer("Вибачте, криптовалюти тимчасово недоступні.", show_alert=True)
        query.edit_message_text("💎 Виберіть діапазон криптовалют:", reply_markup=crypto_chunks_kb(CRYPTO_PAIRS_FULL))
        
    elif data.startswith('crypto_page_'):
        page = int(data.split('_')[2])
        query.edit_message_text("💎 Виберіть діапазон криптовалют:", reply_markup=crypto_chunks_kb(CRYPTO_PAIRS_FULL, page))
    
    elif data == 'menu_stocks':
        if not STOCKS_US_SYMBOLS: return query.answer("Вибачте, акції тимчасово недоступні.", show_alert=True)
        query.edit_message_text("🏢 Акції США:", reply_markup=asset_list_kb('stocks', STOCKS_US_SYMBOLS))

    elif data == 'menu_watchlist':
        user_id = query.from_user.id
        watchlist = get_watchlist(user_id)
        if watchlist:
            query.edit_message_text("⭐ Обрані пари:", reply_markup=asset_list_kb('watchlist', watchlist))
        else:
            query.answer("Ваш список обраного порожній.", show_alert=True)
            
    elif data.startswith('session_'):
        session = data.split('_')[1]
        pairs = FOREX_SESSIONS.get(session, [])
        query.edit_message_text(f"📊 Пари сесії {session}:", reply_markup=asset_list_kb('forex', pairs))

    elif data.startswith('crypto_chunk_'):
        chunk_index = int(data.split('_')[-1])
        query.edit_message_text(f"📊 Криптовалюти:", reply_markup=asset_list_kb('crypto', CRYPTO_PAIRS_FULL, chunk_index))

    elif data.startswith(('analyze_', 'refresh_')):
        is_refresh = data.startswith('refresh_')
        
        parts = data.split('_')
        asset, ticker_safe, display_safe = parts[1], parts[2], parts[3]
        chunk_index = int(parts[4]) if len(parts) > 4 else 0
        ticker, display = ticker_safe.replace('~', '/'), display_safe.replace('~', '/')
        user_id = query.from_user.id
        
        query.edit_message_text(f"⏳ {'Примусово оновлюю' if is_refresh else 'Аналізую'} {display}...")
        
        # --- ВИПРАВЛЕННЯ: Передаємо 'context' у функцію ---
        msg, analysis_data = get_signal_strength_verdict(context, ticker, display, asset, user_id=user_id, force_refresh=is_refresh)
        
        if analysis_data:
            context.user_data[f"analysis_{ticker_safe}"] = analysis_data

        watchlist = get_watchlist(user_id)
        watch_text = "🌟 В обраному" if ticker in watchlist else "⭐ В обране"
        
        back_button_cb = 'main_menu'
        if asset == 'forex':
            back_button_cb = f'session_{next((s for s, p in FOREX_SESSIONS.items() if display in p), "Азіатська")}'
        elif asset == 'crypto':
            back_button_cb = f'crypto_chunk_{chunk_index}'
        elif asset == 'stocks':
            back_button_cb = 'menu_stocks'
        elif asset == 'watchlist':
            back_button_cb = 'menu_watchlist'

        kb_data_prefix = f'{asset}_{ticker_safe}_{display_safe}_{chunk_index}'
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Оновити", callback_data=f'refresh_{kb_data_prefix}')],
            [InlineKeyboardButton("📊 Детальний огляд (MTA)", callback_data=f'fullmta_{kb_data_prefix}')],
            [InlineKeyboardButton("📝 Деталі вердикту", callback_data=f'details_{kb_data_prefix}')],
            [InlineKeyboardButton(watch_text, callback_data=f'togglewatch_{kb_data_prefix}')],
            [InlineKeyboardButton("⬅️ Назад до списку", callback_data=back_button_cb)]
        ])
        query.edit_message_text(text=msg, parse_mode='Markdown', reply_markup=kb)

    elif data.startswith('details_'):
        parts = data.split('_')
        asset, ticker_safe, display_safe, chunk_index = parts[1], parts[2], parts[3], int(parts[4])
        analysis_data = context.user_data.get(f"analysis_{ticker_safe}")
        if not analysis_data:
            return query.answer("Дані застаріли, оновіть сигнал.", show_alert=True)

        reasons = "\n".join([f"• _{r}_" for r in analysis_data.get('reasons', [])]) or "_Немає виражених факторів._"
        support = f"{analysis_data.get('support'):.5f}" if analysis_data.get('support') else "N/A"
        resistance = f"{analysis_data.get('resistance'):.5f}" if analysis_data.get('resistance') else "N/A"
        
        details_text = f"*Ключові фактори:*\n{reasons}\n\n*Рівні:*\n📉 Підтримка: `{support}`\n📈 Опір: `{resistance}`"

        back_callback = f"analyze_{asset}_{ticker_safe}_{display_safe}_{chunk_index}"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад до вердикту", callback_data=back_callback)]])
        query.edit_message_text(text=details_text, parse_mode='Markdown', reply_markup=kb)

    elif data.startswith('togglewatch_'):
        parts = data.split('_')
        asset, ticker_safe, display_safe, chunk_index = parts[1], parts[2], parts[3], int(parts[4])
        ticker = ticker_safe.replace('~', '/')
        user_id = query.from_user.id
        toggle_watch(user_id, ticker)
        query.answer(text=f"{ticker} оновлено в списку спостереження!", show_alert=True)
        current_kb = query.message.reply_markup.inline_keyboard
        watchlist = get_watchlist(user_id)
        watch_text = "🌟 В обраному" if ticker in watchlist else "⭐ В обране"
        for row in current_kb:
            for button in row:
                if button.callback_data.startswith('togglewatch_'):
                    button.text = watch_text
        query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(current_kb))

    elif data.startswith('fullmta_'):
        parts = data.split('_')
        asset, ticker_safe, display_safe, chunk_index = parts[1], parts[2], parts[3], int(parts[4])
        ticker, display = ticker_safe.replace('~', '/'), display_safe.replace('~', '/')
        user_id = query.from_user.id
        query.edit_message_text(f"⏳ Збираю MTF для {display}...")
        # --- ВИПРАВЛЕННЯ: Передаємо 'context' у функцію ---
        msg = get_full_mta_verdict(context, ticker, display, asset, user_id=user_id)
        back_callback = f"analyze_{asset}_{ticker_safe}_{display_safe}_{chunk_index}"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад до вердикту", callback_data=back_callback)]])
        query.edit_message_text(text=msg, parse_mode='Markdown', reply_markup=kb)

def register_handlers(dispatcher):
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(MessageHandler(Filters.text("МЕНЮ"), menu_command))
    dispatcher.add_handler(CallbackQueryHandler(button_handler))