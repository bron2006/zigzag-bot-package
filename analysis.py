# analysis.py
import logging
import time
from typing import Optional, Tuple

import pandas as pd
import pandas_ta as ta
from twisted.internet import defer, reactor
from twisted.internet.defer import Deferred, DeferredList
from twisted.internet.threads import deferToThreadPool

import ml_models
import news_filter
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAGetTrendbarsReq,
    ProtoOAGetTrendbarsRes,
)
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import (
    ProtoOATrendbarPeriod as TrendbarPeriod,
)
from price_utils import resolve_price_divisor
from state import app_state

logger = logging.getLogger("analysis")

PERIOD_MAP = {
    "1m": TrendbarPeriod.M1,
    "5m": TrendbarPeriod.M5,
    "15m": TrendbarPeriod.M15,
}

MARKET_DATA_TIMEOUT = 18
CPU_ANALYSIS_TIMEOUT = 12

# Модель навчена на цих назвах
MODEL_FEATURE_NAMES = ["ATR", "ADX", "RSI", "EMA50", "EMA200"]

# А pandas_ta повертає такі назви
FEATURE_SOURCE_MAP = {
    "ATR": ["ATRr_14", "ATR_14"],
    "ADX": ["ADX_14"],
    "RSI": ["RSI_14"],
    "EMA50": ["EMA_50"],
    "EMA200": ["EMA_200"],
}


def _blocking_pool():
    return app_state.blocking_pool or reactor.getThreadPool()


def _normalize_pair(pair: str) -> str:
    return (pair or "").replace("/", "").upper().strip()


def _resolve_symbol_details(symbol_cache, pair: str):
    norm = _normalize_pair(pair)
    with_slash = f"{norm[:3]}/{norm[3:]}" if len(norm) >= 6 else None

    candidates = [
        pair,
        pair.upper() if isinstance(pair, str) else pair,
        norm,
        with_slash,
        pair.replace("/", "") if isinstance(pair, str) else pair,
        pair.replace("/", "").upper() if isinstance(pair, str) else pair,
    ]

    for candidate in candidates:
        if candidate and candidate in symbol_cache:
            return symbol_cache[candidate]

    get_symbol_details = getattr(app_state, "get_symbol_details", None)
    if callable(get_symbol_details):
        return get_symbol_details(norm)

    return None


def _prepare_features(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    df = df.copy()

    try:
        df.ta.rsi(length=14, append=True)
        df.ta.adx(length=14, append=True)
        df.ta.atr(length=14, append=True)
        df.ta.ema(length=50, append=True)
        df.ta.ema(length=200, append=True)

        latest = df.tail(1)

        prepared = {}
        missing = []

        for target_name, source_candidates in FEATURE_SOURCE_MAP.items():
            found_value = None

            for source_name in source_candidates:
                if source_name in latest.columns:
                    value = latest[source_name].iloc[0]
                    if pd.notna(value):
                        found_value = value
                        break

            if found_value is None:
                missing.append(f"{target_name} <- {source_candidates}")
            else:
                prepared[target_name] = found_value

        if missing:
            logger.warning(f"Відсутні фічі для моделі: {missing}")
            return None

        features_df = pd.DataFrame([prepared], columns=MODEL_FEATURE_NAMES)

        if features_df.isnull().any().any():
            logger.debug("NaN в підготовлених фічах — недостатньо барів для індикаторів")
            return None

        return features_df

    except Exception as e:
        logger.error(f"Помилка розрахунку індикаторів: {e}")
        return None


def _run_technical_analysis(df: pd.DataFrame) -> Tuple[int, str]:
    if df is None or df.empty or len(df) < 250:
        return 50, "NEUTRAL"

    if not (ml_models.LGBM_MODEL and ml_models.SCALER):
        return 50, "NEUTRAL"

    features_df = _prepare_features(df)
    if features_df is None:
        return 50, "NEUTRAL"

    try:
        features_scaled = ml_models.SCALER.transform(features_df)
        probs = ml_models.LGBM_MODEL.predict_proba(features_scaled)
        score = int(probs[0][1] * 100)

        if score > 75:
            verdict = "BUY"
        elif score < 25:
            verdict = "SELL"
        else:
            verdict = "NEUTRAL"

        return score, verdict

    except Exception as e:
        logger.error(f"ML inference error: {e}")
        return 50, "NEUTRAL"


def _select_timeframes(requested_timeframe: str) -> tuple[str, str]:
    requested = (requested_timeframe or "5m").strip()

    if requested == "15m":
        return "5m", "15m"
    if requested == "1m":
        return "1m", "5m"

    return "1m", "5m"


def _combine_verdicts_sync(
    symbol: str,
    requested_timeframe: str,
    tf_a: str,
    df_a: pd.DataFrame,
    tf_b: str,
    df_b: pd.DataFrame,
) -> dict:
    score_a, verdict_a = _run_technical_analysis(df_a)
    score_b, verdict_b = _run_technical_analysis(df_b)

    logger.info(
        f"[{_normalize_pair(symbol)}] {tf_a}: {verdict_a}({score_a}) | "
        f"{tf_b}: {verdict_b}({score_b})"
    )

    avg_score = int(round((score_a + score_b) / 2.0))

    if verdict_a == "BUY" and verdict_b in ("BUY", "NEUTRAL"):
        final_verdict = "BUY"
        final_score = score_a
    elif verdict_a == "SELL" and verdict_b in ("SELL", "NEUTRAL"):
        final_verdict = "SELL"
        final_score = score_a
    elif verdict_a == verdict_b and verdict_a != "NEUTRAL":
        final_verdict = verdict_a
        final_score = avg_score
    else:
        final_verdict = "NEUTRAL"
        final_score = avg_score

    last_close = float(df_a["Close"].iloc[-1]) if df_a is not None and not df_a.empty else 0.0

    timeframe_details = {
        tf_a: {"score": score_a, "verdict": verdict_a},
        tf_b: {"score": score_b, "verdict": verdict_b},
    }

    reasons = [
        f"{tf_a.upper()}: {verdict_a} ({score_a}%) | {tf_b.upper()}: {verdict_b} ({score_b}%)"
    ]

    return {
        "pair": symbol,
        "price": last_close,
        "verdict_text": final_verdict,
        "score": final_score,
        "reasons": reasons,
        "ts": time.time(),
        "timeframe": requested_timeframe,
        "sentiment": "N/A",
        "is_trade_allowed": final_verdict in ("BUY", "SELL"),
        "timeframe_details": timeframe_details,
        "news_source": None,
    }


def _fallback_result(symbol: str, timeframe: str, reason: str, verdict_text: str = "WAIT") -> dict:
    return {
        "pair": symbol,
        "price": 0.0,
        "verdict_text": verdict_text,
        "score": 50,
        "reasons": [reason],
        "ts": time.time(),
        "timeframe": timeframe,
        "sentiment": "N/A",
        "is_trade_allowed": False,
        "error": reason if verdict_text == "ERROR" else None,
        "timeframe_details": {},
        "news_source": None,
    }


@defer.inlineCallbacks
def _analysis_flow(client, symbol_cache, symbol, user_id, timeframe="5m"):
    pair_norm = _normalize_pair(symbol)

    try:
        if client is None or getattr(client, "_client", None) is None:
            return _fallback_result(symbol, timeframe, "Клієнт cTrader не ініціалізований", "ERROR")

        if not getattr(client._client, "account_id", None):
            return _fallback_result(symbol, timeframe, "Акаунт cTrader ще не авторизований", "WAIT")

        tf_a, tf_b = _select_timeframes(timeframe)

        d_a = get_market_data(client, symbol_cache, pair_norm, tf_a, 300)
        d_b = get_market_data(client, symbol_cache, pair_norm, tf_b, 300)

        d_a.addTimeout(MARKET_DATA_TIMEOUT, reactor)
        d_b.addTimeout(MARKET_DATA_TIMEOUT, reactor)

        results = yield DeferredList([d_a, d_b], consumeErrors=True)

        ok_a, df_a = results[0]
        ok_b, df_b = results[1]

        if not ok_a or not ok_b:
            reasons = []
            if not ok_a:
                reasons.append(f"Не вдалося завантажити {tf_a.upper()}")
            if not ok_b:
                reasons.append(f"Не вдалося завантажити {tf_b.upper()}")
            return _fallback_result(
                symbol,
                timeframe,
                "; ".join(reasons) or "Не вдалося завантажити дані",
                "WAIT",
            )

        d_cpu = deferToThreadPool(
            reactor,
            _blocking_pool(),
            _combine_verdicts_sync,
            symbol,
            timeframe,
            tf_a,
            df_a,
            tf_b,
            df_b,
        )
        d_cpu.addTimeout(CPU_ANALYSIS_TIMEOUT, reactor)

        try:
            base_result = yield d_cpu
        except Exception as e:
            logger.error(f"CPU analysis timeout/error for {symbol}: {e}")
            return _fallback_result(symbol, timeframe, "Технічний аналіз перевищив час очікування", "WAIT")

        # ГОЛОВНИЙ ФІКС:
        # тільки async-версія, без sync news_filter.get_latest_news_sentiment(...)
        try:
            news_result = yield news_filter.get_latest_news_sentiment_async(pair_norm)
        except Exception as e:
            logger.warning(f"News filter error for {pair_norm}: {e}")
            news_result = {
                "verdict": "GO",
                "reason": "Помилка запиту до Gemini",
                "source": "fallback_error",
                "model": "gemini-flash-latest",
                "available": False,
                "http_status": None,
            }

        result = dict(base_result)

        news_verdict = news_result.get("verdict", "GO")
        news_reason = news_result.get("reason", "")
        news_source = news_result.get("source")
        news_model = news_result.get("model")
        news_available = bool(news_result.get("available", False))
        news_http_status = news_result.get("http_status")

        result["news_source"] = news_source

        if news_available:
            result["sentiment"] = news_verdict

            if news_verdict == "BLOCK":
                result["is_trade_allowed"] = False
                if result.get("verdict_text") in ("BUY", "SELL"):
                    result["verdict_text"] = "NEWS_WAIT"

                result["reasons"].append(
                    f"ШІ: BLOCK — {news_reason}"
                    if news_reason
                    else "ШІ: Ризиковані новини. Вхід заблоковано."
                )
            else:
                reason_text = news_reason or "Новини ок"
                if news_model:
                    reason_text = f"{reason_text} [{news_model}]"
                result["reasons"].append(f"ШІ: GO — {reason_text}")
                result["is_trade_allowed"] = result.get("verdict_text") in ("BUY", "SELL")
        else:
            result["sentiment"] = "UNAVAILABLE"
            result["is_trade_allowed"] = result.get("verdict_text") in ("BUY", "SELL")

            if news_http_status:
                result["reasons"].append(f"ШІ: недоступний — HTTP {news_http_status}")
            elif news_reason:
                result["reasons"].append(f"ШІ: недоступний — {news_reason}")
            else:
                result["reasons"].append("ШІ: недоступний")

        result["ts"] = time.time()
        return result

    except Exception as e:
        logger.exception(f"Analysis error for {symbol}")
        return _fallback_result(symbol, timeframe, str(e), "ERROR")


def get_api_detailed_signal_data(client, symbol_cache, symbol, user_id, timeframe="5m"):
    return defer.maybeDeferred(_analysis_flow, client, symbol_cache, symbol, user_id, timeframe)


def get_market_data(client, symbol_cache, norm_pair: str, period: str, count: int):
    d = Deferred()

    symbol_details = _resolve_symbol_details(symbol_cache, norm_pair)
    if not symbol_details:
        reactor.callLater(0, d.errback, Exception(f"Символ {norm_pair} не знайдено."))
        return d

    tf_proto = PERIOD_MAP.get(period)
    if not tf_proto:
        reactor.callLater(0, d.errback, Exception(f"Невідомий таймфрейм: {period}"))
        return d

    if client is None or getattr(client, "_client", None) is None:
        reactor.callLater(0, d.errback, Exception("cTrader client is not ready"))
        return d

    if not getattr(client._client, "account_id", None):
        reactor.callLater(0, d.errback, Exception("cTrader account_id is missing"))
        return d

    now = int(time.time() * 1000)
    seconds = {"1m": 60, "5m": 300, "15m": 900}.get(period, 300)
    from_ts = now - (count * seconds * 1000)

    req = ProtoOAGetTrendbarsReq(
        ctidTraderAccountId=client._client.account_id,
        symbolId=symbol_details.symbolId,
        period=tf_proto,
        fromTimestamp=from_ts,
        toTimestamp=now,
    )

    api_deferred = client.send(req, timeout=15)

    def on_res(msg):
        try:
            res = ProtoOAGetTrendbarsRes()
            res.ParseFromString(msg.payload)

            if not res.trendbar:
                d.callback(pd.DataFrame())
                return

            div = resolve_price_divisor(symbol_details)
            bars = [
                {
                    "ts": pd.to_datetime(b.utcTimestampInMinutes * 60, unit="s", utc=True),
                    "Open": (b.low + b.deltaOpen) / div,
                    "High": (b.low + b.deltaHigh) / div,
                    "Low": b.low / div,
                    "Close": (b.low + b.deltaClose) / div,
                }
                for b in res.trendbar
            ]

            df = pd.DataFrame(bars).sort_values("ts")
            d.callback(df)

        except Exception as e:
            d.errback(e)

    def on_err(failure):
        d.errback(failure)

    api_deferred.addCallbacks(on_res, on_err)
    return d