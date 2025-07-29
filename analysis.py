# analysis.py
import pandas as pd
import pandas_ta as ta
from datetime import datetime, time
from concurrent.futures import ThreadPoolExecutor

from config import logger, binance, td, PAIR_ACTIVE_HOURS, ANALYSIS_TIMEFRAMES

def get_market_data(pair, tf, asset, limit=300):
    """Отримує ринкові дані без кешування."""
    try:
        if asset == 'crypto':
            bars = binance.fetch_ohlcv(pair, timeframe=tf, limit=limit)
            df = pd.DataFrame(bars, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
            df['ts'] = pd.to_datetime(df['ts'], unit='ms', utc=True)
            return df.rename(columns={'o': 'Open', 'h': 'High', 'l': 'Low', 'c': 'Close', 'v': 'Volume'})
        
        if asset in ('forex', 'stocks'):
            td_tf_map = {'1m': '1min', '5m': '5min', '15m': '15min', '1h': '1hour', '4h': '4hour', '1d': '1day'}
            ts = td.time_series(symbol=pair, interval=td_tf_map.get(tf), outputsize=limit)
            df = ts.as_pandas()
            if not df.empty:
                # Перетворюємо індекс на стовпець "ts" для сумісності
                df = df.reset_index()
                df = df.rename(columns={'index': 'ts'})
                return df.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'volume': 'Volume'})
        return pd.DataFrame()
    except Exception as e:
        logger.error(f"Помилка отримання даних для {pair}: {e}")
        return pd.DataFrame()

def _calculate_core_signal(df):
    """Розраховує базовий сигнал на основі RSI."""
    df.ta.rsi(length=14, append=True, col_names=('RSI',))
    last = df.iloc[-1]
    if pd.isna(last['RSI']): raise ValueError("Не вдалося розрахувати RSI")
    
    score = 50
    rsi = float(last['RSI'])
    if rsi < 35: score += 15
    elif rsi > 65: score -= 15

    # Додаємо додаткові фактори для деталізації
    reasons = []
    if rsi < 30: reasons.append("RSI в зоні перепроданості")
    elif rsi > 70: reasons.append("RSI в зоні перекупленості")

    # Простий приклад підтримки/опору (можна розширити)
    support = df['Low'].min()
    resistance = df['High'].max()

    # Простий приклад об'єму
    volume_info = "Низький"
    if df['Volume'].iloc[-1] > df['Volume'].mean():
        volume_info = "Високий"

    # Простий приклад патерну свічки (можна розширити)
    candle_pattern = {"text": "Немає вираженого патерну"}

    return {
        "score": int(score),
        "price": float(last['Close']),
        "reasons": reasons,
        "support": support,
        "resistance": resistance,
        "candle_pattern": candle_pattern,
        "volume_info": volume_info
    }

def get_api_detailed_signal_data(pair, timeframe='1m', user_id=None, force_refresh=False):
    """Головна функція для отримання детального сигналу для API та бота."""
    asset = 'crypto' if 'USDT' in pair else ('forex' if '/' in pair else 'stocks')
    
    # Кешування прибрано, дані завжди отримуються заново
    df = get_market_data(pair, timeframe, asset)

    if df.empty or len(df) < 20:
        return {"error": "Недостатньо даних для аналізу."}

    try:
        analysis = _calculate_core_signal(df)
        score = analysis['score']
        verdict_text = "Нейтрально"
        verdict_level = "neutral"
        if score > 55:
            verdict_text = "Сигнал на покупку"
            verdict_level = "buy"
        elif score < 45:
            verdict_text = "Сигнал на продаж"
            verdict_level = "sell"

        # Додаємо запис в історію, якщо є user_id
        if user_id:
            from db import add_signal_to_history # Імпортуємо тут, щоб уникнути циклічної залежності
            add_signal_to_history({
                "user_id": user_id,
                "pair": pair,
                "price": analysis['price'],
                "bull_percentage": score # Використовуємо score як bull_percentage
            })

        return {
            "pair": pair,
            "price": analysis['price'],
            "timeframe": timeframe,
            "verdict_text": verdict_text,
            "verdict_level": verdict_level,
            "reasons": analysis.get('reasons', []),
            "support": analysis.get('support'),
            "resistance": analysis.get('resistance'),
            "candle_pattern": analysis.get('candle_pattern'),
            "volume_info": analysis.get('volume_info'),
            "history": { # Повертаємо дані для графіка
                "dates": df['ts'].dt.strftime('%Y-%m-%d %H:%M:%S').tolist(),
                "open": df['Open'].tolist(),
                "high": df['High'].tolist(),
                "low": df['Low'].tolist(),
                "close": df['Close'].tolist()
            }
        }
    except Exception as e:
        logger.error(f"Помилка генерації сигналу для {pair}: {e}")
        return {"error": "Помилка аналізу."}

# --- Функції, які ВИКЛИКАЮТЬСЯ з bot.py та telegram_ui.py ---

def get_signal_strength_verdict(pair, display_name, asset_type, timeframe='1m', user_id=None, force_refresh=False):
    """
    Функція для отримання вердикту сили сигналу для Telegram бота.
    Ця функція тепер просто обгортка для get_api_detailed_signal_data.
    """
    signal_data = get_api_detailed_signal_data(pair, timeframe, user_id, force_refresh)

    if signal_data.get("error"):
        return f"❌ Помилка: {signal_data['error']}", None

    verdict_text = signal_data['verdict_text']
    price = signal_data['price']
    score = signal_data.get('bull_percentage', 50) # Використовуємо score як bull_percentage

    msg = (
        f"*{display_name}* ({signal_data['timeframe']})\n"
        f"Ціна: `{price:.4f}`\n"
        f"Сигнал: *{verdict_text}* (Сила: {score}%)"
    )
    return msg, signal_data

def get_full_mta_verdict(pair, display_name, asset_type, force_refresh=False):
    """
    Функція для отримання детального MTA аналізу для Telegram бота.
    Наразі повертає заглушку, оскільки MTA логіка не реалізована.
    """
    # Ми не маємо реальної MTA логіки, тому повертаємо заглушку
    logger.info(f"Викликано get_full_mta_verdict для {pair}. MTA логіка не реалізована.")
    return f"*{display_name}* - Детальний огляд (MTA)\n\n_Детальний мультитаймфреймовий аналіз наразі недоступний._"

def rank_assets_for_api(pairs, asset_type):
    """Ранжує активи (зараз просто повертає список як є)."""
    logger.info(f"Викликано rank_assets_for_api для {asset_type}")
    return [{'ticker': p, 'score': 0, 'active': True} for p in pairs]

def sort_pairs_by_activity(pairs: list[dict]) -> list[dict]:
    """Сортує активи (зараз просто повертає список як є)."""
    logger.info("Викликано sort_pairs_by_activity")
    return pairs
