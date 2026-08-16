"""backtest.py - standalone, one-shot, LOCAL-only backtest of signal_outcomes
against real cTrader price history, simulating cTrader-style TP/SL trading
instead of Binomo's fixed-horizon binary options.

    python backtest.py --days 30 [--position-size 1000] [--spread-atr-fraction 0.1]
                        [--pairs EURUSD,GBPUSD] [--limit 200]

WHY this exists (2026-08-14, user request): the numbers this session has
been watching all day are Binomo-style (did price move the predicted
direction over a FIXED horizon - e.g. 5 minutes - yes/no). That's a
different game from real cTrader trading with TP/SL and no fixed exit time.
This answers a separate question: if the SAME historical signals had been
traded on cTrader with TP=entry+-1.5*ATR, SL=entry-+1*ATR
(config.SIGNAL_TP_ATR_MULTIPLIER/SIGNAL_SL_ATR_MULTIPLIER - the same
multipliers signal_outcomes used before it switched to horizon-based
tracking), walking the REAL minute-by-minute price path until TP or SL
actually fires, what would the P&L and win-rate have been?

READ-ONLY: never writes to signal_outcomes, never touches binomo_executor.py,
never deploys anything. Prints a report to stdout and exits.

DATA SOURCE AND ITS LIMITS (confirmed live 2026-08-14, before writing this):
  - cTrader Open API only exposes OHLC trendbars, not tick data. M1 (1-minute
    bars) is the finest granularity available - analysis.py's own
    PERIOD_MAP only goes down to M1.
  - Within a single M1 bar we only know its high/low, not the order in
    which they were touched. If BOTH the TP and SL level fall inside the
    same bar's [low, high] range, there is no way to know which one a real
    tick-by-tick fill would have hit first. POLICY (user decision,
    2026-08-14): resolve this conservatively - assume SL fired first. This
    can only ever make the backtest's numbers pessimistic relative to
    reality, never optimistic.
  - No artificial timeout-close (user decision, 2026-08-14): a trade is
    held until TP or SL genuinely fires in the real price path, however
    long that takes. BACKTEST_MAX_FORWARD_DAYS (config.py) is a SAFETY cap
    on how far forward this will paginate looking for a resolution, not a
    forced-close horizon - a signal that hasn't resolved within that many
    days is reported as "still open," not force-closed at the cap.
  - Exactly how far back cTrader's M1 history actually reaches is NOT
    something this script assumes - it's whatever the API actually returns.
    Signals older than that come back with fewer/no bars and are reported
    as skipped (insufficient historical data), not silently dropped.

R-MULTIPLE IS FIXED BY CONSTRUCTION, not computed per-trade: since TP is
always exactly 1.5x the SL distance from the (spread-adjusted) entry, every
win is worth exactly +1.5R and every loss exactly -1.0R - there's no partial
exit or trailing stop here. The number worth actually reading is the
path-dependent WIN RATE; total R and money P&L follow directly from it
(wins*1.5R - losses*1.0R) and are reported mainly for convenience.

Position sizing: FIXED size for every trade (config.BACKTEST_DEFAULT_
POSITION_SIZE, overridable via --position-size) in units of the pair's base
currency - a deliberate simplification (no per-pair risk normalization, no
quote-currency conversion for cross pairs), disclosed here rather than
hidden. Spread is modelled as a cost applied against the trader at entry,
sized as a FRACTION OF THE SIGNAL'S OWN M1 ATR (config.BACKTEST_DEFAULT_
SPREAD_ATR_FRACTION / --spread-atr-fraction) rather than a fixed "pip" -
see the AUDIT FIX comment on _simulate_one_signal for why a pip-derived
cost was wrong (it silently assumed every symbol's quoting precision
implies the traditional pip convention, which understated JPY-pair
spread by ~100x on this broker).
"""

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone

import pandas as pd
from twisted.internet import defer, reactor, task

import config
import ctrader
import db
from analysis import (
    PERIOD_MAP,
    _latest_atr_from_df,
    _normalize_pair,
    _resolve_symbol_details,
    _send_market_data_request,
    _trendbar_to_row,
)
from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAGetTrendbarsReq, ProtoOAGetTrendbarsRes
from price_utils import resolve_price_divisor
from state import app_state

logger = logging.getLogger("backtest")

ATR_LENGTH = 14
# pandas_ta's ATR needs a bit more than `length` bars of warm-up to have
# stabilized past its own smoothing lag - see _latest_atr_from_df's own
# `len(df) <= length` guard, which this comfortably clears.
ATR_WARMUP_BARS = ATR_LENGTH + 20
BAR_PERIOD = "1m"
BAR_SECONDS = 60
# cTrader's own practical cap on trendbars per ProtoOAGetTrendbarsReq
# response is well short of what a multi-day forward walk needs - this
# paginates in chunks of this size rather than assuming one request covers
# the whole range.
BARS_PER_REQUEST = 900


@defer.inlineCallbacks
def _fetch_trendbar_range(client, symbol_cache, pair: str, from_ts_s: int, to_ts_s: int):
    """Fetches M1 trendbars for [from_ts_s, to_ts_s) (both in whole seconds),
    paginating in BARS_PER_REQUEST-sized chunks. Returns a timestamp-sorted
    DataFrame, or None if the symbol/account isn't resolvable or the API
    returned nothing at all (e.g. the range predates cTrader's own M1
    retention window)."""
    symbol_details = _resolve_symbol_details(symbol_cache, pair)
    if symbol_details is None:
        defer.returnValue(None)
        return

    account_id = getattr(getattr(client, "_client", None), "account_id", None)
    if not account_id:
        defer.returnValue(None)
        return

    divisor = resolve_price_divisor(symbol_details)
    chunk_span_s = BARS_PER_REQUEST * BAR_SECONDS

    all_rows = []
    cursor = from_ts_s
    while cursor < to_ts_s:
        chunk_end = min(cursor + chunk_span_s, to_ts_s)
        req = ProtoOAGetTrendbarsReq(
            ctidTraderAccountId=account_id,
            symbolId=symbol_details.symbolId,
            period=PERIOD_MAP[BAR_PERIOD],
            fromTimestamp=cursor * 1000,
            toTimestamp=chunk_end * 1000,
        )
        try:
            msg = yield _send_market_data_request(client, req, response_timeout=25)
        except Exception:
            logger.warning("Trendbar fetch failed for %s [%s, %s)", pair, cursor, chunk_end, exc_info=True)
            break

        res = ProtoOAGetTrendbarsRes()
        res.ParseFromString(msg.payload)
        if not res.trendbar:
            break

        all_rows.extend(_trendbar_to_row(bar, divisor) for bar in res.trendbar)
        cursor = chunk_end

    if not all_rows:
        defer.returnValue(None)
        return

    df = pd.DataFrame(all_rows)
    if "Timestamp" not in df.columns:
        defer.returnValue(None)
        return
    df = df.sort_values("Timestamp").drop_duplicates(subset="Timestamp").reset_index(drop=True)
    defer.returnValue(df)


@defer.inlineCallbacks
def _simulate_one_signal(client, symbol_cache, signal: dict, *, position_size: float, spread_atr_fraction: float):
    """Walks the real M1 price path forward from a single signal's entry_ts
    until TP or SL fires (no timeout-close), and returns a result dict:

        {"status": "win"|"loss"|"still_open"|"insufficient_data",
         "pair", "r": float, "money_pnl": float, "entry_ts", ...}

    See this module's docstring for the same-bar TP+SL tie-break rule
    (SL wins) and the BACKTEST_MAX_FORWARD_DAYS safety cap.

    AUDIT FIX (2026-08-16, high): spread used to be derived as
    spread_pips * (10.0 / resolve_price_divisor(symbol_details)), i.e. it
    assumed the broker's quoting precision (digits) implies the
    traditional pip convention (0.0001 for majors, 0.01 for JPY pairs).
    Live-confirmed this broker quotes JPY pairs at the same 5-digit
    precision as majors, so that formula understated JPY-pair spread by
    ~100x (making JPY pairs look artificially strong in the first 30-day
    backtest run) while also overstating spread for pairs whose M1 ATR is
    small relative to a flat pip cost. Sizing spread as a fraction of the
    signal's own M1 ATR removes the pip-convention assumption entirely -
    ATR is already computed in raw price units with no ambiguity."""
    pair = signal["pair"]
    norm_pair = _normalize_pair(pair)
    entry_price = signal["entry_price"]
    direction = signal["verdict"]  # "BUY" | "SELL"
    entry_dt = signal["entry_ts"]
    entry_ts_s = int(entry_dt.replace(tzinfo=timezone.utc).timestamp())

    symbol_details = _resolve_symbol_details(symbol_cache, norm_pair)
    if symbol_details is None:
        defer.returnValue({"status": "insufficient_data", "pair": pair, "reason": "symbol not found"})
        return

    warmup_from = entry_ts_s - (ATR_WARMUP_BARS + 5) * BAR_SECONDS
    warmup_df = yield _fetch_trendbar_range(client, symbol_cache, norm_pair, warmup_from, entry_ts_s)
    atr = _latest_atr_from_df(warmup_df, length=ATR_LENGTH) if warmup_df is not None else None
    if atr is None:
        defer.returnValue({"status": "insufficient_data", "pair": pair, "reason": "no ATR (insufficient warm-up bars)"})
        return
    spread_cost = spread_atr_fraction * atr

    if direction == "BUY":
        effective_entry = entry_price + spread_cost
        sl_price = effective_entry - config.SIGNAL_SL_ATR_MULTIPLIER * atr
        tp_price = effective_entry + config.SIGNAL_TP_ATR_MULTIPLIER * atr
    else:  # SELL
        effective_entry = entry_price - spread_cost
        sl_price = effective_entry + config.SIGNAL_SL_ATR_MULTIPLIER * atr
        tp_price = effective_entry - config.SIGNAL_TP_ATR_MULTIPLIER * atr

    sl_distance = abs(effective_entry - sl_price)
    max_forward_ts = entry_ts_s + config.BACKTEST_MAX_FORWARD_DAYS * 86400
    now_s = int(datetime.now(timezone.utc).timestamp())
    search_ceiling = min(max_forward_ts, now_s)

    cursor = entry_ts_s
    while cursor < search_ceiling:
        chunk_end = min(cursor + BARS_PER_REQUEST * BAR_SECONDS, search_ceiling)
        forward_df = yield _fetch_trendbar_range(client, symbol_cache, norm_pair, cursor, chunk_end)
        if forward_df is None or forward_df.empty:
            # No more data at all (reached cTrader's own retention edge, or
            # genuinely caught up to "now") - can't resolve this signal.
            defer.returnValue({"status": "still_open", "pair": pair, "reason": "no more price data"})
            return

        for _, bar in forward_df.iterrows():
            hit_tp = bar["High"] >= tp_price if direction == "BUY" else bar["Low"] <= tp_price
            hit_sl = bar["Low"] <= sl_price if direction == "BUY" else bar["High"] >= sl_price

            if hit_tp and hit_sl:
                outcome = "loss"  # same-bar ambiguity: SL assumed first (conservative, see docstring)
            elif hit_sl:
                outcome = "loss"
            elif hit_tp:
                outcome = "win"
            else:
                continue

            r = config.SIGNAL_TP_ATR_MULTIPLIER if outcome == "win" else -config.SIGNAL_SL_ATR_MULTIPLIER
            money_pnl = r * sl_distance * position_size
            defer.returnValue({
                "status": outcome, "pair": pair, "r": r, "money_pnl": money_pnl,
                "entry_ts": entry_dt, "atr": atr,
            })
            return

        cursor = chunk_end

    defer.returnValue({"status": "still_open", "pair": pair, "reason": "no TP/SL within BACKTEST_MAX_FORWARD_DAYS"})


def _print_report(results: list[dict], binomo_style_stats: dict, days: int) -> None:
    resolved = [r for r in results if r["status"] in ("win", "loss")]
    wins = [r for r in resolved if r["status"] == "win"]
    losses = [r for r in resolved if r["status"] == "loss"]
    still_open = [r for r in results if r["status"] == "still_open"]
    skipped = [r for r in results if r["status"] == "insufficient_data"]

    total_r = sum(r["r"] for r in resolved)
    total_money = sum(r["money_pnl"] for r in resolved)
    win_rate = (len(wins) / len(resolved) * 100.0) if resolved else None

    print(f"\n=== cTrader TP/SL backtest, останні {days} днів ===")
    print(f"Сигналів усього: {len(results)}  |  резолвнуто: {len(resolved)}  |  "
          f"ще відкриті: {len(still_open)}  |  пропущено (брак даних): {len(skipped)}")
    print(f"\nWin-rate (TP/SL, path-dependent): "
          f"{win_rate:.1f}%  ({len(wins)}W / {len(losses)}L)" if win_rate is not None else "\nWin-rate: n/a (0 resolved)")
    print(f"Win-rate (Binomo-style, той самий пул сигналів): "
          f"{binomo_style_stats.get('win_rate', 'n/a')}")
    print(f"\nСумарний R: {total_r:+.2f}R")
    print(f"Умовний грошовий P&L: {total_money:+.2f}")

    by_pair: dict[str, list[dict]] = {}
    for r in resolved:
        by_pair.setdefault(r["pair"], []).append(r)

    print(f"\n{'Пара':<10} {'Угод':>5} {'Win%':>7} {'R':>8} {'P&L':>12}")
    for pair, rows in sorted(by_pair.items(), key=lambda kv: -len(kv[1])):
        pair_wins = sum(1 for r in rows if r["status"] == "win")
        pair_r = sum(r["r"] for r in rows)
        pair_money = sum(r["money_pnl"] for r in rows)
        print(f"{pair:<10} {len(rows):>5} {pair_wins / len(rows) * 100:>6.1f}% {pair_r:>+8.2f} {pair_money:>+12.2f}")

    if skipped:
        reasons = {}
        for r in skipped:
            reasons[r.get("reason", "?")] = reasons.get(r.get("reason", "?"), 0) + 1
        print(f"\nПропущено через брак даних: {dict(reasons)}")


@defer.inlineCallbacks
def _run(args) -> None:
    pairs = [p.strip().upper() for p in args.pairs.split(",")] if args.pairs else None
    signals = db.get_signal_outcome_rows_for_backtest(args.days, pairs=pairs)
    if args.limit:
        signals = signals[: args.limit]

    if not signals:
        print("Немає сигналів (BUY/SELL) за цей період — нема що бектестити.")
        reactor.stop()
        return

    print(f"Знайдено {len(signals)} сигналів. Підключаюсь до cTrader...")
    client = ctrader.start_ctrader_client()
    if client is None:
        print("Не вдалось запустити cTrader-клієнт.")
        reactor.stop()
        return

    yield task.deferLater(reactor, 0.1, lambda: None)
    while not app_state.SYMBOLS_LOADED:
        yield task.deferLater(reactor, 1.0, lambda: None)

    print(f"cTrader готовий ({len(app_state.symbol_cache)} символів). Починаю симуляцію...")

    results = []
    for i, signal in enumerate(signals, start=1):
        result = yield _simulate_one_signal(
            client, app_state.symbol_cache, signal,
            position_size=args.position_size, spread_atr_fraction=args.spread_atr_fraction,
        )
        results.append(result)
        if i % 10 == 0 or i == len(signals):
            print(f"  ...{i}/{len(signals)}")

    binomo_style_stats = db.get_signal_outcome_stats(days=args.days, binomo_style=True)
    win_rate = binomo_style_stats.get("win_rate")
    binomo_style_stats["win_rate"] = f"{win_rate:.1f}%" if isinstance(win_rate, (int, float)) else "n/a"

    _print_report(results, binomo_style_stats, args.days)

    try:
        client.stop()
    except Exception:
        pass
    reactor.stop()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    parser = argparse.ArgumentParser(
        description="One-shot cTrader TP/SL backtest of signal_outcomes. Read-only, local-only.",
    )
    parser.add_argument("--days", type=int, required=True, help="How many days back to pull signals from.")
    parser.add_argument(
        "--position-size", type=float, default=config.BACKTEST_DEFAULT_POSITION_SIZE,
        help=f"Fixed position size (base-currency units) for every trade. Default: {config.BACKTEST_DEFAULT_POSITION_SIZE}.",
    )
    parser.add_argument(
        "--spread-atr-fraction", type=float, default=config.BACKTEST_DEFAULT_SPREAD_ATR_FRACTION,
        help="Spread cost as a fraction of the signal's own M1 ATR, applied against the trader at "
             f"entry (replaces a fixed pip cost - see backtest.py's module docstring for why). "
             f"Default: {config.BACKTEST_DEFAULT_SPREAD_ATR_FRACTION}.",
    )
    parser.add_argument("--pairs", type=str, default=None, help="Comma-separated pair filter, e.g. EURUSD,GBPUSD.")
    parser.add_argument("--limit", type=int, default=None, help="Cap the number of signals processed (for a quick trial run).")
    args = parser.parse_args()

    reactor.callWhenRunning(_run, args)
    reactor.run()


if __name__ == "__main__":
    main()
