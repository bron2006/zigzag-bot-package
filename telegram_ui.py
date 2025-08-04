# telegram_ui.py
import math
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import CallbackContext, CommandHandler, MessageHandler, Filters, CallbackQueryHandler
from telegram.error import BadRequest

from config import CRYPTO_PAIRS_FULL, CRYPTO_CHUNK_SIZE, STOCK_TICKERS, FOREX_SESSIONS
from db import get_watchlist, toggle_watch
from analysis import get_signal_strength_verdict, get_full_mta_verdict

dp = None

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
        ticker = pair_name
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
        if nav_row: keyboard.append(nav_row)
        keyboard.append([InlineKeyboardButton("🏠 Головне меню", callback_data='main_menu')])
        
    return InlineKeyboardMarkup(keyboard)

def start(update: Update, context: CallbackContext):
    keyboard = [["МЕНЮ"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)
    update.message.reply_text("👋 Вітаю! Натисніть «МЕНЮ» нижче.", reply_markup=reply_markup)

def menu_command(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id
    try: context.bot.delete_message(chat_id=chat_id, message_id=update.message.message_id)
    except BadRequest: pass
    if 'last_menu_id' in context.user_data:
        try: context.bot.delete_message(chat_id=chat_id, message_id=context.user_data['last_menu_id'])
        except BadRequest: pass
    sent_message = context.bot.send_message(chat_id=chat_id, text="🏠 Головне меню:", reply_markup=main_kb())
    context.user_data['last_menu_id'] = sent_message.message_id

def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    data = query.data
    context.user_data['last_menu_id'] = query.message.message_id
    
    if data == 'main_menu':
        query.edit_message_text("🏠 Головне меню:", reply_markup=main_kb())

    elif data.startswith('menu_crypto_'):
        chunk_index = int(data.split('_')[-1])
        start_pos, end_pos = chunk_index * CRYPTO_CHUNK_SIZE, (chunk_index + 1) * CRYPTO_CHUNK_SIZE
        pairs_chunk = CRYPTO_PAIRS_FULL[start_pos:end_pos]
        query.edit_message_text(f"📈 Криптовалюти (Сторінка {chunk_index + 1}):", reply_markup=asset_list_kb('crypto', pairs_chunk, chunk_index))

    elif data == 'menu_forex':
        query.edit_message_text("💹 Виберіть сесію:", reply_markup=forex_session_kb())
    
    elif data == 'menu_stocks':
        query.edit_message_text("🏢 Виберіть акцію:", reply_markup=asset_list_kb('stocks', STOCK_TICKERS))

    elif data.startswith('session_'):
        session = data.split('_')[1]
        pairs = FOREX_SESSIONS.get(session, [])
        query.edit_message_text(f"📊 Пари сесії {session}:", reply_markup=asset_list_kb('forex', pairs))

    elif data.startswith(('analyze_', 'refresh_')):
        is_refresh = data.startswith('refresh_')
        _, asset, ticker_safe, display_safe, chunk_idx_str = data.split('_', 4)
        ticker, display = ticker_safe.replace('~', '/'), display_safe.replace('~', '/')
        user_id = query.from_user.id
        
        query.edit_message_text(f"⏳ {'Примусово оновлюю' if is_refresh else 'Аналізую'} {display}...")
        
        msg, analysis_data = get_signal_strength_verdict(ticker, display, asset, user_id=user_id, force_refresh=is_refresh)
        
        if analysis_data: context.user_data[f"analysis_{ticker_safe}"] = analysis_data

        watchlist = get_watchlist(user_id)
        watch_text = "🌟 В обраному" if ticker in watchlist else "⭐ В обране"
        
        if asset == 'crypto': back_button_cb = f'menu_crypto_{chunk_idx_str}'
        elif asset == 'forex': back_button_cb = f'session_{next((s for s, p in FOREX_SESSIONS.items() if display in p), "Азіатська")}'
        else: back_button_cb = 'menu_stocks'

        kb_data_prefix = f'{asset}_{ticker_safe}_{display_safe}_{chunk_idx_str}'
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Оновити", callback_data=f'refresh_{kb_data_prefix}')],
            [InlineKeyboardButton("📊 Детальний огляд (MTA)", callback_data=f'fullmta_{kb_data_prefix}')],
            [InlineKeyboardButton("📝 Деталі вердикту", callback_data=f'details_{kb_data_prefix}')],
            [InlineKeyboardButton(watch_text, callback_data=f'togglewatch_{kb_data_prefix}')],
            [InlineKeyboardButton("⬅️ Назад до списку", callback_data=back_button_cb)]
        ])
        query.edit_message_text(text=msg, parse_mode='Markdown', reply_markup=kb)

    elif data.startswith('details_'):
        _, asset, ticker_safe, display_safe, chunk_idx_str = data.split('_', 4)
        analysis_data = context.user_data.get(f"analysis_{ticker_safe}")
        if not analysis_data: return query.answer("Дані застаріли, оновіть сигнал.", show_alert=True)

        reasons = "\n".join([f"• _{r}_" for r in analysis_data.get('reasons', [])]) or "_Немає виражених факторів._"
        support = f"{analysis_data.get('support'):.5f}" if analysis_data.get('support') else "N/A"
        resistance = f"{analysis_data.get('resistance'):.5f}" if analysis_data.get('resistance') else "N/A"
        
        details_text = f"*Ключові фактори:*\n{reasons}\n\n*Рівні:*\n📉 Підтримка: `{support}`\n📈 Опір: `{resistance}`"

        back_callback = f"analyze_{asset}_{ticker_safe}_{display_safe}_{chunk_idx_str}"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад до вердикту", callback_data=back_callback)]])
        query.edit_message_text(text=details_text, parse_mode='Markdown', reply_markup=kb)

    elif data.startswith('togglewatch_'):
        _, asset, ticker_safe, display_safe, chunk_idx_str = data.split('_', 4)
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
        _, asset, ticker_safe, display_safe, chunk_idx_str = data.split('_', 4)
        ticker, display = ticker_safe.replace('~', '/'), display_safe.replace('~', '/')
        user_id = query.from_user.id
        query.edit_message_text(f"⏳ Збираю MTF для {display}...")
        msg = get_full_mta_verdict(ticker, display, asset, user_id=user_id)
        back_callback = f"analyze_{asset}_{ticker_safe}_{display_safe}_{chunk_idx_str}"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад до вердикту", callback_data=back_callback)]])
        query.edit_message_text(text=msg, parse_mode='Markdown', reply_markup=kb)

def register_handlers(dispatcher):
    global dp
    dp = dispatcher
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(MessageHandler(Filters.text("МЕНЮ"), menu_command))
    dp.add_handler(CallbackQueryHandler(button_handler))