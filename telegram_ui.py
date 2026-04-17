# telegram_ui.py
import html
import logging
import time
from typing import Callable

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.ext import CallbackContext
from twisted.internet import reactor
from twisted.internet.threads import deferToThreadPool

import db
from analysis import get_api_detailed_signal_data
from config import COMMODITIES, CRYPTO_PAIRS, FOREX_SESSIONS, STOCK_TICKERS, TRADING_HOURS
from state import app_state
from utils_message_cleanup import bot_clear_messages, bot_track_message

logger = logging.getLogger(__name__)

EXPIRATIONS = ["1m", "5m", "15m"]


def _blocking_pool():
    return app_state.blocking_pool or reactor.getThreadPool()


def _get_chat_id(update: Update) -> int:
    if update.effective_chat:
        return update.effective_chat.id
    if update.callback_query and update.callback_query.message:
        return update.callback_query.message.chat_id
    if update.effective_user:
        return update.effective_user.id
    return 0


def _safe_delete(bot, chat_id: int, message_id: int):
    try:
        bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass


def _bot_call_async(func: Callable, *args, **kwargs):
    return deferToThreadPool(
        reactor,
        _blocking_pool(),
        func,
        *args,
        **kwargs,
    )


def get_reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([[KeyboardButton("МЕНЮ")]], resize_keyboard=True)


def get_main_menu_kb() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("⭐ Мій список (Обране)", callback_data="category_watchlist")],
        [InlineKeyboardButton("💹 Валютні пари (Forex)", callback_data="category_forex")],
        [InlineKeyboardButton("💎 Криптовалюти", callback_data="category_crypto")],
        [InlineKeyboardButton("📈 Акції/Індекси", callback_data="category_stocks")],
        [InlineKeyboardButton("🥇 Сировина", callback_data="category_commodities")],
    ]

    scanner_map = {
        "forex": "💹 Forex",
        "crypto": "💎 Crypto",
        "commodities": "🥇 Сировина",
        "watchlist": "⭐ Обране",
    }

    for key, text in scanner_map.items():
        status = "✅" if app_state.get_scanner_state(key) else "❌"
        keyboard.append(
            [InlineKeyboardButton(f"{status} Сканер {text}", callback_data=f"toggle_scanner_{key}")]
        )

    return InlineKeyboardMarkup(keyboard)


def get_expiration_kb(category: str) -> InlineKeyboardMarkup:
    kb = [[InlineKeyboardButton(exp, callback_data=f"exp_{category}_{exp}") for exp in EXPIRATIONS]]
    kb.append([InlineKeyboardButton("⬅️ Назад до категорій", callback_data="main_menu")])
    return InlineKeyboardMarkup(kb)


def get_forex_sessions_kb(expiration: str) -> InlineKeyboardMarkup:
    kb = [
        [
            InlineKeyboardButton(
                f"{TRADING_HOURS.get(s, '')} {s}".strip(),
                callback_data=f"session_forex_{expiration}_{s}",
            )
        ]
        for s in FOREX_SESSIONS
    ]
    kb.append([InlineKeyboardButton("⬅️ Назад до експірацій", callback_data="category_forex")])
    return InlineKeyboardMarkup(kb)


def get_assets_kb(asset_list: list, category: str, expiration: str) -> InlineKeyboardMarkup:
    kb, row = [], []

    for asset in asset_list:
        clean = asset.replace("/", "").upper()
        callback_data = f"analyze_{expiration}_{clean}"

        row.append(InlineKeyboardButton(asset, callback_data=callback_data))

        if len(row) == 2:
            kb.append(row)
            row = []

    if row:
        kb.append(row)

    back = "⬅️ Назад до сесій" if category == "forex" else "⬅️ Назад до експірацій"
    callback_back = f"exp_forex_{expiration}" if category == "forex" else f"category_{category}"
    kb.append([InlineKeyboardButton(back, callback_data=callback_back)])

    return InlineKeyboardMarkup(kb)


def _safe_html(value) -> str:
    return html.escape("" if value is None else str(value))


def _label_verdict(value) -> str:
    labels = {
        "BUY": "купівля",
        "SELL": "продаж",
        "NEUTRAL": "нейтрально",
        "WAIT": "очікування",
        "NEWS_WAIT": "пауза через новини",
        "ERROR": "помилка",
    }
    return labels.get(str(value or "").upper(), "невідомо")


def _label_sentiment(value) -> str:
    labels = {
        "GO": "дозволено",
        "BLOCK": "заблоковано",
    }
    return labels.get(str(value or "").upper(), "невідомо")


def _label_timeframe(value) -> str:
    labels = {
        "1m": "1 хв",
        "5m": "5 хв",
        "15m": "15 хв",
    }
    return labels.get(str(value or ""), "" if value is None else str(value))


def _format_reason_uk(reason) -> str:
    text = "" if reason is None else str(reason)

    replacements = {
        "NEWS_WAIT": "пауза через новини",
        "NEUTRAL": "нейтрально",
        "BLOCK": "заблоковано",
        "BUY": "купівля",
        "SELL": "продаж",
        "WAIT": "очікування",
        "ERROR": "помилка",
        "GO": "дозволено",
        "TF:": "Таймфрейми:",
        "News filter:": "Фільтр новин:",
        "ML": "ШІ",
        "fallback": "резервний режим",
        "timeout": "час очікування вичерпано",
        "invalid_json_response": "некоректна відповідь",
        "all_models_unavailable": "моделі недоступні",
        "Symbol not found": "символ не знайдено",
        "No Account ID": "акаунт не готовий",
        "Unsupported timeframe": "непідтримуваний таймфрейм",
        "No trendbars returned": "історичні дані не отримано",
    }

    for source, target in replacements.items():
        text = text.replace(source, target)

    text = text.replace("1m", "1 хв")
    text = text.replace("5m", "5 хв")
    text = text.replace("15m", "15 хв")
    return text


def _format_timeframe_details(result: dict) -> str:
    details = result.get("timeframe_details") or {}
    if not details:
        return ""

    lines = ["", "🧠 <b>Таймфрейми:</b>"]

    for tf, item in details.items():
        verdict = _safe_html(_label_verdict(item.get("verdict", "немає даних")))
        score = _safe_html(item.get("score", "немає даних"))
        lines.append(f"• <b>{_safe_html(_label_timeframe(tf))}</b>: {verdict} ({score}%)")

    return "\n".join(lines)


def _format_signal_message(result: dict, expiration: str) -> str:
    if result.get("error"):
        return "❌ Помилка: <code>технічна помилка аналізу</code>"

    pair = _safe_html(result.get("pair", "немає даних"))
    price = result.get("price")
    verdict = _safe_html(_label_verdict(result.get("verdict_text", "WAIT")))
    sentiment = _safe_html(_label_sentiment(result.get("sentiment", "GO")))
    trade_allowed = "✅ Так" if result.get("is_trade_allowed") else "⛔ Ні"

    price_str = "немає даних"
    if isinstance(price, (int, float)):
        price_str = f"{price:.5f}"

    lines = [
        f"📈 <b>Сигнал для {pair}</b> ({_safe_html(_label_timeframe(expiration))})",
        f"<b>Прогноз:</b> {verdict}",
        f"<b>Ціна:</b> <code>{price_str}</code>",
        f"<b>Новини:</b> {sentiment}",
        f"<b>Вхід дозволено:</b> {trade_allowed}",
        f"<b>Підсумкова оцінка:</b> {_safe_html(result.get('score', 'немає даних'))}%",
    ]

    tf_block = _format_timeframe_details(result)
    if tf_block:
        lines.append(tf_block)

    reasons = result.get("reasons", [])
    if reasons:
        lines.append("")
        lines.append("📑 <b>Фактори аналізу:</b>")

        for reason in reasons:
            lines.append(f"• <i>{_safe_html(_format_reason_uk(reason))}</i>")

    return "\n".join(lines)


def start(update: Update, context: CallbackContext):
    chat_id = _get_chat_id(update)
    sent = update.message.reply_text("👋 Вітаю! Натисніть «МЕНЮ».", reply_markup=get_reply_keyboard())
    bot_track_message(context.bot_data, chat_id, sent.message_id)
    menu(update, context)


def menu(update: Update, context: CallbackContext):
    chat_id = _get_chat_id(update)

    try:
        bot_clear_messages(context.bot, context.bot_data, chat_id, limit=100)
    except Exception:
        pass

    sent = context.bot.send_message(chat_id, "🏠 Головне меню:", reply_markup=get_main_menu_kb())
    bot_track_message(context.bot_data, chat_id, sent.message_id)


def stats_command(update, context):
    now = time.time()
    cache = app_state.latest_analysis_cache

    lines = ["📊 <b>Статистика за 1 год:</b>"]

    for pair, result in cache.items():
        if now - result.get("ts", 0) < 3600:
            verdict = _safe_html(_label_verdict(result.get("verdict_text", "немає даних")))
            score = _safe_html(result.get("score", "немає даних"))
            lines.append(f"• <b>{_safe_html(pair)}</b>: {verdict} ({score}%)")

    update.message.reply_text(
        "\n".join(lines) if len(lines) > 1 else "Немає даних",
        parse_mode="HTML",
        reply_markup=get_reply_keyboard(),
    )


def live_command(update, context):
    lines = ["💹 <b>Ціни:</b>"]

    for pair, data in app_state.get_live_prices_snapshot().items():
        age = time.time() - data.get("ts", 0)
        mid = data.get("mid")
        mid_str = f"{mid:.5f}" if isinstance(mid, (float, int)) else "немає даних"

        lines.append(
            f"{'🟢' if age < 30 else '🔴'} <code>{_safe_html(pair)}</code>: "
            f"{mid_str} ({age:.0f}s)"
        )

    update.message.reply_text(
        "\n".join(lines) if len(lines) > 1 else "Ефір порожній",
        parse_mode="HTML",
        reply_markup=get_reply_keyboard(),
    )


def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    chat_id = _get_chat_id(update)
    _safe_delete(context.bot, chat_id, query.message.message_id)

    parts = query.data.split("_")
    action = parts[0]

    if action == "toggle" and len(parts) > 2:
        cat = parts[2]
        app_state.set_scanner_state(cat, not app_state.get_scanner_state(cat))
        menu(update, context)
        return

    if action in ("main_menu", "main"):
        menu(update, context)
        return

    if action == "category":
        cat = parts[1]

        if cat == "watchlist":
            assets = db.get_watchlist(chat_id)
            if not assets:
                context.bot.send_message(
                    chat_id,
                    "📭 Список порожній.",
                    reply_markup=get_main_menu_kb(),
                )
            else:
                context.bot.send_message(
                    chat_id,
                    "⭐ Обране. Оберіть ТФ:",
                    reply_markup=get_expiration_kb("watchlist"),
                )
        else:
            context.bot.send_message(
                chat_id,
                f"Експірація для {cat}:",
                reply_markup=get_expiration_kb(cat),
            )
        return

    if action == "exp":
        _, cat, exp = parts

        if cat == "watchlist":
            context.bot.send_message(
                chat_id,
                f"⭐ Обране ({exp}):",
                reply_markup=get_assets_kb(db.get_watchlist(chat_id), "watchlist", exp),
            )
        elif cat == "forex":
            context.bot.send_message(
                chat_id,
                "Сесії Forex:",
                reply_markup=get_forex_sessions_kb(exp),
            )
        else:
            assets = {
                "crypto": CRYPTO_PAIRS,
                "stocks": STOCK_TICKERS,
                "commodities": COMMODITIES,
            }.get(cat, [])

            context.bot.send_message(
                chat_id,
                "Оберіть актив:",
                reply_markup=get_assets_kb(assets, cat, exp),
            )
        return

    if action == "session":
        _, _, exp, sess = parts

        context.bot.send_message(
            chat_id,
            f"Пари {sess}:",
            reply_markup=get_assets_kb(FOREX_SESSIONS.get(sess, []), "forex", exp),
        )
        return

    if action == "analyze":
        exp = parts[1]
        symbol = "_".join(parts[2:]).replace("/", "").upper()

        loading = context.bot.send_message(chat_id, f"⏳ Аналіз {symbol}...")

        d = get_api_detailed_signal_data(
            app_state.client,
            app_state.symbol_cache,
            symbol,
            chat_id,
            exp,
        )

        def on_res(res):
            result = res if isinstance(res, dict) else {}
            result_message = _format_signal_message(result, exp)

            chain = _bot_call_async(
                context.bot.delete_message,
                chat_id=chat_id,
                message_id=loading.message_id,
            )

            def _send_result(_):
                return _bot_call_async(
                    context.bot.send_message,
                    chat_id=chat_id,
                    text=result_message,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                    reply_markup=get_reply_keyboard(),
                )

            def _send_menu(_):
                return _bot_call_async(
                    context.bot.send_message,
                    chat_id=chat_id,
                    text="🏠 Головне меню:",
                    reply_markup=get_main_menu_kb(),
                )

            chain.addBoth(_send_result)
            chain.addBoth(_send_menu)

            def _final_error(failure):
                logger.error(
                    "Помилка надсилання результату analyze для %s: %s",
                    symbol,
                    failure.getErrorMessage(),
                )
                return None

            chain.addErrback(_final_error)
            return res

        def on_err(failure):
            logger.error("Помилка аналізу %s: %s", symbol, failure.getErrorMessage())

            chain = _bot_call_async(
                context.bot.delete_message,
                chat_id=chat_id,
                message_id=loading.message_id,
            )

            def _send_error(_):
                return _bot_call_async(
                    context.bot.send_message,
                    chat_id=chat_id,
                    text=f"❌ Помилка аналізу для <b>{_safe_html(symbol)}</b>",
                    parse_mode="HTML",
                    reply_markup=get_reply_keyboard(),
                )

            def _send_menu(_):
                return _bot_call_async(
                    context.bot.send_message,
                    chat_id=chat_id,
                    text="🏠 Головне меню:",
                    reply_markup=get_main_menu_kb(),
                )

            chain.addBoth(_send_error)
            chain.addBoth(_send_menu)
            return None

        d.addCallbacks(on_res, on_err)
        return


def reset_ui(update, context):
    update.message.reply_text("Натисніть МЕНЮ.", reply_markup=get_reply_keyboard())


def symbols_command(update, context):
    update.message.reply_text(
        f"Символів: {len(getattr(app_state, 'all_symbol_names', []))}",
        reply_markup=get_reply_keyboard(),
    )
