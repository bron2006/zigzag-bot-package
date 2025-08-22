import logging
import pandas as pd
import pandas_ta as ta
import numpy as np
import time
from twisted.internet.defer import Deferred, DeferredList

from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAGetTrendbarsReq, ProtoOAGetTrendbarsRes,
    ProtoOASubscribeSpotsReq, ProtoOAUnsubscribeSpotsReq
)
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOATrendbarPeriod as TrendbarPeriod
from db import add_signal_to_history

logger = logging.getLogger(__name__)

PERIOD_MAP = {
    "15min": TrendbarPeriod.M15, "1h": TrendbarPeriod.H1,
    "4h": TrendbarPeriod.H4, "1day": TrendbarPeriod.D1
}

def get_live_price(client, symbol_cache, norm_pair: str) -> Deferred:
    d = Deferred()
    symbol_details = symbol_cache.get(norm_pair)
    if not symbol_details:
        return Deferred.fail(Exception(f"Символ '{norm_pair}' не знайдено для live price."))
    
    symbol_id = symbol_details.symbolId
    account_id = client._client.account_id
    event_name = f"spot_event_{symbol_id}"
    
    def on_spot_event(spot_event):
        logger.info(f"Live price received for {norm_pair}. Unsubscribing...")
        unsubscribe_req = ProtoOAUnsubscribeSpotsReq(ctidTraderAccountId=account_id, symbolId=[symbol_id])
        client.send(unsubscribe_req)
        
        client.remove_listener(event_name, on_spot_event)
        
        # --- ПОЧАТОК ЗМІН: Використовуємо правильні імена полів 'bid' та 'ask' ---
        # Перевіряємо наявність полів перед використанням
        if spot_event.HasField('bid') and spot_event.HasField('ask'):
            price = (spot_event.bid + spot_event.ask) / 2
            d.callback(price / (10**5))
        else:
            # Якщо з якоїсь причини ціни немає, повертаємо None
            d.callback(None)
        # --- КІНЕЦЬ ЗМІН ---

    client.on(event_name, on_spot_event)

    logger.info(f"Subscribing to live price for {norm_pair} (symbolId: {symbol_id})")
    subscribe_req = ProtoOASubscribeSpotsReq(ctidTraderAccountId=account_id, symbolId=[symbol_id])
    client.send(subscribe_req)

    return d

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
        symbolId=symbol_details.symbolId,
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

        divisor = 10**5
        bars = [{
            'ts': pd.to_datetime(bar.utcTimestampInMinutes * 60, unit='s', utc=True),
            'open': (bar.low + bar.deltaOpen) / divisor,
            'high': (bar.low + bar.deltaHigh) / divisor,
            'low': bar.low / divisor,
            'close': (bar.low + bar.deltaClose) / divisor,
            'volume': bar.volume
        } for bar in response.trendbar]
        
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
            success1, df = results[0]
            success2, daily_df = results[1]
            success3, live_price = results[2]

            if not (success1 and success2) or df.empty or len(df) < 25 or daily_df.empty:
                logger.warning(f"Not enough historical data to analyze {symbol}.")
                return {"error": "Not enough historical data for analysis."}

            analysis = _calculate_core_signal(df, daily_df)
            
            current_price = live_price if success3 and live_price is not None else analysis['price']

            verdict = _generate_verdict(analysis['score'])
            add_signal_to_history({
                'user_id': user_id, 'pair': symbol, 
                'price': current_price, 'bull_percentage': analysis['score']
            })
            
            response_data = {
                "pair": symbol, 
                "price": current_price,
                "verdict_text": verdict, 
                "reasons": analysis['reasons'], 
                "support": analysis['support'], 
                "resistance": analysis['resistance'],
                "bull_percentage": analysis['score'],
                "bear_percentage": 100 - analysis['score']
            }
            return response_data
            
        except Exception as e:
            logger.exception(f"Critical analysis error for {symbol}: {e}")
            return {"error": "Internal data processing error."}

    d1 = get_market_data(client, symbol_cache, symbol, '15min', 100)
    d2 = get_market_data(client, symbol_cache, symbol, '1day', 100)
    d3 = get_live_price(client, symbol_cache, symbol)
    
    d_list = DeferredList([d1, d2, d3], consumeErrors=True)
    d_list.addCallback(on_data_ready)
    return d_list