# threshold_advisor.py
"""Part 2: daily recommendation for the BUY/SELL entry threshold, computed
from accumulated SignalOutcome data (see signal_tracking.py / Part 1).

This module ONLY sends a suggestion to the admin via Telegram - it never
changes app_state.IDEAL_ENTRY_THRESHOLD itself. Auto-adjusting a live
trading-signal threshold is a decision with real financial consequences and
stays with a human."""
import logging

import db
from config import (
    THRESHOLD_RECOMMENDATION_LOOKBACK_DAYS,
    THRESHOLD_RECOMMENDATION_MIN_IMPROVEMENT_PP,
    THRESHOLD_RECOMMENDATION_MIN_SAMPLES,
)
from state import app_state

logger = logging.getLogger("threshold_advisor")

# Candidate thresholds evaluated against the current one. Score buckets are
# 5-wide (see db.get_signal_outcome_score_breakdown), so candidates are kept
# on that same grid.
_CANDIDATE_THRESHOLDS = [55, 60, 65, 70, 75, 80, 85, 90, 95]


def _cohort_stats(buckets: list[dict], threshold: int) -> dict:
    """Aggregate every bucket at or above `threshold` into one win-rate
    figure: "what would win-rate look like if only signals scoring at least
    this much had been taken"."""
    wins = sum(b["wins"] for b in buckets if b["bucket_start"] >= threshold)
    losses = sum(b["losses"] for b in buckets if b["bucket_start"] >= threshold)
    decided = wins + losses
    return {
        "threshold": threshold,
        "decided": decided,
        "win_rate": round(100.0 * wins / decided, 1) if decided else None,
    }


def build_recommendation() -> str | None:
    """Returns a human-readable recommendation message, or None if there
    isn't enough resolved-signal data yet to say anything meaningful."""
    buckets = db.get_signal_outcome_score_breakdown(
        days=THRESHOLD_RECOMMENDATION_LOOKBACK_DAYS,
        bucket_size=5,
    )
    if not buckets:
        return None

    current_threshold = app_state.IDEAL_ENTRY_THRESHOLD
    current = _cohort_stats(buckets, current_threshold)
    if current["decided"] < THRESHOLD_RECOMMENDATION_MIN_SAMPLES or current["win_rate"] is None:
        return None

    candidates = [
        _cohort_stats(buckets, threshold)
        for threshold in _CANDIDATE_THRESHOLDS
        if threshold != current_threshold
    ]
    candidates = [
        c for c in candidates
        if c["decided"] >= THRESHOLD_RECOMMENDATION_MIN_SAMPLES and c["win_rate"] is not None
    ]

    best = max(candidates, key=lambda c: c["win_rate"], default=None)

    lines = [
        "📈 Рекомендація по порогу входу (аналіз, НЕ автозміна)",
        f"Період: останні {THRESHOLD_RECOMMENDATION_LOOKBACK_DAYS}д",
        f"Поточний поріг {current_threshold}: winrate {current['win_rate']}% "
        f"({current['decided']} закритих угод)",
    ]

    improvement = (best["win_rate"] - current["win_rate"]) if best else 0
    if best and improvement >= THRESHOLD_RECOMMENDATION_MIN_IMPROVEMENT_PP:
        lines.append(
            f"Спробуй поріг {best['threshold']}: winrate {best['win_rate']}% "
            f"({best['decided']} угод) — на {improvement:.1f}пп краще."
        )
        lines.append("Це лише рекомендація на основі накопиченої статистики — рішення про зміну IDEAL_ENTRY_THRESHOLD за тобою.")
    else:
        lines.append("Суттєво кращої альтернативи серед перевірених порогів поки не знайдено.")

    return "\n".join(lines)


def send_daily_recommendation() -> None:
    try:
        message = build_recommendation()
    except Exception:
        logger.exception("Failed to build threshold recommendation")
        return

    if not message:
        logger.info("Threshold advisor: недостатньо даних для рекомендації")
        return

    logger.info("Threshold advisor: %s", message.replace("\n", " | "))

    try:
        from notifier import notify_admin

        notify_admin(message, alert_key="threshold_recommendation_daily")
    except Exception:
        logger.exception("Failed to send threshold recommendation to admin")
