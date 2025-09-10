# analysis.py
import logging
import pandas as pd
import pandas_ta as ta
import numpy as np
import time
from typing import Optional, Dict

from twisted.internet.defer import Deferred, DeferredList
from twisted.python.failure import Failure
from twisted.internet import reactor

from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAGetTrendbarsReq, ProtoOAGetTrendbarsRes
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOATrendbarPeriod as TrendbarPeriod

from db import add_signal_to_history
from state import app_state
import ml_models

logger = logging.getLogger("analysis")

PERIOD_MAP = { "1m": TrendbarPeriod.M1, "5m": TrendbarPeriod.M5, "15m": TrendbarPeriod.M15 }

def _sanitize(value, default=0.0):
    if value is None or pd.isna(value) or np.isinf(value):
        return default
    return float(value)

def get_market_data(client, symbol_cache, norm_pair: str, period: str, count: int) -> Deferred:
    d = Deferred()
    symbol_details = symbol_cache.get(norm_pair)
    if not symbol_details: return d.errback(Exception(f"Пара '{norm_pair}' не знайдена в кеші."))
    tf_proto = PERIOD_MAP.get(period)
    if not tf_proto: return d.errback(Exception(f"Непідтримуваний таймфрейм: {period}"))
    now = int(time.time() * 1000)
    seconds_in_period = {'1m': 60, '5m': 300, '15m': 900}.get(period, 300)
    from_ts = now - (count * seconds_in_period * 1000)
    request = ProtoOAGetTrendbarsReq(ctidTraderAccountId=client._client.account_id, symbolId=symbol_details.symbolId, period=tf_proto, fromTimestamp=from_ts, toTimestamp=now)
    deferred = client.send(request, timeout=30)
    def process_response(message):
        try:
            response = ProtoOAGetTrendbarsRes(); response.ParseFromString(message.payload)
            logger.info(f"✅ Received {len(response.trendbar)} candles for {norm_pair} ({period}).")
            if not response.trendbar: return d.callback(pd.DataFrame())
            divisor = 10**5
            bars = [{'ts': pd.to_datetime(bar.utcTimestampInMinutes * 60, unit='s', utc=True), 'Open': (bar.low + bar.deltaOpen) / divisor, 'High': (bar.low + bar.deltaHigh) / divisor, 'Low': bar.low / divisor, 'Close': (bar.low + bar.deltaClose) / divisor, 'Volume': bar.volume} for bar in response.trendbar]
            df = pd.DataFrame(bars); d.callback(df.sort_values(by='ts').reset_index(drop=True))
        except Exception as e: d.errback(e)
    deferred.addCallbacks(process_response, d.errback)
    return d

def _get_prediction_from_model(df: pd.DataFrame) -> Dict:
    if ml_models.LGBM_MODEL is None or ml_models.SCALER is None:
        return {"score": 50, "reasons": ["ML модель не завантажена."]}

    if df.empty or len(df) < 200:
        return {"score": 50, "reasons": ["Недостатньо даних для розрахунку характеристик."]}

    try:
        # Розраховуємо ті ж характеристики, що й при тренуванні
        df.ta.atr(length=14, append=True)
        df.ta.adx(length=14, append=True)
        df.ta.rsi(length=14, append=True)
        df.ta.ema(length=50, append=True, col_names=('EMA50',))
        df.ta.ema(length=200, append=True, col_names=('EMA200',))
        
        last_features = df.iloc[[-1]]
        
        features_list = ['ATR', 'ADX_14', 'RSI_14', 'EMA50', 'EMA200']
        if not all(col in last_features.columns for col in features_list):
            return {"score": 50, "reasons": ["Не вдалося розрахувати всі характеристики."]}

        # Готуємо дані
        features = last_features[features_list].copy()
        scaled_features = ml_models.SCALER.transform(features)
        
        # Отримуємо ймовірності для обох класів (0 - програш, 1 - виграш)
        probabilities = ml_models.LGBM_MODEL.predict_proba(scaled_features)
        
        # Беремо ймовірність виграшу (клас 1) і перетворюємо у відсотки
        win_probability = probabilities[0][1] * 100
        
        reasons = [
            f"RSI: {_sanitize(last_features['RSI_14'].iloc[0], 0):.1f}",
            f"ADX: {_sanitize(last_features['ADX_14'].iloc[0], 0):.1f}",
            f"ATR: {_sanitize(last_features['ATR'].iloc[0], 0):.5f}",
        ]
        
        return {"score": int(win_probability), "reasons": reasons, "close": last_features['Close'].iloc[0]}

    except Exception as e:
        logger.error(f"Помилка під час прогнозування моделлю: {e}")
        return {"score": 50, "reasons": ["Помилка роботи ML моделі."]}

def _generate_verdict_from_score(score: int) -> str:
    if score >= 75: return "⬆️ Висока ймовірність CALL"
    if score >= 60: return "↗️ Помірна ймовірність CALL"
    if score <= 25: return "⬇️ Висока ймовірність PUT"
    if score <= 40: return "↘️ Помірна ймовірність PUT"
    return "🟡 НЕЙТРАЛЬНО"

def get_api_detailed_signal_data(client, symbol_cache, symbol: str, user_id: int, timeframe: str = "5m") -> Deferred:
    final_deferred = Deferred()

    def on_data_ready(df: pd.DataFrame):
        try:
            analysis = _get_prediction_from_model(df)
            verdict = _generate_verdict_from_score(analysis['score'])
            
            response_data = {
                "pair": symbol,
                "price": _sanitize(analysis.get("close")),
                "verdict_text": verdict,
                "reasons": analysis.get("reasons", []),
                "score": analysis.get("score", 50) # Тепер це ймовірність
            }
            
            if user_id != 0 and (analysis['score'] >= 60 or analysis['score'] <= 40):
                add_signal_to_history({
                    'user_id': user_id, 'pair': symbol,
                    'price': response_data['price'], 
                    'bull_percentage': analysis['score']
                })
            final_deferred.callback(response_data)
        except Exception as e:
            logger.exception(f"Critical analysis error for {symbol}: {e}")
            final_deferred.errback(e)

    # ML модель вимагає більше даних для розрахунку всіх індикаторів
    d = get_market_data(client, symbol_cache, symbol, timeframe, 300)
    d.addCallbacks(on_data_ready, final_deferred.errback)
    
    return final_deferred