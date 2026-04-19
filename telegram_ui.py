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
import crypto_pay
from analysis import get_api_detailed_signal_data
from config import COMMODITIES, CRYPTO_PAIRS, FOREX_SESSIONS, STOCK_TICKERS
from locales import (
    LANGUAGE_NAMES,
    SUPPORTED_LANGS,
    language_name,
    localize_reason,
    localize_signal_payload,
    normalize_lang,
    quality_label,
    session_label,
    sentiment_label,
    t,
    timeframe_label,
    verdict_label,
)
from session_times import session_time_label
from state import app_state
from utils_message_cleanup import bot_clear_messages, bot_track_message

logger = logging.getLogger(__name__)

EXPIRATIONS = ["1m", "5m", "15m"]
CATEGORY_KEYS = {
    "forex": "forex_pairs",
    "crypto": "crypto",
    "stocks": "stocks",
    "commodities": "commodities",
    "watchlist": "watchlist",
}


def _get_user_id(update: Update | None = None) -> int:
    user = getattr(update, "effective_user", None)
    return int(getattr(user, "id", 0) or 0)


def _lang(update: Update | None = None) -> str:
    user_id = _get_user_id(update)
    saved_lang = db.get_user_language(user_id) if user_id else None
    if saved_lang:
        return normalize_lang(saved_lang)

    user = getattr(update, "effective_user", None)
    return normalize_lang(getattr(user, "language_code", None))


def _timezone(update: Update | None = None) -> str:
    user_id = _get_user_id(update)
    return db.get_user_timezone(user_id) if user_id else "Europe/Kyiv"


def _category_label(category: str, lang: str) -> str:
    return t(CATEGORY_KEYS.get(category, "watchlist"), lang)


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


def _send_tracked(context: CallbackContext, chat_id: int, text: str, **kwargs):
    sent = context.bot.send_message(chat_id=chat_id, text=text, **kwargs)
    bot_track_message(context.bot_data, chat_id, sent.message_id)
    return sent


def _bot_call_async(func: Callable, *args, **kwargs):
    return deferToThreadPool(
        reactor,
        _blocking_pool(),
        func,
        *args,
        **kwargs,
    )


def _send_subscription_denied(context: CallbackContext, chat_id: int, lang: str):
    return _send_tracked(
        context,
        chat_id,
        t("access_denied_subscription", lang),
        reply_markup=get_payment_kb(lang),
    )


def _format_subscription_date(value: str | None) -> str:
    if not value:
        return "∞"
    return value.replace("T", " ").replace("Z", " UTC")


def get_reply_keyboard(lang: str = "en") -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([[KeyboardButton(t("reply_menu", lang))]], resize_keyboard=True)


def get_start_kb(lang: str = "en") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t("trial_button", lang), callback_data="trial_start")],
            [InlineKeyboardButton(t("pay_button", lang), callback_data="pay_subscription")],
        ]
    )


def get_payment_kb(lang: str = "en", invoice_url: str | None = None) -> InlineKeyboardMarkup:
    if invoice_url:
        return InlineKeyboardMarkup([[InlineKeyboardButton(t("open_invoice", lang), url=invoice_url)]])
    return InlineKeyboardMarkup([[InlineKeyboardButton(t("pay_button", lang), callback_data="pay_subscription")]])


def get_main_menu_kb(lang: str = "en") -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(t("language_settings", lang), callback_data="language_menu")],
        [InlineKeyboardButton(t("my_watchlist", lang), callback_data="category_watchlist")],
        [InlineKeyboardButton(t("forex_pairs", lang), callback_data="category_forex")],
        [InlineKeyboardButton(t("crypto", lang), callback_data="category_crypto")],
        [InlineKeyboardButton(t("stocks", lang), callback_data="category_stocks")],
        [InlineKeyboardButton(t("commodities", lang), callback_data="category_commodities")],
    ]

    scanner_map = {
        "forex": t("scanner_forex", lang),
        "crypto": t("scanner_crypto", lang),
        "commodities": t("scanner_commodities", lang),
        "watchlist": t("scanner_watchlist", lang),
    }

    for key, text in scanner_map.items():
        status = "✅" if app_state.get_scanner_state(key) else "❌"
        keyboard.append(
            [InlineKeyboardButton(f"{status} {t('scanner', lang)} {text}", callback_data=f"toggle_scanner_{key}")]
        )

    return InlineKeyboardMarkup(keyboard)


def get_language_kb(lang: str = "en") -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                f"{'✅ ' if code == lang else ''}{name}",
                callback_data=f"setlang_{code}",
            )
        ]
        for code, name in LANGUAGE_NAMES.items()
        if code in SUPPORTED_LANGS
    ]
    rows.append([InlineKeyboardButton(t("back_categories", lang), callback_data="main_menu")])
    return InlineKeyboardMarkup(rows)


def get_expiration_kb(category: str, lang: str = "en") -> InlineKeyboardMarkup:
    kb = [[InlineKeyboardButton(exp, callback_data=f"exp_{category}_{exp}") for exp in EXPIRATIONS]]
    kb.append([InlineKeyboardButton(t("back_categories", lang), callback_data="main_menu")])
    return InlineKeyboardMarkup(kb)


def get_forex_sessions_kb(expiration: str, lang: str = "en", user_timezone: str | None = None) -> InlineKeyboardMarkup:
    kb = [
        [
            InlineKeyboardButton(
                f"{session_time_label(s, user_timezone)} {session_label(s, lang)}".strip(),
                callback_data=f"session_forex_{expiration}_{s}",
            )
        ]
        for s in FOREX_SESSIONS
    ]
    kb.append([InlineKeyboardButton(t("back_expirations", lang), callback_data="category_forex")])
    return InlineKeyboardMarkup(kb)


def get_assets_kb(asset_list: list, category: str, expiration: str, lang: str = "en") -> InlineKeyboardMarkup:
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

    back = t("back_sessions", lang) if category == "forex" else t("back_expirations", lang)
    callback_back = f"exp_forex_{expiration}" if category == "forex" else f"category_{category}"
    kb.append([InlineKeyboardButton(back, callback_data=callback_back)])

    return InlineKeyboardMarkup(kb)


def _safe_html(value) -> str:
    return html.escape("" if value is None else str(value))


def _label_verdict(value, lang: str = "en") -> str:
    return verdict_label(value, lang)


def _label_verdict_strong(value, lang: str = "en") -> str:
    return verdict_label(value, lang, strong=True)


def _label_sentiment(value, lang: str = "en") -> str:
    return sentiment_label(value, lang)


def _label_timeframe(value, lang: str = "en") -> str:
    return timeframe_label(value, lang)


def _format_reason(reason, lang: str = "en") -> str:
    return localize_reason(reason, lang)


def _format_timeframe_details(result: dict, lang: str = "en") -> list[str]:
    details = result.get("timeframe_details") or {}
    if not details:
        return []

    lines = [t("timeframes", lang)]

    for tf, item in details.items():
        verdict = _safe_html(_label_verdict_strong(item.get("verdict", "WAIT"), lang))
        score = _safe_html(item.get("score", t("no_data", lang)))
        lines.append(f"• <b>{_safe_html(_label_timeframe(tf, lang))}</b>: {verdict} ({score}%)")

    return lines


def _label_signal_quality(value, lang: str = "en") -> str:
    return quality_label(value, lang)


def _format_data_status(result: dict, lang: str = "en") -> list[str]:
    status = result.get("data_status") or {}
    items = [
        (t("quote_feed", lang), status.get("ctrader")),
        (t("price", lang), status.get("price")),
        (t("calendar", lang), status.get("calendar")),
        (t("model", lang), status.get("ml")),
        (t("market_data", lang), status.get("market_data")),
    ]

    lines = []
    for title, item in items:
        if not isinstance(item, dict):
            continue

        ok = item.get("ok")
        icon = "✅" if ok is True else "⚠️" if ok is False else "⏳"
        label = _format_reason(item.get("label") or t("no_data", lang), lang)
        lines.append(f"• {icon} <b>{_safe_html(title)}:</b> {_safe_html(label)}")

    if not lines:
        return []

    return [t("source_check", lang), *lines]


def _format_action_panel(pair: str, expiration: str, raw_verdict: str, verdict: str, trade_allowed: str, lang: str = "en") -> list[str]:
    tf = _safe_html(_label_timeframe(expiration, lang))

    if raw_verdict == "BUY":
        return [
            t("buy_panel", lang),
            f"⬆️⬆️⬆️ <b>{verdict}</b> ⬆️⬆️⬆️",
            f"<b>{pair}</b> · {tf}",
            f"<b>{trade_allowed}</b>",
        ]

    if raw_verdict == "SELL":
        return [
            t("sell_panel", lang),
            f"⬇️⬇️⬇️ <b>{verdict}</b> ⬇️⬇️⬇️",
            f"<b>{pair}</b> · {tf}",
            f"<b>{trade_allowed}</b>",
        ]

    if raw_verdict == "NEWS_WAIT":
        return [
            t("pause_panel", lang),
            f"⏸️⏸️⏸️ <b>{verdict}</b> ⏸️⏸️⏸️",
            f"<b>{pair}</b> · {tf}",
            f"<b>{trade_allowed}</b>",
        ]

    return [
        t("no_trade_panel", lang),
        f"↔️↔️↔️ <b>{verdict}</b> ↔️↔️↔️",
        f"<b>{pair}</b> · {tf}",
        f"<b>{trade_allowed}</b>",
    ]


def _format_signal_message(result: dict, expiration: str, lang: str = "en") -> str:
    result = localize_signal_payload(result, lang)

    if result.get("error"):
        return f"❌ {t('error', lang)}: <code>{_safe_html(t('technical_error', lang))}</code>"

    pair = _safe_html(result.get("pair", t("no_data", lang)))
    price = result.get("price")
    raw_verdict = str(result.get("verdict_text", "WAIT") or "WAIT").upper()
    verdict = _safe_html(_label_verdict_strong(raw_verdict, lang))
    sentiment = _safe_html(_label_sentiment(result.get("sentiment", "GO"), lang))
    trade_allowed = t("trade_allowed", lang) if result.get("is_trade_allowed") else t("trade_not_recommended", lang)
    score = int(float(result.get("score", 50) or 50))
    bear_score = max(0, min(100, 100 - score))

    arrow = "↔️"
    if raw_verdict == "BUY":
        arrow = "⬆️"
    elif raw_verdict == "SELL":
        arrow = "⬇️"
    elif raw_verdict == "NEWS_WAIT":
        arrow = "⏸️"

    price_str = t("no_data", lang)
    if isinstance(price, (int, float)):
        price_str = f"{price:.5f}"

    lines = [
        f"📈 <b>{pair}</b>  <i>{t('expiration', lang)}: {_safe_html(_label_timeframe(expiration, lang))}</i>",
        "",
        f"{arrow} <b>{verdict}</b>",
        f"💵 <code>{price_str}</code>",
        f"✅ <b>{t('news', lang)}:</b> {sentiment}",
        "",
        f"🐂 <b>{t('bulls', lang)}:</b> {score}%    🐃 <b>{t('bears', lang)}:</b> {bear_score}%",
        "",
    ]

    lines.extend(_format_timeframe_details(result, lang))
    status_lines = _format_data_status(result, lang)
    if status_lines:
        lines.extend(["", *status_lines])

    quality = _safe_html(_label_signal_quality(result.get("signal_quality"), lang))
    lines.extend(["", t("signal_quality", lang, quality=quality)])

    reasons = result.get("reasons", [])
    if reasons:
        lines.append("")
        lines.append(t("analysis_factors", lang))

        for reason in reasons:
            lines.append(f"• <i>{_safe_html(_format_reason(reason, lang))}</i>")

    lines.extend(
        [
            "",
            t("short", lang),
            *_format_action_panel(pair, expiration, raw_verdict, verdict, trade_allowed, lang),
        ]
    )

    return "\n".join(lines)


def start(update: Update, context: CallbackContext):
    lang = _lang(update)
    chat_id = _get_chat_id(update)
    user_id = _get_user_id(update) or chat_id
    status = db.get_user_access_status(user_id, language_hint=lang, notify_expired=False)
    sent = update.message.reply_text(
        t("start", lang),
        reply_markup=get_reply_keyboard(lang),
    )
    bot_track_message(context.bot_data, chat_id, sent.message_id)
    keyboard = get_main_menu_kb(lang) if (status or {}).get("access_allowed") else get_start_kb(lang)
    _send_tracked(context, chat_id, t("main_menu", lang), reply_markup=keyboard)


def menu(update: Update, context: CallbackContext):
    lang = _lang(update)
    chat_id = _get_chat_id(update)

    try:
        bot_clear_messages(context.bot, context.bot_data, chat_id, limit=100)
    except Exception:
        pass

    _send_tracked(context, chat_id, t("main_menu", lang), reply_markup=get_main_menu_kb(lang))


def stats_command(update, context):
    lang = _lang(update)
    now = time.time()
    cache = app_state.latest_analysis_cache

    lines = [t("stats_title", lang)]

    for pair, result in cache.items():
        if now - result.get("ts", 0) < 3600:
            verdict = _safe_html(_label_verdict(result.get("verdict_text", "WAIT"), lang))
            score = _safe_html(result.get("score", t("no_data", lang)))
            lines.append(f"• <b>{_safe_html(pair)}</b>: {verdict} ({score}%)")

    update.message.reply_text(
        "\n".join(lines) if len(lines) > 1 else t("no_data", lang),
        parse_mode="HTML",
        reply_markup=get_reply_keyboard(lang),
    )


def live_command(update, context):
    lang = _lang(update)
    lines = [t("prices", lang)]

    for pair, data in app_state.get_live_prices_snapshot().items():
        age = time.time() - data.get("ts", 0)
        mid = data.get("mid")
        mid_str = f"{mid:.5f}" if isinstance(mid, (float, int)) else t("no_data", lang)

        lines.append(
            f"{'🟢' if age < 30 else '🔴'} <code>{_safe_html(pair)}</code>: "
            f"{mid_str} ({age:.0f} сек)"
        )

    update.message.reply_text(
        "\n".join(lines) if len(lines) > 1 else t("empty_feed", lang),
        parse_mode="HTML",
        reply_markup=get_reply_keyboard(lang),
    )


def language_command(update, context):
    lang = _lang(update)
    chat_id = _get_chat_id(update)
    _send_tracked(
        context,
        chat_id,
        t("language_choose", lang),
        reply_markup=get_language_kb(lang),
    )


def set_language_command(update, context):
    command = ""
    if update.message and update.message.text:
        command = update.message.text.split()[0].lstrip("/").lower()

    new_lang = normalize_lang(command)
    if command not in SUPPORTED_LANGS:
        return language_command(update, context)

    chat_id = _get_chat_id(update)
    user_id = _get_user_id(update) or chat_id
    db.set_user_language(user_id, new_lang)
    sent = update.message.reply_text(
        t("language_saved", new_lang, language=language_name(new_lang)),
        reply_markup=get_reply_keyboard(new_lang),
    )
    bot_track_message(context.bot_data, chat_id, sent.message_id)
    _send_tracked(context, chat_id, t("main_menu", new_lang), reply_markup=get_main_menu_kb(new_lang))


def button_handler(update: Update, context: CallbackContext):
    lang = _lang(update)
    query = update.callback_query
    query.answer()

    chat_id = _get_chat_id(update)
    _safe_delete(context.bot, chat_id, query.message.message_id)

    parts = query.data.split("_")
    action = parts[0]

    if action == "language":
        _send_tracked(
            context,
            chat_id,
            t("language_choose", lang),
            reply_markup=get_language_kb(lang),
        )
        return

    if action == "setlang" and len(parts) > 1:
        new_lang = normalize_lang(parts[1])
        user_id = _get_user_id(update) or chat_id
        db.set_user_language(user_id, new_lang)
        _send_tracked(
            context,
            chat_id,
            t("language_saved", new_lang, language=language_name(new_lang)),
            reply_markup=get_reply_keyboard(new_lang),
        )
        _send_tracked(context, chat_id, t("main_menu", new_lang), reply_markup=get_main_menu_kb(new_lang))
        return

    if action == "trial":
        user_id = _get_user_id(update) or chat_id
        status, activated = db.start_user_trial(user_id, language=lang)
        if activated:
            end_date = _format_subscription_date((status or {}).get("subscription_end_date"))
            _send_tracked(
                context,
                chat_id,
                f"{t('trial_activated', lang)}\n{t('subscription_active_until', lang, date=end_date)}",
                reply_markup=get_main_menu_kb(lang),
            )
        else:
            _send_tracked(
                context,
                chat_id,
                t("trial_already_used", lang),
                reply_markup=get_payment_kb(lang),
            )
        return

    if action == "pay":
        user_id = _get_user_id(update) or chat_id
        try:
            invoice = crypto_pay.create_subscription_invoice(user_id, language=lang)
        except Exception:
            logger.exception("Не вдалося створити Crypto Pay інвойс для user_id=%s", user_id)
            _send_tracked(
                context,
                chat_id,
                t("payment_invoice_error", lang),
                reply_markup=get_payment_kb(lang),
            )
            return

        _send_tracked(
            context,
            chat_id,
            t(
                "payment_invoice_created",
                lang,
                amount=invoice.get("subscription_amount", ""),
                asset=invoice.get("subscription_asset", ""),
                days=invoice.get("subscription_days", ""),
            ),
            reply_markup=get_payment_kb(lang, invoice.get("invoice_url")),
        )
        return

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
                _send_tracked(
                    context,
                    chat_id,
                    t("watchlist_empty", lang),
                    reply_markup=get_main_menu_kb(lang),
                )
            else:
                _send_tracked(
                    context,
                    chat_id,
                    t("watchlist_choose_tf", lang),
                    reply_markup=get_expiration_kb("watchlist", lang),
                )
        else:
            _send_tracked(
                context,
                chat_id,
                t("choose_timeframe", lang, category=_category_label(cat, lang)),
                reply_markup=get_expiration_kb(cat, lang),
            )
        return

    if action == "exp":
        _, cat, exp = parts

        if cat == "watchlist":
            _send_tracked(
                context,
                chat_id,
                t("watchlist_exp", lang, exp=exp),
                reply_markup=get_assets_kb(db.get_watchlist(chat_id), "watchlist", exp, lang),
            )
        elif cat == "forex":
            _send_tracked(
                context,
                chat_id,
                t("forex_sessions", lang),
                reply_markup=get_forex_sessions_kb(exp, lang, _timezone(update)),
            )
        else:
            assets = {
                "crypto": CRYPTO_PAIRS,
                "stocks": STOCK_TICKERS,
                "commodities": COMMODITIES,
            }.get(cat, [])

            _send_tracked(
                context,
                chat_id,
                t("choose_asset", lang),
                reply_markup=get_assets_kb(assets, cat, exp, lang),
            )
        return

    if action == "session":
        _, _, exp, sess = parts

        _send_tracked(
            context,
            chat_id,
            t("session_pairs", lang, session=sess),
            reply_markup=get_assets_kb(FOREX_SESSIONS.get(sess, []), "forex", exp, lang),
        )
        return

    if action == "analyze":
        exp = parts[1]
        symbol = "_".join(parts[2:]).replace("/", "").upper()
        user_id = _get_user_id(update) or chat_id

        access = db.get_user_access_status(user_id, language_hint=lang)
        if not access or not access.get("access_allowed"):
            _send_subscription_denied(context, chat_id, lang)
            return

        loading = _send_tracked(context, chat_id, t("analyzing", lang, symbol=symbol))

        d = get_api_detailed_signal_data(
            app_state.client,
            app_state.symbol_cache,
            symbol,
            chat_id,
            exp,
            lang,
        )

        def on_res(res):
            result = res if isinstance(res, dict) else {}
            result_message = _format_signal_message(result, exp, lang)

            chain = _bot_call_async(
                context.bot.delete_message,
                chat_id=chat_id,
                message_id=loading.message_id,
            )

            def _send_result(_):
                d_send = _bot_call_async(
                    context.bot.send_message,
                    chat_id=chat_id,
                    text=result_message,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                    reply_markup=get_reply_keyboard(lang),
                )
                d_send.addCallback(
                    lambda sent: bot_track_message(context.bot_data, chat_id, sent.message_id)
                    or sent
                )
                return d_send

            chain.addBoth(_send_result)

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
                d_send = _bot_call_async(
                    context.bot.send_message,
                    chat_id=chat_id,
                    text=t("analysis_error", lang, symbol=_safe_html(symbol)),
                    parse_mode="HTML",
                    reply_markup=get_reply_keyboard(lang),
                )
                d_send.addCallback(
                    lambda sent: bot_track_message(context.bot_data, chat_id, sent.message_id)
                    or sent
                )
                return d_send

            chain.addBoth(_send_error)
            return None

        d.addCallbacks(on_res, on_err)
        return


def reset_ui(update, context):
    lang = _lang(update)
    update.message.reply_text(t("press_menu", lang), reply_markup=get_reply_keyboard(lang))


def symbols_command(update, context):
    lang = _lang(update)
    update.message.reply_text(
        t("symbols", lang, count=len(getattr(app_state, "all_symbol_names", []))),
        reply_markup=get_reply_keyboard(lang),
    )
