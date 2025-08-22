# analysis.py
import logging
import pandas as pd
import pandas_ta as ta
import numpy as np
import time
from twisted.internet.defer import Deferred, DeferredList

from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAGetTrendbarsReq, ProtoOAGetTrendbarsRes
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOATrendbarPeriod as TrendbarPeriod
from db import add_signal_to_history

logger = logging.getLogger(__name__)

PERIOD_MAP = {
    "15min": TrendbarPeriod.M15, "1h": TrendbarPeriod.H1,
    "4h": TrendbarPeriod.H4, "1day": TrendbarPeriod.D1
}

def get_market_data(client, symbol_cache, norm_pair: str, period: str, count: int) -> Deferred:
    d = Deferred()
    symbol_details = symbol_cache.get(norm_pair)

    if not symbol_details:
        return Deferred.fail(Exception(f"Пара '{norm_pair}' не знайдена в кеші."))

    tf_proto = PERIOD_MAP.get(period)
    if not tf_proto:
        return Deferred.fail(Exception(f"Непідтримуваний таймфрейм: {period}"))

    now = int(time.time() * 1000)
    seconds_per_bar = {'15min': 900, '1h': 3600, '4h': 14400, '1day': 86400}
    from_ts = now - (count * seconds_per_bar[period] * 1000)

    request = ProtoOAGetTrendbarsReq(
        ctidTraderAccountId=client._client.account_id,
        symbolId=symbol_details.symbolId, # <-- Тепер це працює, бо ми беремо ID з ProtoOALightSymbol
        period=tf_proto,
        fromTimestamp=from_ts,
        toTimestamp=now
    )
    
    logger.info(f"Requesting candles for {norm_pair} ({period})...")
    deferred = client.send(request, timeout=25)

    def process_response(message):
        response = ProtoOAGetTrendbarsRes()
        response.ParseFromString(message.payload)
        logger.info(f"✅ Received {len(response.trendbar)} candles for {norm_pair} ({period}).")
        
        if not response.trendbar: return pd.DataFrame()

        # --- КЛЮЧОВЕ ВИПРАВЛЕННЯ З ВАШОГО КОДУ ---
        # Використовуємо жорстко заданий дільник, оскільки '.digits' недоступний
        divisor = 10**5
        bars = [{
            'ts': pd.to_datetime(bar.utcTimestampInMinutes * 60, unit='s', utc=True),
            'open': (bar.low + bar.deltaOpen) / divisor,
            'high': (bar.low + bar.deltaHigh) / divisor,
            'low': bar.low / divisor,
            'close': (bar.low + bar.deltaClose) / divisor,
            'volume': bar.volume
        } for bar in response.trendbar]
        # --- КІНЕЦЬ ВИПРАВЛЕННЯ ---
        
        df = pd.DataFrame(bars)
        d.callback(df.sort_values(by='ts').reset_index(drop=True))

    def on_error(failure):
        err = failure.getErrorMessage() if hasattr(failure, 'getErrorMessage') else str(failure)
        logger.error(f"❌ Data request failed for {norm_pair} ({period}): {err}")
        d.errback(failure)

    deferred.addCallbacks(process_response, on_error)
    return d

def _calculate_core_signal(df, daily_df):
    df.ta.rsi(length=14, append=True, col_names=('RSI',))
    df.ta.kama(length=14, append=True, col_names=('KAMA',))
    last = df.iloc[-1]
    price = float(last['close'])
    
    lows = daily_df['low'].tail(30); highs = daily_df['high'].tail(30)
    support = lows[lows < price].max(); resistance = highs[highs > price].min()

    score, reasons = 50, []
    if price > last['KAMA']: score += 15; reasons.append("Price > KAMA(14)")
    else: score -= 15; reasons.append("Price < KAMA(14)")
    if last['RSI'] < 30: score += 20; reasons.append("RSI < 30 (oversold)")
    elif last['RSI'] > 70: score -= 20; reasons.append("RSI > 70 (overbought)")
    
    return {
        "score": int(np.clip(score, 0, 100)), "reasons": reasons,
        "support": float(support) if pd.notna(support) else None,
        "resistance": float(resistance) if pd.notna(resistance) else None,
        "price": price
    }

def _generate_verdict(score):
    if score > 65: return "⬆️ Strong BUY"
    if score > 55: return "↗️ Moderate BUY"
    if score < 35: return "⬇️ Strong SELL"
    if score < 45: return "↘️ Moderate SELL"
    return "🟡 NEUTRAL"

def get_api_detailed_signal_data(client, symbol_cache, symbol: str, user_id: int) -> Deferred:
    def on_data_ready(results):
        try:
            success1, df = results[0]; success2, daily_df = results[1]
            if not (success1 and success2) or df.empty or len(df) < 25 or daily_df.empty:
                logger.warning(f"Not enough data to analyze {symbol}.")
                return {"error": "Not enough historical data for analysis."}

            analysis = _calculate_core_signal(df, daily_df)
            verdict = _generate_verdict(analysis['score'])
            add_signal_to_history({'user_id': user_id, 'pair': symbol, 'price': analysis['price'], 'bull_percentage': analysis['score']})
            
            return {"pair": symbol, "price": analysis['price'], "verdict_text": verdict, "reasons": analysis['reasons'], "support": analysis['support'], "resistance": analysis['resistance']}
        except Exception as e:
            logger.exception(f"Critical analysis error for {symbol}: {e}")
            return {"error": "Internal data processing error."}

    d1 = get_market_data(client, symbol_cache, symbol, '15min', 100)
    d2 = get_market_data(client, symbol_cache, symbol, '1day', 100)
    
    d_list = DeferredList([d1, d2], consumeErrors=True)
    d_list.addCallback(on_data_ready)
    return d_list