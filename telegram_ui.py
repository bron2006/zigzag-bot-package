# -*- coding: utf-8 -*-
import logging
from typing import List

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from telegram.ext import (
    CallbackContext,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    Filters,
)

import state
import config
from analysis import get_api_detailed_signal_data

log = logging.getLogger("telegram_ui")

def normalize_for_display(norm: str) -> str:
    n = (norm or "").upper().replace("/", "")
    if len(n) >= 6:
        return f"{n[:3]}/{n[3:6]}"
    return n

# --- Keyboards ---
def main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([[KeyboardButton("МЕНЮ")]], resize_keyboard=True, one_time_keyboard=False)

def main_inline_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("💹 Валютні пари (Forex)", callback_data="menu_forex")]])

def sessions_kb() -> InlineKeyboardMarkup:
    keyboard = []
    for session in config.FOREX_SESSIONS:
        keyboard.append([InlineKeyboardButton(f"--- {session} ---", callback_data=f"session_{session}")])
    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")])
    return InlineKeyboardMarkup(keyboard)

def pairs_kb(session: str) -> InlineKeyboardMarkup:
    pairs = config.FOREX_SESSIONS.get(session, []) if session in config.FOREX_SESSIONS else []
    rows = []
    row = []
    for p in pairs:
        # callback_data as normalized (EURUSD)
        norm = p.replace("/", "").replace("\\", "").upper().strip()
        row.append(InlineKeyboardButton(p, callback_data=norm))
        if len(row) == 3:
            rows.append(row); row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="menu_forex")])
    return InlineKeyboardMarkup(rows)

# --- Handlers ---
def cmd_start(update: Update, context: CallbackContext):
    try:
        update.message.reply_text("Вітаю. Натисніть «МЕНЮ» для вибору активів.", reply_markup=main_menu_kb())
    except Exception:
        log.exception("start failed")

def reset_ui(update: Update, context: CallbackContext):
    if getattr(update, "message", None) and update.message.text != "МЕНЮ":
        cmd_start(update, context)

def menu_handler(update: Update, context: CallbackContext):
    try:
        # delete user message if possible
        try:
            context.bot.delete_message(chat_id=update.message.chat_id, message_id=update.message.message_id)
        except Exception:
            pass
        sent = update.message.reply_text("🏠 Головне меню:", reply_markup=main_inline_menu_kb())
        context.user_data['last_menu_id'] = sent.message_id
    except Exception:
        log.exception("menu_handler failed")

def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    data = query.data or ""
    context.user_data['last_menu_id'] = query.message.message_id

    if data == "main_menu":
        query.edit_message_text("🏠 Головне меню:", reply_markup=main_inline_menu_kb()); return
    if data == "menu_forex":
        query.edit_message_text("💹 Виберіть сесію:", reply_markup=sessions_kb()); return
    if data.startswith("session_"):
        session = data.split("_", 1)[1]
        query.edit_message_text(f"Пари сесії {session}:", reply_markup=pairs_kb(session)); return

    # else data is normalized symbol like EURUSD
    symbol_norm = data.upper().strip()
    if not getattr(state, "client", None) or not getattr(state.client, "isConnected", False):
        query.answer(text="❌ cTrader не підключено", show_alert=True); return
    if symbol_norm not in state.symbol_cache:
        query.answer(text=f"⚠️ Символ {symbol_norm} не знайдено", show_alert=True); return

    display = normalize_for_display(symbol_norm)
    query.edit_message_text(text=f"⏳ Отримую аналіз для {display}...")

    user_id = getattr(query.from_user, "id", None)

    def on_success(result):
        try:
            if isinstance(result, dict) and result.get("error"):
                txt = f"❌ Помилка аналізу: {result['error']}"
            else:
                # format result
                price = result.get("price") if isinstance(result, dict) else None
                verdict = result.get("verdict_text") if isinstance(result, dict) else str(result)
                price_str = f"{float(price):.5f}" if price else "N/A"
                txt = f"📈 Аналіз для {display}\n\nСигнал: {verdict}\nПоточна ціна: `{price_str}`"
            query.edit_message_text(text=txt, parse_mode='Markdown', reply_markup=sessions_kb())
        except Exception:
            log.exception("on_success formatting error")
            query.edit_message_text(text="❌ Помилка при форматуванні результату", reply_markup=sessions_kb())

    def on_error(failure):
        try:
            msg = failure.getErrorMessage() if hasattr(failure, 'getErrorMessage') else str(failure)
        except Exception:
            msg = str(failure)
        log.error("Error getting signal for %s: %s", symbol_norm, msg)
        query.edit_message_text(text=f"❌ Помилка при отриманні сигналу для {display}", reply_markup=sessions_kb())

    # call analysis (returns Deferred in original code)
    d = get_api_detailed_signal_data(state.client, symbol_norm, user_id)
    try:
        d.addCallbacks(on_success, on_error)
    except Exception:
        # if it returned sync result
        try:
            res = d() if callable(d) else d
            on_success(res)
        except Exception:
            on_error(Exception("Unknown"))

# --- registration for main ---
def register_handlers(dispatcher):
    dispatcher.add_handler(CommandHandler("start", cmd_start))
    dispatcher.add_handler(MessageHandler(Filters.regex(r"^(МЕНЮ)$"), menu_handler))
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, reset_ui))
    dispatcher.add_handler(CallbackQueryHandler(button_handler))
