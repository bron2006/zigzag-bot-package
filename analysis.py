# analysis.py
import logging
import time
import pandas as pd
import numpy as np
from typing import Optional, Dict

from twisted.internet.defer import Deferred
from twisted.python.failure import Failure
from twisted.internet import reactor

from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAGetTrendbarsReq, ProtoOAGetTrendbarsRes
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOATrendbarPeriod as TrendbarPeriod

from db import add_signal_to_history
from state import app_state
from price_utils import resolve_price_divisor

logger = logging.getLogger("analysis")

PERIOD_MAP = { "1m": TrendbarPeriod.M1, "5m": TrendbarPeriod.M5, "15m": TrendbarPeriod.M15 }

def _sanitize(value, default=0.0):
    if value is None or pd.isna(value) or np.isinf(value):
        return default
    return float(value)

def get_market_data(client, symbol_cache, norm_pair: str, period: str, count: int) -> Deferred:
    d = Deferred()
    symbol_details = symbol_cache.get(norm_pair)
    
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
                
            divisor = resolve_price_divisor(symbol_details)
            
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
    
    return {"score": 50, "reasons": ["Аналіз готовий."]}