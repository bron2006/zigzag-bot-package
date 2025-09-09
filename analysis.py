# analysis.py
import logging
import pandas as pd
import pandas_ta as ta
import numpy as np
import time
from typing import Optional, Dict, List

from twisted.internet.defer import Deferred
from twisted.internet import reactor

from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAGetTrendbarsReq, ProtoOAGetTrendbarsRes
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOATrendbarPeriod as TrendbarPeriod

from db import add_signal_to_history
from state import app_state

logger = logging.getLogger("analysis")

PERIOD_MAP = {
    "1m": TrendbarPeriod.M1, "5m": TrendbarPeriod.M5, "15m": TrendbarPeriod.M15
}

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
    seconds_in_period = {'1m': 60, '5m': 300, '15m': 900}.get(period, 60)
    from_ts = now - (count * seconds_in_period * 1000)
    
    request = ProtoOAGetTrendbarsReq(
        ctidTraderAccountId=client._client.account_id,
        symbolId=symbol_details.symbolId,
        period=tf_proto,
        fromTimestamp=from_ts,
        toTimestamp=now
    )
    
    deferred = client.send(request, timeout=30)
    
    def process_response(message):
        try:
            response = ProtoOAGetTrendbarsRes()
            response.ParseFromString(message.payload)
            logger.info(f"✅ Received {len(response.trendbar)} candles for {norm_pair} ({period}).")
            if not response.trendbar:
                d.callback(pd.DataFrame())
                return

            divisor = 10**5
            bars = [{'ts': pd.to_datetime(bar.utcTimestampInMinutes * 60, unit='s', utc=True),
                     'Open': (bar.low + bar.deltaOpen) / divisor, 'High': (bar.low + bar.deltaHigh) / divisor,
                     'Low': bar.low / divisor, 'Close': (bar.low + bar.deltaClose) / divisor,
                     'Volume': bar.volume} for bar in response.trendbar]
            df = pd.DataFrame(bars)
            d.callback(df.sort_values(by='ts').reset_index(drop=True))
        except Exception as e:
            d.errback(e)

    def on_error(failure):
        d.errback(failure)

    deferred.addCallbacks(process_response, on_error)
    return d

def _calculate_binary_signal(df: pd.DataFrame) -> Dict:
    if df.empty or len(df) < 20:
        return {"verdict": "NEUTRAL", "reasons": ["Недостатньо даних для аналізу."]}

    try:
        df.ta.bbands(length=20, std=2.0, append=True, col_names=('BBL', 'BBM', 'BBU', 'BBB', 'BBP'))
        df.ta.stoch(k=14, d=3, smooth_k=3, append=True, col_names=('STOCHk', 'STOCHd'))
    except Exception as e:
        logger.error(f"Помилка розрахунку індикаторів: {e}")
        return {"verdict": "NEUTRAL", "reasons": ["Помилка розрахунку індикаторів."]}

    last = df.iloc[-1]
    
    verdict = "NEUTRAL"
    reasons = []

    is_oversold = last['STOCHk'] < 25
    is_touching_lower_band = last['Low'] <= last['BBL']
    is_bullish_candle = last['Close'] > last['Open']

    if is_oversold and is_touching_lower_band and is_bullish_candle:
        verdict = "⬆️ CALL"
        reasons.append("Стохастик у зоні перепроданості (<25)")
        reasons.append("Ціна торкнулася нижньої лінії Боллінджера")
        reasons.append("Остання свічка - бичача")

    is_overbought = last['STOCHk'] > 75
    is_touching_upper_band = last['High'] >= last['BBU']
    is_bearish_candle = last['Close'] < last['Open']

    if is_overbought and is_touching_upper_band and is_bearish_candle:
        verdict = "⬇️ PUT"
        reasons.append("Стохастик у зоні перекупленості (>75)")
        reasons.append("Ціна торкнулася верхньої лінії Боллінджера")
        reasons.append("Остання свічка - ведмежа")
        
    return {"verdict": verdict, "reasons": reasons, "stochastic": last['STOCHk'], "close": last['Close']}

def get_api_detailed_signal_data(client, symbol_cache, symbol: str, user_id: int, timeframe: str = "5m") -> Deferred:
    final_deferred = Deferred()

    def on_data_ready(df: pd.DataFrame):
        try:
            analysis = _calculate_binary_signal(df)
            
            response_data = {
                "pair": symbol,
                "price": analysis.get('close'),
                "verdict_text": analysis['verdict'],
                "reasons": analysis['reasons'],
                "bull_percentage": int(analysis.get('stochastic', 50)),
                "bear_percentage": 100 - int(analysis.get('stochastic', 50)),
                "special_warning": None, "candle_pattern": None, "volume_info": None,
                "support": None, "resistance": None
            }
            
            if user_id != 0 and analysis['verdict'] != "NEUTRAL":
                add_signal_to_history({
                    'user_id': user_id, 'pair': symbol,
                    'price': analysis.get('close'), 
                    'bull_percentage': int(analysis.get('stochastic', 50))
                })

            final_deferred.callback(response_data)

        except Exception as e:
            logger.exception(f"Critical analysis error for {symbol}: {e}")
            final_deferred.errback(e)

    d = get_market_data(client, symbol_cache, symbol, timeframe, 100)
    d.addCallbacks(on_data_ready, final_deferred.errback)
    
    return final_deferred