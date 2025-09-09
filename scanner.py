# scanner.py
import time
import queue
import logging
from twisted.internet import reactor

from state import app_state
import telegram_ui
import db
import analysis as analysis_module
from config import (
    FOREX_SESSIONS, CRYPTO_PAIRS, COMMODITIES,
    SCANNER_COOLDOWN_SECONDS, get_chat_id
)

logger = logging.getLogger("scanner")
get_api_detailed_signal_data = analysis_module.get_api_detailed_signal_data

def _collect_assets_to_scan():
    assets = []
    if app_state.get_scanner_state("forex"):
        for session_pairs in FOREX_SESSIONS.values():
            assets.extend(session_pairs)
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

# --- ПОЧАТОК ЗМІН: Нова логіка обробки результату ---
def _handle_analysis_result(pair_norm, result):
    try:
        if not result or result.get("error"):
            if result and result.get("error"):
                 logger.warning(f"Analysis failed for {pair_norm}: {result.get('error')}")
            return
        
        verdict = result.get("verdict_text", "NEUTRAL")
        
        # Перевіряємо, чи є сигнал CALL або PUT
        is_signal = verdict in ["⬆️ CALL", "⬇️ PUT"]
        
        logger.info(f"[SCANNER_DIAG] Pair: {pair_norm}, Verdict: {verdict}. Is signal: {is_signal}")

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
                # Використовуємо '1m'/'5m' як заглушку для експірації, оскільки сканер не має цього контексту
                message = telegram_ui._format_signal_message(result, "5m") 
                kb = telegram_ui.get_main_menu_kb()
                app_state.updater.bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown', reply_markup=kb)
            except Exception:
                logger.exception("Failed to send telegram notification")

        app_state.scanner_cooldown_cache[pair_norm] = now
        logger.info(f"SCANNER: Notified for {pair_norm} (Verdict: {verdict})")
    except Exception:
        logger.exception("Error handling analysis result")
# --- КІНЕЦЬ ЗМІН ---

def _process_one_asset(pair: str):
    try:
        pair_norm = pair.replace("/", "")
        if not app_state.SYMBOLS_LOADED:
            logger.debug("Symbols not loaded yet, skipping asset processing.")
            return
        
        # Сканер за замовчуванням використовує 5-хвилинний таймфрейм для аналізу
        d = get_api_detailed_signal_data(app_state.client, app_state.symbol_cache, pair_norm, 0, "5m")
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