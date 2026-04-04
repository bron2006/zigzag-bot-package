import logging
import time
import pandas as pd
import numpy as np
import pandas_ta as ta
from typing import Optional, Dict
from twisted.internet.defer import Deferred
from twisted.internet import reactor

from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAGetTrendbarsReq, ProtoOAGetTrendbarsRes
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOATrendbarPeriod as TrendbarPeriod

from state import app_state
from price_utils import resolve_price_divisor
import ml_models
import news_filter  # Підключаємо твій новий фільтр новин

logger = logging.getLogger("analysis")
PERIOD_MAP = { "1m": TrendbarPeriod.M1, "5m": TrendbarPeriod.M5, "15m": TrendbarPeriod.M15 }

def _prepare_features(df: pd.DataFrame):
    """Розрахунок 5 основних індикаторів для LightGBM."""
    df = df.copy()
    try:
        df.ta.rsi(length=14, append=True)
        df.ta.adx(length=14, append=True)
        df.ta.atr(length=14, append=True)
        df.ta.ema(length=50, append=True)
        df.ta.ema(length=200, append=True)
        
        latest = df.tail(1)
        features = [
            latest["ATRr_14"].values[0],
            latest["ADX_14"].values[0],
            latest["RSI_14"].values[0],
            latest["EMA_50"].values[0],
            latest["EMA_200"].values[0]
        ]
        return np.array([features])
    except Exception as e:
        logger.error(f"Indicator calculation error: {e}")
        return None

def get_api_detailed_signal_data(client, symbol_cache, symbol, user_id, timeframe="5m"):
    pair_norm = symbol.replace("/", "")
    main_d = Deferred()
    market_d = get_market_data(client, symbol_cache, pair_norm, timeframe, 300)
    
    def process_result(df):
        try:
            if df is None or df.empty or len(df) < 250:
                main_d.callback({"pair": symbol, "verdict_text": "WAIT", "price": 0.0, "score": 50, "reasons": ["Очікуємо дані..."]})
                return

            last_close = float(df['Close'].iloc[-1])
            score = 50
            verdict = "NEUTRAL"
            reasons = []

            # 1. ТЕХНІЧНИЙ АНАЛІЗ (LightGBM)
            if ml_models.LGBM_MODEL and ml_models.SCALER:
                features_raw = _prepare_features(df)
                if features_raw is not None and not np.isnan(features_raw).any():
                    features_scaled = ml_models.SCALER.transform(features_raw)
                    probs = ml_models.LGBM_MODEL.predict_proba(features_scaled)
                    score = int(probs[0][1] * 100)
                    
                    if score > 75: verdict = "BUY"
                    elif score < 25: verdict = "SELL"
            
            # 2. ФІЛЬТР НОВИН (Gemini AI)
            # Запитуємо Gemini тільки якщо техніка дає сигнал
            if verdict != "NEUTRAL":
                ai_news = news_filter.get_latest_news_sentiment(symbol)
                if ai_news == "BLOCK":
                    logger.info(f"🚨 {symbol} BLOCKED by News Filter")
                    verdict = "NEWS_WAIT"
                    reasons.append("ШІ: Ризиковані новини. Вхід заборонено.")
                else:
                    reasons.append(f"ШІ: Новини ок. Технічний Score: {score}%")
            else:
                reasons.append(f"Score: {score}%. Сигнал відсутній.")

            main_d.callback({
                "pair": symbol, "price": last_close, "verdict_text": verdict,
                "score": score, "reasons": reasons, "ts": time.time()
            })
        except Exception as e:
            logger.exception("Analysis Error")
            main_d.callback({"pair": symbol, "verdict_text": "ERROR", "score": 50, "reasons": [str(e)]})

    market_d.addCallbacks(process_result, lambda err: main_d.callback({"pair": symbol, "verdict_text": "TIMEOUT"}))
    return main_d

def get_market_data(client, symbol_cache, norm_pair, period, count):
    d = Deferred()
    symbol_details = symbol_cache.get(norm_pair)
    if not symbol_details:
        reactor.callLater(0, d.errback, Exception(f"Символ {norm_pair} не знайдено."))
        return d
    tf_proto = PERIOD_MAP.get(period)
    now = int(time.time() * 1000)
    seconds = {'1m': 60, '5m': 300, '15m': 900}.get(period, 300)
    from_ts = now - (count * seconds * 1000)
    
    request = ProtoOAGetTrendbarsReq(ctidTraderAccountId=client._client.account_id, symbolId=symbol_details.symbolId, period=tf_proto, fromTimestamp=from_ts, toTimestamp=now)
    api_deferred = client.send(request, timeout=20)
    
    def on_res(message):
        try:
            res = ProtoOAGetTrendbarsRes(); res.ParseFromString(message.payload)
            if not res.trendbar: return d.callback(pd.DataFrame())
            div = resolve_price_divisor(symbol_details)
            bars = [{'ts': pd.to_datetime(b.utcTimestampInMinutes*60, unit='s', utc=True),
                     'Open': (b.low+b.deltaOpen)/div, 'High': (b.low+b.deltaHigh)/div,
                     'Low': b.low/div, 'Close': (b.low+b.deltaClose)/div} for b in res.trendbar]
            d.callback(pd.DataFrame(bars).sort_values('ts'))
        except Exception as e: d.errback(e)
    api_deferred.addCallbacks(on_res, d.errback)
    return d
