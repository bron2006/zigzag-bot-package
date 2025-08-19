# -*- coding: utf-8 -*-
import os
import json
import logging
from typing import Any, Dict, Optional

from klein import Klein
from twisted.internet import reactor, defer
from twisted.internet.defer import maybeDeferred
from twisted.web.static import File

# Локальні модулі
import state
import config
import analysis
import telegram_ui

# ---------- ЛОГІНГ ----------
logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO")),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
log = logging.getLogger("main")

app = Klein()

# Статика для /webapp/*
WEBAPP_DIR = os.path.join(os.path.dirname(__file__), "webapp")
if os.path.isdir(WEBAPP_DIR):
    # /webapp/index.html та решта фронтенду
    app.resource.putChild(b"webapp", File(WEBAPP_DIR))

# ---------- JSON УТИЛІТИ ----------
def on_success(data: Any) -> Dict[str, Any]:
    return {"ok": True, "data": data}

def on_error(code: str, message: str, details: Optional[Any] = None) -> Dict[str, Any]:
    err = {"ok": False, "error": {"code": code, "message": message}}
    if details is not None:
        err["error"]["details"] = details
    return err

def _json_response(request, payload: Dict[str, Any], status: int = 200):
    request.setHeader(b"Content-Type", b"application/json; charset=utf-8")
    request.setResponseCode(status)
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")

def _get_arg(request, name: str) -> Optional[str]:
    """Повертає GET-параметр як str або None."""
    raw = request.args.get(name.encode("utf-8"))
    if not raw:
        return None
    return raw[0].decode("utf-8")

def _get_json_body(request) -> Dict[str, Any]:
    try:
        body = request.content.read()
        if not body:
            return {}
        return json.loads(body.decode("utf-8"))
    except Exception:
        return {}

# ---------- HEALTH ----------
@app.route("/health", methods=["GET"])
def health(request):
    payload = on_success(
        {
            "status": "ok",
            "symbols_cached": len(state.symbol_cache) if getattr(state, "symbol_cache", None) else 0,
            "telegram_webhook": bool(getattr(state, "updater", None)),
        }
    )
    return _json_response(request, payload, 200)

# ---------- РЕЙТИНГ ПАР ДЛЯ WEBAPP ----------
@app.route("/api/get_ranked_pairs", methods=["GET"])
def get_ranked_pairs(request):
    try:
        pairs = []
        # 1) Якщо є кеш символів з cTrader — беремо з нього
        if getattr(state, "symbol_cache", None):
            for s in state.symbol_cache:
                sym = str(s)
                if "/" in sym or "_" in sym:
                    pairs.append(sym.replace("_", "/"))
        # 2) Якщо кеш порожній — беремо зі статичного конфіга
        if not pairs and hasattr(config, "FOREX_PAIRS"):
            pairs = list(config.FOREX_PAIRS)
        # 3) Фолбек
        if not pairs:
            pairs = ["EUR/USD", "GBP/USD", "USD/JPY", "BTC/USD", "ETH/USD"]

        # Проста "ранжировка" — алфавітом (у вас може бути своя логіка)
        pairs = sorted(set(pairs))
        data = [{"pair": p, "label": p} for p in pairs[:200]]

        return _json_response(request, on_success(data), 200)
    except Exception as e:
        log.exception("get_ranked_pairs failed")
        return _json_response(request, on_error("RANKED_PAIRS_ERROR", "Не вдалося отримати список пар", str(e)), 200)

# ---------- API: СИГНАЛ ----------
@app.route("/api/signal", methods=["GET", "POST"])
def api_signal(request):
    try:
        # Підтримка обох форматів: GET ?pair=EUR/USD і POST {"pair": "..."}
        pair = _get_arg(request, "pair")
        if not pair:
            body = _get_json_body(request)
            pair = body.get("pair") or body.get("symbol")

        if not pair:
            return _json_response(request, on_error("VALIDATION_ERROR", "Пара (pair) обовʼязкова"), 200)

        # Аналіз може бути sync або async — maybeDeferred покриває обидва випадки
        d = maybeDeferred(analysis.get_signal, pair)

        @d.addCallback
        def _ok(res):
            payload = on_success({"pair": pair, "signal": res})
            return _json_response(request, payload, 200)

        @d.addErrback
        def _fail(f):
            log.error("api_signal error for %s: %s", pair, f.getErrorMessage())
            payload = on_error("ANALYSIS_ERROR", "Не вдалося отримати сигнал", f.getErrorMessage())
            return _json_response(request, payload, 200)

        return d
    except Exception as e:
        log.exception("api_signal unexpected error")
        return _json_response(request, on_error("UNEXPECTED", "Непередбачена помилка", str(e)), 200)

# ---------- API: MTA ----------
@app.route("/api/get_mta", methods=["GET", "POST"])
def api_get_mta(request):
    try:
        pair = _get_arg(request, "pair")
        if not pair:
            body = _get_json_body(request)
            pair = body.get("pair") or body.get("symbol")

        if not pair:
            return _json_response(request, on_error("VALIDATION_ERROR", "Пара (pair) обовʼязкова"), 200)

        d = maybeDeferred(analysis.get_mta, pair)

        @d.addCallback
        def _ok(res):
            payload = on_success({"pair": pair, "mta": res})
            return _json_response(request, payload, 200)

        @d.addErrback
        def _fail(f):
            log.error("api_get_mta error for %s: %s", pair, f.getErrorMessage())
            payload = on_error("MTA_ERROR", "Не вдалося отримати MTA", f.getErrorMessage())
            return _json_response(request, payload, 200)

        return d
    except Exception as e:
        log.exception("api_get_mta unexpected error")
        return _json_response(request, on_error("UNEXPECTED", "Непередбачена помилка", str(e)), 200)

# ---------- TELEGRAM WEBHOOK (ОБОВʼЯЗКОВО, ЩОБ БОТ НЕ ПАДАВ) ----------
@app.route("/<token>", methods=["POST"])
def telegram_webhook(request, token: str):
    """
    Telegram надсилає оновлення на URL виду: https://<host>/<BOT_TOKEN>
    Раніше у вас були 404 — тепер обробляємо й передаємо в Dispatcher.
    """
    try:
        if not getattr(state, "updater", None) or token != state.BOT_TOKEN:
            return _json_response(request, on_error("WEBHOOK_DISABLED", "Бот не ініціалізований або токен не збігається"), 404)

        body = request.content.read()
        if not body:
            return _json_response(request, on_error("EMPTY", "Порожнє тіло запиту"), 200)

        from telegram import Update as TgUpdate  # імпорт тут, щоб не ламати завантаження, якщо немає токена
        update = TgUpdate.de_json(json.loads(body.decode("utf-8")), state.updater.bot)
        state.dispatcher.process_update(update)
        return _json_response(request, on_success({"status": "accepted"}), 200)
    except Exception as e:
        log.exception("telegram_webhook failed")
        return _json_response(request, on_error("WEBHOOK_ERROR", "Помилка обробки вебхука", str(e)), 200)

# ---------- ІНІЦІАЛІЗАЦІЯ БОТА ----------
def _looks_like_token(token: str) -> bool:
    return bool(token and ":" in token and len(token) > 20)

def init_telegram_bot():
    """
    Ініціалізація без pollinga: лише dispatcher + webhook.
    Якщо токен відсутній або некоректний — НЕ падаємо, просто логуємо.
    """
    token = getattr(config, "TELEGRAM_BOT_TOKEN", os.getenv("TELEGRAM_BOT_TOKEN", "")).strip()
    state.BOT_TOKEN = token

    if not _looks_like_token(token):
        log.warning("TELEGRAM_BOT_TOKEN не заданий або виглядає некоректно — бот не буде запущений.")
        state.updater = None
        state.dispatcher = None
        return

    try:
        from telegram.ext import Updater

        state.updater = Updater(token, use_context=True)
        state.dispatcher = state.updater.dispatcher

        # Регіструємо всі хендлери в одному місці
        telegram_ui.register_handlers(state.dispatcher)

        # Налаштовуємо webhook, якщо задано URL
        webhook_url = getattr(config, "TELEGRAM_WEBHOOK_URL", os.getenv("TELEGRAM_WEBHOOK_URL", "")).strip()
        if webhook_url:
            state.updater.bot.set_webhook(webhook_url.rstrip("/") + f"/{token}")
            log.info("Telegram webhook встановлено: %s", webhook_url)
        else:
            log.warning("TELEGRAM_WEBHOOK_URL не заданий — прийматимемо оновлення, якщо Telegram шле на /<token> напряму.")
    except Exception as e:
        # Критично: не валимо увесь застосунок, якщо помилився токен
        log.error("Помилка ініціалізації Telegram-бота: %s", e, exc_info=True)
        state.updater = None
        state.dispatcher = None

# ---------- CTRADER І БАЗА (ОПЦІЙНО: лишаємо як було у вас) ----------
def init_db():
    try:
        import db
        db.init_db()
        log.info("✅ Базу даних ініціалізовано.")
    except Exception as e:
        log.error("DB init failed: %s", e, exc_info=True)

def init_ctrader():
    try:
        import spotware_connect
        # ваш внутрішній старт клієнта; якщо він асинхронний — у вас уже це було налаштовано
        spotware_connect.start()
        log.info("✅ cTrader клієнт ініціалізовано.")
    except Exception as e:
        log.error("cTrader init failed: %s", e, exc_info=True)

# ---------- ЗАПУСК ----------
if __name__ == "__main__":
    init_db()
    init_telegram_bot()  # важливо — тепер бот не валить процес при InvalidToken
    try:
        init_ctrader()
    except Exception:
        pass

    # Klein
    app.run("0.0.0.0", int(os.getenv("PORT", "8080")))
    reactor.run()
