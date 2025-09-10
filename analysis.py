# analysis.py
import logging
import pandas as pd
import pandas_ta as ta
import numpy as np
import time
from typing import Optional, Dict, List

from twisted.internet.defer import Deferred, DeferredList
from twisted.python.failure import Failure
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

def _calculate_score_and_reasons(signal_df: pd.DataFrame, trend_df: pd.DataFrame) -> Dict:
    if any(df.empty or len(df) < 50 for df in [signal_df, trend_df]):
        return {"score": 50, "reasons": ["Недостатньо даних для аналізу."]}

    try:
        signal_df.ta.bbands(length=20, std=2.0, append=True)
        signal_df.ta.stoch(k=14, d=3, smooth_k=3, append=True)
        signal_df.ta.rsi(length=14, append=True)
        trend_df.ta.ema(length=50, append=True, col_names=('EMA50',))
        trend_df.ta.ema(length=200, append=True, col_names=('EMA200',))
    except Exception as e:
        return {"score": 50, "reasons": [f"Помилка розрахунку індикаторів: {e}"]}

    last_signal = signal_df.iloc[-1]
    last_trend = trend_df.iloc[-1]
    
    score = 50  # Початкова нейтральна оцінка
    reasons = []

    # 1. Аналіз глобального тренду (найвагоміший фактор: +/- 20 балів)
    ema50 = last_trend.get('EMA50')
    ema200 = last_trend.get('EMA200')
    if ema50 is not None and ema200 is not None:
        if ema50 > ema200:
            score += 20
            reasons.append("📈 Глобальний тренд: висхідний (EMA50 > EMA200)")
        else:
            score -= 20
            reasons.append("📉 Глобальний тренд: низхідний (EMA50 < EMA200)")

    # 2. Аналіз моментуму: Stochastic (+/- 15 балів)
    stoch_k = last_signal.get('STOCHk_14_3_3')
    if pd.notna(stoch_k):
        if stoch_k < 20:
            score += 15
            reasons.append("🐂 Моментум: сильна перепроданість (Stochastic < 20)")
        elif stoch_k > 80:
            score -= 15
            reasons.append("🐃 Моментум: сильна перекупленість (Stochastic > 80)")

    # 3. Аналіз моментуму: RSI (+/- 10 балів)
    rsi = last_signal.get('RSI_14')
    if pd.notna(rsi):
        if rsi < 30:
            score += 10
            reasons.append("🐂 Моментум: перепроданість (RSI < 30)")
        elif rsi > 70:
            score -= 10
            reasons.append("🐃 Моментум: перекупленість (RSI > 70)")

    # 4. Аналіз волатильності: Bollinger Bands (+/- 10 балів)
    bb_p = last_signal.get('BBP_20_2.0')
    if pd.notna(bb_p):
        if bb_p < 0.05: # Ціна дуже близько до нижньої межі
            score += 10
            reasons.append("📈 Волатильність: ціна біля нижньої межі Боллінджера")
        elif bb_p > 0.95: # Ціна дуже близько до верхньої межі
            score -= 10
            reasons.append("📉 Волатильність: ціна біля верхньої межі Боллінджера")

    final_score = int(np.clip(score, 0, 100))
    
    return {
        "score": final_score,
        "reasons": reasons if reasons else ["Ринок нейтральний, немає явних факторів."],
        "close": last_signal.get('Close'),
        # Повертаємо сирі дані для відображення в UI
        "raw_indicators": {
            "rsi": rsi,
            "stoch_k": stoch_k,
            "bb_percent_b": bb_p,
            "trend": trend,
        }
    }

def _generate_verdict_from_score(score: int) -> str:
    if score >= 85: return "⬆️ Дуже сильний CALL"
    if score >= 65: return "↗️ CALL"
    if score <= 15: return "⬇️ Дуже сильний PUT"
    if score <= 35: return "↘️ PUT"
    return "🟡 NEUTRAL"

def get_api_detailed_signal_data(client, symbol_cache, symbol: str, user_id: int, timeframe: str = "5m") -> Deferred:
    final_deferred = Deferred()
    
    trend_timeframe_map = {"1m": "5m", "5m": "15m", "15m": "1h"}
    trend_timeframe = trend_timeframe_map.get(timeframe)
    if not trend_timeframe:
        err_msg = f"Непідтримуваний таймфрейм: {timeframe}"
        d = Deferred(); d.errback(Failure(Exception(err_msg))); return d

    d_signal = get_market_data(client, symbol_cache, symbol, timeframe, 250)
    d_trend = get_market_data(client, symbol_cache, symbol, trend_timeframe, 250)
    d_list = DeferredList([d_signal, d_trend], consumeErrors=True)

    def on_data_ready(results):
        try:
            success_signal, signal_df = results[0]
            success_trend, trend_df = results[1]

            if not (success_signal and success_trend):
                return final_deferred.callback({"error": "Не вдалося завантажити ринкові дані."})

            analysis = _calculate_score_and_reasons(signal_df, trend_df)
            verdict = _generate_verdict_from_score(analysis['score'])
            
            # Зберігаємо дані для відповіді API
            response_data = {
                "pair": symbol,
                "price": _sanitize(analysis.get("close")),
                "verdict_text": verdict,
                "reasons": analysis.get("reasons", []),
                "score": analysis.get("score", 50), # Нове поле з оцінкою
                # Поля для UI, які ми поки не розраховуємо, але залишимо для сумісності
                "market_regime": None,
                "stochastic": {"k": _sanitize(analysis.get("raw_indicators", {}).get("stoch_k"), 50), "d": None},
                "rsi": _sanitize(analysis.get("raw_indicators", {}).get("rsi"), 50),
                "bollinger": {"percent_b": _sanitize(analysis.get("raw_indicators", {}).get("bb_percent_b"), 0.5)},
                "support": None, "resistance": None, "volume": None, "candle_pattern": None, "special_warning": None
            }
            
            # Зберігаємо в історію лише сильні сигнали
            if user_id != 0 and analysis['score'] >= 65 or analysis['score'] <= 35:
                add_signal_to_history({
                    'user_id': user_id, 'pair': symbol,
                    'price': response_data['price'], 
                    'bull_percentage': analysis['score']
                })

            final_deferred.callback(response_data)
        except Exception as e:
            logger.exception(f"Critical analysis error for {symbol}: {e}")
            final_deferred.errback(e)

    d_list.addCallback(on_data_ready)
    return final_deferred