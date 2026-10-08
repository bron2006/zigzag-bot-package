"""vwap_shadow_logger.py - Крок 3.0 of the VWAP LONG-only executor rollout
(feature/vwap-long-executor, 2026-08-21): computes the LIVE session VWAP +-2
std bands for the 25 forex_cross symbols, using the EXACT SAME causal
formula the backtest already verified (compute_causal_vwap_bands, imported
from vwap_mean_reversion_event_study.py - not re-derived), and just LOGS the
levels. Places NO orders, touches no DB, no account state - read-only
market-data polling only.

    python vwap_shadow_logger.py [--poll-seconds 60]

WHY THIS EXISTS (user's own explicit instruction before Крок 3.1): the
research phase's VWAP/session math was validated entirely offline, against
historical M5 trendbars fetched in bulk. This is the first time that same
formula runs against LIVE data on a real polling loop - the user's own
consultation flagged this as exactly the kind of place a session/timezone
boundary bug hides (backtest and live code silently disagreeing about
"when does the session start"), which historical-only testing can never
catch. The user will manually cross-check logged levels against TradingView
(or their own calculation) over 2-3 days before Крок 3.1 (order placement)
is even written.

SESSION DEFINITION: identical to the backtest - London 08:00-16:00 UTC,
weekdays only (see vwap_mean_reversion_event_study.py's own docstring for
why this exact window, unchanged here). At the start of each poll cycle,
computes "today's" session window in UTC; outside that window (or on a
weekend), logs nothing and waits - matches the backtest's own session
boundary exactly, not an approximation.

DATA SOURCE / GRANULARITY (consultation item 1, 2026-08-22, confirmed
explicitly - CRITICAL for the manual TradingView cross-check): every bar
this file fetches, computes, and logs is an **M5 (5-minute) trendbar**
(TrendbarPeriod.M5 in _fetch_session_bars below) - never M1. Set
TradingView's chart to the M5 timeframe before comparing, or the numbers
will not match even with fully correct code: different candle counts mean
different intermediate points and different per-candle volumes feeding
the VWAP sum. Fetches [session_start, now) per symbol per poll via the
same ProtoOAGetTrendbarsReq mechanism every prior fetch script in this
project uses - a single request per symbol per poll (a session is at most
96 M5 bars, well under the 900-bar practical cap, so no pagination is
needed here, unlike the historical bulk-fetch scripts).

LOG FORMAT: appends one CSV row per symbol per poll cycle (while in-session)
to logs/vwap_shadow_log.csv (gitignored, per this repo's existing
logs/ convention for runtime/audit output - see .gitignore) - columns:
polled_at_utc, symbol, session_date, bars_in_session, vwap, upper_2sigma,
lower_2sigma, last_close, last_high, last_low. Every poll is logged
unconditionally (not just on a new bar) so a human comparing against
TradingView at some arbitrary moment always finds a nearby row.

WEEKEND ROLLOVER (consultation item 2, 2026-08-22, verified): forex
reopens Sunday ~22:00 UTC, but the tracked session doesn't start until
Monday 08:00 UTC - a full ~10h after reopen - so there is no "market just
opened" bar inside the tracked window at all; _current_session_window_utc
simply returns None (logs nothing, waits) for the whole Sun 22:00-Mon
08:00 stretch. Whatever residual volatility exists at 08:00 Monday is
covered the same way any other in-session spike is: _filter_anomalous_
bars only ever compares a bar against the last GOOD bar WITHIN the same
session fetch (session_start onward), never against the prior session's
close - Friday's close is never even in the array being filtered, so a
genuine weekend gap can't be mistaken for a data error, and a real
first-bar anomaly still gets caught by the same >5% guard as any other
bar (see FilterAnomalousBarsTest.test_monday_session_start_gap_is_never_
compared_against_fridays_close in the test file).

RESILIENCE / RECONNECT GAPS (consultation item 3, 2026-08-22, verified):
same _wait_for_live_client pattern every long-running script in this
project already uses (ctrader.py's own auto-reconnect replaces
app_state.client after a drop; this script re-reads that reference fresh
on every poll rather than holding a stale one) - a transient disconnect
stalls one poll cycle, not the whole 2-3 day run. More importantly, this
file keeps NO incremental "last fetched bar" cursor anywhere - every
single poll re-requests the FULL [session_start, now) range from scratch
(see _poll_all_symbols: from_ts is always session_start, never a saved
pointer). cTrader's own trendbar history is server-side and complete
regardless of whether THIS client was connected to observe it live, so a
multi-cycle outage self-heals automatically on the next successful poll -
there is no code path that could produce a bar-sequence gap from a missed
cycle, because nothing is ever appended incrementally in the first place.
"""
import argparse
import csv
import logging
import os
from datetime import datetime, timedelta, timezone

from twisted.internet import defer, reactor, task

import ctrader
from analysis import _resolve_symbol_details, _send_market_data_request, _trendbar_to_row
from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAGetTrendbarsReq, ProtoOAGetTrendbarsRes
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOATrendbarPeriod as TrendbarPeriod
from price_utils import resolve_price_divisor
from state import app_state
from vwap_mean_reversion_event_study import compute_causal_vwap_bands

logger = logging.getLogger("vwap_shadow_logger")

LOG_PATH = "logs/vwap_shadow_log.csv"
LOG_COLUMNS = [
    "polled_at_utc", "symbol", "session_date", "bars_in_session",
    "vwap", "upper_2sigma", "lower_2sigma", "last_close", "last_high", "last_low",
]

SYMBOLS = [
    "AUDCAD", "AUDCHF", "AUDJPY", "AUDNZD", "AUDSGD", "CADCHF", "CADJPY", "CHFJPY",
    "EURAUD", "EURCAD", "EURCHF", "EURGBP", "EURJPY", "EURNZD", "EURSGD",
    "GBPAUD", "GBPCAD", "GBPCHF", "GBPJPY", "GBPNZD", "GBPSGD",
    "NZDCAD", "NZDCHF", "NZDJPY", "SGDJPY",
]

SESSION_START_HOUR_UTC = 8
SESSION_END_HOUR_UTC = 16
DEFAULT_POLL_SECONDS = 60.0

# M5 bar duration in seconds - used only to derive each bar's CLOSE time
# from its "Timestamp" column, which _trendbar_to_row sets from cTrader's
# utcTimestampInMinutes. Confirmed via cTrader's own Open API docs/forum
# (2026-08-22 consultation review) that utcTimestampInMinutes is the bar's
# OPEN tick time, not close - so "Timestamp" alone is NOT safe to compare
# directly against `now` for a causality/completeness check; every such
# comparison in this file adds M5_PERIOD_SECONDS first. See
# _drop_incomplete_trailing_bars's docstring for why this matters.
M5_PERIOD_SECONDS = 300

# Checklist item 3 (2026-08-22 consultation): a single spurious bar this
# early in a session poisons every later VWAP value, since the calc is
# cumulative from session start - same failure class as the documented
# EURUSD entry_price=1.10000 bug elsewhere in this repo (CLAUDE.md), just
# bar-level instead of tick-level (this logger only ever sees bars, never
# raw ticks, per DATA SOURCE in the module docstring).
ANOMALOUS_BAR_MAX_DEVIATION = 0.05


def _drop_incomplete_trailing_bars(df, now_ts: int):
    """Defensive completeness guard, not strictly proven necessary: cTrader's
    docs/forum suggest ProtoOAGetTrendbarsReq (what this file uses) only
    ever returns closed historical bars - live in-progress bars are meant
    to arrive through the separate ProtoOASubscribeLiveTrendbarReq/
    ProtoOASpotEvent channel this file never subscribes to. That's inferred
    from "for live data you must separately subscribe to
    ProtoOASubscribeLiveTrendbarReq", not something either doc page states
    outright for the request/response path.

    Kept anyway as insurance rather than trusting that inference: a bar
    whose close time (open time + M5_PERIOD_SECONDS) hasn't happened yet
    is by definition not final - its OHLC/Volume would still be changing
    on the next poll - so this drops any such bar before it can reach
    compute_causal_vwap_bands, regardless of whether cTrader would ever
    actually send one. A no-op whenever every returned bar is already
    closed, which per the above should be always."""
    if df is None or df.empty:
        return df
    return df[df["Timestamp"] + M5_PERIOD_SECONDS <= now_ts].reset_index(drop=True)


def _filter_anomalous_bars(df, symbol: str, max_deviation: float = ANOMALOUS_BAR_MAX_DEVIATION):
    """Drops any bar whose Close deviates more than max_deviation (relative)
    from the last KEPT bar's Close - chained against the last good value
    rather than the raw previous bar, so a run of consecutive bad bars
    can't "walk" the reference price away from reality one small step at a
    time. The first bar in the session has no earlier reference and is
    always kept. Returns a (filtered_df, dropped_count) pair so the caller
    can log how many bars this pass actually removed."""
    if df is None or df.empty:
        return df, 0

    keep_mask = [True] * len(df)
    closes = df["Close"].to_numpy(dtype=float)
    last_good_close = closes[0]

    for i in range(1, len(closes)):
        close = closes[i]
        deviation = abs(close - last_good_close) / last_good_close if last_good_close else float("inf")
        if deviation > max_deviation:
            keep_mask[i] = False
            logger.warning(
                "%s: аномальний бар відкинуто (close=%.6f, попередній валідний=%.6f, "
                "відхилення=%.2f%% > %.0f%%)",
                symbol, close, last_good_close, deviation * 100, max_deviation * 100,
            )
        else:
            last_good_close = close

    dropped = keep_mask.count(False)
    return df[keep_mask].reset_index(drop=True), dropped


def _current_session_window_utc(now: datetime) -> tuple[datetime, datetime] | None:
    """Same window the backtest uses (vwap_mean_reversion_event_study._
    assign_sessions: hour in [8,16), weekday<5) - returns None outside it
    (weekend or off-hours), in which case the caller logs nothing this
    cycle rather than fabricating a session that doesn't exist."""
    if now.weekday() >= 5:
        return None
    start = now.replace(hour=SESSION_START_HOUR_UTC, minute=0, second=0, microsecond=0)
    end = now.replace(hour=SESSION_END_HOUR_UTC, minute=0, second=0, microsecond=0)
    if now < start or now >= end:
        return None
    return start, end


@defer.inlineCallbacks
def _wait_for_live_client(*, max_wait_seconds: float = 120.0):
    waited = 0.0
    poll_interval = 2.0
    while not (app_state.client and app_state.SYMBOLS_LOADED):
        if waited >= max_wait_seconds:
            defer.returnValue(False)
            return
        yield task.deferLater(reactor, poll_interval, lambda: None)
        waited += poll_interval
    defer.returnValue(True)


@defer.inlineCallbacks
def _fetch_session_bars(symbol: str, from_ts_s: int, to_ts_s: int):
    """Single-request fetch (a session is <=96 M5 bars, well under the
    900-bar practical cap every other fetch script in this project
    paginates around) - returns a DataFrame or None."""
    symbol_details = _resolve_symbol_details(app_state.symbol_cache, symbol)
    if symbol_details is None:
        defer.returnValue(None)
        return

    account_id = getattr(getattr(app_state.client, "_client", None), "account_id", None)
    if not account_id:
        defer.returnValue(None)
        return

    divisor = resolve_price_divisor(symbol_details)
    req = ProtoOAGetTrendbarsReq(
        ctidTraderAccountId=account_id,
        symbolId=symbol_details.symbolId,
        period=TrendbarPeriod.M5,
        fromTimestamp=from_ts_s * 1000,
        toTimestamp=to_ts_s * 1000,
    )
    try:
        msg = yield _send_market_data_request(app_state.client, req, response_timeout=20)
    except Exception:
        logger.warning("%s: live trendbar fetch failed", symbol, exc_info=True)
        defer.returnValue(None)
        return

    res = ProtoOAGetTrendbarsRes()
    res.ParseFromString(msg.payload)
    if not res.trendbar:
        defer.returnValue(None)
        return

    import pandas as pd
    rows = [_trendbar_to_row(bar, divisor) for bar in res.trendbar]
    df = pd.DataFrame(rows).drop_duplicates(subset="Timestamp").sort_values("Timestamp").reset_index(drop=True)
    defer.returnValue(df)


def _ensure_log_header() -> None:
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    if not os.path.exists(LOG_PATH):
        with open(LOG_PATH, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(LOG_COLUMNS)


def _append_log_row(row: dict) -> None:
    with open(LOG_PATH, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([row[col] for col in LOG_COLUMNS])


_last_outside_session_print_ts: float = 0.0
OUTSIDE_SESSION_PRINT_INTERVAL_SECONDS = 900.0  # avoid flooding the log over idle nights/weekends


@defer.inlineCallbacks
def _poll_all_symbols():
    global _last_outside_session_print_ts
    now = datetime.now(timezone.utc)
    window = _current_session_window_utc(now)
    if window is None:
        now_ts = now.timestamp()
        if now_ts - _last_outside_session_print_ts >= OUTSIDE_SESSION_PRINT_INTERVAL_SECONDS:
            print(f"[{now:%Y-%m-%d %H:%M:%S} UTC] поза сесією (Лондон 08:00-16:00 UTC, будні) - чекаю")
            _last_outside_session_print_ts = now_ts
        return

    ready = yield _wait_for_live_client()
    if not ready:
        print(f"[{now:%Y-%m-%d %H:%M:%S} UTC] cTrader-клієнт не готовий, пропускаю цикл")
        return

    session_start, _ = window
    from_ts = int(session_start.timestamp())
    to_ts = int(now.timestamp())
    session_date = session_start.strftime("%Y-%m-%d")

    logged = 0
    for symbol in SYMBOLS:
        df = yield _fetch_session_bars(symbol, from_ts, to_ts)
        if df is None or df.empty:
            continue

        df = _drop_incomplete_trailing_bars(df, to_ts)
        df, dropped = _filter_anomalous_bars(df, symbol)
        if dropped:
            logger.info("%s: відкинуто %s аномальних барів цього циклу", symbol, dropped)
        if df.empty:
            continue

        vwap, upper, lower = compute_causal_vwap_bands(
            df["Close"].to_numpy(dtype=float), df["Volume"].to_numpy(dtype=float),
        )
        if len(vwap) == 0 or (vwap[-1] != vwap[-1]):  # NaN check without importing numpy just for this
            continue

        row = {
            "polled_at_utc": now.isoformat(timespec="seconds"),
            "symbol": symbol,
            "session_date": session_date,
            "bars_in_session": len(df),
            "vwap": round(float(vwap[-1]), 6),
            "upper_2sigma": round(float(upper[-1]), 6),
            "lower_2sigma": round(float(lower[-1]), 6),
            "last_close": round(float(df["Close"].iloc[-1]), 6),
            "last_high": round(float(df["High"].iloc[-1]), 6),
            "last_low": round(float(df["Low"].iloc[-1]), 6),
        }
        _append_log_row(row)
        logged += 1

    print(f"[{now:%Y-%m-%d %H:%M:%S} UTC] сесія {session_date}: залоговано {logged}/{len(SYMBOLS)} символів")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    parser = argparse.ArgumentParser(description="Крок 3.0: live session VWAP shadow logger, no trading.")
    parser.add_argument("--poll-seconds", type=float, default=DEFAULT_POLL_SECONDS)
    args = parser.parse_args()

    _ensure_log_header()
    print(f"Тіньовий логер VWAP запущено. Лог: {LOG_PATH}")
    print(f"Сесія: Лондон {SESSION_START_HOUR_UTC:02d}:00-{SESSION_END_HOUR_UTC:02d}:00 UTC, будні. "
          f"Опитування кожні {args.poll_seconds:.0f}с. Жодних угод не виставляється.")
    print("Таймфрейм барів: M5 (5-хвилинні трендбари). Для ручної звірки постав "
          "TradingView саме на M5 - інакше значення не збіжаться навіть при "
          "правильному коді (різна кількість барів і об'ємів на M1).\n")

    def _start():
        client = ctrader.start_ctrader_client()
        if client is None:
            print("Не вдалось запустити cTrader-клієнт.")
            reactor.stop()
            return
        lc = task.LoopingCall(_poll_all_symbols)
        lc.start(args.poll_seconds, now=True)

    reactor.callWhenRunning(_start)
    reactor.run()


if __name__ == "__main__":
    main()
