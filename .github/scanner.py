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
# --- ПОЧАТОК ЗМІН: Видаляємо IDEAL_ENTRY_THRESHOLD з імпортів ---
from config import (
    FOREX_SESSIONS, CRYPTO_PAIRS, COMMODITIES,
    SCANNER_COOLDOWN_SECONDS, get_chat_id, 
    SCANNER_TIMEFRAME
)
# --- КІНЕЦЬ ЗМІН ---

logger = logging.getLogger("scanner")
get_api_detailed_signal_data = analysis_module.get_api_detailed_signal_data

def _get_active_forex_sessions() -> list:
    SESSION_TIMES_UTC = {
        "Тихоокеанська": (21, 6), "Азіатська": (0, 9),
        "Європейська": (7, 16), "Американська": (13, 22)
    }
    utc_now = datetime.now(pytz.utc)
    current_hour = utc_now.hour
    active_sessions = []
    for session, (start, end) in SESSION_TIMES_UTC.items():
        if start > end: 
            if current_hour >= start or current_hour < end:
                active_sessions.append(session)
        else:
            if start <= current_hour < end:
                active_sessions.append(session)
    return active_sessions

def _collect_assets_to_scan():
    assets = []
    if app_state.get_scanner_state("forex"):
        active_sessions = _get_active_forex_sessions()
        logger.info(f"Active Forex sessions: {active_sessions}")
        for session_name in active_sessions:
            assets.extend(FOREX_SESSIONS.get(session_name, []))
    if app_state.get_scanner_state("crypto"):
        assets.extend(CRYPTO_PAIRS)
    if app_state.get_scanner_state("commodities"):
        assets.extend(COMMODITIES)
    if app_state.get_scanner_state("watchlist"):
        user_id = get_chat_id()
        if user_id:
            logger.info(f"Scanning watchlist for main user: {user_id}")
            watchlist_pairs = db.get_watchlist(user_id)
            assets.extend(watchlist_pairs)
    seen = set()
    return [a for a in assets if not (a in seen or seen.add(a))]

def _handle_analysis_result(pair_norm, result):
    try:
        if not result or result.get("error"):
            if result and result.get("error"):
                logger.warning(f"Analysis failed for {pair_norm}: {result.get('error')}")
            return
        
        score = result.get("score", 50)
        
        # --- ПОЧАТОК ЗМІН: Використовуємо поріг з app_state ---
        threshold = app_state.IDEAL_ENTRY_THRESHOLD
        lower_bound = 100 - threshold
        is_signal = score >= threshold or score <= lower_bound
        
        logger.info(f"[SCANNER_DIAG] Pair: {pair_norm}, Score: {score}. Is signal: {is_signal} (Threshold: >= {threshold} or <= {lower_bound})")
        # --- КІНЕЦЬ ЗМІН ---

        if not is_signal:
            return

        now = time.time()
        if (now - app_state.scanner_cooldown_cache.get(pair_norm, 0)) < SCANNER_COOLDOWN_SECONDS:
            logger.debug(f"{pair_norm} on cooldown, skip notify")
            return
        
        logger.info(f"[SCANNER_DIAG] Signal for {pair_norm} PASSED filter. Notifying.")
        
        try:
            app_state.sse_queue.put_nowait(result)
        except queue.Full:
            logger.warning("SSE queue full - dropping")

        app_state.latest_analysis_cache[pair_norm] = result
        chat_id = get_chat_id()
        if chat_id and app_state.updater:
            try:
                expiration = result.get('timeframe', '1m')
                message = telegram_ui._format_signal_message(result, expiration)
                kb = telegram_ui.get_main_menu_kb()
                app_state.updater.bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown', reply_markup=kb)
            except Exception:
                logger.exception("Failed to send telegram notification")

        app_state.scanner_cooldown_cache[pair_norm] = now
        logger.info(f"SCANNER: Notified for {pair_norm} (Score: {score})")
    except Exception:
        logger.exception("Error handling analysis result")

def _process_one_asset(pair: str):
    try:
        pair_norm = pair.replace("/", "")
        if not app_state.SYMBOLS_LOADED:
            logger.debug("Symbols not loaded yet, skipping asset processing.")
            return
        
        d = get_api_detailed_signal_data(app_state.client, app_state.symbol_cache, pair_norm, 0, SCANNER_TIMEFRAME)

        d.addCallback(lambda result, p=pair_norm: _handle_analysis_result(p, result))
        d.addErrback(lambda failure, p=pair_norm: logger.error(f"Critical error in analysis chain for {p}: {failure.getErrorMessage()}"))
    except Exception:
        logger.exception(f"Exception preparing analysis for asset {pair}")

def scan_markets_once():
    try:
        if not any(app_state.SCANNER_STATE.values()):
            logger.debug("All scanners disabled; skipping scan loop.")
            return
        assets = _collect_assets_to_scan()
        if not assets:
            logger.info("No assets configured for scanning.")
            return
        logger.info(f"SCANNER: Scheduling scan for {len(assets)} assets...")
        for i, pair in enumerate(assets):
            delay = i * 2.0
            reactor.callLater(delay, _process_one_asset, pair)
    except Exception:
        logger.exception("Error in scan_markets_once scheduler")