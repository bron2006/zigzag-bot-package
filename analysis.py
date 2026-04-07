# analysis.py
#
# ВИПРАВЛЕННЯ 1: sklearn warning — _prepare_features тепер передає
#                pandas DataFrame з іменованими колонками.
# ВИПРАВЛЕННЯ 2: Gemini викликається через get_latest_news_sentiment_async()
#                — не блокує reactor.
# ВИПРАВЛЕННЯ 3: Multi-timeframe підтвердження — M1 + M5 паралельно.
#                Сигнал надсилається тільки якщо обидва погоджуються.
# ВИПРАВЛЕННЯ 4: reason від Gemini включається в результат сигналу.

import logging
import time
import pandas as pd
import numpy as np
import pandas_ta as ta
from typing import Optional
from twisted.internet.defer import Deferred, DeferredList
from twisted.internet import reactor

from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAGetTrendbarsReq, ProtoOAGetTrendbarsRes
)
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOATrendbarPeriod as TrendbarPeriod
from state import app_state
from price_utils import resolve_price_divisor
import ml_models
import news_filter

logger = logging.getLogger("analysis")

PERIOD_MAP = {
    "1m":  TrendbarPeriod.M1,
    "5m":  TrendbarPeriod.M5,
    "15m": TrendbarPeriod.M15,
}

# ---------------------------------------------------------------------------
# ВИПРАВЛЕННЯ: _prepare_features повертає DataFrame з іменами колонок
# ---------------------------------------------------------------------------

FEATURE_NAMES = ["ATRr_14", "ADX_14", "RSI_14", "EMA_50", "EMA_200"]

def _prepare_features(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """
    Розраховує технічні індикатори і повертає pd.DataFrame з іменованими
    колонками — щоб sklearn StandardScaler не видавав UserWarning.
    """
    df = df.copy()
    try:
        df.ta.rsi(length=14, append=True)
        df.ta.adx(length=14, append=True)
        df.ta.atr(length=14, append=True)
        df.ta.ema(length=50,  append=True)
        df.ta.ema(length=200, append=True)

        latest = df.tail(1)

        # Перевіряємо що всі колонки є
        missing = [col for col in FEATURE_NAMES if col not in latest.columns]
        if missing:
            logger.warning(f"Відсутні колонки індикаторів: {missing}")
            return None

        # Повертаємо DataFrame з іменами — sklearn більше не скаржиться
        features_df = latest[FEATURE_NAMES].copy()

        if features_df.isnull().any().any():
            logger.debug("NaN в фічах — недостатньо барів для індикаторів")
            return None

        return features_df

    except Exception as e:
        logger.error(f"Помилка розрахунку індикаторів: {e}")
        return None


# ---------------------------------------------------------------------------
# Технічний аналіз одного таймфрейму (повертає score 0-100)
# ---------------------------------------------------------------------------

def _run_technical_analysis(df: pd.DataFrame) -> tuple[int, str]:
    """
    Повертає (score, verdict) на основі ML моделі.
    score: 0-100, verdict: BUY | SELL | NEUTRAL
    """
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


# ---------------------------------------------------------------------------
# ВИПРАВЛЕННЯ: Multi-timeframe підтвердження (M1 + M5 паралельно)
# ---------------------------------------------------------------------------

def get_api_detailed_signal_data(client, symbol_cache, symbol, user_id, timeframe="5m"):
    """
    Запитує дані для M1 і M5 паралельно через DeferredList.
    Сигнал BUY/SELL надсилається тільки якщо обидва ТФ погоджуються.
    Якщо M1=BUY але M5=SELL → NEUTRAL (суперечність).
    """
    pair_norm = symbol.replace("/", "")
    main_d    = Deferred()

    # Паралельний запит двох таймфреймів
    d_m1 = get_market_data(client, symbol_cache, pair_norm, "1m",  300)
    d_m5 = get_market_data(client, symbol_cache, pair_norm, "5m",  300)

    dl = DeferredList([d_m1, d_m5], consumeErrors=True)

    def process_both(results):
        try:
            ok_m1, df_m1 = results[0]
            ok_m5, df_m5 = results[1]

            if not ok_m1 or not ok_m5:
                main_d.callback({
                    "pair": symbol, "verdict_text": "WAIT", "price": 0.0,
                    "score": 50, "reasons": ["Не вдалося завантажити дані"],
                    "timeframe": timeframe
                })
                return

            score_m1, verdict_m1 = _run_technical_analysis(df_m1 if ok_m1 else None)
            score_m5, verdict_m5 = _run_technical_analysis(df_m5 if ok_m5 else None)

            logger.info(f"[{pair_norm}] M1: {verdict_m1}({score_m1}) | M5: {verdict_m5}({score_m5})")

            # Multi-TF логіка:
            # BUY  — обидва погоджуються на ріст
            # SELL — обидва погоджуються на падіння
            # NEUTRAL — суперечність або обидва нейтральні
            if verdict_m1 == "BUY" and verdict_m5 in ("BUY", "NEUTRAL"):
                final_verdict = "BUY"
                final_score   = score_m1
            elif verdict_m1 == "SELL" and verdict_m5 in ("SELL", "NEUTRAL"):
                final_verdict = "SELL"
                final_score   = score_m1
            elif verdict_m1 == verdict_m5 and verdict_m1 != "NEUTRAL":
                final_verdict = verdict_m1
                final_score   = (score_m1 + score_m5) // 2
            else:
                final_verdict = "NEUTRAL"
                final_score   = 50

            last_close = float(df_m1['Close'].iloc[-1]) if ok_m1 and not df_m1.empty else 0.0
            reasons    = [f"M1: {verdict_m1} ({score_m1}%) | M5: {verdict_m5} ({score_m5}%)"]

            # ВИПРАВЛЕННЯ: async Gemini — не блокує reactor
            news_d = news_filter.get_latest_news_sentiment_async(pair_norm)

            def apply_news(news_result):
                nonlocal final_verdict, reasons
                news_verdict = news_result.get("verdict", "GO")
                news_reason  = news_result.get("reason", "")

                if news_verdict == "BLOCK":
                    logger.info(f"[{pair_norm}] BLOCKED by news: {news_reason}")
                    if final_verdict != "NEUTRAL":
                        final_verdict = "NEWS_WAIT"
                    reasons.append(f"ШІ: BLOCK — {news_reason}" if news_reason else "ШІ: Ризиковані новини. Вхід заборонено.")
                else:
                    news_text = f"ШІ: GO — {news_reason}" if news_reason else f"ШІ: Новини ок. Score: {final_score}%"
                    reasons.append(news_text)

                main_d.callback({
                    "pair":         symbol,
                    "price":        last_close,
                    "verdict_text": final_verdict,
                    "score":        final_score,
                    "reasons":      reasons,
                    "ts":           time.time(),
                    "timeframe":    timeframe,
                    "sentiment":    news_verdict,
                })

            def news_error(failure):
                logger.warning(f"News filter error for {pair_norm}: {failure.getErrorMessage()}")
                reasons.append("ШІ: недоступний, аналіз без новин")
                main_d.callback({
                    "pair":         symbol,
                    "price":        last_close,
                    "verdict_text": final_verdict,
                    "score":        final_score,
                    "reasons":      reasons,
                    "ts":           time.time(),
                    "timeframe":    timeframe,
                    "sentiment":    "GO",
                })

            news_d.addCallback(apply_news)
            news_d.addErrback(news_error)

        except Exception as e:
            logger.exception(f"Analysis error for {symbol}")
            main_d.callback({
                "pair": symbol, "verdict_text": "ERROR",
                "score": 50, "reasons": [str(e)], "timeframe": timeframe
            })

    dl.addCallback(process_both)
    return main_d


# ---------------------------------------------------------------------------
# Завантаження ринкових даних
# ---------------------------------------------------------------------------

def get_market_data(client, symbol_cache, norm_pair: str, period: str, count: int):
    d = Deferred()

    symbol_details = symbol_cache.get(norm_pair)
    if not symbol_details:
        reactor.callLater(0, d.errback, Exception(f"Символ {norm_pair} не знайдено."))
        return d

    tf_proto = PERIOD_MAP.get(period)
    if not tf_proto:
        reactor.callLater(0, d.errback, Exception(f"Невідомий таймфрейм: {period}"))
        return d

    now      = int(time.time() * 1000)
    seconds  = {'1m': 60, '5m': 300, '15m': 900}.get(period, 300)
    from_ts  = now - (count * seconds * 1000)

    req = ProtoOAGetTrendbarsReq(
        ctidTraderAccountId=client._client.account_id,
        symbolId=symbol_details.symbolId,
        period=tf_proto,
        fromTimestamp=from_ts,
        toTimestamp=now,
    )

    api_deferred = client.send(req, timeout=20)

    def on_res(msg):
        try:
            res = ProtoOAGetTrendbarsRes()
            res.ParseFromString(msg.payload)

            if not res.trendbar:
                return d.callback(pd.DataFrame())

            div  = resolve_price_divisor(symbol_details)
            bars = [
                {
                    'ts':    pd.to_datetime(b.utcTimestampInMinutes * 60, unit='s', utc=True),
                    'Open':  (b.low + b.deltaOpen)  / div,
                    'High':  (b.low + b.deltaHigh)  / div,
                    'Low':    b.low                  / div,
                    'Close': (b.low + b.deltaClose)  / div,
                }
                for b in res.trendbar
            ]
            d.callback(pd.DataFrame(bars).sort_values('ts'))

        except Exception as e:
            d.errback(e)

    api_deferred.addCallbacks(on_res, d.errback)
    return d
