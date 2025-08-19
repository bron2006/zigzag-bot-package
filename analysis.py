# analysis.py
import pandas as pd
import pandas_ta as ta
import numpy as np
import time
import logging
import random
from twisted.internet import defer, reactor
from twisted.internet.error import TimeoutError

from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import ProtoMessage
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAGetTrendbarsReq, ProtoOAGetTrendbarsRes,
    ProtoOASymbolByIdReq
)
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOATrendbarPeriod as TrendbarPeriod

from db import add_signal_to_history
from config import get_demo_account_id

logger = logging.getLogger(__name__)
MARKET_DATA_CACHE = {}

def _normalize_pair(pair: str) -> str:
    return pair.replace("/", "").replace("\\", "").upper().strip()

def _get_mta_signal_data():
    timeframes = ["15min", "1h", "4h", "1day"]
    signals = ["BUY", "SELL", "NEUTRAL"]
    return [{"tf": tf, "signal": random.choice(signals)} for tf in timeframes]

def get_full_symbol_details(client, symbol_id: int):
    from state import symbol_cache
    
    for details in symbol_cache.values():
        if details.get('symbolId') == symbol_id and 'pipPosition' in details:
            return defer.succeed(details)
            
    d = defer.Deferred()
    request = ProtoOASymbolByIdReq(ctidTraderAccountId=get_demo_account_id(), symbolId=[symbol_id])
    
    timeout_handler = reactor.callLater(
        15, lambda: not d.called and d.errback(TimeoutError(f"Таймаут отримання деталей для symbolId {symbol_id}"))
    )

    def on_symbol_data(symbol_data):
        if timeout_handler.active():
            timeout_handler.cancel()

        symbol_name = getattr(symbol_data, 'symbolName', None)
        pip_position = getattr(symbol_data, 'pipPosition', None)
        digits = getattr(symbol_data, 'digits', None)

        if not symbol_name or pip_position is None or digits is None:
            err_msg = f"cTrader повернув неповні дані для symbolId {symbol_id}"
            logger.error(f"[ANALYSIS] {err_msg}. Отримано: {symbol_data}")
            if not d.called:
                d.errback(Exception(err_msg))
            return

        norm_name = symbol_name.replace("/", "").strip()
        if norm_name in symbol_cache:
            symbol_cache[norm_name]['pipPosition'] = pip_position
            symbol_cache[norm_name]['digits'] = digits
            if not d.called:
                d.callback(symbol_cache[norm_name])
        
        if on_symbol_data in client._events.get("symbolDataLoaded", []):
            client._events["symbolDataLoaded"].remove(on_symbol_data)
            
    client.on("symbolDataLoaded")(on_symbol_data)
    client.send(request)
    return d

def get_market_data(client, pair, tf, limit=300, full_symbol_details=None):
    norm_pair = _normalize_pair(pair)
    key = f"{norm_pair}_{tf}_{limit}"
    if key in MARKET_DATA_CACHE:
        d = defer.Deferred()
        d.callback(MARKET_DATA_CACHE[key])
        return d
        
    if not full_symbol_details:
        return defer.fail(Exception(f"Для {pair} відсутня детальна інформація про символ."))

    tf_map = {"15min": TrendbarPeriod.M15, "1h": TrendbarPeriod.H1, "4h": TrendbarPeriod.H4, "1day": TrendbarPeriod.D1}
    if tf not in tf_map:
        return defer.fail(Exception(f"Непідтримуваний таймфрейм: {tf}"))

    now = int(time.time() * 1000)
    seconds_per_bar = {'15min': 900, '1h': 3600, '4h': 14400, '1day': 86400}
    from_ts = now - (limit * seconds_per_bar[tf] * 1000)

    request = ProtoOAGetTrendbarsReq(
        ctidTraderAccountId=get_demo_account_id(),
        symbolId=full_symbol_details['symbolId'],
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
        
        divisor = 10**full_symbol_details.get('digits', 5)
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
    from state import symbol_cache
    norm_pair = _normalize_pair(pair)
    
    base_symbol_info = symbol_cache.get(norm_pair)
    if not base_symbol_info:
        return defer.fail(Exception(f"Пара '{pair}' не знайдена в базовому кеші."))

    def on_details_loaded(full_symbol_details):
        d1 = get_market_data(client, norm_pair, '15min', 100, full_symbol_details)
        d2 = get_market_data(client, norm_pair, '1day', 100, full_symbol_details)
        d_list = defer.DeferredList([d1, d2], consumeErrors=True)
        d_list.addCallback(on_data_ready)
        return d_list

    def on_data_ready(results):
        success1, df = results[0]
        success2, daily_df = results[1]

        if not (success1 and success2):
            errors = []
            if not success1: errors.append(f"15min data failed ({results[0][1].getErrorMessage()})")
            if not success2: errors.append(f"1day data failed ({results[1][1].getErrorMessage()})")
            return {"error": f"Не вдалося завантажити ринкові дані: {', '.join(errors)}."}
        
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
        
        mta_data = _get_mta_signal_data()
        
        return { 
            "pair": pair, "price": analysis_result['price'], "verdict_text": verdict_text, 
            "verdict_level": verdict_level, "reasons": analysis_result['reasons'], 
            "support": analysis_result['support'], "resistance": analysis_result['resistance'], 
            "history": history,
            "mta": mta_data
        }

    details_deferred = get_full_symbol_details(client, base_symbol_info['symbolId'])
    details_deferred.addCallback(on_details_loaded)
    return details_deferred# analysis.py
import pandas as pd
import pandas_ta as ta
import numpy as np
import time
import logging
import random
from twisted.internet import defer

from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import ProtoMessage
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAGetTrendbarsReq, ProtoOAGetTrendbarsRes,
    ProtoOASymbolByIdReq # ДОДАНО
)
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOATrendbarPeriod as TrendbarPeriod

from db import add_signal_to_history
from config import get_demo_account_id

logger = logging.getLogger(__name__)
MARKET_DATA_CACHE = {}

def _normalize_pair(pair: str) -> str:
    return pair.replace("/", "").replace("\\", "").upper().strip()

def _get_mta_signal_data():
    """Імітує отримання сигналу мульти-таймфрейм аналізу (MTA)."""
    timeframes = ["15min", "1h", "4h", "1day"]
    signals = ["BUY", "SELL", "NEUTRAL"]
    return [{"tf": tf, "signal": random.choice(signals)} for tf in timeframes]

# --- ПОЧАТОК ФІНАЛЬНОГО ВИПРАВЛЕННЯ: Нова функція для отримання детальних даних ---
def get_full_symbol_details(client, symbol_id: int):
    """Робить запит на отримання повної інформації про символ за його ID."""
    from state import symbol_cache
    
    # Спочатку перевіряємо, чи є вже детальна інформація в кеші
    for details in symbol_cache.values():
        if details['symbolId'] == symbol_id and 'pipPosition' in details:
            logger.info(f"[ANALYSIS] Детальна інформація для symbolId {symbol_id} вже є в кеші.")
            return defer.succeed(details)
            
    d = defer.Deferred()
    request = ProtoOASymbolByIdReq(ctidTraderAccountId=get_demo_account_id(), symbolId=[symbol_id])
    
    # Тимчасово підписуємося на подію, щоб отримати відповідь
    def on_symbol_data(symbol_data):
        # Оновлюємо наш головний кеш
        norm_name = getattr(symbol_data, 'symbolName', '').replace("/", "").strip()
        if norm_name:
            symbol_cache[norm_name]['pipPosition'] = getattr(symbol_data, 'pipPosition', 5)
            symbol_cache[norm_name]['digits'] = getattr(symbol_data, 'digits', 5)
        
        # Видаляємо обробник, щоб уникнути дублювання
        client._events.get("symbolDataLoaded", []).remove(on_symbol_data)
        if not d.called:
            d.callback(symbol_cache[norm_name])

    client.on("symbolDataLoaded")(on_symbol_data)
    client.send(request)
    return d
# --- КІНЕЦЬ ФІНАЛЬНОГО ВИПРАВЛЕННЯ ---


def get_market_data(client, pair, tf, limit=300, full_symbol_details=None):
    norm_pair = _normalize_pair(pair)
    key = f"{norm_pair}_{tf}_{limit}"
    if key in MARKET_DATA_CACHE:
        d = defer.Deferred()
        d.callback(MARKET_DATA_CACHE[key])
        return d
        
    if not full_symbol_details:
        return defer.fail(Exception(f"Для {pair} відсутня детальна інформація про символ."))

    tf_map = {"15min": TrendbarPeriod.M15, "1h": TrendbarPeriod.H1, "4h": TrendbarPeriod.H4, "1day": TrendbarPeriod.D1}
    if tf not in tf_map:
        return defer.fail(Exception(f"Непідтримуваний таймфрейм: {tf}"))

    now = int(time.time() * 1000)
    seconds_per_bar = {'15min': 900, '1h': 3600, '4h': 14400, '1day': 86400}
    from_ts = now - (limit * seconds_per_bar[tf] * 1000)

    request = ProtoOAGetTrendbarsReq(
        ctidTraderAccountId=get_demo_account_id(),
        symbolId=full_symbol_details['symbolId'],
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
        
        # ВИПРАВЛЕНО: Використовуємо 'digits' з детальної інформації
        divisor = 10**full_symbol_details.get('digits', 5)
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
    from state import symbol_cache
    norm_pair = _normalize_pair(pair)
    
    base_symbol_info = symbol_cache.get(norm_pair)
    if not base_symbol_info:
        return defer.fail(Exception(f"Пара '{pair}' не знайдена в базовому кеші."))

    # --- ПОЧАТОК ФІНАЛЬНОГО ВИПРАВЛЕННЯ: Нова логіка з отриманням деталей ---
    def on_details_loaded(full_symbol_details):
        d1 = get_market_data(client, norm_pair, '15min', 100, full_symbol_details)
        d2 = get_market_data(client, norm_pair, '1day', 100, full_symbol_details)
        d_list = defer.DeferredList([d1, d2], consumeErrors=True)
        d_list.addCallback(on_data_ready)
        return d_list

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
        
        mta_data = _get_mta_signal_data()
        
        return { 
            "pair": pair, "price": analysis_result['price'], "verdict_text": verdict_text, 
            "verdict_level": verdict_level, "reasons": analysis_result['reasons'], 
            "support": analysis_result['support'], "resistance": analysis_result['resistance'], 
            "history": history,
            "mta": mta_data
        }

    # Запускаємо ланцюжок: спочатку деталі, потім дані
    details_deferred = get_full_symbol_details(client, base_symbol_info['symbolId'])
    details_deferred.addCallback(on_details_loaded)
    return details_deferred
    # --- КІНЕЦЬ ФІНАЛЬНОГО ВИПРАВЛЕННЯ ---