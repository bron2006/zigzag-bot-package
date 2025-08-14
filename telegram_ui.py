# telegram_ui.py
import math
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import CallbackContext, CommandHandler, MessageHandler, Filters, CallbackQueryHandler
from telegram.error import BadRequest

# --- ВИДАЛЕНО ЗАЙВІ ІМПОРТИ ---
from config import FOREX_SESSIONS
from db import get_watchlist, toggle_watch
from analysis import get_signal_strength_verdict, get_full_mta_verdict

# --- ВИДАЛЕНО ГЛОБАЛЬНУ ЗМІННУ dp ---

def main_kb():
    # --- ЗАЛИШАЄМО ТІЛЬКИ FOREX ---
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💹 Валютні пари", callback_data='menu_forex')],
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
        # --- ВИДАЛЕНО chunk_index з callback_data, бо він потрібен лише для крипто ---
        callback_data = f'analyze_{asset_type}_{ticker.replace("/", "~")}_{pair_name.replace("/", "~")}'
        keyboard.append([InlineKeyboardButton(pair_name, callback_data=callback_data)])
    
    if asset_type == 'forex':
        keyboard.append([InlineKeyboardButton("⬅️ НАЗАД", callback_data='menu_forex')])
        
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

    elif data == 'menu_forex':
        query.edit_message_text("💹 Виберіть сесію:", reply_markup=forex_session_kb())

    elif data.startswith('session_'):
        session = data.split('_')[1]
        pairs = FOREX_SESSIONS.get(session, [])
        query.edit_message_text(f"📊 Пари сесії {session}:", reply_markup=asset_list_kb('forex', pairs))

    elif data.startswith(('analyze_', 'refresh_')):
        is_refresh = data.startswith('refresh_')
        # --- СПРОЩЕНО РОЗБІР callback_data ---
        parts = data.split('_')
        asset, ticker_safe, display_safe = parts[1], parts[2], parts[3]
        ticker, display = ticker_safe.replace('~', '/'), display_safe.replace('~', '/')
        user_id = query.from_user.id
        
        query.edit_message_text(f"⏳ {'Примусово оновлюю' if is_refresh else 'Аналізую'} {display}...")
        
        msg, analysis_data = get_signal_strength_verdict(ticker, display, asset, user_id=user_id, force_refresh=is_refresh)
        
        if analysis_data: context.user_data[f"analysis_{ticker_safe}"] = analysis_data

        watchlist = get_watchlist(user_id)
        watch_text = "🌟 В обраному" if ticker in watchlist else "⭐ В обране"
        
        back_button_cb = f'session_{next((s for s, p in FOREX_SESSIONS.items() if display in p), "Азіатська")}'

        kb_data_prefix = f'{asset}_{ticker_safe}_{display_safe}'
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
        asset, ticker_safe, display_safe = parts[1], parts[2], parts[3]
        analysis_data = context.user_data.get(f"analysis_{ticker_safe}")
        if not analysis_data: return query.answer("Дані застаріли, оновіть сигнал.", show_alert=True)

        reasons = "\n".join([f"• _{r}_" for r in analysis_data.get('reasons', [])]) or "_Немає виражених факторів._"
        support = f"{analysis_data.get('support'):.5f}" if analysis_data.get('support') else "N/A"
        resistance = f"{analysis_data.get('resistance'):.5f}" if analysis_data.get('resistance') else "N/A"
        
        details_text = f"*Ключові фактори:*\n{reasons}\n\n*Рівні:*\n📉 Підтримка: `{support}`\n📈 Опір: `{resistance}`"

        back_callback = f"analyze_{asset}_{ticker_safe}_{display_safe}"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад до вердикту", callback_data=back_callback)]])
        query.edit_message_text(text=details_text, parse_mode='Markdown', reply_markup=kb)

    elif data.startswith('togglewatch_'):
        parts = data.split('_')
        asset, ticker_safe, display_safe = parts[1], parts[2], parts[3]
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
        asset, ticker_safe, display_safe = parts[1], parts[2], parts[3]
        ticker, display = ticker_safe.replace('~', '/'), display_safe.replace('~', '/')
        user_id = query.from_user.id
        query.edit_message_text(f"⏳ Збираю MTF для {display}...")
        msg = get_full_mta_verdict(ticker, display, asset, user_id=user_id)
        back_callback = f"analyze_{asset}_{ticker_safe}_{display_safe}"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад до вердикту", callback_data=back_callback)]])
        query.edit_message_text(text=msg, parse_mode='Markdown', reply_markup=kb)


def register_handlers(dispatcher):
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(MessageHandler(Filters.text("МЕНЮ"), menu_command))
    dispatcher.add_handler(CallbackQueryHandler(button_handler))