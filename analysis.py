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
    "1m": TrendbarPeriod.M1, "5m": TrendbarPeriod.M5, "15m": TrendbarPeriod.M15
}

# --- ПОЧАТОК ЗМІН: Додаємо функцію для очищення даних ---
def _sanitize(value, default=0.0):
    """Перетворює NaN або None на безпечне значення float."""
    if value is None or pd.isna(value):
        return default
    return float(value)
# --- КІНЕЦЬ ЗМІН ---

def get_market_data(client, symbol_cache, norm_pair: str, period: str, count: int) -> Deferred:
    d = Deferred()
    symbol_details = symbol_cache.get(norm_pair)
    if not symbol_details:
        reactor.callLater(0, d.errback, Exception(f"Пара '{norm_pair}' не знайдена в кеші."))
        return d
        
    tf_proto = PERIOD_MAP.get(period)
    if not tf_proto:
        reactor.callLater(0, d.errback, Exception(f"Непідтримуваний таймфрейм: {period}"))
        return d

    now = int(time.time() * 1000)
    seconds_in_period = {'1m': 60, '5m': 300, '15m': 900}.get(period, 60)
    from_ts = now - (count * seconds_in_period * 1000)
    
    request = ProtoOAGetTrendbarsReq(
        ctidTraderAccountId=client._client.account_id,
        symbolId=symbol_details.symbolId,
        period=tf_proto,
        fromTimestamp=from_ts,
        toTimestamp=now
    )
    
    deferred = client.send(request, timeout=30)
    
    def process_response(message):
        try:
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
        except Exception as e:
            d.errback(e)

    def on_error(failure):
        d.errback(failure)

    deferred.addCallbacks(process_response, on_error)
    return d

def _calculate_full_analysis(signal_df: pd.DataFrame, trend_df: pd.DataFrame) -> Dict:
    if signal_df.empty or len(signal_df) < 50 or trend_df.empty or len(trend_df) < 50:
        return {"verdict": "NEUTRAL", "reasons": ["Недостатньо даних для аналізу."]}

    try:
        signal_df.ta.bbands(length=20, std=2.0, append=True)
        signal_df.ta.stoch(k=14, d=3, smooth_k=3, append=True)
        signal_df.ta.rsi(length=14, append=True)
        signal_df.ta.adx(length=14, append=True)
        trend_df.ta.ema(length=50, append=True)
    except Exception as e:
        logger.error(f"Помилка розрахунку індикаторів: {e}")
        return {"verdict": "NEUTRAL", "reasons": ["Помилка розрахунку індикаторів."]}

    last_signal = signal_df.iloc[-1]
    last_trend = trend_df.iloc[-1]

    trend = "NEUTRAL"
    trend_ema = last_trend.get('EMA_50')
    if pd.notna(trend_ema) and pd.notna(last_signal.get('Close')):
        if last_signal['Close'] > trend_ema:
            trend = "UPTREND"
        else:
            trend = "DOWNTREND"

    adx = last_signal.get('ADX_14', 0)
    is_trending = adx > 20

    current_volume = last_signal['Volume']
    avg_volume = signal_df['Volume'].rolling(window=20).mean().iloc[-1]
    is_volume_high = current_volume > avg_volume * 1.5
    
    recent_period = signal_df.tail(50)
    support = recent_period['Low'].min()
    resistance = recent_period['High'].max()

    verdict = "NEUTRAL"
    reasons = []

    stoch_k = last_signal.get('STOCHk_14_3_3', 50)
    bb_p = last_signal.get('BBP_20_2.0', 0.5)

    if trend == "UPTREND" and is_trending:
        if stoch_k < 30 and bb_p < 0.2:
            verdict = "⬆️ CALL"
            reasons.append(f"Глобальний тренд висхідний (EMA 50 на {trend_df.name})")
            reasons.append(f"Стохастик у зоні перепроданості ({stoch_k:.1f})")
            reasons.append(f"Ціна знаходиться в нижніх 20% каналу Боллінджера")
            if is_volume_high:
                reasons.append("🟢 Сигнал підтверджено підвищеним об'ємом")

    if trend == "DOWNTREND" and is_trending:
        if stoch_k > 70 and bb_p > 0.8:
            verdict = "⬇️ PUT"
            reasons.append(f"Глобальний тренд низхідний (EMA 50 на {trend_df.name})")
            reasons.append(f"Стохастик у зоні перекупленості ({stoch_k:.1f})")
            reasons.append(f"Ціна знаходиться у верхніх 20% каналу Боллінджера")
            if is_volume_high:
                reasons.append("🟢 Сигнал підтверджено підвищеним об'ємом")

    return {
        "verdict": verdict,
        "reasons": reasons,
        "close": last_signal.get('Close'),
        "rsi": last_signal.get('RSI_14'),
        "stoch_k": stoch_k,
        "stoch_d": last_signal.get('STOCHd_14_3_3'),
        "bb_upper": last_signal.get('BBU_20_2.0'),
        "bb_lower": last_signal.get('BBL_20_2.0'),
        "bb_percent_b": bb_p,
        "trend": f"{trend} (ADX: {adx:.1f})",
        "support": support,
        "resistance": resistance,
        "volume_now": current_volume,
        "volume_avg": avg_volume,
        "volume_ratio": current_volume / avg_volume if avg_volume > 0 else 1,
        "candle_pattern": None,
        "special_warning": None
    }

def get_api_detailed_signal_data(client, symbol_cache, symbol: str, user_id: int, timeframe: str = "5m") -> Deferred:
    final_deferred = Deferred()
    
    trend_timeframe_map = {"1m": "5m", "5m": "15m"}
    trend_timeframe = trend_timeframe_map.get(timeframe, "15m")

    d_signal = get_market_data(client, symbol_cache, symbol, timeframe, 100)
    d_trend = get_market_data(client, symbol_cache, symbol, trend_timeframe, 100)
    d_list = DeferredList([d_signal, d_trend], consumeErrors=True)

    def on_data_ready(results):
        try:
            success_signal, signal_df = results[0]
            success_trend, trend_df = results[1]

            if not (success_signal and success_trend):
                final_deferred.callback({"error": "Не вдалося завантажити ринкові дані."})
                return

            signal_df.name = timeframe
            trend_df.name = trend_timeframe

            analysis = _calculate_full_analysis(signal_df, trend_df)
            
            # --- ПОЧАТОК ЗМІН: Застосовуємо санітарну обробку до всіх числових даних ---
            response_data = {
                "pair": symbol,
                "price": _sanitize(analysis.get("close")),
                "verdict_text": analysis["verdict"],
                "reasons": analysis["reasons"],
                "stochastic": {
                    "k": _sanitize(analysis.get("stoch_k"), 50),
                    "d": _sanitize(analysis.get("stoch_d"), 50)
                },
                "rsi": _sanitize(analysis.get("rsi"), 50),
                "bollinger": {
                    "upper": _sanitize(analysis.get("bb_upper")),
                    "lower": _sanitize(analysis.get("bb_lower")),
                    "percent_b": _sanitize(analysis.get("bb_percent_b"), 0.5)
                },
                "trend": analysis.get("trend"),
                "support": _sanitize(analysis.get("support")),
                "resistance": _sanitize(analysis.get("resistance")),
                "volume": {
                    "current": _sanitize(analysis.get("volume_now")),
                    "avg": _sanitize(analysis.get("volume_avg")),
                    "ratio": _sanitize(analysis.get("volume_ratio"))
                },
                "candle_pattern": analysis.get("candle_pattern"),
                "special_warning": analysis.get("special_warning")
            }
            # --- КІНЕЦЬ ЗМІН ---
            
            if user_id != 0 and analysis['verdict'] != "NEUTRAL":
                add_signal_to_history({
                    'user_id': user_id, 'pair': symbol,
                    'price': response_data['price'], 
                    'bull_percentage': int(response_data['stochastic']['k'])
                })

            final_deferred.callback(response_data)

        except Exception as e:
            logger.exception(f"Critical analysis error for {symbol}: {e}")
            final_deferred.errback(e)

    d_list.addCallback(on_data_ready)
    return final_deferred