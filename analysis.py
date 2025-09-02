# analysis.py
import logging
import pandas as pd
import pandas_ta as ta
import numpy as np
import time
from twisted.internet.defer import Deferred, DeferredList
from twisted.internet import reactor, error as terror

from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAGetTrendbarsReq, ProtoOAGetTrendbarsRes, ProtoOASubscribeSpotsReq, ProtoOASymbolsListReq
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOATrendbarPeriod as TrendbarPeriod
from db import add_signal_to_history
import state

logger = logging.getLogger(__name__)

PERIOD_MAP = {
    "1m": TrendbarPeriod.M1, "5m": TrendbarPeriod.M5, "15m": TrendbarPeriod.M15,
    "1h": TrendbarPeriod.H1, "4h": TrendbarPeriod.H4, "1day": TrendbarPeriod.D1
}

def _send_with_retry(client, request, timeout=60, retries=1):
    d = Deferred()
    def _attempt(remaining):
        inner = client.send(request, timeout=timeout)
        def ok(msg):
            if not d.called: d.callback(msg)
        def err(f):
            if f.check(terror.TimeoutError) and remaining > 0:
                reactor.callLater(0.2, _attempt, remaining - 1)
            else:
                if not d.called: d.errback(f)
        inner.addCallbacks(ok, err)
    _attempt(retries)
    return d

# --- ПОЧАТОК ЗМІН: Повністю переписано функцію get_live_price ---
def get_live_price(client, symbol_cache, norm_pair: str) -> float:
    """
    Отримує останню ціну з кешу. Якщо на символ ще немає підписки, створює її.
    """
    # 1. Перевіряємо, чи є ціна вже в кеші
    last_price = state.live_price_cache.get(norm_pair)
    if last_price:
        return last_price

    # 2. Якщо ціни немає, перевіряємо, чи є вже активна підписка
    if norm_pair in state.active_subscriptions:
        logger.warning(f"Subscription for {norm_pair} exists, but no price in cache yet.")
        return None

    # 3. Якщо немає ні ціни, ні підписки - створюємо нову
    logger.info(f"No price for {norm_pair}. Creating persistent subscription...")
    symbol_details = symbol_cache.get(norm_pair)
    if not symbol_details:
        logger.error(f"Symbol '{norm_pair}' not found for live price subscription.")
        return None

    subscribe_req = ProtoOASubscribeSpotsReq(ctidTraderAccountId=client.account_id, symbolId=[symbol_details.symbolId])
    client.send(subscribe_req)
    state.active_subscriptions.add(norm_pair)
    logger.info(f"Subscription for {norm_pair} sent. Total subscriptions: {len(state.active_subscriptions)}")
    
    # Для першого запиту повертаємо None. Аналізатор використає ціну закриття.
    return None
# --- КІНЕЦЬ ЗМІН ---

def get_market_data(client, symbol_cache, norm_pair: str, period: str, count: int) -> Deferred:
    d = Deferred()
    symbol_details = symbol_cache.get(norm_pair)
    if not symbol_details:
        return d.errback(Exception(f"Пара '{norm_pair}' не знайдена в кеші."))
    tf_proto = PERIOD_MAP.get(period)
    if not tf_proto:
        return d.errback(Exception(f"Непідтримуваний таймфрейм: {period}"))
    now = int(time.time() * 1000)
    seconds_per_bar = {'1m': 60, '5m': 300, '15m': 900, '1h': 3600, '4h': 14400, '1day': 86400}
    from_ts = now - (count * seconds_per_bar[period] * 1000)
    request = ProtoOAGetTrendbarsReq(ctidTraderAccountId=client.account_id, symbolId=symbol_details.symbolId, period=tf_proto, fromTimestamp=from_ts, toTimestamp=now)
    deferred = _send_with_retry(client, request, timeout=60, retries=1)
    def process_response(message):
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
    deferred.addCallback(process_response)
    return d

def group_close_values(values, threshold=0.01):
    if not values: return []
    s = pd.Series(sorted(values)).dropna()
    if s.empty: return []
    group_ids = (s.pct_change() > threshold).cumsum()
    return s.groupby(group_ids).mean().tolist()

def identify_support_resistance_levels(df, window=20, threshold=0.01):
    try:
        lows = df['Low'].rolling(window=window, center=True, min_periods=3).min()
        highs = df['High'].rolling(window=window, center=True, min_periods=3).max()
        return group_close_values(df.loc[df['Low'] == lows, 'Low'].tolist(), threshold), group_close_values(df.loc[df['High'] == highs, 'High'].tolist(), threshold)
    except Exception:
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
        return {'name': pattern_name, 'type': pattern_type, 'text': f"{'⬆️' if pattern_type == 'bullish' else '⬇️'} {pattern_name}"}
    except Exception:
        return None

def analyze_volume(df):
    if len(df) < 21: return "Недостатньо даних"
    try:
        df['Volume_MA'] = df['Volume'].rolling(window=20).mean()
        last = df.iloc[-1]
        if pd.isna(last['Volume_MA']): return "Недостатньо даних"
        if last['Volume'] > last['Volume_MA'] * 1.5: return "🟢 Підвищений об'єм"
        if last['Volume'] < last['Volume_MA'] * 0.5: return "🧊 Аномально низький об'єм"
        return "Об'єм нейтральний"
    except Exception: return "Помилка аналізу об'єму"

def _calculate_core_signal(df, daily_df, current_price):
    try:
        df.ta.rsi(length=14, append=True)
        df.ta.macd(append=True)
        df.ta.atr(length=14, append=True)
        daily_df.ta.kama(length=14, append=True, col_names=('KAMA_14',))
        df.ta.ichimoku(append=True)
    except Exception:
        return { "score": 50, "reasons": ["Помилка розрахунку індикаторів"] }
    last = df.iloc[-1]
    last_daily = daily_df.iloc[-1]
    score = 50
    reasons = []
    critical_warning = None
    is_daily_uptrend = last_daily['Close'] > last_daily['KAMA_14'] if pd.notna(last_daily.get('KAMA_14')) else None
    
    if pd.notna(last.get('MACDh_12_26_9')):
        if last['MACDh_12_26_9'] > 0: score += 15; reasons.append("MACD росте")
        else: score -= 15; reasons.append("MACD падає")
    if pd.notna(last.get('ISA_9')) and pd.notna(last.get('ISB_26')):
        if current_price > max(last['ISA_9'], last['ISB_26']): score += 15; reasons.append("Тренд: Ціна над Хмарою")
        else: score -= 15; reasons.append("Тренд: Ціна під Хмарою")

    candle_pattern = analyze_candle_patterns(df)
    if candle_pattern:
        pattern_name = candle_pattern['name'].upper()
        if not any(neutral in pattern_name for neutral in ["SPINNINGTOP", "DOJI", "DOJISTAR", "SHORTLINE", "HIGHWAVE", "HARAMI"]):
            if candle_pattern['type'] == 'bullish': score += 20; reasons.append(f"Бичачий патерн: {candle_pattern['name']}")
            else: score -= 20; reasons.append(f"Ведмежий патерн: {candle_pattern['name']}")

    rsi = last.get('RSI_14')
    if pd.notna(rsi):
        if rsi < 30: score += 10; reasons.append("Ознаки перепроданості (RSI)")
        elif rsi > 70: reasons.append("Ознаки перекупленості (RSI)")
    
    if is_daily_uptrend is not None:
        if not is_daily_uptrend and score > 50: critical_warning = "❗️ Сигнал суперечить денному даунтренду"; score = 50
        elif is_daily_uptrend and score < 50: critical_warning = "❗️ Сигнал суперечить денному аптренду"; score = 50
    
    score = int(np.clip(score, 0, 100))
    support, resistance = identify_support_resistance_levels(daily_df)
    
    if pd.notna(rsi):
        if score > 80 and rsi > 75: critical_warning = "❗️ Сигнал скасовано: сильна перекупленість (RSI > 75)"; score = 50
        elif score < 20 and rsi < 25: critical_warning = "❗️ Сигнал скасовано: сильна перепроданість (RSI < 25)"; score = 50

    return {"score": score, "reasons": reasons, "support": next((s for s in reversed(support) if s < current_price), None),
            "resistance": next((r for r in reversed(resistance) if r > current_price), None), "candle_pattern": candle_pattern,
            "volume_info": analyze_volume(df), "critical_warning": critical_warning}

def _generate_verdict(score):
    if score > 80: return "⬆️ Сильна ПОКУПКА"
    if score > 65: return "↗️ Помірна ПОКУПКА"
    if score < 20: return "⬇️ Сильний ПРОДАЖ"
    if score < 35: return "↘️ Помірний ПРОДАЖ"
    return "🟡 НЕЙТРАЛЬНО"

def get_api_detailed_signal_data(client, symbol_cache, symbol: str, user_id: int, timeframe: str = "15m") -> Deferred:
    final_deferred = Deferred()
    def on_data_ready(results):
        try:
            success1, df = results[0]
            success2, daily_df = results[1]
            if not (success1 and success2) or len(df) < 50 or daily_df.empty:
                return final_deferred.callback({"error": f"Not enough historical data for {timeframe}."})
            
            # --- ПОЧАТОК ЗМІН: Змінено логіку отримання ціни ---
            live_price = get_live_price(client, symbol_cache, symbol)
            current_price = live_price if live_price is not None else df.iloc[-1]['Close']
            # --- КІНЕЦЬ ЗМІН ---

            analysis = _calculate_core_signal(df, daily_df, current_price)
            verdict = _generate_verdict(analysis['score'])
            add_signal_to_history({'user_id': user_id, 'pair': symbol, 'price': current_price, 'bull_percentage': analysis['score']})
            response_data = {"pair": symbol, "price": current_price, "verdict_text": verdict, **analysis}
            final_deferred.callback(response_data)
        except Exception as e:
            logger.exception(f"Analysis error for {symbol}: {e}")
            final_deferred.errback(e)
    d1 = get_market_data(client, symbol_cache, symbol, timeframe, 200)
    d2 = get_market_data(client, symbol_cache, symbol, '1day', 100)
    # --- ПОЧАТОК ЗМІН: Видалено Deferred для live_price ---
    DeferredList([d1, d2], consumeErrors=True).addCallback(on_data_ready)
    # --- КІНЕЦЬ ЗМІН ---
    return final_deferred