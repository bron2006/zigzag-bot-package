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
import ml_models

logger = logging.getLogger("analysis")

PERIOD_MAP = {
    "1m": TrendbarPeriod.M1, "5m": TrendbarPeriod.M5, "15m": TrendbarPeriod.M15, 
    "1h": TrendbarPeriod.H1, "4h": TrendbarPeriod.H4, "1day": TrendbarPeriod.D1
}

def _sanitize(value, default=0.0):
    if value is None or pd.isna(value) or np.isinf(value):
        return default
    return float(value)

def get_current_market_regime(df: pd.DataFrame) -> str:
    if ml_models.KMEANS_MODEL is None or ml_models.SCALER is None:
        return "Not Available"
    
    try:
        # --- ПОЧАТОК ЗМІН: Адаптуємо назви колонок до тих, що генерує бібліотека ---
        features_to_select = ['ATR', 'ADX_14', 'RSI']
        # --- КІНЕЦЬ ЗМІН ---
        
        # Перевіряємо, чи всі необхідні колонки існують
        if not all(col in df.columns for col in features_to_select):
            missing = [col for col in features_to_select if col not in df.columns]
            logger.warning(f"Cannot determine market regime, missing columns: {missing}")
            return "Incomplete Data"

        features = df[features_to_select].copy()
        last_features = features.iloc[[-1]]
        
        scaled_features = ml_models.SCALER.transform(last_features)
        prediction = ml_models.KMEANS_MODEL.predict(scaled_features)[0]
        
        regime_names = {0: "Млявий флет", 1: "Бичачий тренд", 2: "Ведмежий тренд", 3: "Шторм"}
        return regime_names.get(prediction, "Unknown")
    except Exception as e:
        logger.error(f"Failed to determine market regime: {e}")
        return "Error"

def get_market_data(client, symbol_cache, norm_pair: str, period: str, count: int) -> Deferred:
    d = Deferred()
    symbol_details = symbol_cache.get(norm_pair)
    if not symbol_details: return d.errback(Exception(f"Пара '{norm_pair}' не знайдена в кеші."))
    tf_proto = PERIOD_MAP.get(period)
    if not tf_proto: return d.errback(Exception(f"Непідтримуваний таймфрейм: {period}"))
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
    try:
        patterns = df.ta.cdl_pattern(name="all")
        if patterns.empty: return None
        last_candle_patterns = patterns.iloc[-1]
        found_patterns = last_candle_patterns[last_candle_patterns != 0]
        if found_patterns.empty: return None
        pattern_name = found_patterns.index[0].replace("CDL_", "")
        signal_strength = found_patterns.iloc[0]
        if "DOJI" in pattern_name.upper(): return f"⚪️ {pattern_name} (Нейтральний)"
        if signal_strength > 0: return f"⬆️ {pattern_name} (Бичачий)"
        if signal_strength < 0: return f"⬇️ {pattern_name} (Ведмежий)"
        return None
    except Exception: return None

def _calculate_full_analysis(signal_df: pd.DataFrame, trend_df: pd.DataFrame, daily_df: pd.DataFrame) -> Dict:
    if any(df.empty or len(df) < 30 for df in [signal_df, trend_df, daily_df]):
        return {"verdict": "NEUTRAL", "reasons": ["Недостатньо даних для аналізу."]}

    try:
        signal_df.ta.bbands(length=20, std=2.0, append=True)
        signal_df.ta.stoch(k=14, d=3, smooth_k=3, append=True)
        # --- ПОЧАТОК ЗМІН: Явно вказуємо назви, щоб уникнути плутанини ---
        signal_df.ta.rsi(length=14, append=True, col_names=('RSI',))
        signal_df.ta.adx(length=14, append=True, col_names=('ADX_14', 'DMP_14', 'DMN_14'))
        signal_df.ta.atr(length=14, append=True, col_names=('ATR',))
        # --- КІНЕЦЬ ЗМІН ---
        trend_df.ta.ema(length=50, append=True, col_names=('EMA50',))
        trend_df.ta.ema(length=200, append=True, col_names=('EMA200',))
    except Exception as e:
        return {"verdict": "NEUTRAL", "reasons": [f"Помилка розрахунку індикаторів: {e}"]}

    last_signal = signal_df.iloc[-1]
    last_trend = trend_df.iloc[-1]
    prev_day = daily_df.iloc[-2] if len(daily_df) > 1 else daily_df.iloc[-1]

    market_regime = get_current_market_regime(signal_df)
    verdict = "NEUTRAL"; reasons = [f"Режим ринку: {market_regime}"]
    
    if market_regime == "Млявий флет":
        stoch_k = last_signal.get('STOCHk_14_3_3', 50)
        bb_p = last_signal.get('BBP_20_2.0', 0.5)
        if stoch_k < 25 and bb_p < 0.1:
            verdict = "⬆️ CALL"; reasons.append("Ціна в нижній зоні Боллінджера + Стохастик перепроданий")
        elif stoch_k > 75 and bb_p > 0.9:
            verdict = "⬇️ PUT"; reasons.append("Ціна в верхній зоні Боллінджера + Стохастик перекуплений")
    
    pivot_point = (prev_day['High'] + prev_day['Low'] + prev_day['Close']) / 3
    support = (2 * pivot_point) - prev_day['High']
    resistance = (2 * pivot_point) - prev_day['Low']
    
    return {
        "verdict": verdict, "reasons": reasons, "close": last_signal.get('Close'),
        "market_regime": market_regime,
        "rsi": last_signal.get('RSI'), "stoch_k": last_signal.get('STOCHk_14_3_3'), "stoch_d": last_signal.get('STOCHd_14_3_3'),
        "bb_upper": last_signal.get('BBU_20_2.0'), "bb_lower": last_signal.get('BBL_20_2.0'),
        "bb_percent_b": last_signal.get('BBP_20_2.0'), "trend": None, "support": support,
        "resistance": resistance, "volume_now": last_signal.get('Volume'), "volume_avg": signal_df['Volume'].rolling(window=20).mean().iloc[-1],
        "volume_ratio": 0, "candle_pattern": _find_candle_pattern(signal_df), "special_warning": None
    }

def get_api_detailed_signal_data(client, symbol_cache, symbol: str, user_id: int, timeframe: str = "5m") -> Deferred:
    final_deferred = Deferred()
    
    # --- ПОЧАТОК ЗМІН: Розширюємо логіку для всіх таймфреймів ---
    trend_timeframe_map = {"1m": "5m", "5m": "15m", "15m": "1h"}
    trend_timeframe = trend_timeframe_map.get(timeframe) # Немає значення за замовчуванням
    # --- КІНЕЦЬ ЗМІН ---

    # --- ПОЧАТОК ЗМІН: Перевіряємо, чи підтримується таймфрейм ---
    if not trend_timeframe:
        err_msg = f"Непідтримуваний таймфрейм для аналізу тренду: {timeframe}"
        logger.warning(err_msg)
        # Повертаємо Deferred, який одразу виконається з помилкою
        return Deferred.fromFailure(Exception(err_msg))
    # --- КІНЕЦЬ ЗМІН ---

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
                return final_deferred.callback({"error": "Не вдалося завантажити всі ринкові дані."})

            signal_df.name = timeframe; trend_df.name = trend_timeframe
            analysis = _calculate_full_analysis(signal_df, trend_df, daily_df)
            
            response_data = {
                "pair": symbol, "price": _sanitize(analysis.get("close")), "verdict_text": analysis["verdict"],
                "reasons": analysis["reasons"], "market_regime": analysis.get("market_regime"),
                "stochastic": {"k": _sanitize(analysis.get("stoch_k"), 50), "d": _sanitize(analysis.get("stoch_d"), 50)},
                "rsi": _sanitize(analysis.get("rsi"), 50),
                "bollinger": {"upper": _sanitize(analysis.get("bb_upper")), "lower": _sanitize(analysis.get("bb_lower")), "percent_b": _sanitize(analysis.get("bb_percent_b"), 0.5)},
                "support": _sanitize(analysis.get("support")), "resistance": _sanitize(analysis.get("resistance")),
                "volume": {"current": _sanitize(analysis.get("volume_now")), "avg": _sanitize(analysis.get("volume_avg")), "ratio": _sanitize(analysis.get("volume_ratio"))},
                "candle_pattern": analysis.get("candle_pattern"), "special_warning": analysis.get("special_warning")
            }
            
            if user_id != 0 and analysis['verdict'] != "NEUTRAL":
                add_signal_to_history({'user_id': user_id, 'pair': symbol, 'price': response_data['price'], 'bull_percentage': int(response_data['stochastic']['k'])})

            final_deferred.callback(response_data)
        except Exception as e:
            logger.exception(f"Critical analysis error for {symbol}: {e}")
            final_deferred.errback(e)

    d_list.addCallback(on_data_ready)
    return final_deferred