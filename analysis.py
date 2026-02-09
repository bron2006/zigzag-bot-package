# analysis.py
import logging
import time
from typing import Optional, Dict

from twisted.internet.defer import Deferred
from twisted.python.failure import Failure
from twisted.internet import reactor

from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAGetTrendbarsReq, ProtoOAGetTrendbarsRes
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOATrendbarPeriod as TrendbarPeriod

from db import add_signal_to_history
from state import app_state

logger = logging.getLogger("analysis")

PERIOD_MAP = { "1m": TrendbarPeriod.M1, "5m": TrendbarPeriod.M5, "15m": TrendbarPeriod.M15 }

def _sanitize(value, default=0.0):
    import pandas as pd
    import numpy as np
    if value is None or pd.isna(value) or np.isinf(value):
        return default
    return float(value)

def get_market_data(client, symbol_cache, norm_pair: str, period: str, count: int) -> Deferred:
    import pandas as pd
    from twisted.internet import reactor
    
    d = Deferred()
    symbol_details = symbol_cache.get(norm_pair)
    
    # ВИПРАВЛЕНО: Тепер функція завжди повертає об'єкт Deferred, навіть при помилці
    if not symbol_details:
        reactor.callLater(0, d.errback, Exception(f"Пара '{norm_pair}' не знайдена в кеші."))
        return d
        
    tf_proto = PERIOD_MAP.get(period)
    if not tf_proto:
        reactor.callLater(0, d.errback, Exception(f"Непідтримуваний таймфрейм: {period}"))
        return d
        
    now = int(time.time() * 1000)
    seconds_in_period = {'1m': 60, '5m': 300, '15m': 900}.get(period, 300)
    from_ts = now - (count * seconds_in_period * 1000)
    
    request = ProtoOAGetTrendbarsReq(
        ctidTraderAccountId=client._client.account_id, 
        symbolId=symbol_details.symbolId, 
        period=tf_proto, 
        fromTimestamp=from_ts, 
        toTimestamp=now
    )
    
    api_deferred = client.send(request, timeout=30)
    
    def process_response(message):
        try:
            response = ProtoOAGetTrendbarsRes()
            response.ParseFromString(message.payload)
            logger.info(f"✅ Received {len(response.trendbar)} candles for {norm_pair} ({period}).")
            
            if not response.trendbar:
                return d.callback(pd.DataFrame())
                
            divisor = 10**5
            bars = [{
                'ts': pd.to_datetime(bar.utcTimestampInMinutes * 60, unit='s', utc=True),
                'Open': (bar.low + bar.deltaOpen) / divisor,
                'High': (bar.low + bar.deltaHigh) / divisor,
                'Low': bar.low / divisor,
                'Close': (bar.low + bar.deltaClose) / divisor,
                'Volume': bar.volume
            } for bar in response.trendbar]
            
            df = pd.DataFrame(bars)
            d.callback(df.sort_values(by='ts').reset_index(drop=True))
        except Exception as e:
            d.errback(e)
            
    api_deferred.addCallbacks(process_response, d.errback)
    return d

def _get_prediction_from_model(df) -> Dict:
    import ml_models
    if ml_models.LGBM_MODEL is None or ml_models.SCALER is None:
        return {"score": 50, "reasons": ["ML модель не завантажена."]}

    if df.empty or len(df) < 250:
        return {"score": 50, "reasons": ["Недостатньо даних (мінімум 250 свічок)."]}

    try:
        import pandas_ta as ta
        df.ta.atr(length=14, append=True)
        df.ta.adx(length=14, append=True)
        df.ta.rsi(length=14, append=True)
        df.ta.ema(length=50, append=True, col_names=('EMA50',))
        df.ta.ema(length=200, append=True, col_names=('EMA200',))
        
        last_features_raw = df.iloc[[-1]]
        
        feature_map = {
            "ATRr_14": "ATR", "ADX_14": "ADX", "RSI_14": "RSI",
            "EMA50": "EMA50", "EMA200": "EMA200"
        }
        
        if not all(col in last_features_raw.columns for col in feature_map.keys()):
            return {"score": 50, "reasons": ["Помилка розрахунку індикаторів."]}

        features_for_model = last_features_raw[list(feature_map.keys())].copy()
        features_for_model.rename(columns=feature_map, inplace=True)

        scaled_features = ml_models.SCALER.transform(features_for_model)
        probabilities = ml_models.LGBM_MODEL.predict_proba(scaled_features)
        win_probability = probabilities[0][1] * 100
        
        reasons = [
            f"RSI: {_sanitize(last_features_raw['RSI_14'].iloc[0]):.1f}",
            f"ADX: {_sanitize(last_features_raw['ADX_14'].iloc[0]):.1f}",
            f"ATR: {_sanitize(last_features_raw['ATRr_14'].iloc[0]):.5f}",
        ]
        
        return {"score": int(win_probability), "reasons": reasons, "close": last_features_raw['Close'].iloc[0]}
    except Exception as e:
        logger.error(f"ML Error: {e}")
        return {"score": 50, "reasons": ["Помилка роботи моделі."]}

def _generate_verdict_from_score(score: int) -> str:
    if score >= 75: return "⬆️ Висока ймовірність CALL"
    if score >= 60: return "↗️ Помірна ймовірність CALL"
    if score <= 25: return "⬇️ Висока ймовірність PUT"
    if score <= 40: return "↘️ Помірна ймовірність PUT"
    return "🟡 NEUTRAL"

def get_api_detailed_signal_data(client, symbol_cache, symbol: str, user_id: int, timeframe: str = "5m") -> Deferred:
    import pandas as pd
    final_deferred = Deferred()

    def on_data_ready(df: pd.DataFrame):
        try:
            if df.empty:
                final_deferred.callback({
                    "pair": symbol, "verdict_text": "Немає даних", "score": 50
                })
                return

            analysis = _get_prediction_from_model(df)
            verdict = _generate_verdict_from_score(analysis['score'])
            
            response_data = {
                "pair": symbol, "price": _sanitize(analysis.get("close")),
                "verdict_text": verdict, "reasons": analysis.get("reasons", []),
                "score": analysis.get("score", 50)
            }
            
            if user_id != 0 and (analysis['score'] >= 60 or analysis['score'] <= 40):
                add_signal_to_history({
                    'user_id': user_id, 'pair': symbol,
                    'price': response_data['price'], 'bull_percentage': analysis['score']
                })
            final_deferred.callback(response_data)
        except Exception as e:
            logger.exception(f"Analysis error for {symbol}: {e}")
            final_deferred.errback(e)

    # Викликаємо отримання даних
    d = get_market_data(client, symbol_cache, symbol, timeframe, 300)
    d.addCallbacks(on_data_ready, final_deferred.errback)
    
    return final_deferred
