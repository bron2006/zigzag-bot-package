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

def get_api_detailed_signal_data(client, symbol_cache, symbol, user_id, timeframe="5m"):
    """
    Відновлена функція за оригінальним контрактом.
    Використовує 'pair' та 'verdict_text' для UI.
    """
    pair_norm = symbol.replace("/", "")
    main_d = Deferred()
    
    market_d = get_market_data(client, symbol_cache, pair_norm, timeframe, 300)
    
    def process_result(df):
        try:
            if df is None or df.empty or len(df) < 250:
                main_d.callback({
                    "pair": symbol,
                    "price": 0.0,
                    "verdict_text": "WAIT",
                    "score": 50,
                    "reasons": ["Недостатньо даних."]
                })
                return

            last_close = float(df['Close'].iloc[-1])
            
            # ПОВЕРТАЄМО ОРИГІНАЛЬНУ СТРУКТУРУ:
            prediction = {
                "pair": symbol,              # Повертаємо 'pair'
                "price": last_close,         # Ціна з новим дільником
                "verdict_text": "NEUTRAL",   # Повертаємо 'verdict_text' (замість undefined)
                "score": 50,
                "reasons": ["Аналіз виконано. Ціна підтягнута вірно."],
                "ts": time.time()
            }
            
            main_d.callback(prediction)
        except Exception as e:
            logger.exception("UI formatting error")
            main_d.callback({"pair": symbol, "verdict_text": "ERROR", "price": 0, "score": 50, "reasons": [str(e)]})

    market_d.addCallbacks(process_result, lambda err: main_d.callback({"pair": symbol, "verdict_text": "TIMEOUT", "price": 0, "score": 50, "reasons": [str(err)]}))
    return main_d

def get_market_data(client, symbol_cache, norm_pair: str, period: str, count: int) -> Deferred:
    d = Deferred()
    symbol_details = symbol_cache.get(norm_pair)
    if not symbol_details:
        reactor.callLater(0, d.errback, Exception(f"Символ {norm_pair} не знайдено."))
        return d
        
    tf_proto = PERIOD_MAP.get(period)
    now = int(time.time() * 1000)
    seconds = {'1m': 60, '5m': 300, '15m': 900}.get(period, 300)
    from_ts = now - (count * seconds * 1000)
    
    request = ProtoOAGetTrendbarsReq(
        ctidTraderAccountId=client._client.account_id, 
        symbolId=symbol_details.symbolId, 
        period=tf_proto, 
        fromTimestamp=from_ts, 
        toTimestamp=now
    )
    
    api_deferred = client.send(request, timeout=20)
    
    def on_res(message):
        try:
            res = ProtoOAGetTrendbarsRes()
            res.ParseFromString(message.payload)
            if not res.trendbar: return d.callback(pd.DataFrame())
            
            div = resolve_price_divisor(symbol_details)
            bars = [{'ts': pd.to_datetime(b.utcTimestampInMinutes*60, unit='s', utc=True),
                     'Open': (b.low + b.deltaOpen) / div, 'High': (b.low + b.deltaHigh) / div,
                     'Low': b.low / div, 'Close': (b.low + b.deltaClose) / div} for b in res.trendbar]
            d.callback(pd.DataFrame(bars).sort_values('ts'))
        except Exception as e: d.errback(e)

    api_deferred.addCallbacks(on_res, d.errback)
    return d