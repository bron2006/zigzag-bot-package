# scanner.py
import logging
import time
from datetime import datetime

import pytz
from twisted.internet import reactor
from twisted.internet.defer import DeferredList, DeferredSemaphore, succeed
from twisted.internet.threads import deferToThreadPool

import analysis as analysis_module
import db
import telegram_ui
from config import (
    COMMODITIES,
    CRYPTO_PAIRS,
    FOREX_SESSIONS,
    SCANNER_COOLDOWN_SECONDS,
    SCANNER_TIMEFRAME,
    get_chat_id,
)
from errors import safe_call
from notifier import send_signal
from state import app_state

logger = logging.getLogger("scanner")

STALE_PRICE_THRESHOLD = 300
_MAX_CONCURRENT_ANALYSIS = 4

get_api_detailed_signal_data = analysis_module.get_api_detailed_signal_data

_scan_semaphore = DeferredSemaphore(tokens=_MAX_CONCURRENT_ANALYSIS)
_scan_active = False


def _blocking_pool():
    return app_state.blocking_pool or reactor.getThreadPool()


def _get_active_forex_sessions() -> list:
    session_times_utc = {
        "Тихоокеанська": (21, 6),
        "Азіатська": (0, 9),
        "Європейська": (7, 16),
        "Американська": (13, 22),
    }

    utc_now = datetime.now(pytz.utc)
    current_hour = utc_now.hour
    active = []

    for session, (start, end) in session_times_utc.items():
        if start > end:
            if current_hour >= start or current_hour < end:
                active.append(session)
        else:
            if start <= current_hour < end:
                active.append(session)

    return active


@safe_call("collect_assets", threshold=5, default=[])
def _collect_assets_to_scan() -> list:
    assets = []

    if app_state.get_scanner_state("forex"):
        active_sessions = _get_active_forex_sessions()
        logger.info(f"Активні Forex сесії: {active_sessions}")
        for session_name in active_sessions:
            assets.extend(FOREX_SESSIONS.get(session_name, []))

    if app_state.get_scanner_state("crypto"):
        assets.extend(CRYPTO_PAIRS)

    if app_state.get_scanner_state("commodities"):
        assets.extend(COMMODITIES)

    if app_state.get_scanner_state("watchlist"):
        user_id = get_chat_id()
        if user_id:
            assets.extend(db.get_watchlist(user_id))

    seen = set()
    normalized = []
    for asset in assets:
        pair = asset.replace("/", "").upper()
        if pair not in seen:
            seen.add(pair)
            normalized.append(pair)

    return normalized


def _send_signal_async(chat_id: int, message: str, reply_markup=None):
    return deferToThreadPool(
        reactor,
        _blocking_pool(),
        send_signal,
        chat_id,
        message,
        "Markdown",
        reply_markup,
    )


def _handle_analysis_result(pair_norm: str, result: dict):
    if not result:
        return succeed(None)

    if result.get("error"):
        logger.warning(f"Аналіз не вдався для {pair_norm}: {result.get('error')}")
        return succeed(None)

    score = int(result.get("score", 50))
    verdict = result.get("verdict_text", "NEUTRAL")
    trade_allowed = bool(result.get("is_trade_allowed", False))
    sentiment = result.get("sentiment", "GO")

    threshold = app_state.IDEAL_ENTRY_THRESHOLD
    lower_bound = 100 - threshold

    is_signal = False
    if trade_allowed and sentiment != "BLOCK":
        if verdict == "BUY" and score >= threshold:
            is_signal = True
        elif verdict == "SELL" and score <= lower_bound:
            is_signal = True

    logger.info(
        f"[SCANNER] {pair_norm}: verdict={verdict}, score={score}, "
        f"sentiment={sentiment}, trade_allowed={trade_allowed}, signal={is_signal}"
    )

    app_state.latest_analysis_cache[pair_norm] = result

    if not is_signal:
        return succeed(None)

    now = time.time()
    last_ts = app_state.scanner_cooldown_cache.get(pair_norm, 0)
    if (now - last_ts) < SCANNER_COOLDOWN_SECONDS:
        logger.debug(f"{pair_norm} на cooldown, пропускаємо")
        return succeed(None)

    result.setdefault("type", "signal")
    result["pair"] = pair_norm
    result["ts"] = now

    app_state.publish_sse(result)
    app_state.scanner_cooldown_cache[pair_norm] = now

    chat_id = get_chat_id()
    if not chat_id:
        logger.info(f"[SCANNER] Сигнал для {pair_norm} готовий, але CHAT_ID не задано")
        return succeed(result)

    expiration = result.get("timeframe", SCANNER_TIMEFRAME)
    message = telegram_ui._format_signal_message(result, expiration)
    kb = telegram_ui.get_main_menu_kb()

    logger.info(f"[SCANNER] Надсилаємо сигнал для {pair_norm}")
    d = _send_signal_async(chat_id, message, reply_markup=kb)

    def _done(_):
        logger.info(f"SCANNER: Сигнал надіслано для {pair_norm} (score={score})")
        return result

    def _failed(failure):
        logger.error(f"SCANNER: Не вдалося надіслати сигнал для {pair_norm}: {failure.getErrorMessage()}")
        return None

    d.addCallbacks(_done, _failed)
    return d


def _process_one_asset(pair_norm: str):
    if not app_state.SYMBOLS_LOADED:
        logger.debug("Символи ще не завантажені, пропускаємо.")
        return succeed(None)

    price_data = app_state.get_live_price(pair_norm)
    if price_data is None:
        logger.debug(f"Немає живої ціни для {pair_norm} — ще не прийшла, пропускаємо.")
        return succeed(None)

    age = time.time() - price_data.get("ts", 0)
    if age > STALE_PRICE_THRESHOLD:
        logger.warning(
            f"{pair_norm}: ціна застаріла ({age:.0f}s > {STALE_PRICE_THRESHOLD}s), пропускаємо."
        )
        return succeed(None)

    try:
        d = get_api_detailed_signal_data(
            app_state.client,
            app_state.symbol_cache,
            pair_norm,
            0,
            SCANNER_TIMEFRAME,
        )
        d.addCallback(lambda result, p=pair_norm: _handle_analysis_result(p, result))
        d.addErrback(
            lambda failure, p=pair_norm: logger.error(
                f"Критична помилка в ланцюгу аналізу для {p}: {failure.getErrorMessage()}"
            )
        )
        return d
    except Exception:
        logger.exception(f"Виняток при підготовці аналізу для {pair_norm}")
        return succeed(None)


@safe_call("scanner_loop", threshold=5, default=None)
def scan_markets_once() -> None:
    global _scan_active

    if _scan_active:
        logger.warning("SCANNER: попередній цикл ще триває — пропускаємо новий запуск")
        return

    state_snapshot = app_state.get_scanner_state_snapshot()
    if not any(state_snapshot.values()):
        logger.debug("Всі сканери вимкнені; пропускаємо.")
        return

    assets = _collect_assets_to_scan()
    if not assets:
        logger.info("Немає активів для сканування.")
        return

    if not app_state.get_live_prices_snapshot() and app_state.SYMBOLS_LOADED:
        logger.warning("live_prices порожній але символи завантажені — перезапускаємо підписку")
        try:
            from ctrader import start_price_subscriptions
            reactor.callLater(0, start_price_subscriptions)
        except Exception:
            logger.exception("Не вдалося перезапустити підписку")

    logger.info(f"SCANNER: Запускаю скан для {len(assets)} активів...")
    _scan_active = True

    deferreds = []

    for asset in assets:
        d = _scan_semaphore.run(_process_one_asset, asset)
        deferreds.append(d)

    dl = DeferredList(deferreds, consumeErrors=True)

    def _finish(_):
        global _scan_active
        _scan_active = False
        logger.info("SCANNER: цикл завершено")
        return None

    def _finish_err(failure):
        global _scan_active
        _scan_active = False
        logger.error(f"SCANNER: цикл завершився з помилкою: {failure.getErrorMessage()}")
        return None

    dl.addCallbacks(_finish, _finish_err)