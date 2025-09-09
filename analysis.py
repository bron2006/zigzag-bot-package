# analysis.py
import logging
import pandas as pd
import pandas_ta as ta
import numpy as np
import time
from typing import Optional, Dict, List

from twisted.internet.defer import Deferred, DeferredList
from twisted.internet import reactor

from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAGetTrendbarsReq, ProtoOAGetTrendbarsRes
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOATrendbarPeriod as TrendbarPeriod

from db import add_signal_to_history
from state import app_state

logger = logging.getLogger("analysis")

PERIOD_MAP = {
    "1m": TrendbarPeriod.M1, "5m": TrendbarPeriod.M5, "15m": TrendbarPeriod.M15, "1h": TrendbarPeriod.H1, "4h": TrendbarPeriod.H4, "1day": TrendbarPeriod.D1
}

def _sanitize(value, default=0.0):
    """Перетворює невалідні числові значення на безпечний float."""
    if value is None or pd.isna(value) or np.isinf(value):
        return default
    return float(value)

def get_market_data(client, symbol_cache, norm_pair: str, period: str, count: int) -> Deferred:
    d = Deferred()
    symbol_details = symbol_cache.get(norm_pair)
    if not symbol_details:
        return d.errback(Exception(f"Пара '{norm_pair}' не знайдена в кеші."))
        
    tf_proto = PERIOD_MAP.get(period)
    if not tf_proto:
        return d.errback(Exception(f"Непідтримуваний таймфрейм: {period}"))

    now = int(time.time() * 1000)
    seconds_in_period = {'1m': 60, '5m': 300, '15m': 900, '1h': 3600, '4h': 14400, '1day': 86400}.get(period, 300)
    from_ts = now - (count * seconds_in_period * 1000)
    
    request = ProtoOAGetTrendbarsReq(ctidTraderAccountId=client._client.account_id, symbolId=symbol_details.symbolId, period=tf_proto, fromTimestamp=from_ts, toTimestamp=now)
    
    deferred = client.send(request, timeout=30)
    
    def process_response(message):
        try:
            response = ProtoOAGetTrendbarsRes(); response.ParseFromString(message.payload)
            logger.info(f"✅ Received {len(response.trendbar)} candles for {norm_pair} ({period}).")
            if not response.trendbar: return d.callback(pd.DataFrame())
            divisor = 10**5
            bars = [{'ts': pd.to_datetime(bar.utcTimestampInMinutes * 60, unit='s', utc=True), 'Open': (bar.low + bar.deltaOpen) / divisor, 'High': (bar.low + bar.deltaHigh) / divisor, 'Low': bar.low / divisor, 'Close': (bar.low + bar.deltaClose) / divisor, 'Volume': bar.volume} for bar in response.trendbar]
            df = pd.DataFrame(bars); d.callback(df.sort_values(by='ts').reset_index(drop=True))
        except Exception as e: d.errback(e)

    deferred.addCallbacks(process_response, d.errback)
    return d

def _find_candle_pattern(df: pd.DataFrame):
    """Простий аналіз свічкових патернів, як радив експерт."""
    try:
        # pandas-ta має вбудовану функцію для пошуку всіх патернів
        patterns = df.ta.cdl_pattern(name="all")
        if patterns.empty: return None
        
        last_candle_patterns = patterns.iloc[-1]
        found_patterns = last_candle_patterns[last_candle_patterns != 0]
        
        if found_patterns.empty: return None
        
        # Беремо перший знайдений патерн
        pattern_name = found_patterns.index[0].replace("CDL_", "")
        signal_strength = found_patterns.iloc[0]
        
        if "DOJI" in pattern_name.upper(): return f"⚪️ {pattern_name} (Нейтральний)"
        if signal_strength > 0: return f"⬆️ {pattern_name} (Бичачий)"
        if signal_strength < 0: return f"⬇️ {pattern_name} (Ведмежий)"
        
        return None
    except Exception:
        return None # Помилка не є критичною

def _calculate_full_analysis(signal_df: pd.DataFrame, trend_df: pd.DataFrame, daily_df: pd.DataFrame) -> Dict:
    if any(df.empty or len(df) < 50 for df in [signal_df, trend_df, daily_df]):
        return {"verdict": "NEUTRAL", "reasons": ["Недостатньо даних для аналізу."]}

    try:
        # --- Розрахунок індикаторів ---
        signal_df.ta.bbands(length=20, std=2.0, append=True)
        signal_df.ta.stoch(k=14, d=3, smooth_k=3, append=True)
        signal_df.ta.rsi(length=14, append=True)
        signal_df.ta.adx(length=14, append=True)
        signal_df.ta.atr(length=14, append=True)
        trend_df.ta.ema(length=50, append=True, col_names=('EMA50',))
        trend_df.ta.ema(length=200, append=True, col_names=('EMA200',))
    except Exception as e:
        logger.error(f"Помилка розрахунку індикаторів: {e}")
        return {"verdict": "NEUTRAL", "reasons": ["Помилка розрахунку індикаторів."]}

    # --- Отримання останніх даних ---
    last_signal = signal_df.iloc[-1]
    last_trend = trend_df.iloc[-1]
    prev_day = daily_df.iloc[-2] # Для Pivot Points

    # --- 1. Фільтр сили тренду (ADX) ---
    adx = last_signal.get('ADX_14', 0)
    if adx < 15:
        # Якщо ринок "боковий", не генеруємо сигналів
        return {"verdict": "NEUTRAL (Боковий ринок)", "reasons": [f"ADX ({adx:.1f}) < 15, ринок занадто слабкий."]}

    # --- 2. Визначення глобального тренду (EMA 50/200) ---
    trend = "NEUTRAL"
    trend_strength = "Weak"
    if last_trend.get('EMA50') > last_trend.get('EMA200'):
        trend = "UPTREND"
        if adx > 25: trend_strength = "Strong"
    elif last_trend.get('EMA50') < last_trend.get('EMA200'):
        trend = "DOWNTREND"
        if adx > 25: trend_strength = "Strong"

    # --- 3. Розрахунок рівнів Підтримки/Опору (Pivot Points) ---
    pivot_high = prev_day['High']
    pivot_low = prev_day['Low']
    pivot_close = prev_day['Close']
    pivot_point = (pivot_high + pivot_low + pivot_close) / 3
    support = (2 * pivot_point) - pivot_high
    resistance = (2 * pivot_point) - pivot_low

    # --- 4. Аналіз об'єму ---
    current_volume = last_signal['Volume']
    avg_volume = signal_df['Volume'].rolling(window=20).mean().iloc[-1]
    is_volume_high = current_volume > avg_volume * 1.2
    
    # --- 5. Генерація вердикту та причин ---
    verdict = "NEUTRAL"
    reasons = []
    stoch_k = last_signal.get('STOCHk_14_3_3', 50)
    rsi = last_signal.get('RSI_14', 50)
    bb_p = last_signal.get('BBP_20_2.0', 0.5)

    # Сигнал CALL (Вгору)
    if trend == "UPTREND" and stoch_k < 30 and rsi < 50 and bb_p < 0.15:
        verdict = "⬆️ CALL (Сильний)"
        reasons = ["Глобальний тренд висхідний", "Stochastic + RSI вказують на перепроданість", "Ціна в нижній зоні Боллінджера"]
        if is_volume_high: reasons.append("🟢 Підтверджено об'ємом")

    # Сигнал PUT (Вниз)
    elif trend == "DOWNTREND" and stoch_k > 70 and rsi > 50 and bb_p > 0.85:
        verdict = "⬇️ PUT (Сильний)"
        reasons = ["Глобальний тренд низхідний", "Stochastic + RSI вказують на перекупленість", "Ціна в верхній зоні Боллінджера"]
        if is_volume_high: reasons.append("🟢 Підтверджено об'ємом")

    # --- 6. Збір всіх даних для відповіді ---
    return {
        "verdict": verdict, "reasons": reasons, "close": last_signal.get('Close'),
        "rsi": rsi, "stoch_k": stoch_k, "stoch_d": last_signal.get('STOCHd_14_3_3'),
        "bb_upper": last_signal.get('BBU_20_2.0'), "bb_lower": last_signal.get('BBL_20_2.0'),
        "bb_percent_b": bb_p, "trend": f"{trend} ({trend_strength})", "support": support,
        "resistance": resistance, "volume_now": current_volume, "volume_avg": avg_volume,
        "volume_ratio": current_volume / avg_volume if avg_volume > 0 else 1,
        "candle_pattern": _find_candle_pattern(signal_df),
        "special_warning": None
    }

def get_api_detailed_signal_data(client, symbol_cache, symbol: str, user_id: int, timeframe: str = "5m") -> Deferred:
    final_deferred = Deferred()
    
    trend_timeframe_map = {"1m": "5m", "5m": "15m"}
    trend_timeframe = trend_timeframe_map.get(timeframe, "15m")

    d_signal = get_market_data(client, symbol_cache, symbol, timeframe, 200)
    d_trend = get_market_data(client, symbol_cache, symbol, trend_timeframe, 250)
    d_daily = get_market_data(client, symbol_cache, symbol, "1day", 50)
    d_list = DeferredList([d_signal, d_trend, d_daily], consumeErrors=True)

    def on_data_ready(results):
        try:
            success_signal, signal_df = results[0]
            success_trend, trend_df = results[1]
            success_daily, daily_df = results[2]

            if not (success_signal and success_trend and success_daily):
                final_deferred.callback({"error": "Не вдалося завантажити всі ринкові дані."})
                return

            signal_df.name = timeframe
            trend_df.name = trend_timeframe

            analysis = _calculate_full_analysis(signal_df, trend_df, daily_df)
            
            response_data = {
                "pair": symbol, "price": _sanitize(analysis.get("close")), "verdict_text": analysis["verdict"],
                "reasons": analysis["reasons"],
                "stochastic": {"k": _sanitize(analysis.get("stoch_k"), 50), "d": _sanitize(analysis.get("stoch_d"), 50)},
                "rsi": _sanitize(analysis.get("rsi"), 50),
                "bollinger": {"upper": _sanitize(analysis.get("bb_upper")), "lower": _sanitize(analysis.get("bb_lower")), "percent_b": _sanitize(analysis.get("bb_percent_b"), 0.5)},
                "trend": analysis.get("trend"), "support": _sanitize(analysis.get("support")), "resistance": _sanitize(analysis.get("resistance")),
                "volume": {"current": _sanitize(analysis.get("volume_now")), "avg": _sanitize(analysis.get("volume_avg")), "ratio": _sanitize(analysis.get("volume_ratio"))},
                "candle_pattern": analysis.get("candle_pattern"), "special_warning": analysis.get("special_warning")
            }
            
            if user_id != 0 and analysis['verdict'] != "NEUTRAL":
                add_signal_to_history({
                    'user_id': user_id, 'pair': symbol, 'price': response_data['price'], 
                    'bull_percentage': int(response_data['stochastic']['k'])
                })

            final_deferred.callback(response_data)
        except Exception as e:
            logger.exception(f"Critical analysis error for {symbol}: {e}")
            final_deferred.errback(e)

    d_list.addCallback(on_data_ready)
    return final_deferred