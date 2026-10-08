"""vwap_fetch_history.py - fetch step for the VWAP mean-reversion research
(feature/vwap-mean-reversion, 2026-08-21). Same split-fetch-from-analysis
pattern as stat_arb_fetch_history.py - fetch is network-bound (~20-25 min
for the full universe at M5), analysis is pure pandas and reruns in seconds.

    python vwap_fetch_history.py [--days 60]

WINDOW: 60 days of M5 bars (WINDOW_DAYS) - a deliberately modest window for
what the task explicitly frames as the CHEAPEST screening check of the VWAP-
reversion hypothesis, not a full historical study. 60 days gives ~43
weekday London sessions per forex symbol and 60 daily "sessions" per crypto
symbol (see vwap_mean_reversion_event_study.py's session definitions) -
enough for a first bootstrap read, expandable later only if Step 2 shows a
real effect worth deepening.

M5 (not M1, not H1): the task specifies M5 bars with tick volume as the
(already-approved, per the task's own consultant) volume proxy for VWAP.
TrendbarPeriod.M5, fetched the same way H1 was for stat-arb - just a
different period constant and a shorter window (M5 pagination chunks are
much shorter in calendar time than H1's, so the same BARS_PER_REQUEST cap
means more chunks per symbol here).

Universe: same as stat-arb/mean-reversion - config.CRYPTO_PAIRS + the union
of config.FOREX_SESSIONS, unchanged, per the task's explicit instruction not
to restrict to majors or crypto alone.

READ-ONLY: only reads trendbars via the existing cTrader client. Writes only
to data/vwap_m5_universe.csv (OHLCV, one row per symbol per bar).
"""
import argparse
import logging
import time
from datetime import datetime, timezone

import pandas as pd
from twisted.internet import defer, reactor, task

import config
import ctrader
from analysis import _resolve_symbol_details, _send_market_data_request, _trendbar_to_row
from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAGetTrendbarsReq, ProtoOAGetTrendbarsRes
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOATrendbarPeriod as TrendbarPeriod
from price_utils import resolve_price_divisor
from state import app_state

logger = logging.getLogger("vwap_fetch")

OUTPUT_CSV = "data/vwap_m5_universe.csv"
BAR_SECONDS = 300  # M5
BARS_PER_REQUEST = 900
FETCH_RETRY_ATTEMPTS = 3
FETCH_RETRY_DELAY_SECONDS = 15.0


def _full_universe() -> list[str]:
    crypto = [p.replace("/", "").upper() for p in config.CRYPTO_PAIRS]
    forex = set()
    for pairs in config.FOREX_SESSIONS.values():
        for p in pairs:
            forex.add(p.replace("/", "").upper())
    return sorted(set(crypto)) + sorted(forex)


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
def _fetch_symbol_history(symbol: str, from_ts_s: int, to_ts_s: int):
    symbol_details = _resolve_symbol_details(app_state.symbol_cache, symbol)
    if symbol_details is None:
        logger.warning("%s: symbol not found in symbol_cache", symbol)
        defer.returnValue(None)
        return

    account_id = getattr(getattr(app_state.client, "_client", None), "account_id", None)
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
            period=TrendbarPeriod.M5,
            fromTimestamp=cursor * 1000,
            toTimestamp=chunk_end * 1000,
        )
        try:
            msg = yield _send_market_data_request(app_state.client, req, response_timeout=25)
        except Exception:
            logger.warning("%s: trendbar fetch failed [%s, %s)", symbol, cursor, chunk_end, exc_info=True)
            break

        res = ProtoOAGetTrendbarsRes()
        res.ParseFromString(msg.payload)
        if res.trendbar:
            all_rows.extend(_trendbar_to_row(bar, divisor) for bar in res.trendbar)
        cursor = chunk_end

    if not all_rows:
        defer.returnValue(None)
        return

    df = pd.DataFrame(all_rows).drop_duplicates(subset="Timestamp").sort_values("Timestamp").reset_index(drop=True)
    defer.returnValue(df)


@defer.inlineCallbacks
def _fetch_symbol_history_with_retry(symbol: str, from_ts_s: int, to_ts_s: int):
    result = None
    for attempt in range(1, FETCH_RETRY_ATTEMPTS + 1):
        ready = yield _wait_for_live_client()
        if not ready:
            logger.warning("%s: no live cTrader client after waiting - giving up this attempt", symbol)
        else:
            result = yield _fetch_symbol_history(symbol, from_ts_s, to_ts_s)
            if result is not None and len(result) > 0:
                defer.returnValue(result)
                return
        if attempt < FETCH_RETRY_ATTEMPTS:
            logger.warning("%s: fetch returned no data (attempt %d/%d), retrying in %.0fs...",
                            symbol, attempt, FETCH_RETRY_ATTEMPTS, FETCH_RETRY_DELAY_SECONDS)
            yield task.deferLater(reactor, FETCH_RETRY_DELAY_SECONDS, lambda: None)
    defer.returnValue(result)


@defer.inlineCallbacks
def _run(args) -> None:
    start_time = time.time()

    now_s = int(datetime.now(timezone.utc).timestamp())
    from_ts_s = now_s - int(args.days * 86400)

    symbols = [s.strip().upper() for s in args.symbols.split(",")] if args.symbols else _full_universe()
    print(f"Символів у всесвіті: {len(symbols)}")
    print(f"Період барів: M5  |  вікно: {args.days} днів "
          f"({datetime.fromtimestamp(from_ts_s, tz=timezone.utc):%Y-%m-%d} - "
          f"{datetime.fromtimestamp(now_s, tz=timezone.utc):%Y-%m-%d})\n")

    client = ctrader.start_ctrader_client()
    if client is None:
        print("Не вдалось запустити cTrader-клієнт.")
        reactor.stop()
        return

    ready = yield _wait_for_live_client()
    if not ready:
        print("cTrader-клієнт не став готовим вчасно.")
        reactor.stop()
        return

    print(f"cTrader готовий ({len(app_state.symbol_cache)} символів). Завантажую історію...\n")

    all_frames = []
    ok_count = 0
    for i, symbol in enumerate(symbols, start=1):
        df = yield _fetch_symbol_history_with_retry(symbol, from_ts_s, now_s)
        if df is None:
            print(f"  [{i}/{len(symbols)}] {symbol}: НЕ ВДАЛОСЯ отримати історію")
            continue
        cols = ["Timestamp", "Open", "High", "Low", "Close"]
        if "Volume" in df.columns:
            cols.append("Volume")
        df = df[cols].copy()
        if "Volume" not in df.columns:
            df["Volume"] = 0.0
        df.insert(0, "symbol", symbol)
        all_frames.append(df)
        ok_count += 1
        print(f"  [{i}/{len(symbols)}] {symbol}: {len(df)} барів  (volume>0: {(df['Volume']>0).mean()*100:.0f}%)")
        pd.concat(all_frames, ignore_index=True).to_csv(args.output, index=False)

    if app_state.client:
        try:
            app_state.client.stop()
        except Exception:
            pass

    elapsed = time.time() - start_time
    print(f"\nОтримано символів: {ok_count}/{len(symbols)}")
    print(f"Час виконання: {elapsed/60.0:.1f} хв")
    print(f"Збережено: {args.output}")

    reactor.stop()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    parser = argparse.ArgumentParser(description="Fetch M5 history (with tick volume) for the VWAP mean-reversion universe.")
    parser.add_argument("--days", type=int, default=60)
    parser.add_argument("--symbols", type=str, default=None,
                         help="Comma-separated symbol list to scope the fetch (default: full crypto+forex universe).")
    parser.add_argument("--output", type=str, default=OUTPUT_CSV)
    args = parser.parse_args()

    reactor.callWhenRunning(_run, args)
    reactor.run()


if __name__ == "__main__":
    main()
