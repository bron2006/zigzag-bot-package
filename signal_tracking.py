# signal_tracking.py
"""Tracks whether BUY/SELL signals the bot actually issued went on to hit
their take-profit or stop-loss, so win-rate can be measured instead of
guessed. TP/SL are sized off ATR at signal time (config.py multipliers);
outcomes are resolved later against live prices by resolve_pending_signals()."""
import logging
from datetime import datetime, timedelta, timezone

import db
from config import (
    SIGNAL_OUTCOME_TIMEOUT_HOURS,
    SIGNAL_SL_ATR_MULTIPLIER,
    SIGNAL_TP_ATR_MULTIPLIER,
)
from state import app_state

logger = logging.getLogger("signal_tracking")


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def compute_tp_sl(verdict: str, entry_price: float, atr: float) -> tuple[float, float] | None:
    if not isinstance(entry_price, (int, float)) or not isinstance(atr, (int, float)):
        return None
    if entry_price <= 0 or atr <= 0:
        return None

    tp_distance = atr * SIGNAL_TP_ATR_MULTIPLIER
    sl_distance = atr * SIGNAL_SL_ATR_MULTIPLIER

    if verdict == "BUY":
        return entry_price + tp_distance, entry_price - sl_distance
    if verdict == "SELL":
        return entry_price - tp_distance, entry_price + sl_distance
    return None


def maybe_record_signal(result: dict) -> int | None:
    """Record a pending SignalOutcome for a result the bot actually surfaced
    as a signal (is_trade_allowed=True, directional verdict). Safe to call
    on every such result — recording failures are logged, never raised."""
    if not isinstance(result, dict) or not result.get("is_trade_allowed"):
        return None

    verdict = str(result.get("verdict_text") or "").upper()
    if verdict not in {"BUY", "SELL"}:
        return None

    pair = result.get("pair")
    entry_price = result.get("price")
    atr = result.get("atr")

    if not pair or not isinstance(entry_price, (int, float)):
        logger.debug("Skipping outcome tracking for %s: no entry price", pair)
        return None

    if not isinstance(atr, (int, float)) or atr <= 0:
        logger.debug("Skipping outcome tracking for %s: no ATR available", pair)
        return None

    levels = compute_tp_sl(verdict, entry_price, atr)
    if levels is None:
        return None

    tp_price, sl_price = levels
    outcome_id = db.create_signal_outcome(
        pair=pair,
        timeframe=result.get("timeframe") or "",
        verdict=verdict,
        score=result.get("score"),
        entry_price=entry_price,
        tp_price=tp_price,
        sl_price=sl_price,
    )
    if outcome_id:
        logger.info(
            "SIGNAL_OUTCOME: recorded pending #%s %s %s entry=%.5f tp=%.5f sl=%.5f",
            outcome_id, pair, verdict, entry_price, tp_price, sl_price,
        )
    return outcome_id


def _pip_multiplier(pair: str) -> float:
    symbol = app_state.get_symbol_details(pair)
    pip_position = getattr(symbol, "pipPosition", None)
    if isinstance(pip_position, int) and pip_position >= 0:
        return float(10 ** pip_position)

    digits = getattr(symbol, "digits", None)
    if isinstance(digits, int) and digits >= 1:
        return float(10 ** (digits - 1))

    return 10000.0


def _calc_pnl_pips(pair: str, verdict: str, entry_price: float, exit_price: float) -> float:
    multiplier = _pip_multiplier(pair)
    diff = (exit_price - entry_price) if verdict == "BUY" else (entry_price - exit_price)
    return diff * multiplier


def resolve_pending_signals() -> None:
    pending = db.get_pending_signal_outcomes()
    if not pending:
        return

    now = _utcnow_naive()
    timeout_delta = timedelta(hours=max(0.25, float(SIGNAL_OUTCOME_TIMEOUT_HOURS or 4)))

    for row in pending:
        pair = row["pair"]
        verdict = row["verdict"]
        entry_price = row["entry_price"]
        tp_price = row["tp_price"]
        sl_price = row["sl_price"]
        entry_ts = row["entry_ts"]

        price_data = app_state.get_live_price(pair)
        live_price = price_data.get("mid") if price_data else None

        outcome = None
        exit_price = None

        if isinstance(live_price, (int, float)) and tp_price is not None and sl_price is not None:
            if verdict == "BUY":
                if live_price >= tp_price:
                    outcome, exit_price = "tp", tp_price
                elif live_price <= sl_price:
                    outcome, exit_price = "sl", sl_price
            elif verdict == "SELL":
                if live_price <= tp_price:
                    outcome, exit_price = "tp", tp_price
                elif live_price >= sl_price:
                    outcome, exit_price = "sl", sl_price

        if outcome is None and isinstance(entry_ts, datetime) and (now - entry_ts) >= timeout_delta:
            outcome = "timeout"
            exit_price = live_price if isinstance(live_price, (int, float)) else entry_price

        if outcome is None:
            continue

        pnl_pips = None
        if exit_price is not None:
            try:
                pnl_pips = _calc_pnl_pips(pair, verdict, entry_price, exit_price)
            except Exception:
                logger.debug("Could not compute pnl_pips for %s", pair, exc_info=True)

        if db.resolve_signal_outcome(row["id"], outcome=outcome, pnl_pips=pnl_pips):
            logger.info(
                "SIGNAL_OUTCOME: #%s %s %s -> %s (pnl_pips=%s)",
                row["id"],
                pair,
                verdict,
                outcome,
                f"{pnl_pips:.1f}" if pnl_pips is not None else "n/a",
            )
