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

import analysis
import config

log = logging.getLogger("telegram_ui")

# ---------- УТИЛІТИ ДЛЯ ВІДПОВІДЕЙ ----------
def on_success(data):
    return {"ok": True, "data": data}

def on_error(code, message, details=None):
    err = {"ok": False, "error": {"code": code, "message": message}}
    if details is not None:
        err["error"]["details"] = str(details)
    return err

# ---------- ПОСТІЙНА КЛАВІАТУРА ----------
def _main_menu_kb() -> ReplyKeyboardMarkup:
    # Саме one_time_keyboard=False фіксує клавіатуру назавжди
    return ReplyKeyboardMarkup(
        [[KeyboardButton("МЕНЮ")]],
        resize_keyboard=True,
        one_time_keyboard=False,
    )

# ---------- INLINE КНОПКИ З ПАРАМИ ----------
def _pairs_inline_kb(pairs: List[str]) -> InlineKeyboardMarkup:
    rows = []
    row = []
    for i, p in enumerate(pairs):
        row.append(InlineKeyboardButton(p, callback_data=f"PAIR:{p}"))
        if (i + 1) % 3 == 0:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(rows)

def _list_pairs() -> List[str]:
    # Беремо з конфіга або фолбек
    pairs = getattr(config, "FOREX_PAIRS", None) or ["EUR/USD", "GBP/USD", "USD/JPY", "BTC/USD", "ETH/USD"]
    # Перші 12 для компактної клавіатури
    return pairs[:12]

# ---------- ХЕНДЛЕРИ ----------
def cmd_start(update: Update, context: CallbackContext):
    try:
        update.message.reply_text(
            "Головне меню відкрито. Оберіть «МЕНЮ» нижче, щоб вибрати пару.",
            reply_markup=_main_menu_kb(),
        )
        # Можемо відразу показати інлайн-кнопки з парами
        pairs = _list_pairs()
        update.message.reply_text("Виберіть торгову пару:", reply_markup=_pairs_inline_kb(pairs))
    except Exception as e:
        log.exception("cmd_start failed")
        update.message.reply_text("Виникла помилка при відкритті меню.")

def msg_menu(update: Update, context: CallbackContext):
    try:
        pairs = _list_pairs()
        update.message.reply_text("Виберіть торгову пару:", reply_markup=_pairs_inline_kb(pairs))
    except Exception as e:
        log.exception("msg_menu failed")
        update.message.reply_text("Не вдалося показати меню.")

def cb_pair(update: Update, context: CallbackContext):
    query = update.callback_query
    try:
        query.answer()
        data = query.data or ""
        if not data.startswith("PAIR:"):
            query.edit_message_text("Невідома дія.")
            return
        pair = data.split(":", 1)[1]
        # Отримуємо сигнал
        res = analysis.get_signal(pair)
        # Підтримка корутин/синхронного виклику
        if hasattr(res, "__await__"):
            # якщо async
            import asyncio
            res = asyncio.get_event_loop().run_until_complete(res)

        text = f"Пара: {pair}\nСигнал: {res}"
        query.edit_message_text(text)
    except Exception as e:
        log.exception("cb_pair failed")
        query.edit_message_text("Помилка аналізу. Спробуйте ще раз.")

# ---------- ПУБЛІЧНИЙ API ДЛЯ main.py ----------
def register_handlers(dp):
    dp.add_handler(CommandHandler("start", cmd_start))
    # Постійна кнопка «МЕНЮ» — звичайний текстовий меседж
    dp.add_handler(MessageHandler(Filters.regex(r"^(МЕНЮ)$"), msg_menu))
    # Обробка натискань на інлайн-кнопки з парами
    dp.add_handler(CallbackQueryHandler(cb_pair))
