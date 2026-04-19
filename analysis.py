import logging
import time
from typing import Optional, Tuple

import pandas as pd
import pandas_ta as ta
from twisted.internet import defer, reactor
from twisted.internet.defer import Deferred, DeferredList, succeed
from twisted.internet.threads import deferToThreadPool

import ml_models
import news_filter
from config import broker_symbol_key
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

MARKET_DATA_TIMEOUT = 45
CPU_ANALYSIS_TIMEOUT = 30
PRICE_FRESH_SECONDS = 60

MODEL_FEATURE_NAMES = ["ATR", "ADX", "RSI", "EMA50", "EMA200"]

FEATURE_SOURCE_MAP = {
    "ATR": ["ATRr_14", "ATR_14"],
    "ADX": ["ADX_14"],
    "RSI": ["RSI_14"],
    "EMA50": ["EMA_50"],
    "EMA200": ["EMA_200"],
}


def _label_verdict(value: str) -> str:
    labels = {
        "BUY": "купівля",
        "SELL": "продаж",
        "NEUTRAL": "нейтрально",
        "WAIT": "очікування",
        "NEWS_WAIT": "пауза через новини",
        "ERROR": "помилка",
    }
    return labels.get((value or "").upper(), "невідомо")


def _label_sentiment(value: str) -> str:
    labels = {
        "GO": "дозволено",
        "BLOCK": "заблоковано",
    }
    return labels.get((value or "").upper(), "невідомо")


def _label_timeframe(value: str) -> str:
    labels = {
        "1m": "1 хв",
        "5m": "5 хв",
        "15m": "15 хв",
    }
    return labels.get(value or "", value or "")


def _blocking_pool():
    return app_state.blocking_pool or reactor.getThreadPool()


def _normalize_pair(pair: str) -> str:
    return (pair or "").replace("/", "").upper().strip()


def _resolve_symbol_details(symbol_cache, pair: str):
    norm = _normalize_pair(pair)
    broker_norm = broker_symbol_key(pair)

    candidates = [
        norm,
        broker_norm,
        pair,
        pair.upper() if pair else "",
    ]

    if len(norm) >= 6:
        candidates.append(f"{norm[:3]}/{norm[3:]}")
    if len(broker_norm) >= 6:
        candidates.append(f"{broker_norm[:3]}/{broker_norm[3:]}")

    for candidate in candidates:
        if candidate and candidate in symbol_cache:
            return symbol_cache[candidate]

    return None


def _models_ready() -> bool:
    return (
        ml_models.SCALER is not None
        and ml_models.LGBM_MODEL is not None
        and hasattr(ml_models.SCALER, "transform")
        and hasattr(ml_models.LGBM_MODEL, "predict_proba")
    )


def _prepare_features(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    if df is None or df.empty:
        return None

    required = {"Open", "High", "Low", "Close"}
    if not required.issubset(df.columns):
        logger.warning("OHLC dataframe is missing columns: %s", sorted(required - set(df.columns)))
        return None

    df = df.copy()

    try:
        df.ta.rsi(close=df["Close"], length=14, append=True)
        df.ta.adx(high=df["High"], low=df["Low"], close=df["Close"], length=14, append=True)
        df.ta.atr(high=df["High"], low=df["Low"], close=df["Close"], length=14, append=True)
        df.ta.ema(close=df["Close"], length=50, append=True)
        df.ta.ema(close=df["Close"], length=200, append=True)

        latest = df.tail(1)
        prepared = {}

        for target, sources in FEATURE_SOURCE_MAP.items():
            for src in sources:
                if src in latest.columns:
                    val = latest[src].iloc[0]
                    if pd.notna(val):
                        prepared[target] = val
                        break

        if len(prepared) < len(MODEL_FEATURE_NAMES):
            logger.warning(
                "Not enough ML features. Got=%s expected=%s columns=%s",
                sorted(prepared.keys()),
                MODEL_FEATURE_NAMES,
                list(df.columns),
            )
            return None

        return pd.DataFrame([prepared], columns=MODEL_FEATURE_NAMES)

    except Exception:
        logger.exception("Failed to prepare technical features")
        return None


def _run_technical_analysis(df: pd.DataFrame) -> Tuple[int, str, str]:
    if df is None or len(df) < 250:
        return 50, "WAIT", "Недостатньо історії"

    if not _models_ready():
        return 50, "WAIT", "Модель ШІ не завантажена"

    features = _prepare_features(df)
    if features is None:
        return 50, "WAIT", "Не вдалося підготувати індикатори"

    try:
        scaled = ml_models.SCALER.transform(features)
        prob = ml_models.LGBM_MODEL.predict_proba(scaled)[0][1]
        score = int(prob * 100)
        verdict = "BUY" if score > 75 else "SELL" if score < 25 else "NEUTRAL"
        return score, verdict, ""
    except Exception:
        logger.exception("ML prediction failed")
        return 50, "WAIT", "Помилка прогнозу ШІ"


def _latest_price_from_df(df: pd.DataFrame):
    try:
        if df is not None and not df.empty:
            val = df["Close"].iloc[-1]
            if pd.notna(val):
                return float(val)
    except Exception:
        pass
    return None


def _price_status(pair_norm: str) -> dict:
    price_data = app_state.get_live_price(pair_norm)
    if not price_data:
        return {
            "ok": False,
            "label": "поточна ціна ще не отримана",
            "age_seconds": None,
            "mid": None,
        }

    age = max(0, int(time.time() - price_data.get("ts", 0)))
    mid = price_data.get("mid")
    ok = isinstance(mid, (int, float)) and age <= PRICE_FRESH_SECONDS

    return {
        "ok": ok,
        "label": f"свіжа, {age} сек тому" if ok else f"застаріла, {age} сек тому",
        "age_seconds": age,
        "mid": mid if isinstance(mid, (int, float)) else None,
        "bid": price_data.get("bid"),
        "ask": price_data.get("ask"),
    }


def _base_status(pair_norm: str) -> dict:
    account_ready = bool(getattr(getattr(app_state.client, "_client", None), "account_id", None))
    models_ready = _models_ready()
    return {
        "ctrader": {
            "ok": bool(app_state.SYMBOLS_LOADED and account_ready),
            "label": "готовий" if app_state.SYMBOLS_LOADED and account_ready else "не готовий",
        },
        "price": _price_status(pair_norm),
        "ml": {
            "ok": models_ready,
            "label": "готова" if models_ready else "модель не завантажена",
        },
        "calendar": {
            "ok": None,
            "label": "ще не перевірено",
        },
        "market_data": {
            "ok": None,
            "label": "ще не перевірено",
        },
        "generated_at": int(time.time()),
    }


def _calendar_status(news_res: dict) -> dict:
    if not news_res:
        return {"ok": False, "label": "календар не відповів", "source": None}

    verdict = news_res.get("verdict")
    available = bool(news_res.get("available", False))
    source = news_res.get("source")
    reason = news_res.get("reason") or ""

    if verdict == "BLOCK":
        label = f"заблоковано: {reason}" if reason else "заблоковано"
        ok = False
    elif available:
        label = reason or "календар працює"
        ok = True
    else:
        label = f"недоступний: {reason}" if reason else "недоступний"
        ok = None

    return {
        "ok": ok,
        "label": label,
        "source": source,
        "verdict": verdict,
        "available": available,
    }


def _signal_quality(score: int, trade_allowed: bool) -> str:
    if not trade_allowed:
        return "чекати"

    distance = abs(score - 50)
    if distance >= 35:
        return "сильний"
    if distance >= 25:
        return "середній"
    return "слабкий"


@defer.inlineCallbacks
def _analysis_flow(client, symbol_cache, symbol, user_id, timeframe="5m", lang: str | None = None):
    pair_norm = _normalize_pair(symbol)
    data_status = _base_status(pair_norm)

    try:
        if client is None or not getattr(client, "_client", None):
            return {
                "pair": pair_norm,
                "timeframe": timeframe,
                "verdict_text": "WAIT",
                "score": 50,
                "sentiment": "GO",
                "reasons": ["cTrader клієнт не готовий"],
                "data_status": data_status,
                "is_trade_allowed": False,
            }

        if not getattr(client._client, "account_id", None):
            return {
                "pair": pair_norm,
                "timeframe": timeframe,
                "verdict_text": "WAIT",
                "score": 50,
                "sentiment": "GO",
                "reasons": ["Акаунт не готовий"],
                "data_status": data_status,
                "is_trade_allowed": False,
            }

        tf_a, tf_b = ("1m", "5m") if timeframe == "1m" else ("5m", "15m")

        d_a = get_market_data(client, symbol_cache, pair_norm, tf_a, 300)
        d_b = get_market_data(client, symbol_cache, pair_norm, tf_b, 300)

        results = yield DeferredList([d_a, d_b], consumeErrors=True)

        df_a = results[0][1] if results[0][0] else None
        df_b = results[1][1] if results[1][0] else None

        if df_a is None or df_b is None:
            data_status["market_data"] = {
                "ok": False,
                "label": "історичні дані не отримано",
            }
            reasons = ["Помилка даних"]
            if not results[0][0]:
                reasons.append(f"{tf_a}: {results[0][1].getErrorMessage()}")
            if not results[1][0]:
                reasons.append(f"{tf_b}: {results[1][1].getErrorMessage()}")

            return {
                "pair": pair_norm,
                "timeframe": timeframe,
                "verdict_text": "WAIT",
                "score": 50,
                "sentiment": "GO",
                "reasons": reasons,
                "data_status": data_status,
                "is_trade_allowed": False,
            }

        data_status["market_data"] = {
            "ok": True,
            "label": f"отримано ({tf_a} і {tf_b})",
        }

        score_a, verdict_a, reason_a = _run_technical_analysis(df_a)
        score_b, verdict_b, reason_b = _run_technical_analysis(df_b)

        news_res = yield news_filter.get_latest_news_sentiment_async(pair_norm, lang)
        news_v = news_res.get("verdict", "GO")
        data_status["calendar"] = _calendar_status(news_res)
        data_status["price"] = _price_status(pair_norm)

        reasons = [
            (
                f"Таймфрейми: {_label_timeframe(tf_a)} = {_label_verdict(verdict_a)}, "
                f"{_label_timeframe(tf_b)} = {_label_verdict(verdict_b)}"
            ),
            f"Новини: {_label_sentiment(news_v)}",
        ]
        if reason_a:
            reasons.append(f"{_label_timeframe(tf_a)}: {reason_a}")
        if reason_b:
            reasons.append(f"{_label_timeframe(tf_b)}: {reason_b}")
        if news_res.get("reason"):
            if news_v == "BLOCK":
                reasons.append(f"Фільтр новин: {news_res['reason']}")
            elif not news_res.get("available", True):
                reasons.append(f"Фільтр новин: {news_res['reason']} (вхід не блокується)")

        score = int((score_a + score_b) / 2)
        verdict = "NEWS_WAIT" if news_v == "BLOCK" else verdict_a
        price_ok = bool(data_status["price"].get("ok"))
        if not price_ok:
            reasons.append(f"Ціна: {data_status['price'].get('label', 'не готова')}")

        trade_allowed = verdict_a in ("BUY", "SELL") and news_v == "GO" and price_ok
        quality = _signal_quality(score, trade_allowed)

        return {
            "pair": pair_norm,
            "timeframe": timeframe,
            "price": _latest_price_from_df(df_a),
            "verdict_text": verdict,
            "score": score,
            "sentiment": news_v,
            "news_filter": news_res,
            "data_status": data_status,
            "signal_quality": quality,
            "is_trade_allowed": trade_allowed,
            "reasons": reasons,
            "timeframe_details": {
                tf_a: {"verdict": verdict_a, "score": score_a},
                tf_b: {"verdict": verdict_b, "score": score_b},
            },
        }

    except Exception as e:
        logger.exception("Analysis flow failed for %s", pair_norm)
        return {
            "pair": pair_norm,
            "timeframe": timeframe,
            "verdict_text": "ERROR",
            "score": 50,
            "sentiment": "GO",
            "reasons": [str(e)],
            "error": str(e),
            "data_status": data_status,
            "is_trade_allowed": False,
        }


def get_api_detailed_signal_data(client, symbol_cache, symbol, user_id, timeframe="5m", lang: str | None = None):
    return defer.maybeDeferred(_analysis_flow, client, symbol_cache, symbol, user_id, timeframe, lang)


def _trendbar_to_row(bar, divisor: float) -> dict:
    low_raw = getattr(bar, "low", 0)
    open_raw = low_raw + getattr(bar, "deltaOpen", 0)
    high_raw = low_raw + getattr(bar, "deltaHigh", 0)
    close_raw = low_raw + getattr(bar, "deltaClose", 0)

    row = {
        "Open": open_raw / divisor,
        "High": high_raw / divisor,
        "Low": low_raw / divisor,
        "Close": close_raw / divisor,
    }

    if hasattr(bar, "volume"):
        row["Volume"] = getattr(bar, "volume", 0)

    if hasattr(bar, "utcTimestampInMinutes"):
        row["Timestamp"] = int(getattr(bar, "utcTimestampInMinutes")) * 60

    return row


def get_market_data(client, symbol_cache, norm_pair: str, period: str, count: int):
    d = Deferred()

    symbol_details = _resolve_symbol_details(symbol_cache, norm_pair)
    if not symbol_details:
        reactor.callLater(0, d.errback, Exception(f"Symbol not found: {norm_pair}"))
        return d

    if period not in PERIOD_MAP:
        reactor.callLater(0, d.errback, Exception(f"Unsupported timeframe: {period}"))
        return d

    account_id = getattr(getattr(client, "_client", None), "account_id", None)
    if not account_id:
        reactor.callLater(0, d.errback, Exception("No Account ID"))
        return d

    now = int(time.time() * 1000)
    seconds = {"1m": 60, "5m": 300, "15m": 900}.get(period, 300)
    from_ts = now - (count * seconds * 1000)

    req = ProtoOAGetTrendbarsReq(
        ctidTraderAccountId=account_id,
        symbolId=symbol_details.symbolId,
        period=PERIOD_MAP[period],
        fromTimestamp=from_ts,
        toTimestamp=now,
    )

    try:
        api_d = client.send(req, responseTimeoutInSeconds=25)
    except Exception as e:
        reactor.callLater(0, d.errback, e)
        return d

    def on_res(msg):
        if d.called:
            return None

        try:
            res = ProtoOAGetTrendbarsRes()
            res.ParseFromString(msg.payload)

            if not res.trendbar:
                d.errback(Exception(f"No trendbars returned for {norm_pair} {period}"))
                return None

            divisor = resolve_price_divisor(symbol_details)
            rows = [_trendbar_to_row(bar, divisor) for bar in res.trendbar]
            df = pd.DataFrame(rows)

            if "Timestamp" in df.columns:
                df = df.sort_values("Timestamp").reset_index(drop=True)

            d.callback(df)
        except Exception as e:
            d.errback(e)

        return None

    def on_err(failure):
        if not d.called:
            d.errback(failure)
        return None

    api_d.addCallbacks(on_res, on_err)
    d.addTimeout(MARKET_DATA_TIMEOUT, reactor)
    return d
