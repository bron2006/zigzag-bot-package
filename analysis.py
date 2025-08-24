import logging
import pandas as pd
import pandas_ta as ta
import numpy as np
import time
from twisted.internet.defer import Deferred, DeferredList
from twisted.internet import reactor

from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAGetTrendbarsReq, ProtoOAGetTrendbarsRes,
    ProtoOASubscribeSpotsReq, ProtoOAUnsubscribeSpotsReq
)
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOATrendbarPeriod as TrendbarPeriod
from db import add_signal_to_history

logger = logging.getLogger(__name__)

PERIOD_MAP = {
    "1m": TrendbarPeriod.M1, "5m": TrendbarPeriod.M5, "15m": TrendbarPeriod.M15,
    "1h": TrendbarPeriod.H1, "4h": TrendbarPeriod.H4, "1day": TrendbarPeriod.D1
}

def get_live_price(client, symbol_cache, norm_pair: str) -> Deferred:
    d = Deferred()
    symbol_details = symbol_cache.get(norm_pair)
    if not symbol_details:
        return Deferred.fail(Exception(f"Символ '{norm_pair}' не знайдено для live price."))
    
    symbol_id = symbol_details.symbolId
    account_id = client._client.account_id
    event_name = f"spot_event_{symbol_id}"
    
    timeout_call = None

    def cleanup():
        unsubscribe_req = ProtoOAUnsubscribeSpotsReq(ctidTraderAccountId=account_id, symbolId=[symbol_id])
        client.send(unsubscribe_req)
        client.remove_listener(event_name, on_spot_event)
        if timeout_call and not timeout_call.called:
            timeout_call.cancel()

    def on_spot_event(spot_event):
        logger.info(f"Live price received for {norm_pair}. Unsubscribing...")
        cleanup()
        
        if spot_event.HasField('bid') and spot_event.HasField('ask'):
            price = (spot_event.bid + spot_event.ask) / 2
            if not d.called: d.callback(price / (10**5))
        else:
            if not d.called: d.callback(None)

    def on_timeout():
        logger.warning(f"Live price request for {norm_pair} timed out. Market might be closed.")
        cleanup()
        if not d.called: d.callback(None)

    client.on(event_name, on_spot_event)
    timeout_call = reactor.callLater(5, on_timeout)

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
    seconds_per_bar = {'1m': 60, '5m': 300, '15m': 900, '1h': 3600, '4h': 14400, '1day': 86400}
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
            'Open': (bar.low + bar.deltaOpen) / divisor,
            'High': (bar.low + bar.deltaHigh) / divisor,
            'Low': bar.low / divisor,
            'Close': (bar.low + bar.deltaClose) / divisor,
            'Volume': bar.volume
        } for bar in response.trendbar]
        
        df = pd.DataFrame(bars)
        d.callback(df.sort_values(by='ts').reset_index(drop=True))

    def on_error(failure):
        err = failure.getErrorMessage() if hasattr(failure, 'getErrorMessage') else str(failure)
        logger.error(f"❌ Data request failed for {norm_pair} ({period}): {err}")
        d.errback(failure)

    deferred.addCallbacks(process_response, on_error)
    return d

def group_close_values(values, threshold=0.01):
    if not len(values):
        return []
    
    s = pd.Series(sorted(values)).dropna()
    if s.empty:
        return []
        
    group_starts = s.pct_change() > threshold
    group_ids = group_starts.cumsum()
    
    return s.groupby(group_ids).mean().tolist()

def identify_support_resistance_levels(df, window=20, threshold=0.01):
    try:
        lows = df['Low'].rolling(window=window, center=True, min_periods=3).min()
        highs = df['High'].rolling(window=window, center=True, min_periods=3).max()
        support_levels = group_close_values(df.loc[df['Low'] == lows, 'Low'].tolist(), threshold)
        resistance_levels = group_close_values(df.loc[df['High'] == highs, 'High'].tolist(), threshold)
        return sorted(support_levels), sorted(resistance_levels, reverse=True)
    except Exception as e:
        logger.error(f"Помилка в identify_support_resistance_levels: {e}")
        return [], []

def analyze_candle_patterns(df: pd.DataFrame):
    try:
        patterns = df.ta.cdl_pattern(name="all")
        if patterns.empty: return None
        last_candle = patterns.iloc[-1]
        found_patterns = last_candle[last_candle != 0]
        if found_patterns.empty: return None
        signal_strength = found_patterns.iloc[0]
        if abs(signal_strength) < 100:
            return None
        pattern_name = found_patterns.index[0].replace("CDL_", "")
        pattern_type = 'bullish' if signal_strength > 0 else 'bearish'
        arrow = '⬆️' if pattern_type == 'bullish' else '⬇️'
        text = f'{arrow} {pattern_name}'
        return {'name': pattern_name, 'type': pattern_type, 'text': text}
    except Exception as e:
        logger.error(f"Помилка в analyze_candle_patterns: {e}")
        return None

def analyze_volume(df):
    if df.empty or 'Volume' not in df.columns or len(df) < 21: return "Недостатньо даних"
    df['Volume_MA'] = df['Volume'].rolling(window=20).mean()
    last = df.iloc[-1]
    if pd.isna(last['Volume_MA']): return "Недостатньо даних"
    if last['Volume'] > last['Volume_MA'] * 1.5:
        return "🟢 Підвищений об'єм"
    elif last['Volume'] < last['Volume_MA'] * 0.5:
        return "🧊 Аномально низький об'єм"
    return "Об'єм нейтральний"

# --- ПОЧАТОК ЗМІН: Інтегруємо аналіз Хмари Ішимоку ---
def _calculate_core_signal(df, daily_df, current_price):
    # Розрахунок індикаторів
    df.ta.rsi(length=14, append=True, col_names=('RSI',))
    df.ta.kama(length=14, append=True, col_names=('KAMA',))
    bbands = df.ta.bbands(length=20, std=2, append=True)
    df.ta.ichimoku(append=True) # Розраховуємо Ішимоку

    last = df.iloc[-1]
    if pd.isna(last['RSI']) or pd.isna(last['KAMA']):
        raise ValueError("Помилка розрахунку базових індикаторів")

    support_levels, resistance_levels = identify_support_resistance_levels(daily_df)
    candle_pattern = analyze_candle_patterns(df)
    volume_info = analyze_volume(df)
    
    score = 50
    reasons = []
    
    # Фактор 1: KAMA
    if current_price > last['KAMA']: score += 10; reasons.append("Ціна вище KAMA(14)")
    else: score -= 10; reasons.append("Ціна нижче KAMA(14)")
    
    # Фактор 2: RSI
    rsi = float(last['RSI'])
    if rsi < 30: score += 15; reasons.append("RSI в зоні перепроданості (<30)")
    elif rsi > 70: score -= 15; reasons.append("RSI в зоні перекупленості (>70)")

    # Фактор 3: Смуги Боллінджера
    if 'BBL_20_2.0' in last and pd.notna(last['BBL_20_2.0']):
        if current_price <= last['BBL_20_2.0']:
            score += 15; reasons.append("Ціна на нижній смузі Боллінджера")
        elif current_price >= last['BBU_20_2.0']:
            score -= 15; reasons.append("Ціна на верхній смузі Боллінджера")

    # Фактор 4: Хмара Ішимоку
    tenkan = last.get('ITS_9')
    kijun = last.get('IKS_26')
    senkou_a = last.get('ISA_9')
    senkou_b = last.get('ISB_26')

    if pd.notna(senkou_a) and pd.notna(senkou_b):
        cloud_top = max(senkou_a, senkou_b)
        cloud_bottom = min(senkou_a, senkou_b)

        if current_price > cloud_top:
            score += 20; reasons.append("Ціна над Хмарою Ішимоку (сильний тренд вгору)")
        elif current_price < cloud_bottom:
            score -= 20; reasons.append("Ціна під Хмарою Ішимоку (сильний тренд вниз)")
        
        if senkou_a > senkou_b:
            score += 5; reasons.append("Висхідна Хмара (бичачий прогноз)")
        else:
            score -= 5; reasons.append("Низхідна Хмара (ведмежий прогноз)")

    if pd.notna(tenkan) and pd.notna(kijun):
        if tenkan > kijun:
            score += 10; reasons.append("Золотий хрест Ішимоку (Tenkan > Kijun)")
        else:
            score -= 10; reasons.append("Мертвий хрест Ішимоку (Tenkan < Kijun)")
            
    # Фактор 5: Рівні підтримки/опору
    if support_levels:
        dist_to_support = min(abs(current_price - sl) for sl in support_levels)
        if dist_to_support / current_price < 0.003:
            score += 15; reasons.append("Ціна ДУЖЕ близько до підтримки")
            
    if resistance_levels:
        dist_to_resistance = min(abs(current_price - rl) for rl in resistance_levels)
        if dist_to_resistance / current_price < 0.003:
            score -= 15; reasons.append("Ціна ДУЖЕ близько до опору")
            
    # Фактор 6: Об'єм
    if "Аномально низький" in volume_info:
        score = np.clip(score, 25, 75); reasons.append("Низький об'єм!")
        
    score = int(np.clip(score, 0, 100))
    support = min(support_levels, key=lambda x: abs(x - current_price)) if support_levels else None
    resistance = min(resistance_levels, key=lambda x: abs(x - current_price)) if resistance_levels else None
    
    return {
        "score": score, "reasons": reasons, "support": support, "resistance": resistance,
        "candle_pattern": candle_pattern, "volume_info": volume_info
    }
# --- КІНЕЦЬ ЗМІН ---

def _generate_verdict(score):
    if score > 65: return "⬆️ Strong BUY"
    if score > 55: return "↗️ Moderate BUY"
    if score < 35: return "⬇️ Strong SELL"
    if score < 45: return "↘️ Moderate SELL"
    return "🟡 NEUTRAL"

def get_api_detailed_signal_data(client, symbol_cache, symbol: str, user_id: int, timeframe: str = "15m") -> Deferred:
    def on_data_ready(results):
        try:
            success1, df = results[0]
            success2, daily_df = results[1]
            success3, live_price = results[2]

            if not (success1 and success2) or df.empty or len(df) < 50: # Збільшуємо вимогу до даних для Ішимоку
                logger.warning(f"Not enough historical data to analyze {symbol} on {timeframe}.")
                return {"error": f"Not enough historical data for {timeframe} analysis."}

            current_price = live_price if success3 and live_price is not None else df.iloc[-1]['Close']
            
            analysis = _calculate_core_signal(df, daily_df, current_price)
            
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
                "bear_percentage": 100 - analysis['score'],
                "candle_pattern": analysis.get('candle_pattern'),
                "volume_analysis": analysis.get('volume_info')
            }
            return response_data
            
        except Exception as e:
            logger.exception(f"Critical analysis error for {symbol}: {e}")
            return {"error": "Internal data processing error."}

    d1 = get_market_data(client, symbol_cache, symbol, timeframe, 200) # Запитуємо більше даних для Ішимоку
    d2 = get_market_data(client, symbol_cache, symbol, '1day', 100)
    d3 = get_live_price(client, symbol_cache, symbol)
    
    d_list = DeferredList([d1, d2, d3], consumeErrors=True)
    d_list.addCallback(on_data_ready)
    return d_list