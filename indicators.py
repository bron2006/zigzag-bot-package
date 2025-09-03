# indicators.py
import pandas as pd
import numpy as np
import talib

def prime_indicators(df: pd.DataFrame) -> dict:
    """
    Розраховує початковий стан індикаторів на основі історичного DataFrame.
    Повертає словник зі станом, який можна оновлювати.
    """
    if df.empty or len(df) < 200:
        return {}

    close = df['Close'].values
    high = df['High'].values
    low = df['Low'].values

    # EMA
    ema50 = talib.EMA(close, timeperiod=50)
    ema200 = talib.EMA(close, timeperiod=200)

    # MACD
    macd, macdsignal, _ = talib.MACD(close, fastperiod=12, slowperiod=26, signalperiod=9)

    # RSI
    rsi = talib.RSI(close, timeperiod=14)
    # Для інкрементального RSI нам потрібен попередній середній ріст/падіння
    price_diff = df['Close'].diff(1)
    gains = price_diff.where(price_diff > 0, 0)
    losses = -price_diff.where(price_diff < 0, 0)
    avg_gain = gains.rolling(window=14).mean()
    avg_loss = losses.rolling(window=14).mean()

    state = {
        'last_close': close[-1],
        'ema50': ema50[-1],
        'ema200': ema200[-1],
        'macd': macd[-1],
        'macdsignal': macdsignal[-1],
        'rsi': rsi[-1],
        'avg_gain': avg_gain.iloc[-1],
        'avg_loss': avg_loss.iloc[-1]
    }
    # Видаляємо NaN, щоб не зберігати невалідний стан
    return {k: v for k, v in state.items() if pd.notna(v)}

def update_indicators(state: dict, new_close: float) -> dict:
    """
    Оновлює стан індикаторів на основі попереднього стану та нової ціни закриття.
    """
    if not state:
        return {}

    # --- EMA ---
    # формула: EMA = (Close - EMA_prev) * multiplier + EMA_prev
    state['ema50'] = (new_close - state['ema50']) * (2 / 51) + state['ema50']
    state['ema200'] = (new_close - state['ema200']) * (2 / 201) + state['ema200']

    # --- MACD ---
    # MACD потребує оновлення своїх двох базових EMA
    ema12_prev = (state['macd'] + state['macdsignal']) / (1 - (2/10))  # Приблизна інверсія
    ema26_prev = ema12_prev - state['macd']
    
    ema12 = (new_close - ema12_prev) * (2 / 13) + ema12_prev
    ema26 = (new_close - ema26_prev) * (2 / 27) + ema26_prev
    
    state['macd'] = ema12 - ema26
    state['macdsignal'] = (state['macd'] - state['macdsignal']) * (2 / 10) + state['macdsignal']

    # --- RSI ---
    change = new_close - state['last_close']
    gain = change if change > 0 else 0
    loss = -change if change < 0 else 0
    
    avg_gain = (state['avg_gain'] * 13 + gain) / 14
    avg_loss = (state['avg_loss'] * 13 + loss) / 14
    
    if avg_loss == 0:
        rs = 100
    else:
        rs = avg_gain / avg_loss
    
    state['rsi'] = 100 - (100 / (1 + rs))
    state['avg_gain'] = avg_gain
    state['avg_loss'] = avg_loss
    
    # Оновлюємо ціну для наступного розрахунку
    state['last_close'] = new_close

    return state