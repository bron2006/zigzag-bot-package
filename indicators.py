# indicators.py
import pandas as pd
import numpy as np
import talib
from typing import List, Tuple

# --- ІСНУЮЧА ЛОГІКА ---

def prime_indicators(df: pd.DataFrame) -> dict:
    """Розраховує початковий стан індикаторів на основі історичного DataFrame."""
    if df.empty or len(df) < 200:
        return {}
    close = df['Close'].values
    state = {
        'last_close': close[-1],
        'ema50': talib.EMA(close, 50)[-1],
        'ema200': talib.EMA(close, 200)[-1],
        'rsi': talib.RSI(close, 14)[-1],
        'adx': talib.ADX(df['High'].values, df['Low'].values, close, 14)[-1],
    }
    macd, macdsignal, _ = talib.MACD(close, 12, 26, 9)
    state['macd'] = macd[-1]
    state['macdsignal'] = macdsignal[-1]
    return {k: v for k, v in state.items() if pd.notna(v)}

def update_indicators(state: dict, candle: dict) -> dict:
    """Оновлює стан індикаторів на основі попереднього стану та нової свічки."""
    if not state: return {}
    new_close = candle['close']
    # EMA
    state['ema50'] = (new_close - state['ema50']) * (2 / 51) + state['ema50']
    state['ema200'] = (new_close - state['ema200']) * (2 / 201) + state['ema200']
    # MACD (спрощене оновлення, для точності потрібен повний стан EMA)
    ema12 = (state['macd'] + state['macdsignal']) * 4.5
    ema26 = ema12 - state['macd']
    new_ema12 = (new_close - ema12) * (2 / 13) + ema12
    new_ema26 = (new_close - ema26) * (2 / 27) + ema26
    state['macd'] = new_ema12 - new_ema26
    state['macdsignal'] = (state['macd'] - state['macdsignal']) * (2 / 10) + state['macdsignal']
    # RSI (потребує буфера, тому це оновлення є наближеним)
    # Точний інкрементальний RSI буде розрахований в процесорі з буфера
    return state

# --- ПОЧАТОК ЗМІН: Перенесено логіку аналізу з analysis.py ---

def _group_close_values(values: List[float], threshold=0.01) -> List[float]:
    if not values: return []
    s = pd.Series(sorted(values)).dropna()
    if s.empty: return []
    group_starts = s.pct_change() > threshold
    group_ids = group_starts.cumsum()
    return s.groupby(group_ids).mean().tolist()

def identify_support_resistance(df: pd.DataFrame, window=20) -> Tuple[List[float], List[float]]:
    """Пошук локальних екстремумів."""
    lows = df['Low'].rolling(window=window, center=True, min_periods=3).min()
    highs = df['High'].rolling(window=window, center=True, min_periods=3).max()
    support = _group_close_values(df.loc[df['Low'] == lows, 'Low'].tolist())
    resistance = _group_close_values(df.loc[df['High'] == highs, 'High'].tolist())
    return sorted(support), sorted(resistance, reverse=True)

def analyze_candle_patterns(df: pd.DataFrame):
    """Аналіз свічкових патернів на останній свічці."""
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
    """Аналіз об'єму на останній свічці."""
    if len(df) < 21 or 'Volume' not in df.columns: return "Недостатньо даних"
    vol_ma20 = df['Volume'].rolling(window=20).mean().iloc[-1]
    last_vol = df['Volume'].iloc[-1]
    if pd.isna(vol_ma20): return "Недостатньо даних"
    if last_vol > vol_ma20 * 1.5: return "🟢 Підвищений об'єм"
    if last_vol < vol_ma20 * 0.5: return "🧊 Аномально низький об'єм"
    return "Об'єм нейтральний"

def calculate_final_signal(state: dict, df: pd.DataFrame, daily_df: pd.DataFrame, current_price: float):
    """
    Основна логіка сигналу. Використовує актуальний стан індикаторів та історію свічок.
    """
    if len(df) < 50 or len(daily_df) < 2:
        return {"error": "Недостатньо даних для аналізу"}

    # Використовуємо точні значення з кешованого стану
    rsi_last = state.get('rsi', 50)
    macd_hist_last = state.get('macd', 0) - state.get('macdsignal', 0)
    adx_last = state.get('adx', 0)
    
    # Розраховуємо патерни та рівні з короткої історії
    candle_pattern = analyze_candle_patterns(df)
    volume_info = analyze_volume(df)
    supports, resistances = identify_support_resistance(daily_df)
    support = next((s for s in supports if s < current_price), None)
    resistance = next((r for r in resistances if r > current_price), None)
    
    # Визначаємо глобальний тренд по денній EMA200
    daily_ema200 = talib.EMA(daily_df['Close'].values, 200)[-1]
    is_daily_uptrend = current_price > daily_ema200

    bullish, bearish = 0, 0
    reasons = []

    if macd_hist_last > 0:
        bullish += 1; reasons.append("MACD росте")
    else:
        bearish += 1; reasons.append("MACD падає")

    if rsi_last < 30:
        bullish += 1; reasons.append("Перепроданість (RSI)")
    elif rsi_last > 70:
        bearish += 1; reasons.append("Перекупленість (RSI)")

    if candle_pattern:
        reasons.append(candle_pattern['text'])
        if candle_pattern['type'] == 'bullish': bullish += 1
        elif candle_pattern['type'] == 'bearish': bearish += 1

    if adx_last > 25:
        reasons.append(f"Сильний тренд (ADX {adx_last:.0f})")

    # Логіка прийняття рішення
    score = 50
    if is_daily_uptrend:
        score += 20 * bullish - 10 * bearish
    else:
        score += 10 * bullish - 20 * bearish
    
    # Коригування за екстремальними значеннями
    if rsi_last > 75 and score > 60: score = 60
    if rsi_last < 25 and score < 40: score = 40
    
    score = int(np.clip(score, 0, 100))

    verdict = "🟡 НЕЙТРАЛЬНО"
    if score > 80: verdict = "⬆️ Сильна ПОКУПКА"
    elif score > 65: verdict = "↗️ Помірна ПОКУПКА"
    elif score < 20: verdict = "⬇️ Сильний ПРОДАЖ"
    elif score < 35: verdict = "↘️ Помірний ПРОДАЖ"
    
    return {
        "price": current_price,
        "verdict_text": verdict,
        "reasons": reasons,
        "support": support,
        "resistance": resistance,
        "bull_percentage": score,
        "bear_percentage": 100 - score,
        "candle_pattern": candle_pattern,
        "volume_info": volume_info
    }
# --- КІНЕЦЬ ЗМІН ---