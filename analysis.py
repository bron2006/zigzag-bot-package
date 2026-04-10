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

# ФІКС: Збільшені таймаути для Fly.io
MARKET_DATA_TIMEOUT = 35
CPU_ANALYSIS_TIMEOUT = 25

MODEL_FEATURE_NAMES = ["ATR", "ADX", "RSI", "EMA50", "EMA200"]

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
    candidates = [pair, pair.upper(), norm]
    for candidate in candidates:
        if candidate and candidate in symbol_cache:
            return symbol_cache[candidate]
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
        for target_name, source_candidates in FEATURE_SOURCE_MAP.items():
            for source_name in source_candidates:
                if source_name in latest.columns:
                    val = latest[source_name].iloc[0]
                    if pd.notna(val):
                        prepared[target_name] = val
                        break
        
        if len(prepared) < len(MODEL_FEATURE_NAMES):
            return None

        return pd.DataFrame([prepared], columns=MODEL_FEATURE_NAMES)
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
        verdict = "BUY" if score > 75 else "SELL" if score < 25 else "NEUTRAL"
        return score, verdict
    except Exception:
        return 50, "NEUTRAL"


@defer.inlineCallbacks
def _analysis_flow(client, symbol_cache, symbol, user_id, timeframe="5m"):
    pair_norm = _normalize_pair(symbol)
    try:
        if not getattr(client._client, "account_id", None):
            return {"verdict_text": "WAIT", "reasons": ["Акаунт не готовий"], "is_trade_allowed": False}

        tf_a, tf_b = ("1m", "5m") if timeframe == "1m" else ("5m", "15m")

        d_a = get_market_data(client, symbol_cache, pair_norm, tf_a, 300)
        d_b = get_market_data(client, symbol_cache, pair_norm, tf_b, 300)

        d_a.addTimeout(MARKET_DATA_TIMEOUT, reactor)
        d_b.addTimeout(MARKET_DATA_TIMEOUT, reactor)

        results = yield DeferredList([d_a, d_b], consumeErrors=True)
        ok_a, df_a = results[0]
        ok_b, df_b = results[1]

        if not ok_a or not ok_b:
            return {"verdict_text": "WAIT", "reasons": ["Не вдалося завантажити бари"], "is_trade_allowed": False}

        score_a, verdict_a = _run_technical_analysis(df_a)
        score_b, verdict_b = _run_technical_analysis(df_b)
        avg_score = int((score_a + score_b) / 2)

        # Новини через OpenRouter
        news_result = yield news_filter.get_latest_news_sentiment_async(pair_norm)
        news_verdict = news_result.get("verdict", "GO")

        is_allowed = (verdict_a in ("BUY", "SELL")) and (news_verdict == "GO")
        
        return {
            "pair": symbol,
            "verdict_text": "NEWS_WAIT" if news_verdict == "BLOCK" else verdict_a,
            "score": avg_score,
            "sentiment": news_verdict,
            "is_trade_allowed": is_allowed,
            "reasons": [f"TF1: {verdict_a}, TF2: {verdict_b}", f"ШІ: {news_verdict}"]
        }
    except Exception as e:
        return {"verdict_text": "ERROR", "reasons": [str(e)], "is_trade_allowed": False}

def get_api_detailed_signal_data(client, symbol_cache, symbol, user_id, timeframe="5m"):
    return defer.maybeDeferred(_analysis_flow, client, symbol_cache, symbol, user_id, timeframe)

def get_market_data(client, symbol_cache, norm_pair: str, period: str, count: int):
    d = Deferred()
    symbol_details = _resolve_symbol_details(symbol_cache, norm_pair)
    if not symbol_details or not getattr(client._client, "account_id", None):
        reactor.callLater(0, d.errback, Exception("Missing details/auth"))
        return d

    now = int(time.time() * 1000)
    seconds = {"1m": 60, "5m": 300, "15m": 900}.get(period, 300)
    from_ts = now - (count * seconds * 1000)

    req = ProtoOAGetTrendbarsReq(
        ctidTraderAccountId=client._client.account_id,
        symbolId=symbol_details.symbolId,
        period=PERIOD_MAP[period],
        fromTimestamp=from_ts,
        toTimestamp=now,
    )

    api_deferred = client.send(req, timeout=20)

    def on_res(msg):
        try:
            res = ProtoOAGetTrendbarsRes()
            res.ParseFromString(msg.payload)
            div = resolve_price_divisor(symbol_details)
            bars = [{"Close": (b.low + b.deltaClose) / div} for b in res.trendbar]
            d.callback(pd.DataFrame(bars))
        except Exception as e: d.errback(e)

    api_deferred.addCallbacks(on_res, d.errback)
    return d