import pandas as pd
import pandas_ta as ta
import numpy as np
import time
import logging
from twisted.internet import defer

from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import ProtoMessage
from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAGetTrendbarsReq, ProtoOAGetTrendbarsRes
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOATrendbarPeriod as TrendbarPeriod

from db import add_signal_to_history
from config import get_demo_account_id

logger = logging.getLogger(__name__)
MARKET_DATA_CACHE = {}

def _normalize_pair(pair: str) -> str:
    return pair.replace("/", "").replace("\\", "").upper().strip()

def get_market_data(client, pair, tf, limit=300):
    norm_pair = _normalize_pair(pair)
    key = f"{norm_pair}_{tf}_{limit}"
    if key in MARKET_DATA_CACHE:
        d = defer.Deferred()
        d.callback(MARKET_DATA_CACHE[key])
        return d

    from state import symbol_cache
    symbol_details = symbol_cache.get(norm_pair)
    if not symbol_details:
        return defer.fail(Exception(f"Пара '{pair}' не знайдена в кеші."))

    tf_map = {"15min": TrendbarPeriod.M15, "1h": TrendbarPeriod.H1, "4h": TrendbarPeriod.H4, "1day": TrendbarPeriod.D1}
    if tf not in tf_map:
        return defer.fail(Exception(f"Непідтримуваний таймфрейм: {tf}"))

    now = int(time.time() * 1000)
    seconds_per_bar = {'15min': 900, '1h': 3600, '4h': 14400, '1day': 86400}
    from_ts = now - (limit * seconds_per_bar[tf] * 1000)

    request = ProtoOAGetTrendbarsReq(
        ctidTraderAccountId=get_demo_account_id(),
        symbolId=symbol_details['symbolId'],
        period=tf_map[tf],
        fromTimestamp=from_ts,
        toTimestamp=now
    )
    
    deferred = client.send(request)

    def process_response(response_proto: ProtoMessage):
        from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOAPayloadType
        if response_proto.payloadType == ProtoOAPayloadType.PROTO_OA_ERROR_RES:
            raise Exception(f"Помилка API при запиті trendbars для {pair}")

        trendbars_response = ProtoOAGetTrendbarsRes()
        trendbars_response.ParseFromString(response_proto.payload)

        if not trendbars_response.trendbar:
            return pd.DataFrame()
        
        # --- ВИПРАВЛЕННЯ: Використовуємо 'digits', яке є завжди, або безпечний fallback ---
        divisor = 10**symbol_details.get('digits', 5)
        bars = [{
            'ts': pd.to_datetime(bar.utcTimestampInMinutes * 60, unit='s', utc=True),
            'open': (bar.low + bar.deltaOpen) / divisor,
            'high': (bar.low + bar.deltaHigh) / divisor,
            'low': bar.low / divisor,
            'close': (bar.low + bar.deltaClose) / divisor,
            'volume': bar.volume
        } for bar in trendbars_response.trendbar]
        
        df = pd.DataFrame(bars)
        if df.empty:
            return df
        df = df.sort_values(by='ts').reset_index(drop=True).tail(limit)
        MARKET_DATA_CACHE[key] = df
        return df

    deferred.addCallback(process_response)
    return deferred

def _calculate_core_signal(df, daily_df):
    df.ta.rsi(close=df['close'], length=14, append=True, col_names=('RSI',))
    df.ta.kama(close=df['close'], length=14, append=True, col_names=('KAMA',))
    last = df.iloc[-1]
    current_price = float(last['close'])
    
    lows = daily_df['low'].tail(30)
    highs = daily_df['high'].tail(30)
    support = lows[lows < current_price].max()
    resistance = highs[highs > current_price].min()
    support = float(support) if pd.notna(support) else None
    resistance = float(resistance) if pd.notna(resistance) else None

    score, reasons = 50, []
    if current_price > last['KAMA']: score += 15; reasons.append("Ціна вище лінії KAMA(14)")
    else: score -= 15; reasons.append("Ціна нижче лінії KAMA(14)")
    if last['RSI'] < 30: score += 20; reasons.append("RSI в зоні перепроданості (<30)")
    elif last['RSI'] > 70: score -= 20; reasons.append("RSI в зоні перекупленості (>70)")
    
    score = int(np.clip(score, 0, 100))
    return { "score": score, "reasons": reasons, "support": support, "resistance": resistance, "price": current_price }

def _generate_verdict(analysis):
    score = analysis['score']
    if score > 65: return "⬆️ Сильний сигнал: КУПУВАТИ", "strong_buy"
    if score > 55: return "↗️ Помірний сигнал: КУПУВАТИ", "moderate_buy"
    if score < 35: return "⬇️ Сильний сигнал: ПРОДАВАТИ", "strong_sell"
    if score < 45: return "↘️ Помірний сигнал: ПРОДАВАТИ", "moderate_sell"
    return "🟡 НЕЙТРАЛЬНА СИТУАЦІЯ", "neutral"

def get_api_detailed_signal_data(client, pair, user_id=None):
    if not isinstance(pair, str) or len(pair) < 3:
        return defer.fail(Exception(f"Некоректна назва пари: '{pair}'."))

    display_pair = pair
    norm_pair = _normalize_pair(pair)

    def on_data_ready(results):
        success1, df = results[0]
        success2, daily_df = results[1]

        if not (success1 and success2):
            errors = []
            if not success1: errors.append(f"15min data failed")
            if not success2: errors.append(f"1day data failed")
            return {"error": f"Не вдалося завантажити ринкові дані ({', '.join(errors)})."}
        
        if df.empty or len(df) < 25 or daily_df.empty:
            return {"error": "Недостатньо історичних даних для аналізу."}

        analysis_result = _calculate_core_signal(df, daily_df)
        verdict_text, verdict_level = _generate_verdict(analysis_result)

        if user_id:
            add_signal_to_history({
                'user_id': user_id, 
                'pair': norm_pair, 
                'price': analysis_result['price'], 
                'bull_percentage': analysis_result['score']
            })
        
        history_df = df.tail(50)
        history = { 
            "dates": history_df['ts'].dt.strftime('%Y-%m-%d %H:%M:%S').tolist(), 
            "open": history_df['open'].tolist(), "high": history_df['high'].tolist(), 
            "low": history_df['low'].tolist(), "close": history_df['close'].tolist() 
        }
        
        return { 
            "pair": display_pair, "price": analysis_result['price'], "verdict_text": verdict_text, 
            "verdict_level": verdict_level, "reasons": analysis_result['reasons'], 
            "support": analysis_result['support'], "resistance": analysis_result['resistance'], 
            "history": history 
        }
    
    def on_error(failure):
        logger.error(f"Загальна помилка в DeferredList для {pair}: {failure.getErrorMessage()}")
        return {"error": "Внутрішня помилка обробки."}

    d1 = get_market_data(client, norm_pair, '15min', 100)
    d2 = get_market_data(client, norm_pair, '1day', 100)
    d_list = defer.DeferredList([d1, d2], consumeErrors=True)
    d_list.addCallbacks(on_data_ready, on_error)
    return d_list