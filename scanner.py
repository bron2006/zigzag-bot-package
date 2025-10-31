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
from utils_message_cleanup import bot_track_message

from config import (
    FOREX_SESSIONS, CRYPTO_PAIRS, COMMODITIES,
    SCANNER_COOLDOWN_SECONDS, get_chat_id,
    SCANNER_TIMEFRAME
)

logger = logging.getLogger("scanner")
get_api_detailed_signal_data = analysis_module.get_api_detailed_signal_data

# ... (інші функції без змін) ...

def _handle_analysis_result(pair_norm, result):
    try:
        if not result or result.get("error"):
            if result and result.get("error"):
                logger.warning(f"Analysis failed for {pair_norm}: {result.get('error')}")
            return

        score = result.get("score", 50)
        threshold = app_state.IDEAL_ENTRY_THRESHOLD
        lower_bound = 100 - threshold
        is_signal = score >= threshold or score <= lower_bound

        logger.info(f"[SCANNER_DIAG] Pair: {pair_norm}, Score: {score}. Is signal: {is_signal} (Threshold: >= {threshold} or <= {lower_bound})")

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
                sent = app_state.updater.bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown', reply_markup=kb)
                # track message in the bot_data used by updater.bot
                bot_track_message(app_state.updater.bot.bot_data, chat_id, sent.message_id)
            except Exception:
                logger.exception("Failed to send telegram notification")

        app_state.scanner_cooldown_cache[pair_norm] = now
        logger.info(f"SCANNER: Notified for {pair_norm} (Score: {score})")
    except Exception:
        logger.exception("Error handling analysis result")
