from copy import deepcopy

DEFAULT_LANG = "en"
SUPPORTED_LANGS = {"en", "uk"}


TRANSLATIONS = {
    "en": {
        "reply_menu": "MENU",
        "main_menu": "🏠 Main menu:",
        "start": "👋 Welcome! Press \"MENU\".",
        "watchlist": "Favorites",
        "my_watchlist": "⭐ My list (Favorites)",
        "forex_pairs": "💹 Currency pairs",
        "crypto": "💎 Crypto",
        "stocks": "📈 Stocks/Indices",
        "commodities": "🥇 Commodities",
        "scanner": "Scanner",
        "scanner_forex": "💹 Currencies",
        "scanner_crypto": "💎 Crypto",
        "scanner_commodities": "🥇 Commodities",
        "scanner_watchlist": "⭐ Favorites",
        "back_categories": "⬅️ Back to categories",
        "back_expirations": "⬅️ Back to expirations",
        "back_sessions": "⬅️ Back to sessions",
        "choose_timeframe": "Expiration for {category}:",
        "watchlist_empty": "📭 The list is empty.",
        "watchlist_choose_tf": "⭐ Favorites. Choose TF:",
        "watchlist_exp": "⭐ Favorites ({exp}):",
        "forex_sessions": "Currency sessions:",
        "choose_asset": "Choose an asset:",
        "session_pairs": "Pairs {session}:",
        "analyzing": "⏳ Analyzing {symbol}...",
        "analysis_error": "❌ Analysis error for <b>{symbol}</b>",
        "technical_error": "technical analysis error",
        "press_menu": "Press MENU.",
        "stats_title": "📊 <b>Stats for 1 hour:</b>",
        "no_data": "No data",
        "prices": "💹 <b>Prices:</b>",
        "empty_feed": "Price feed is empty",
        "symbols": "Symbols: {count}",
        "expiration": "Expiration",
        "news": "News",
        "bulls": "Bulls",
        "bears": "Bears",
        "timeframes": "🧠 <b>Timeframes:</b>",
        "source_check": "🔎 <b>Source check:</b>",
        "price": "Price",
        "calendar": "Calendar",
        "model": "Model",
        "market_data": "Historical data",
        "signal_quality": "🔎 <b>Signal quality:</b> {quality}",
        "analysis_factors": "📑 <b>Analysis factors:</b>",
        "short": "⚡ <b>SHORT:</b>",
        "buy_panel": "🟩🟩🟩 <b>BUY</b> 🟩🟩🟩",
        "sell_panel": "🟥🟥🟥 <b>SELL</b> 🟥🟥🟥",
        "pause_panel": "🟨🟨🟨 <b>PAUSE</b> 🟨🟨🟨",
        "no_trade_panel": "⬜⬜⬜ <b>DO NOT TRADE</b> ⬜⬜⬜",
        "trade_allowed": "✅ ENTRY ALLOWED",
        "trade_not_recommended": "⛔ ENTRY NOT RECOMMENDED",
        "unauthorized": "Unauthorized",
        "user_not_resolved": "User was not resolved",
        "pair_required": "Pair is required",
        "pair_not_actual": "This pair is not in the current list",
        "symbol_unavailable": "This symbol is not in the broker list",
        "bad_analysis_response": "Invalid analysis response format",
        "analysis_timeout": "Analysis timed out",
        "health_title": "📊 ZigZag status",
        "telegram_bot": "Telegram bot",
        "sse_signal_clients": "SSE signal clients",
        "sse_price_clients": "SSE price clients",
        "live_prices": "Live prices",
        "stale_prices": "Stale prices",
        "updated": "Updated",
        "ready": "READY",
        "error": "ERROR",
        "active": "ACTIVE",
        "disabled": "DISABLED",
        "request_failed": "❌ Server request failed",
        "not_found": "Not found",
        "choose_asset_web": "Choose an asset for analysis...",
        "search": "🔍 Search...",
        "terminal_title": "Terminal | Binary Options",
        "expiration_1m": "Expiration 1 min",
        "expiration_5m": "Expiration 5 min",
        "no_broker": "not at broker",
        "favorite_not_updated": "Favorites were not updated",
        "favorite_saved_local": "Favorites were saved on this device. The server did not respond.",
        "source_check_title": "Source check",
        "ops_notifier_unavailable": "[alert] notifier is unavailable. Message: {text}",
        "ops_alert_send_failed": "[alert] failed to send admin alert",
        "ops_recovered_after_errors": "[{context}] recovered after {count} consecutive errors",
        "ops_threshold_reached": "🚨 [{context}] Threshold reached: {count} consecutive errors. {action}",
        "ops_starting_recovery": "Starting recovery...",
        "ops_attention_required": "Attention required.",
        "ops_threshold_callback_failed": "[{context}] on_threshold callback failed",
        "ops_fatal_manual": "🛑 [{context}] UNRECOVERABLE error: {error}\nManual intervention is required.",
        "ops_consecutive": "consecutive",
        "ops_unexpected": "Unexpected",
    },
    "uk": {
        "reply_menu": "МЕНЮ",
        "main_menu": "🏠 Головне меню:",
        "start": "👋 Вітаю! Натисніть «МЕНЮ».",
        "watchlist": "Обране",
        "my_watchlist": "⭐ Мій список (Обране)",
        "forex_pairs": "💹 Валютні пари",
        "crypto": "💎 Криптовалюти",
        "stocks": "📈 Акції/Індекси",
        "commodities": "🥇 Сировина",
        "scanner": "Сканер",
        "scanner_forex": "💹 Валюти",
        "scanner_crypto": "💎 Криптовалюти",
        "scanner_commodities": "🥇 Сировина",
        "scanner_watchlist": "⭐ Обране",
        "back_categories": "⬅️ Назад до категорій",
        "back_expirations": "⬅️ Назад до експірацій",
        "back_sessions": "⬅️ Назад до сесій",
        "choose_timeframe": "Експірація для {category}:",
        "watchlist_empty": "📭 Список порожній.",
        "watchlist_choose_tf": "⭐ Обране. Оберіть ТФ:",
        "watchlist_exp": "⭐ Обране ({exp}):",
        "forex_sessions": "Валютні сесії:",
        "choose_asset": "Оберіть актив:",
        "session_pairs": "Пари {session}:",
        "analyzing": "⏳ Аналіз {symbol}...",
        "analysis_error": "❌ Помилка аналізу для <b>{symbol}</b>",
        "technical_error": "технічна помилка аналізу",
        "press_menu": "Натисніть МЕНЮ.",
        "stats_title": "📊 <b>Статистика за 1 год:</b>",
        "no_data": "Немає даних",
        "prices": "💹 <b>Ціни:</b>",
        "empty_feed": "Ефір порожній",
        "symbols": "Символів: {count}",
        "expiration": "Експірація",
        "news": "Новини",
        "bulls": "Бики",
        "bears": "Ведмеді",
        "timeframes": "🧠 <b>Таймфрейми:</b>",
        "source_check": "🔎 <b>Перевірка джерел:</b>",
        "price": "Ціна",
        "calendar": "Календар",
        "model": "Модель",
        "market_data": "Історичні дані",
        "signal_quality": "🔎 <b>Якість сигналу:</b> {quality}",
        "analysis_factors": "📑 <b>Фактори аналізу:</b>",
        "short": "⚡ <b>КОРОТКО:</b>",
        "buy_panel": "🟩🟩🟩 <b>КУПІВЛЯ</b> 🟩🟩🟩",
        "sell_panel": "🟥🟥🟥 <b>ПРОДАЖ</b> 🟥🟥🟥",
        "pause_panel": "🟨🟨🟨 <b>ПАУЗА</b> 🟨🟨🟨",
        "no_trade_panel": "⬜⬜⬜ <b>НЕ СТАВИТИ</b> ⬜⬜⬜",
        "trade_allowed": "✅ ВХІД ДОЗВОЛЕНО",
        "trade_not_recommended": "⛔ ВХІД НЕ РЕКОМЕНДОВАНИЙ",
        "unauthorized": "Немає доступу",
        "user_not_resolved": "Користувача не визначено",
        "pair_required": "Пару не вказано",
        "pair_not_actual": "Цієї пари немає в актуальному списку",
        "symbol_unavailable": "Цього символу немає в списку брокера",
        "bad_analysis_response": "Невірний формат відповіді аналізу",
        "analysis_timeout": "Час очікування аналізу вичерпано",
        "health_title": "📊 Стан ZigZag",
        "telegram_bot": "Telegram Бот",
        "sse_signal_clients": "SSE клієнтів сигналів",
        "sse_price_clients": "SSE клієнтів цін",
        "live_prices": "Цін в ефірі",
        "stale_prices": "Застарілих",
        "updated": "Оновлено",
        "ready": "ГОТОВО",
        "error": "ПОМИЛКА",
        "active": "АКТИВНИЙ",
        "disabled": "ВИМКНЕНО",
        "request_failed": "❌ Помилка запиту до сервера",
        "not_found": "Не знайдено",
        "choose_asset_web": "Оберіть актив для аналізу...",
        "search": "🔍 Пошук...",
        "terminal_title": "Термінал | Бінарні Опціони",
        "expiration_1m": "Експірація 1 хв",
        "expiration_5m": "Експірація 5 хв",
        "no_broker": "немає у брокера",
        "favorite_not_updated": "Обране не оновлено",
        "favorite_saved_local": "Обране збережено на цьому пристрої. Сервер тимчасово не відповів.",
        "source_check_title": "Перевірка джерел",
        "ops_notifier_unavailable": "[alert] notifier недоступний. Повідомлення: {text}",
        "ops_alert_send_failed": "[alert] не вдалося надіслати алерт адміну",
        "ops_recovered_after_errors": "[{context}] відновлено після {count} помилок підряд",
        "ops_threshold_reached": "🚨 [{context}] Поріг досягнуто: {count} помилок підряд. {action}",
        "ops_starting_recovery": "Запускаю відновлення...",
        "ops_attention_required": "Потрібна увага.",
        "ops_threshold_callback_failed": "[{context}] on_threshold callback впав",
        "ops_fatal_manual": "🛑 [{context}] НЕВІДНОВЛЮВАНА помилка: {error}\nПотрібне ручне втручання.",
        "ops_consecutive": "підряд",
        "ops_unexpected": "Несподіваний",
    },
}

VERDICTS = {
    "en": {
        "BUY": "buy",
        "SELL": "sell",
        "NEUTRAL": "neutral",
        "WAIT": "wait",
        "NEWS_WAIT": "news pause",
        "ERROR": "error",
        "UNKNOWN": "unknown",
    },
    "uk": {
        "BUY": "купівля",
        "SELL": "продаж",
        "NEUTRAL": "нейтрально",
        "WAIT": "очікування",
        "NEWS_WAIT": "пауза через новини",
        "ERROR": "помилка",
        "UNKNOWN": "невідомо",
    },
}

SENTIMENTS = {
    "en": {"GO": "allowed", "BLOCK": "blocked", "UNKNOWN": "unknown"},
    "uk": {"GO": "дозволено", "BLOCK": "заблоковано", "UNKNOWN": "невідомо"},
}

TIMEFRAMES = {
    "en": {"1m": "1 min", "5m": "5 min", "15m": "15 min"},
    "uk": {"1m": "1 хв", "5m": "5 хв", "15m": "15 хв"},
}

QUALITY = {
    "en": {
        "strong": "strong",
        "medium": "medium",
        "weak": "weak",
        "wait": "wait",
        "сильний": "strong",
        "середній": "medium",
        "слабкий": "weak",
        "чекати": "wait",
    },
    "uk": {
        "strong": "сильний",
        "medium": "середній",
        "weak": "слабкий",
        "wait": "чекати",
        "сильний": "сильний",
        "середній": "середній",
        "слабкий": "слабкий",
        "чекати": "чекати",
    },
}

SESSION_NAMES = {
    "en": {
        "Європейська": "European",
        "Американська": "American",
        "Азіатська": "Asian",
        "Тихоокеанська": "Pacific",
    },
    "uk": {
        "Європейська": "Європейська",
        "Американська": "Американська",
        "Азіатська": "Азіатська",
        "Тихоокеанська": "Тихоокеанська",
    },
}

REASON_REPLACEMENTS = {
    "en": [
        ("NEWS_WAIT", "news pause"),
        ("NEUTRAL", "neutral"),
        ("BLOCK", "blocked"),
        ("BUY", "buy"),
        ("SELL", "sell"),
        ("WAIT", "wait"),
        ("ERROR", "error"),
        ("GO", "allowed"),
        ("Таймфрейми:", "Timeframes:"),
        ("Новини:", "News:"),
        ("Фільтр новин:", "News filter:"),
        ("Ціна:", "Price:"),
        ("ШІ", "AI"),
        ("купівля", "buy"),
        ("продаж", "sell"),
        ("нейтрально", "neutral"),
        ("очікування", "wait"),
        ("пауза через новини", "news pause"),
        ("дозволено", "allowed"),
        ("заблоковано", "blocked"),
        ("невідомо", "unknown"),
        ("немає даних", "no data"),
        ("Помилка даних", "Data error"),
        ("Недостатньо історії", "Not enough history"),
        ("Модель ШІ не завантажена", "AI model is not loaded"),
        ("Не вдалося підготувати індикатори", "Failed to prepare indicators"),
        ("Помилка прогнозу ШІ", "AI prediction error"),
        ("cTrader клієнт не готовий", "cTrader client is not ready"),
        ("Акаунт не готовий", "Account is not ready"),
        ("поточна ціна ще не отримана", "live price has not been received yet"),
        ("свіжа", "fresh"),
        ("застаріла", "stale"),
        ("сек тому", "sec ago"),
        ("не готовий", "not ready"),
        ("модель не завантажена", "model is not loaded"),
        ("готовий", "ready"),
        ("готова", "ready"),
        ("ще не перевірено", "not checked yet"),
        ("календар не відповів", "calendar did not respond"),
        ("календар працює", "calendar is working"),
        ("недоступний", "unavailable"),
        ("історичні дані не отримано", "historical data not received"),
        ("отримано", "received"),
        ("подій високої важливості поруч немає", "no nearby high-impact events"),
        ("вхід не блокується", "entry is not blocked"),
        ("символ не знайдено", "symbol not found"),
        ("символи завантажені", "symbols loaded"),
        ("символи не завантажені", "symbols not loaded"),
        ("працює", "working"),
        ("вимкнено", "disabled"),
        ("модель завантажена", "model loaded"),
        ("Таймфрейми:", "Timeframes:"),
        ("Новини:", "News:"),
        ("Фільтр новин:", "News filter:"),
        ("Ціна:", "Price:"),
        ("Модель ШІ не завантажена", "AI model is not loaded"),
        ("Помилка прогнозу ШІ", "AI prediction error"),
        ("Недостатньо історії", "Not enough history"),
        ("Не вдалося підготувати індикатори", "Failed to prepare indicators"),
        ("Помилка даних", "Data error"),
        ("cTrader клієнт не готовий", "cTrader client is not ready"),
        ("Акаунт не готовий", "Account is not ready"),
        ("поточна ціна ще не отримана", "live price has not been received yet"),
        ("свіжа", "fresh"),
        ("застаріла", "stale"),
        ("сек тому", "sec ago"),
        ("готовий", "ready"),
        ("готова", "ready"),
        ("не готовий", "not ready"),
        ("модель не завантажена", "model is not loaded"),
        ("ще не перевірено", "not checked yet"),
        ("календар не відповів", "calendar did not respond"),
        ("заблоковано", "blocked"),
        ("календар працює", "calendar is working"),
        ("недоступний", "unavailable"),
        ("історичні дані не отримано", "historical data not received"),
        ("отримано", "received"),
        ("подій високої важливості поруч немає", "no nearby high-impact events"),
        ("вхід не блокується", "entry is not blocked"),
        ("символ не знайдено", "symbol not found"),
        ("Symbol not found", "symbol not found"),
        ("No Account ID", "account is not ready"),
        ("Unsupported timeframe", "unsupported timeframe"),
        ("No trendbars returned", "historical data not received"),
        ("fallback", "fallback mode"),
        ("timeout", "timeout"),
        ("invalid_json_response", "invalid response"),
        ("all_models_unavailable", "all models unavailable"),
        ("1 хв", "1 min"),
        ("5 хв", "5 min"),
        ("15 хв", "15 min"),
        (" for ", " for "),
    ],
    "uk": [
        ("NEWS_WAIT", "пауза через новини"),
        ("NEUTRAL", "нейтрально"),
        ("BLOCK", "заблоковано"),
        ("BUY", "купівля"),
        ("SELL", "продаж"),
        ("WAIT", "очікування"),
        ("ERROR", "помилка"),
        ("GO", "дозволено"),
        ("TF:", "Таймфрейми:"),
        ("News filter:", "Фільтр новин:"),
        ("ML", "ШІ"),
        ("fallback", "резервний режим"),
        ("timeout", "час очікування вичерпано"),
        ("invalid_json_response", "некоректна відповідь"),
        ("all_models_unavailable", "моделі недоступні"),
        ("Symbol not found", "символ не знайдено"),
        ("No Account ID", "акаунт не готовий"),
        ("Unsupported timeframe", "непідтримуваний таймфрейм"),
        ("No trendbars returned", "історичні дані не отримано"),
        (" for ", " для "),
        ("1m", "1 хв"),
        ("5m", "5 хв"),
        ("15m", "15 хв"),
    ],
}


def normalize_lang(lang: str | None) -> str:
    value = (lang or "").split(",", 1)[0].split("-")[0].split("_")[0].lower()
    return "uk" if value == "uk" else DEFAULT_LANG


def t(key: str, lang: str | None = None, **kwargs) -> str:
    lang = normalize_lang(lang)
    template = TRANSLATIONS.get(lang, {}).get(key) or TRANSLATIONS[DEFAULT_LANG].get(key) or key
    return template.format(**kwargs) if kwargs else template


def verdict_label(value: str, lang: str | None = None, *, strong: bool = False) -> str:
    lang = normalize_lang(lang)
    label = VERDICTS[lang].get(str(value or "").upper(), VERDICTS[lang]["UNKNOWN"])
    return label.upper() if strong else label


def sentiment_label(value: str, lang: str | None = None) -> str:
    lang = normalize_lang(lang)
    return SENTIMENTS[lang].get(str(value or "").upper(), SENTIMENTS[lang]["UNKNOWN"])


def timeframe_label(value: str, lang: str | None = None) -> str:
    lang = normalize_lang(lang)
    return TIMEFRAMES[lang].get(str(value or ""), "" if value is None else str(value))


def quality_label(value: str, lang: str | None = None) -> str:
    lang = normalize_lang(lang)
    return QUALITY[lang].get(str(value or "").lower(), QUALITY[lang]["wait"])


def session_label(value: str, lang: str | None = None) -> str:
    lang = normalize_lang(lang)
    return SESSION_NAMES[lang].get(str(value or ""), "" if value is None else str(value))


def localize_reason(reason, lang: str | None = None) -> str:
    text = "" if reason is None else str(reason)
    for source, target in REASON_REPLACEMENTS[normalize_lang(lang)]:
        text = text.replace(source, target)
    return text


def localize_signal_payload(payload: dict, lang: str | None = None) -> dict:
    lang = normalize_lang(lang)
    result = deepcopy(payload or {})

    if "reasons" in result and isinstance(result["reasons"], list):
        result["reasons"] = [localize_reason(item, lang) for item in result["reasons"]]

    if "error" in result:
        result["error"] = localize_reason(result["error"], lang)

    if "signal_quality" in result:
        result["signal_quality"] = quality_label(result["signal_quality"], lang)

    status = result.get("data_status")
    if isinstance(status, dict):
        for item in status.values():
            if isinstance(item, dict) and "label" in item:
                item["label"] = localize_reason(item["label"], lang)

    news = result.get("news_filter")
    if isinstance(news, dict) and "reason" in news:
        news["reason"] = localize_reason(news["reason"], lang)

    return result
