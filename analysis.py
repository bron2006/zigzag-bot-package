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
    if not len(values): return []
    s = pd.Series(sorted(values)).dropna()
    if s.empty: return []
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
        if abs(signal_strength) < 100: return None
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
    try:
        df['Volume_MA'] = df['Volume'].rolling(window=20).mean()
        last = df.iloc[-1]
        if pd.isna(last['Volume_MA']): return "Недостатньо даних"
        if last['Volume'] > last['Volume_MA'] * 1.5: return "🟢 Підвищений об'єм"
        elif last['Volume'] < last['Volume_MA'] * 0.5: return "🧊 Аномально низький об'єм"
        return "Об'єм нейтральний"
    except Exception: return "Помилка аналізу об'єму"

# --- ПОЧАТОК ЗМІН: Фінальна версія з ієрархічною логікою ---
def _calculate_core_signal(df, daily_df, current_price):
    score = 50
    reasons = []
    special_warning = None

    try:
        df.ta.rsi(length=14, append=True, col_names=('RSI',))
        df.ta.kama(length=14, append=True, col_names=('KAMA',))
        df.ta.bbands(length=20, std=2, append=True)
        df.ta.ichimoku(append=True)
        df.ta.macd(append=True)
        df.ta.adx(append=True)
    except Exception as e:
        logger.error(f"Критична помилка при розрахунку індикаторів: {e}")
        return { "score": 50, "reasons": ["Помилка розрахунку індикаторів"] }

    last = df.iloc[-1]
    
    # --- КРОК 1: Визначаємо стан ринку (флет чи ні) ---
    adx_value = last.get('ADX_14')
    if pd.notna(adx_value) and adx_value < 20:
        special_warning = "❗️❗️❗️ УВАГА: РИНОК \"БОКОВИЙ\" (ФЛЕТ) ❗️❗️❗️"
        reasons.append(f"ADX < 20 (тренд відсутній)")
        score = 50
    
    if special_warning: # Якщо ринок у флеті, подальший аналіз не потрібен
        return {"score": score, "reasons": reasons, "special_warning": special_warning}

    # --- КРОК 2: Якщо є тренд, проводимо повний аналіз ---
    long_term_support, long_term_resistance = identify_support_resistance_levels(daily_df)
    short_term_support, short_term_resistance = identify_support_resistance_levels(df, window=10)
    candle_pattern = analyze_candle_patterns(df)
    volume_info = analyze_volume(df)
    
    is_near_short_support = False
    if short_term_support:
        dist = min(abs(current_price - s) for s in short_term_support if s < current_price) if any(s < current_price for s in short_term_support) else float('inf')
        if dist / current_price < 0.002: is_near_short_support = True

    is_near_short_resistance = False
    if short_term_resistance:
        dist = min(abs(current_price - r) for r in short_term_resistance if r > current_price) if any(r > current_price for r in short_term_resistance) else float('inf')
        if dist / current_price < 0.002: is_near_short_resistance = True
    
    # 2.1 Пріоритет: Розворотні сигнали
    if candle_pattern and candle_pattern['type'] == 'bullish': score += 20; reasons.append(f"Бичачий патерн: {candle_pattern['name']}")
    if candle_pattern and candle_pattern['type'] == 'bearish': score -= 20; reasons.append(f"Ведмежий патерн: {candle_pattern['name']}")
    if is_near_short_support: score += 20; reasons.append("Ціна біля локальної підтримки")
    if is_near_short_resistance: score -= 20; reasons.append("Ціна біля локального опору")
    
    # 2.2 Імпульс
    main_trend_direction, impulse_direction = 0, 0
    if pd.notna(last.get('MACDh_12_26_9')) and len(df['MACDh_12_26_9']) >= 2:
        if last['MACDh_12_26_9'] > df['MACDh_12_26_9'].iloc[-2]:
            score += 15; reasons.append("Імпульс MACD росте"); impulse_direction = 1
        else:
            score -= 15; reasons.append("Імпульс MACD падає"); impulse_direction = -1
    
    # 2.3 Тренд
    if pd.notna(last.get('ISA_9')) and pd.notna(last.get('ISB_26')):
        cloud_top, cloud_bottom = max(last['ISA_9'], last['ISB_26']), min(last['ISA_9'], last['ISB_26'])
        if current_price > cloud_top: score += 15; reasons.append("Тренд: Ціна над Хмарою"); main_trend_direction = 1
        elif current_price < cloud_bottom: score -= 15; reasons.append("Тренд: Ціна під Хмарою"); main_trend_direction = -1
    
    # 2.4 Вторинні фактори
    rsi = last.get('RSI')
    bbl, bbu = last.get('BBL_20_2.0'), last.get('BBU_20_2.0')
    is_on_bbl = pd.notna(bbl) and current_price <= bbl
    is_on_bbu = pd.notna(bbu) and current_price >= bbu
    if pd.notna(rsi):
        if rsi < 30 or is_on_bbl: score += 10; reasons.append("Ознаки перепроданості (RSI/Bollinger)")
        elif rsi > 70 or is_on_bbu: score -= 10; reasons.append("Ознаки перекупленості (RSI/Bollinger)")

    # КРОК 3: Фінальні фільтри-конфлікти
    if (main_trend_direction * impulse_direction) == -1:
        reasons.append("⚠️ КОНФЛІКТ: Імпульс проти тренду!")
        score = int(score * 0.5 + 25) # Зміщуємо до центру

    if score < 35 and (rsi < 30 or is_on_bbl):
        reasons.append("❗️КОНФЛІКТ: Продаж при перепроданості!")
        score = 50

    if score > 65 and (rsi > 70 or is_on_bbu):
        reasons.append("❗️КОНФЛІКТ: Покупка при перекупленості!")
        score = 50
    
    score = int(np.clip(score, 0, 100))
    
    all_support = sorted(long_term_support + short_term_support)
    all_resistance = sorted(long_term_resistance + short_term_resistance)
    support_candidates = [s for s in all_support if s < current_price]
    support = max(support_candidates) if support_candidates else None
    resistance_candidates = [r for r in all_resistance if r > current_price]
    resistance = min(resistance_candidates) if resistance_candidates else None
    
    return {
        "score": score, "reasons": reasons, "support": support, "resistance": resistance,
        "candle_pattern": candle_pattern, "volume_info": analyze_volume(df),
        "special_warning": special_warning
    }
# --- КІНЕЦЬ ЗМІН ---

def _generate_verdict(score):
    if score > 75: return "⬆️ Strong BUY"
    if score > 55: return "↗️ Moderate BUY"
    if score < 25: return "⬇️ Strong SELL"
    if score < 45: return "↘️ Moderate SELL"
    return "🟡 NEUTRAL"

def get_api_detailed_signal_data(client, symbol_cache, symbol: str, user_id: int, timeframe: str = "15m") -> Deferred:
    def on_data_ready(results):
        try:
            success1, df = results[0]
            success2, daily_df = results[1]
            success3, live_price = results[2]

            if not (success1 and success2) or df.empty or len(df) < 50:
                return {"error": f"Not enough historical data for {timeframe} analysis."}

            current_price = live_price if success3 and live_price is not None else df.iloc[-1]['Close']
            
            analysis = _calculate_core_signal(df, daily_df, current_price)
            
            if analysis.get("special_warning"):
                verdict = "🟡 NEUTRAL"
            else:
                verdict = _generate_verdict(analysis['score'])

            add_signal_to_history({
                'user_id': user_id, 'pair': symbol, 
                'price': current_price, 'bull_percentage': analysis['score']
            })
            
            response_data = {
                "pair": symbol, "price": current_price, "verdict_text": verdict, 
                "reasons": analysis['reasons'], "support": analysis['support'], 
                "resistance": analysis['resistance'], "bull_percentage": analysis['score'],
                "bear_percentage": 100 - analysis['score'], "candle_pattern": analysis.get('candle_pattern'),
                "volume_analysis": analysis.get('volume_info'),
                "special_warning": analysis.get("special_warning")
            }
            return response_data
            
        except Exception as e:
            logger.exception(f"Critical analysis error for {symbol}: {e}")
            return {"error": "Internal data processing error."}

    d1 = get_market_data(client, symbol_cache, symbol, timeframe, 200)
    d2 = get_market_data(client, symbol_cache, symbol, '1day', 100)
    d3 = get_live_price(client, symbol_cache, symbol)
    
    d_list = DeferredList([d1, d2, d3], consumeErrors=True)
    d_list.addCallback(on_data_ready)
    return d_list