# signal_tracking.py
"""Tracks whether BUY/SELL signals the bot actually issued went on to move
price in the predicted direction — binary-option style: no TP/SL, just
"did price end up higher or lower than entry after a fixed horizon".
The horizon is tied to which pair of timeframes confirmed the signal (see
compute_horizon_seconds), matching the expiry binomo_executor.py would use
for the same signal. This module knows nothing about Binomo itself — it
only tracks outcomes against cTrader live prices."""
import logging
import math
import time
from datetime import datetime, timedelta, timezone

import db
from config import SIGNAL_OUTCOME_FLAT_THRESHOLD_PERCENT, SIGNAL_PRICE_SANITY_MAX_DIVERGENCE_PERCENT
from notifier import notify_admin
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
_ENDPOINT_TOLERANCE_SECONDS = 5.0
# Allow transport/worker scheduling delay, NOT a later broker-time price.
_ENDPOINT_ARRIVAL_GRACE_SECONDS = 10.0


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def compute_horizon_seconds(timeframe: str) -> int:
    return _HORIZON_BY_TIMEFRAME.get(timeframe, _DEFAULT_HORIZON_SECONDS)


# Confirmed fingerprint of the still-unexplained entry_price corruption bug
# (2026-08-17, recurred 2026-08-18) - see price_sanity_reason's PLACEHOLDER
# GUARD docstring below for why these are blocked unconditionally.
_KNOWN_PLACEHOLDER_ENTRY_PRICES = (1.1, 1.0, 0.0)


def price_sanity_reason(result: dict) -> str | None:
    """HOTFIX (2026-08-17, critical, active incident): confirmed live in
    production - EURUSD BUY signals on the 5m timeframe were repeatedly
    recorded AND broadcast (scanner.py calls this before publishing to
    the SSE stream binomo_executor.py --run consumes) with entry_price
    stuck at exactly 1.10000 while the pair's real live price was ~1.158,
    a ~4.3% gap between the two prices a single signal result carries:
    result["price"] (trendbar-derived) and result["data_status"]["price"]
    ["mid"] (live tick) - both meant to represent "right now", so a large
    gap between them means one is wrong. The exact root cause was NOT
    conclusively identified after investigation (ruled out: hardcoded
    fallback defaults, live-price staleness, symbolId collisions) - this
    is a defense-in-depth plausibility check, not a root-cause fix.

    FAIL-CLOSED (2026-08-17, same-day follow-up): confirmed live that the
    original fail-OPEN version of this check (treating a missing live_mid
    as "nothing to compare, allow through") was the exact loophole letting
    7 more corrupted EURUSD BUY signals through hours AFTER this hotfix
    first deployed - every one of them had entry_price present but
    data_status.price.mid unavailable at generation time. A present
    entry_price with no live_mid to check it against is now treated as
    implausible (blocked), not "unverifiable, therefore fine" - missing
    entry_price itself is still handled separately by maybe_record_signal/
    scanner.py's own is_signal gating, not by this function.

    PLACEHOLDER GUARD (2026-08-18): confirmed live that the SAME 1.10000
    fingerprint recurred - 7 more corrupted EURUSD BUY signals recorded on
    2026-08-18, well after the fail-closed fix above had already been live
    for a full day. That rules out "missing live_mid slipped through" as
    the mechanism this time; the far more likely explanation is that
    whatever produces the corrupted entry_price ALSO corrupts (or shares a
    stale/fallback source with) data_status.price.mid at that exact
    instant, so the two values agree with each other and the divergence
    check below finds nothing wrong. Since 1.10000/1.00000/0.0 are
    essentially never a genuine live quote for any pair this bot trades,
    these are now blocked OUTRIGHT the moment they appear as entry_price -
    before ever comparing against live_mid, so a simultaneously-corrupted
    live_mid can no longer rubber-stamp them as "in agreement".

    Returns a human-readable reason if entry_price can't be verified
    against a live mid (missing/invalid live_mid) or if the two disagree
    by more than config.SIGNAL_PRICE_SANITY_MAX_DIVERGENCE_PERCENT, else
    None (nothing to check yet - entry_price itself missing/invalid - or
    the two genuinely agree)."""
    entry_price = result.get("price")
    if isinstance(entry_price, (int, float)) and any(
        math.isclose(entry_price, placeholder, abs_tol=1e-9)
        for placeholder in _KNOWN_PLACEHOLDER_ENTRY_PRICES
    ):
        return (
            f"entry_price={entry_price:.5f} - відомий фінгерпринт зіпсованого значення "
            "(1.10000/1.00000/0.0), блокується незалежно від live_mid"
        )

    if not isinstance(entry_price, (int, float)) or entry_price <= 0:
        return None  # nothing to sanity-check yet - handled elsewhere

    live_mid = ((result.get("data_status") or {}).get("price") or {}).get("mid")
    if not isinstance(live_mid, (int, float)) or live_mid <= 0:
        return (
            f"entry_price={entry_price:.5f} не можна перевірити на правдоподібність - "
            "жива ціна (data_status.price.mid) недоступна"
        )

    divergence_percent = abs(entry_price - live_mid) / live_mid * 100.0
    if divergence_percent <= SIGNAL_PRICE_SANITY_MAX_DIVERGENCE_PERCENT:
        return None

    return (
        f"entry_price={entry_price:.5f} розходиться з живою ціною mid={live_mid:.5f} "
        f"на {divergence_percent:.2f}% (поріг {SIGNAL_PRICE_SANITY_MAX_DIVERGENCE_PERCENT}%)"
    )


def maybe_record_signal(result: dict) -> int | None:
    """Record a pending SignalOutcome for a result the bot actually surfaced
    as a signal (is_trade_allowed=True, directional verdict). Safe to call
    on every such result — recording failures are logged, never raised."""
    from strategy_mode import legacy_enabled
    if not legacy_enabled():
        return None
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

    sanity_reason = price_sanity_reason(result)
    if sanity_reason:
        logger.error("SIGNAL_OUTCOME: skipping implausible price for %s %s: %s", pair, verdict, sanity_reason)
        notify_admin(
            f"⚠️ Сигнал {pair} {verdict} пропущено: {sanity_reason}",
            alert_key=f"signal_price_sanity_{pair}",
        )
        return None

    horizon_seconds = compute_horizon_seconds(result.get("timeframe"))

    # Scanner opts into a new, separate measurement cohort. Historical callers
    # retain their semantics; never silently rewrite the old candle reference.
    evidence = None
    entry_ts = None
    if result.get("measurement_version") == "live_mid_v1":
        published_ts = result.get("ts")
        quote = result.get("entry_quote")
        if not isinstance(published_ts, (int, float)) or not math.isfinite(published_ts) or not isinstance(quote, dict):
            return None
        if not all(isinstance(quote.get(k), (int, float)) and math.isfinite(quote[k]) for k in ('ts','mid','bid','ask')):
            return None
        if not 0 < quote['bid'] <= quote['ask'] or not math.isclose(quote['mid'], (quote['bid'] + quote['ask']) / 2, rel_tol=1e-12):
            return None
        if not 0 <= published_ts - quote["ts"] <= 5:
            return None
        entry_price = quote["mid"]
        entry_ts = datetime.fromtimestamp(published_ts, timezone.utc).replace(tzinfo=None)
        evidence = {"version": "live_mid_v1", "entry_quote": quote,
                    "model_reference_price": result.get("price"), "source": "cTrader",
                    "publication": {"version": 1, "state": "prepared"}}

    extra = {"evidence": evidence, "entry_ts": entry_ts} if evidence else {}
    outcome_id = db.create_signal_outcome(
        pair=pair,
        timeframe=result.get("timeframe") or "",
        verdict=verdict,
        score=result.get("score"),
        entry_price=entry_price,
        horizon_seconds=horizon_seconds,
        **extra,
    )
    if outcome_id and evidence:
        if time.time() - published_ts > 5:
            evidence["reason"] = "publication_cancelled_db_delay"
            db.resolve_signal_outcome(outcome_id, outcome="unknown", exit_price=None, evidence=evidence)
            return None
        import endpoint_sampler
        endpoint_sampler.register(outcome_id, pair, published_ts + horizon_seconds)
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


def resolve_signal_cycle() -> None:
    import publication_tracking
    publication_tracking.flush_pending()
    resolve_pending_signals()
    import historical_endpoints
    historical_endpoints.recover_missing_endpoints()


def resolve_pending_signals() -> None:
    pending = db.get_pending_signal_outcomes()
    if not pending:
        return

    now = _utcnow_naive()

    for row in pending:
        entry_ts = row["entry_ts"]
        horizon_seconds = row["horizon_seconds"]
        # Database timestamps without tzinfo are UTC, not Windows local time.
        now_epoch = now.replace(tzinfo=timezone.utc).timestamp() if now.tzinfo is None else now.timestamp()
        live_price = None
        outcome = "unknown"
        if isinstance(entry_ts, datetime) and isinstance(horizon_seconds, (int, float)) and math.isfinite(horizon_seconds) and horizon_seconds > 0:
            entry_epoch = entry_ts.replace(tzinfo=timezone.utc).timestamp() if entry_ts.tzinfo is None else entry_ts.timestamp()
            deadline = entry_epoch + horizon_seconds
            evidence = row.get("evidence")
            if evidence:
                import endpoint_sampler
                if not evidence.get("endpoint"):
                    endpoint_sampler.register(row["id"], row["pair"], deadline)
            if now_epoch < deadline:
                continue
            captured = endpoint_sampler.captured(row["id"]) if evidence else None
            quote = (evidence or {}).get("endpoint") or captured or app_state.get_signal_endpoint_quote(row["pair"], deadline, now_epoch, _ENDPOINT_TOLERANCE_SECONDS, full=bool(evidence))
            if quote and not deadline <= quote.get("ts", -1) <= min(deadline + _ENDPOINT_TOLERANCE_SECONDS, now_epoch):
                quote = None
            live_price = quote.get("mid") if quote else None
            entry_price = row["entry_price"]
            if isinstance(entry_price, (int, float)) and math.isfinite(entry_price) and entry_price > 0 and isinstance(live_price, (int, float)) and math.isfinite(live_price) and live_price > 0:
                # Versioned status separates measured endpoints from legacy
                # snapshots without a schema change or rewriting old history.
                outcome = _classify_move(entry_price, live_price) + "_timed"
            elif now_epoch < deadline + _ENDPOINT_TOLERANCE_SECONDS + (_ENDPOINT_ARRIVAL_GRACE_SECONDS if evidence else 0):
                continue  # Allow the fixed quote window to finish.
        if outcome == "unknown":
            live_price = None

        extra = {}
        if row.get("evidence"):
            evidence = dict(row["evidence"])
            if live_price is not None:
                evidence["endpoint"] = quote
                evidence.pop("reason", None)
            else:
                evidence["reason"] = "invalid_entry_or_horizon" if not isinstance(entry_ts, datetime) or not isinstance(horizon_seconds, (int, float)) or not math.isfinite(horizon_seconds) or horizon_seconds <= 0 or not isinstance(row["entry_price"], (int, float)) or not math.isfinite(row["entry_price"]) or row["entry_price"] <= 0 else "no_valid_quote_in_5s_window"
                if evidence["reason"] == "no_valid_quote_in_5s_window":
                    evidence["reason"] = app_state.signal_measurement_gap_reason(row["pair"], deadline)
                    evidence["gap_diagnostics"] = app_state.signal_measurement_gap_snapshot(row["pair"], deadline)
            evidence["checked_at"] = now.isoformat()
            extra["evidence"] = evidence
        if db.resolve_signal_outcome(row["id"], outcome=outcome, exit_price=live_price, **extra):
            if row.get("evidence"):
                import endpoint_sampler
                endpoint_sampler.unregister(row["id"])
            logger.info(
                "SIGNAL_OUTCOME: #%s %s %s -> %s (entry=%s exit=%s)",
                row["id"], row["pair"], row["verdict"], outcome, row["entry_price"], live_price,
            )
