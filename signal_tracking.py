# signal_tracking.py
"""Tracks whether BUY/SELL signals the bot actually issued went on to move
price in the predicted direction — binary-option style: no TP/SL, just
"did price end up higher or lower than entry after a fixed horizon".
The horizon is tied to which pair of timeframes confirmed the signal (see
compute_horizon_seconds), matching the expiry binomo_executor.py would use
for the same signal. This module knows nothing about Binomo itself — it
only tracks outcomes against cTrader live prices."""
import logging
from datetime import datetime, timedelta, timezone

import db
from config import SIGNAL_OUTCOME_FLAT_THRESHOLD_PERCENT
from state import app_state

logger = logging.getLogger("signal_tracking")

# Confirmed-timeframe-pair -> horizon in seconds. analysis.py picks
# ("1m", "5m") when the requested timeframe is "1m", and ("5m", "15m")
# otherwise; the horizon is the longer of the two, giving price more time
# to move in the signal's direction.
_HORIZON_BY_TIMEFRAME = {
    "1m": 5 * 60,
    "5m": 15 * 60,
    "15m": 15 * 60,
}
_DEFAULT_HORIZON_SECONDS = 15 * 60


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def compute_horizon_seconds(timeframe: str) -> int:
    return _HORIZON_BY_TIMEFRAME.get(timeframe, _DEFAULT_HORIZON_SECONDS)


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

    if not pair or not isinstance(entry_price, (int, float)) or entry_price <= 0:
        logger.debug("Skipping outcome tracking for %s: no entry price", pair)
        return None

    horizon_seconds = compute_horizon_seconds(result.get("timeframe"))

    outcome_id = db.create_signal_outcome(
        pair=pair,
        timeframe=result.get("timeframe") or "",
        verdict=verdict,
        score=result.get("score"),
        entry_price=entry_price,
        horizon_seconds=horizon_seconds,
    )
    if outcome_id:
        logger.info(
            "SIGNAL_OUTCOME: recorded pending #%s %s %s entry=%.5f horizon=%ss",
            outcome_id, pair, verdict, entry_price, horizon_seconds,
        )
    return outcome_id


def _classify_move(entry_price: float, exit_price: float) -> str:
    if entry_price <= 0:
        return "flat"

    change_percent = abs(exit_price - entry_price) / entry_price * 100
    if change_percent < SIGNAL_OUTCOME_FLAT_THRESHOLD_PERCENT:
        return "flat"

    return "up" if exit_price > entry_price else "down"


def resolve_pending_signals() -> None:
    pending = db.get_pending_signal_outcomes()
    if not pending:
        return

    now = _utcnow_naive()

    for row in pending:
        entry_ts = row["entry_ts"]
        horizon_seconds = row["horizon_seconds"]
        if not isinstance(entry_ts, datetime) or not horizon_seconds:
            continue

        if now - entry_ts < timedelta(seconds=horizon_seconds):
            continue  # horizon hasn't elapsed yet

        pair = row["pair"]
        price_data = app_state.get_live_price(pair)
        live_price = price_data.get("mid") if price_data else None

        if not isinstance(live_price, (int, float)):
            logger.debug("SIGNAL_OUTCOME: no live price for %s yet, will retry", pair)
            continue

        outcome = _classify_move(row["entry_price"], live_price)

        if db.resolve_signal_outcome(row["id"], outcome=outcome, exit_price=live_price):
            logger.info(
                "SIGNAL_OUTCOME: #%s %s %s -> %s (entry=%.5f exit=%.5f)",
                row["id"], pair, row["verdict"], outcome, row["entry_price"], live_price,
            )
