# analysis.py
import pandas as pd
import pandas_ta as ta
import numpy as np
from concurrent.futures import ThreadPoolExecutor

# --- НОВЕ: Імпортуємо функцію для збереження історії ---
from db import add_signal_to_history
from config import logger, binance, td, CACHE, ANALYSIS_TIMEFRAMES

# --- Лінива ініціалізація пулу потоків ---
_executor = None
def get_executor():
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=2)
    return _executor

# ------------------- ОСНОВНІ ФУНКЦІЇ АНАЛІТИКИ -------------------

def get_market_data(pair, tf, asset, limit=300):
    key = f"{pair}_{tf}_{limit}"
    if key in CACHE: return CACHE[key]
    try:
        df = pd.DataFrame()
        if asset == 'crypto':
            bars = binance.fetch_ohlcv(pair, timeframe=tf, limit=limit)
            df = pd.DataFrame(bars, columns=['ts','o','h','l','c','v'])
            df['ts'] = pd.to_datetime(df['ts'], unit='ms', utc=True)
            df = df.rename(columns={'o':'Open','h':'High','l':'Low','c':'Close','v':'Volume'})
        elif asset in ('forex', 'stocks'):
            td_tf = tf.replace('m', 'min').replace('h', 'hour') if tf != '1d' else '1day'
            ts = td.time_series(symbol=pair, interval=td_tf, outputsize=limit)
            df = ts.as_pandas()
            if not df.empty:
                df = df.rename(columns={'open':'Open','high':'High','low':'Low','close':'Close','volume':'Volume'}).reset_index()
        if df.empty:
            logger.warning(f"API повернуло порожній результат для {pair} на ТФ {tf}")
            return pd.DataFrame()
        CACHE[key] = df
        return df
    except Exception as e:
        logger.error(f"Помилка отримання даних для {pair} на ТФ {tf}: {e}")
        return pd.DataFrame()

def group_close_values(values, threshold=0.01):
    if not len(values): return []
    values = sorted(values)
    groups, current_group = [], [values[0]]
    for value in values[1:]:
        if value - current_group[-1] <= threshold * value:
            current_group.append(value)
        else:
            groups.append(np.mean(current_group))
            current_group = [value]
    groups.append(np.mean(current_group))
    return groups

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
        pattern_name = found_patterns.index[0]
        simple_name = pattern_name.replace("CDL_", "")
        pattern_type = 'neutral'
        if signal_strength > 0: pattern_type = 'bullish'
        elif signal_strength < 0: pattern_type = 'bearish'
        text = f'⏳ Нейтральний патерн: "{simple_name}" (невизначеність)'
        if pattern_type == 'bullish': text = f'✅ Бичачий патерн: "{simple_name}" (ріст ⬆️)'
        elif pattern_type == 'bearish': text = f'❌ Ведмежий патерн: "{simple_name}" (падіння ⬇️)'
        return {'name': simple_name, 'type': pattern_type, 'text': text}
    except Exception as e:
        logger.error(f"Помилка в analyze_candle_patterns: {e}")
        return None

def analyze_volume(df: pd.DataFrame, window=20):
    try:
        df['vol_ma'] = df['Volume'].rolling(window=window).mean()
        last_volume = df['Volume'].iloc[-1]
        avg_volume = df['vol_ma'].iloc[-1]
        if last_volume > avg_volume * 2:
            return f"🔥 Аномально високий об'єм (в {last_volume/avg_volume:.1f}x разів вище середнього)"
        elif last_volume < avg_volume * 0.5:
            return f"🧊 Аномально низький об'єм (в {avg_volume/last_volume:.1f}x разів нижче середнього)"
        return "Об'єм у межах норми"
    except:
        return None

def is_market_active(df: pd.DataFrame, window=10, threshold=0.005):
    if df.empty or len(df) < window:
        return False
    recent_df = df.iloc[-window:]
    market_range = recent_df['High'].max() - recent_df['Low'].min()
    return (market_range / recent_df['Close'].iloc[-1]) > threshold

def _calculate_core_signal(df, daily_df):
    df.ta.rsi(length=14, append=True)
    df.ta.ema(length=21, append=True)
    support_levels, resistance_levels = [], []
    if not daily_df.empty:
        support_levels, resistance_levels = identify_support_resistance_levels(daily_df)
    current_price = df.iloc[-1]['Close']
    candle_pattern = analyze_candle_patterns(df)
    volume_analysis = analyze_volume(df)
    weights = {'ema': 1.0, 'rsi': 1.5, 'support_resistance': 1.3}
    score = 50.0
    reasons = []
    last = df.iloc[-1]
    ema_status = 'above' if last['Close'] > last['EMA_21'] else 'below'
    if ema_status == 'above':
        score += 10 * weights['ema']
        reasons.append("Ціна вище EMA(21)")
    else:
        score -= 10 * weights['ema']
        reasons.append("Ціна нижче EMA(21)")
    rsi = last['RSI_14']
    if rsi < 30:
        score += 15 * weights['rsi']
        reasons.append("RSI в зоні перепроданості (<30)")
    elif rsi > 70:
        score -= 15 * weights['rsi']
        reasons.append("RSI в зоні перекупленості (>70)")
    if support_levels:
        dist_to_support = min(abs(current_price - sl) for sl in support_levels)
        if dist_to_support / current_price < 0.003:
            score += 15 * weights['support_resistance']
            reasons.append("Ціна ДУЖЕ близько до підтримки")
        elif dist_to_support / current_price < 0.005:
            score += 10 * weights['support_resistance']
            reasons.append("Ціна біля рівня підтримки")
    if resistance_levels:
        dist_to_resistance = min(abs(current_price - rl) for rl in resistance_levels)
        if dist_to_resistance / current_price < 0.003:
            score -= 15 * weights['support_resistance']
            reasons.append("Ціна ДУЖЕ близько до опору")
        elif dist_to_resistance / current_price < 0.005:
            score -= 10 * weights['support_resistance']
            reasons.append("Ціна біля рівня опору")
    if volume_analysis and "аномально низький" in volume_analysis:
        score = np.clip(score, 30, 70)
        reasons.append("Сигнал не підтверджено об'ємом!")
    score = int(np.clip(score, 0, 100))
    return {
        "score": score, "reasons": reasons, "support_levels": support_levels,
        "resistance_levels": resistance_levels, "candle_pattern": candle_pattern,
        "volume_analysis": volume_analysis, "current_price": current_price,
        "rsi": rsi, "ema_status": ema_status
    }

# ------------------- ОНОВЛЕНІ ФУНКЦІЇ ДЛЯ UI ТА API -------------------

# --- НОВЕ: функція тепер приймає user_id для збереження історії ---
def get_signal_strength_verdict(pair, display_name, asset, user_id=None):
    df = get_market_data(pair, '1m', asset, limit=50)
    if not is_market_active(df):
        return f" Ринок для *{display_name}* зараз неактивний. Аналіз недоцільний."
    daily_df = get_market_data(pair, '1d', asset, limit=30)
    try:
        analysis = _calculate_core_signal(df, daily_df)
        score = analysis['score']
        bull_percentage, bear_percentage = score, 100 - score
        arrow = '⬆️' if bull_percentage >= 50 else '⬇️'
        
        # --- НОВЕ: Зберігаємо сигнал в історію ---
        if user_id:
            signal_type = "BUY" if bull_percentage > 55 else "SELL" if bull_percentage < 45 else "NEUTRAL"
            nearest_support = min(analysis['support_levels'], key=lambda x: abs(x - analysis['current_price'])) if analysis['support_levels'] else None
            nearest_resistance = min(analysis['resistance_levels'], key=lambda x: abs(x - analysis['current_price'])) if analysis['resistance_levels'] else None
            
            add_signal_to_history(
                user_id=user_id, pair=pair, price=analysis['current_price'],
                signal_type=signal_type, rsi=analysis['rsi'], ema_status=analysis['ema_status'],
                support=nearest_support, resistance=nearest_resistance,
                bull_percentage=bull_percentage, bear_percentage=bear_percentage
            )

        strength_line = f"🐂 Бики {bull_percentage}% ⬆️\n🐃 Ведмеді {bear_percentage}% ⬇️"
        reason_line = f"Підстава: {', '.join(analysis['reasons'])}." if analysis['reasons'] else "Змішані сигнали."
        disclaimer = "\n\n_⚠️ Це не фінансова порада._"
        sr_info = f"Підтримка: `{nearest_support:.4f}` | Опір: `{nearest_resistance:.4f}`"
        final_message = (f"{arrow} *{display_name}*\n\n"
                         f"**🕯️ Індекс сили ринку (1хв)**\n"
                         f"**Поточна ціна:** `{analysis['current_price']:.4f}`\n\n"
                         f"**Баланс сил:**\n{strength_line}\n\n"
                         f"**Рівні S/R (денні):**\n{sr_info}\n\n")
        if analysis['candle_pattern']:
            final_message += f"**Свічковий патерн:**\n{analysis['candle_pattern']['text']}\n\n"
        final_message += f"_{reason_line}_{disclaimer}"
        return final_message
    except Exception as e:
        logger.error(f"Помилка розрахунку індексу для {pair}: {e}")
        return f"⚠️ Помилка аналізу *{display_name}*."

def get_api_detailed_signal_data(pair, user_id=None):
    asset_type = 'stocks'
    if '/' in pair: asset_type = 'crypto' if 'USDT' in pair else 'forex'
    df = get_market_data(pair, '1m', asset_type, limit=100)
    if not is_market_active(df):
        return {"error": f"Ринок для {pair} зараз неактивний."}
    daily_df = get_market_data(pair, '1d', asset_type, limit=50)
    try:
        analysis = _calculate_core_signal(df, daily_df)
        score = analysis['score']
        date_col = 'ts' if 'ts' in df.columns else 'datetime'
        result = {
            "pair": pair, "price": analysis['current_price'], "bull_percentage": score,
            "bear_percentage": 100 - score,
            "support": min(analysis['support_levels'], key=lambda x: abs(x - analysis['current_price'])) if analysis['support_levels'] else None,
            "resistance": min(analysis['resistance_levels'], key=lambda x: abs(x - analysis['current_price'])) if analysis['resistance_levels'] else None,
            "reasons": analysis['reasons'], "candle_pattern": analysis['candle_pattern'], "volume_analysis": analysis['volume_analysis'],
            "history": {
                "dates": df[date_col].dt.strftime('%Y-%m-%d %H:%M:%S').tolist(),
                "open": df['Open'].tolist(), "high": df['High'].tolist(),
                "low": df['Low'].tolist(), "close": df['Close'].tolist(),
            } if not df.empty and pd.api.types.is_datetime64_any_dtype(df[date_col]) else None
        }
        # Ця функція не зберігає історію, щоб не дублювати її з WebApp
        return result
    except Exception as e:
        logger.error(f"Помилка API-сигналу для {pair}: {e}")
        return {"error": "Внутрішня помилка сервера при аналізі"}

def get_full_mta_verdict(pair, display_name, asset):
    def worker(tf):
        df = get_market_data(pair, tf, asset, limit=200)
        if df.empty or len(df) < 55: return (tf, None)
        df.ta.ema(length=21, append=True, col_names='EMA_fast')
        df.ta.ema(length=55, append=True, col_names='EMA_slow')
        sig = "✅ BUY" if df.iloc[-1]['EMA_fast'] > df.iloc[-1]['EMA_slow'] else "❌ SELL"
        return (tf, sig)
    executor = get_executor()
    results = executor.map(worker, ANALYSIS_TIMEFRAMES)
    rows = [r for r in results if r[1] is not None]
    table = "\n".join([f"| {tf:<4} | {sig} |" for tf, sig in rows])
    return f"**📊 Детальний огляд тренду:** *{display_name}*\n\n| ТФ   | Сигнал |\n|:----:|:---:|\n{table}"

def get_api_mta_data(pair, asset_type):
    def worker(tf):
        df = get_market_data(pair, tf, asset_type, limit=200)
        if df.empty or len(df) < 55: return None
        df.ta.ema(length=21, append=True, col_names='EMA_fast')
        df.ta.ema(length=55, append=True, col_names='EMA_slow')
        signal = "BUY" if df.iloc[-1]['EMA_fast'] > df.iloc[-1]['EMA_slow'] else "SELL"
        return {"tf": tf, "signal": signal}
    executor = get_executor()
    results = executor.map(worker, ANALYSIS_TIMEFRAMES)
    return [r for r in results if r is not None]

def rank_assets_for_api(pairs, asset_type):
    def fetch_score(pair):
        try:
            df = get_market_data(pair, '1h', asset_type, limit=50)
            if df.empty: return None
            rsi = df.ta.rsi(length=14).iloc[-1]
            if pd.isna(rsi): return None
            return {'ticker': pair, 'score': abs(rsi - 50)}
        except Exception:
            return None
    executor = get_executor()
    results = executor.map(fetch_score, pairs)
    ranked_assets = [r for r in results if r is not None]
    return sorted(ranked_assets, key=lambda x: x['score'], reverse=True)

def rank_crypto_chunk(pairs_chunk):
    def fetch_score(pair):
        try:
            df = get_market_data(pair, '1h', 'crypto', limit=50)
            if df.empty: return None
            rsi = df.ta.rsi(length=14).iloc[-1]
            if pd.isna(rsi): return None
            return {'display_name': pair, 'ticker': pair, 'score': abs(rsi - 50)}
        except Exception as e:
            logger.error(f"Не вдалося проаналізувати пару {pair}: {e}")
            return None
    executor = get_executor()
    results = executor.map(fetch_score, pairs_chunk)
    ranked_pairs = [r for r in results if r is not None]
    return sorted(ranked_pairs, key=lambda x: x['score'], reverse=True)