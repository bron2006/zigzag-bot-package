# indicators.py
import pandas as pd
import numpy as np
import talib
from typing import List, Tuple

def prime_indicators(df: pd.DataFrame) -> dict:
    if df.empty or len(df) < 21:
        return {}
    close = df['Close'].values
    state = {
        'last_close': close[-1],
        'ema50': talib.EMA(close, 50)[-1] if len(close) >= 50 else None,
        'ema200': talib.EMA(close, 200)[-1] if len(close) >= 200 else None,
        'rsi': talib.RSI(close, 14)[-1] if len(close) >= 15 else None,
        'adx': talib.ADX(df['High'].values, df['Low'].values, close, 14)[-1] if len(close) >= 28 else None,
    }
    if len(close) >= 34:
        macd, macdsignal, _ = talib.MACD(close, 12, 26, 9)
        state['macd'] = macd[-1]
        state['macdsignal'] = macdsignal[-1]
    
    return {k: v for k, v in state.items() if pd.notna(v)}

def _group_close_values(values: List[float], threshold=0.01) -> List[float]:
    if not values: return []
    s = pd.Series(sorted(values)).dropna()
    if s.empty: return []
    group_starts = s.pct_change() > threshold
    group_ids = group_starts.cumsum()
    return s.groupby(group_ids).mean().tolist()

def identify_support_resistance(df: pd.DataFrame, window=20) -> Tuple[List[float], List[float]]:
    lows = df['Low'].rolling(window=window, center=True, min_periods=3).min()
    highs = df['High'].rolling(window=window, center=True, min_periods=3).max()
    support = _group_close_values(df.loc[df['Low'] == lows, 'Low'].tolist())
    resistance = _group_close_values(df.loc[df['High'] == highs, 'High'].tolist())
    return sorted(support), sorted(resistance, reverse=True)

def analyze_candle_patterns(df: pd.DataFrame):
    if len(df) < 2: return None
    open_v, high_v, low_v, close_v = df['Open'].values, df['High'].values, df['Low'].values, df['Close'].values
    patterns = {
        'HAMMER': talib.CDLHAMMER(open_v, high_v, low_v, close_v)[-1],
        'ENGULFING': talib.CDLENGULFING(open_v, high_v, low_v, close_v)[-1],
        'DOJI': talib.CDLDOJI(open_v, high_v, low_v, close_v)[-1],
    }
    for name, result in patterns.items():
        if result != 0:
            p_type = 'bullish' if result > 0 else 'bearish'
            arrow = '⬆️' if p_type == 'bullish' else '⬇️'
            return {'name': name, 'type': p_type, 'text': f"{arrow} {name}"}
    return None

def analyze_volume(df: pd.DataFrame):
    if len(df) < 21 or 'Volume' not in df.columns: return "Недостатньо даних"
    vol_ma20 = df['Volume'].rolling(window=20).mean().iloc[-1]
    last_vol = df['Volume'].iloc[-1]
    if pd.isna(vol_ma20): return "Недостатньо даних"
    if last_vol > vol_ma20 * 1.5: return "🟢 Підвищений об'єм"
    if last_vol < vol_ma20 * 0.5: return "🧊 Аномально низький об'єм"
    return "Об'єм нейтральний"

def calculate_final_signal(state: dict, df: pd.DataFrame, daily_df: pd.DataFrame, current_price: float):
    if len(df) < 21 or len(daily_df) < 2:
        return {"error": "Недостатньо даних для аналізу"}

    rsi_last = state.get('rsi', 50)
    macd_hist_last = state.get('macd', 0) - state.get('macdsignal', 0)
    adx_last = state.get('adx', 0)
    
    candle_pattern = analyze_candle_patterns(df)
    volume_info = analyze_volume(df)
    supports, resistances = identify_support_resistance(daily_df)
    support = next((s for s in supports if s < current_price), None)
    resistance = next((r for r in resistances if r > current_price), None)
    
    daily_ema200 = talib.EMA(daily_df['Close'].values, 200)[-1] if len(daily_df) >= 200 else None
    is_daily_uptrend = current_price > daily_ema200 if daily_ema200 is not None else None

    bullish, bearish = 0, 0
    reasons = []

    if macd_hist_last > 0: bullish += 1; reasons.append("MACD росте")
    else: bearish += 1; reasons.append("MACD падає")
    if rsi_last < 30: bullish += 1; reasons.append("Перепроданість (RSI)")
    elif rsi_last > 70: bearish += 1; reasons.append("Перекупленість (RSI)")
    if candle_pattern:
        reasons.append(candle_pattern['text'])
        if candle_pattern['type'] == 'bullish': bullish += 1
        elif candle_pattern['type'] == 'bearish': bearish += 1
    if adx_last > 25: reasons.append(f"Сильний тренд (ADX {adx_last:.0f})")

    score = 50
    if is_daily_uptrend is True: score += 20 * bullish - 10 * bearish
    elif is_daily_uptrend is False: score += 10 * bullish - 20 * bearish
    else: score += 10 * (bullish - bearish)
    
    if rsi_last > 75 and score > 60: score = 60
    if rsi_last < 25 and score < 40: score = 40
    
    score = int(np.clip(score, 0, 100))
    verdict = "🟡 НЕЙТРАЛЬНО"
    if score > 80: verdict = "⬆️ Сильна ПОКУПКА"
    elif score > 65: verdict = "↗️ Помірна ПОКУПКА"
    elif score < 20: verdict = "⬇️ Сильний ПРОДАЖ"
    elif score < 35: verdict = "↘️ Помірний ПРОДАЖ"
    
    return {
        "price": current_price, "verdict_text": verdict, "reasons": reasons, "support": support,
        "resistance": resistance, "bull_percentage": score, "bear_percentage": 100 - score,
        "candle_pattern": candle_pattern, "volume_info": volume_info
    }