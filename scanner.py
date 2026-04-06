# scanner.py
import time
import queue
import logging
from datetime import datetime
import pytz
from twisted.internet import reactor
from state import app_state
import telegram_ui
import db
import analysis as analysis_module
from config import (
    FOREX_SESSIONS, CRYPTO_PAIRS, COMMODITIES,
    SCANNER_COOLDOWN_SECONDS, get_chat_id,
    SCANNER_TIMEFRAME
)
from errors import safe_call, safe_twisted, StaleDataError
from notifier import send_signal

logger = logging.getLogger("scanner")

STALE_PRICE_THRESHOLD = 300   # секунд — має збігатись з ctrader._STALE_THRESHOLD

get_api_detailed_signal_data = analysis_module.get_api_detailed_signal_data


# ---------------------------------------------------------------------------
# Сесії та активи
# ---------------------------------------------------------------------------

def _get_active_forex_sessions() -> list:
    SESSION_TIMES_UTC = {
        "Тихоокеанська": (21, 6), "Азіатська":   (0,  9),
        "Європейська":   (7, 16), "Американська": (13, 22)
    }
    utc_now      = datetime.now(pytz.utc)
    current_hour = utc_now.hour
    active       = []
    for session, (start, end) in SESSION_TIMES_UTC.items():
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
            logger.info(f"Скануємо watchlist для: {user_id}")
            assets.extend(db.get_watchlist(user_id))
    seen = set()
    return [a for a in assets if not (a in seen or seen.add(a))]


# ---------------------------------------------------------------------------
# Обробка результату аналізу
# ---------------------------------------------------------------------------

@safe_twisted("handle_analysis_result", threshold=10)
def _handle_analysis_result(pair_norm: str, result: dict) -> None:
    if not result or result.get("error"):
        if result and result.get("error"):
            logger.warning(f"Аналіз не вдався для {pair_norm}: {result.get('error')}")
        return

    score       = result.get("score", 50)
    threshold   = app_state.IDEAL_ENTRY_THRESHOLD
    lower_bound = 100 - threshold
    is_signal   = score >= threshold or score <= lower_bound

    logger.info(
        f"[SCANNER] {pair_norm}: score={score}, signal={is_signal} "
        f"(поріг: >={threshold} або <={lower_bound})"
    )
    if not is_signal:
        return

    now = time.time()
    if (now - app_state.scanner_cooldown_cache.get(pair_norm, 0)) < SCANNER_COOLDOWN_SECONDS:
        logger.debug(f"{pair_norm} на cooldown, пропускаємо")
        return

    logger.info(f"[SCANNER] Сигнал для {pair_norm} пройшов фільтр. Надсилаємо.")

    try:
        app_state.sse_queue.put_nowait(result)
    except queue.Full:
        logger.warning("SSE черга повна — сигнал скинуто")

    app_state.latest_analysis_cache[pair_norm] = result

    chat_id = get_chat_id()
    if chat_id:
        expiration = result.get('timeframe', '1m')
        message    = telegram_ui._format_signal_message(result, expiration)
        kb         = telegram_ui.get_main_menu_kb()
        sent_ok    = send_signal(chat_id, message, reply_markup=kb)

        if sent_ok and app_state.updater:
            # Відстежуємо повідомлення для подальшого очищення
            try:
                pass  # send_signal не повертає message_id — при потребі розширити
            except Exception:
                logger.exception("Не вдалося зберегти message_id в bot_data")

    app_state.scanner_cooldown_cache[pair_norm] = now
    logger.info(f"SCANNER: Сигнал надіслано для {pair_norm} (score={score})")


# ---------------------------------------------------------------------------
# Обробка одного активу
# ---------------------------------------------------------------------------

@safe_call("process_asset", threshold=10, default=None)
def _process_one_asset(pair: str) -> None:
    pair_norm = pair.replace("/", "")

    if not app_state.SYMBOLS_LOADED:
        logger.debug("Символи ще не завантажені, пропускаємо.")
        return

    # Перевірка стейл цін перед аналізом
    price_data = app_state.live_prices.get(pair_norm)
    if price_data is None:
        raise StaleDataError(f"Немає живої ціни для {pair_norm}", pair=pair_norm)

    age = time.time() - price_data.get("ts", 0)
    if age > STALE_PRICE_THRESHOLD:
        raise StaleDataError(
            f"Ціна {pair_norm} застаріла ({age:.0f}s, поріг={STALE_PRICE_THRESHOLD}s)",
            pair=pair_norm,
            age_seconds=age,
        )

    d = get_api_detailed_signal_data(
        app_state.client, app_state.symbol_cache, pair_norm, 0, SCANNER_TIMEFRAME
    )
    d.addCallback(lambda result, p=pair_norm: _handle_analysis_result(p, result))
    d.addErrback(
        lambda failure, p=pair_norm: logger.error(
            f"Критична помилка в ланцюгу аналізу для {p}: {failure.getErrorMessage()}"
        )
    )


# ---------------------------------------------------------------------------
# Головний цикл сканера
# ---------------------------------------------------------------------------

@safe_call("scanner_loop", threshold=5, default=None)
def scan_markets_once() -> None:
    if not any(app_state.SCANNER_STATE.values()):
        logger.debug("Всі сканери вимкнені; пропускаємо.")
        return

    assets = _collect_assets_to_scan()
    if not assets:
        logger.info("Немає активів для сканування.")
        return

    logger.info(f"SCANNER: Планую скан для {len(assets)} активів...")
    for i, pair in enumerate(assets):
        delay = i * 2.0
        try:
            reactor.callLater(delay, _process_one_asset, pair)
        except Exception:
            logger.exception(f"Не вдалося запланувати скан для {pair}")
