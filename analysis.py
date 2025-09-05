# analysis.py
import logging
import time
import json
from typing import Tuple, List, Optional, Dict

import pandas as pd
import numpy as np
import talib

from twisted.internet.defer import Deferred, DeferredList
from twisted.internet import reactor, error as terror, threads

from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAGetTrendbarsReq, ProtoOAGetTrendbarsRes
)
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOATrendbarPeriod as TrendbarPeriod

from db import add_signal_to_history
import state
from redis_client import get_redis

logger = logging.getLogger("analysis")
logger.setLevel(logging.INFO)

PERIOD_MAP = {
    "1m": TrendbarPeriod.M1, "5m": TrendbarPeriod.M5, "15m": TrendbarPeriod.M15,
    "1h": TrendbarPeriod.H1, "4h": TrendbarPeriod.H4, "1day": TrendbarPeriod.D1
}

# ----------------- low-level helpers -----------------
def _send_with_retry(client, request, timeout=60, retries=1) -> Deferred:
    d = Deferred()
    def _attempt(remaining):
        inner = client.send(request, timeout=timeout)
        def ok(msg):
            if not d.called: d.callback(msg)
        def err(f):
            if f.check(terror.TimeoutError) and remaining > 0:
                logger.warning(f"Request {type(request).__name__} timed out, retrying ({remaining} left)...")
                reactor.callLater(0.2, _attempt, remaining - 1)
            else:
                if not d.called: d.errback(f)
        inner.addCallbacks(ok, err)
    _attempt(retries)
    return d

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
    seconds_per_bar = {'1m': 60, '5m': 300, '15m': 900, '1h': 3600, '4h': 14400, '1day': 86400}
    from_ts = now - (count * seconds_per_bar[period] * 1000)

    request = ProtoOAGetTrendbarsReq(
        ctidTraderAccountId=client._client.account_id,
        symbolId=symbol_details.symbolId,
        period=tf_proto, fromTimestamp=from_ts, toTimestamp=now
    )

    logger.info(f"Requesting candles for {norm_pair} ({period})...")
    deferred = _send_with_retry(client, request, timeout=60, retries=1)

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

# --- ПОЧАТОК ЗМІН: Нова функція для розрахунку Pivot Points ---
def calculate_pivot_points(daily_df: pd.DataFrame) -> Optional[Dict[str, float]]:
    """Розраховує класичні денні Pivot Points на основі даних попереднього дня."""
    if daily_df is None or len(daily_df) < 2:
        return None
    try:
        prev_day = daily_df.iloc[-2]
        high, low, close = prev_day['High'], prev_day['Low'], prev_day['Close']
        
        pivot = (high + low + close) / 3
        r1 = (2 * pivot) - low
        s1 = (2 * pivot) - high
        r2 = pivot + (high - low)
        s2 = pivot - (high - low)
        r3 = high + 2 * (pivot - low)
        s3 = low - 2 * (pivot - high)
        
        return {'P': pivot, 'R1': r1, 'R2': r2, 'R3': r3, 'S1': s1, 'S2': s2, 'S3': s3}
    except IndexError:
        return None
    except Exception as e:
        logger.error(f"Failed to calculate Pivot Points: {e}")
        return None
# --- КІНЕЦЬ ЗМІН ---

def analyze_candle_patterns(df: pd.DataFrame):
    try:
        if df.empty or len(df) < 5: return None
        open_v, high_v, low_v, close_v = df['Open'].values, df['High'].values, df['Low'].values, df['Close'].values
        hammer = talib.CDLHAMMER(open_v, high_v, low_v, close_v)[-1]
        engulfing = talib.CDLENGULFING(open_v, high_v, low_v, close_v)[-1]
        doji = talib.CDLDOJI(open_v, high_v, low_v, close_v)[-1]
        
        if hammer != 0:
            ptype = 'bullish' if hammer > 0 else 'bearish'
            return {'name': 'HAMMER', 'type': ptype, 'text': f"{'⬆️' if ptype == 'bullish' else '⬇️'} HAMMER"}
        if engulfing != 0:
            ptype = 'bullish' if engulfing > 0 else 'bearish'
            return {'name': 'ENGULFING', 'type': ptype, 'text': f"{'⬆️' if ptype == 'bullish' else '⬇️'} ENGULFING"}
        if doji != 0:
            return {'name': 'DOJI', 'type': 'neutral', 'text': '⚪ DOJI'}
        return None
    except Exception: return None

def analyze_volume(df: pd.DataFrame):
    if df.empty or 'Volume' not in df.columns or len(df) < 21: return "Недостатньо даних"
    try:
        df['Volume_MA20'] = df['Volume'].rolling(window=20).mean()
        last_vol, last_ma = df.iloc[-1]['Volume'], df.iloc[-1]['Volume_MA20']
        if pd.isna(last_ma): return "Недостатньо даних"
        if last_vol > last_ma * 1.5: return "🟢 Підвищений об'єм"
        if last_vol < last_ma * 0.5: return "🧊 Аномально низький об'єм"
        return "Об'єм нейтральний"
    except Exception: return "Помилка аналізу об'єму"

# ----------------- core signal logic -----------------
def _calculate_core_signal(df: pd.DataFrame, daily_df: pd.DataFrame, current_price: float):
    if df.empty or daily_df.empty or len(df) < 200:
        return {"score": 50, "reasons": ["Недостатньо даних для аналізу"], "verdict_text": "🟡 НЕЙТРАЛЬНО"}

    try:
        close = df['Close'].values; close_daily = daily_df['Close'].values
        ema200_daily = talib.EMA(close_daily, timeperiod=200)
        rsi = talib.RSI(close, timeperiod=14)
        macd, macdsignal, macdhist = talib.MACD(close, fastperiod=12, slowperiod=26, signalperiod=9)
        last_rsi = float(rsi[-1]) if len(rsi) > 0 else 50
        last_macd_hist = float(macdhist[-1]) if len(macdhist) > 0 else 0
        last_ema200_daily = float(ema200_daily[-1]) if len(ema200_daily) > 0 else None
        candle_pattern = analyze_candle_patterns(df)
        volume_info = analyze_volume(df)
    except Exception as e:
        logger.exception(f"Indicator calculation failed: {e}")
        return {"score": 50, "reasons": ["Помилка розрахунку індикаторів"], "verdict_text": "🟡 НЕЙТРАЛЬНО"}

    reasons, bullish_factors, bearish_factors = [], 0, 0
    if last_macd_hist > 0: bullish_factors += 1; reasons.append("MACD росте")
    else: bearish_factors += 1; reasons.append("MACD падає")
    if candle_pattern:
        if candle_pattern.get('type') == 'bullish': bullish_factors += 1; reasons.append(f"Бичачий патерн: {candle_pattern.get('name')}")
        elif candle_pattern.get('type') == 'bearish': bearish_factors += 1; reasons.append(f"Ведмежий патерн: {candle_pattern.get('name')}")
    if last_rsi < 30: bullish_factors += 1; reasons.append("Ознаки перепроданості (RSI < 30)")
    elif last_rsi > 70: bearish_factors += 1; reasons.append("Ознаки перекупленості (RSI > 70)")

    is_daily_uptrend = None
    if last_ema200_daily is not None: is_daily_uptrend = current_price > last_ema200_daily

    verdict, score, critical_warning = "🟡 НЕЙТРАЛЬНО", 50, None
    if is_daily_uptrend is True:
        reasons.append("📈 Глобальний тренд: Бичачий (D1)")
        if bullish_factors >= 2: score, verdict = 85, "⬆️ Сильна ПОКУПКА"
        elif bullish_factors == 1: score, verdict = 65, "↗️ Помірна ПОКУПКА"
        if bearish_factors >= 1: critical_warning = "❗️ Сигнал на продаж проти сильного денного тренду"; reasons.append(critical_warning)
    elif is_daily_uptrend is False:
        reasons.append("📉 Глобальний тренд: Ведмежий (D1)")
        if bearish_factors >= 2: score, verdict = 15, "⬇️ Сильний ПРОДАЖ"
        elif bearish_factors == 1: score, verdict = 35, "↘️ Помірний ПРОДАЖ"
        if bullish_factors >= 1: critical_warning = "❗️ Сигнал на покупку проти сильного денного тренду"; reasons.append(critical_warning)
    else:
        reasons.append("↔️ Глобальний тренд: Боковий/Невизначений (D1)")
        if bullish_factors >= 2: score, verdict = 75, "↗️ Помірна ПОКУПКА"
        elif bearish_factors >= 2: score, verdict = 25, "↘️ Помірний ПРОДАЖ"

    # --- ПОЧАТОК ЗМІН: Використовуємо Pivot Points для аналізу ризиків ---
    pivots = calculate_pivot_points(daily_df)
    support, resistance = None, None
    if pivots:
        support_levels = sorted([pivots[k] for k in ['S1', 'S2', 'S3'] if k in pivots], reverse=True)
        resistance_levels = sorted([pivots[k] for k in ['R1', 'R2', 'R3'] if k in pivots])
        support = next((s for s in support_levels if s < current_price), None)
        resistance = next((r for r in resistance_levels if r > current_price), None)
        
        # Перевіряємо конфлікт між сигналом та рівнями
        for r_level in resistance_levels:
            if r_level and current_price < r_level and (r_level - current_price) / current_price < 0.005: # поріг 0.5%
                if score > 60: # Якщо є сигнал на покупку біля опору
                    verdict = "⚠️ Ризикована ПОКУПКА"
                    reasons.append(f"❗️ Ціна впритул до Pivot опору ({r_level:.5f})")
                    score = 60 # Знижуємо впевненість
                break # Достатньо одного найближчого рівня
                
        for s_level in support_levels:
            if s_level and current_price > s_level and (current_price - s_level) / current_price < 0.005: # поріг 0.5%
                if score < 40: # Якщо є сигнал на продаж біля підтримки
                    verdict = "⚠️ Ризикований ПРОДАЖ"
                    reasons.append(f"❗️ Ціна впритул до Pivot підтримки ({s_level:.5f})")
                    score = 40 # Знижуємо впевненість
                break
    # --- КІНЕЦЬ ЗМІН ---
    
    return {"score": int(np.clip(score, 0, 100)), "reasons": reasons,
            "support": support, "resistance": resistance,
            "candle_pattern": candle_pattern, "volume_info": volume_info,
            "critical_warning": critical_warning, "verdict_text": verdict}

# ----------------- public API -----------------
def get_api_detailed_signal_data(client, symbol_cache, norm_pair: str, user_id: int, period: str = "15m", count: int = 500) -> Deferred:
    final_deferred = Deferred()
    d1 = get_market_data(client, symbol_cache, norm_pair, period, count)
    d2 = get_market_data(client, symbol_cache, norm_pair, "1day", max(200, count))
    dl = DeferredList([d1, d2], consumeErrors=True)

    def on_ready(results):
        try:
            success_df, df = results[0]; success_daily, daily_df = results[1]
            if not success_df or df is None or df.empty or not success_daily or daily_df is None or daily_df.empty:
                err_msg = "Недостатньо історичних даних для аналізу"
                logger.warning(f"Analysis failed for {norm_pair}: {err_msg}")
                final_deferred.callback({"error": err_msg}); return

            current_price = None
            live_price_data = state.live_prices.get(norm_pair)
            if live_price_data and live_price_data.get("mid") and (time.time() - live_price_data.get("ts", 0)) < 30:
                current_price = float(live_price_data["mid"])
            if current_price is None:
                current_price = float(df.iloc[-1]['Close'])

            analysis = _calculate_core_signal(df, daily_df, current_price)
            score = analysis.get("score", 50)
            response_data = {"pair": norm_pair, "price": current_price,
                             "verdict_text": analysis.get("verdict_text"),
                             "reasons": analysis.get("reasons", []),
                             "support": analysis.get("support"), "resistance": analysis.get("resistance"),
                             "bull_percentage": int(score), "bear_percentage": 100 - int(score),
                             "candle_pattern": analysis.get("candle_pattern"),
                             "volume_info": analysis.get("volume_info"),
                             "special_warning": analysis.get("critical_warning")}
            
            if user_id != 0:
                add_signal_to_history({'user_id': user_id, 'pair': norm_pair, 'price': current_price, 'bull_percentage': int(score)})
            
            try:
                r = get_redis()
                if r: r.set(f"signal:{norm_pair}:{period}", json.dumps(response_data, ensure_ascii=False), ex=60 * 60 * 2)
            except Exception: logger.exception("Failed to save signal to Redis")
            
            final_deferred.callback(response_data)
        except Exception as e:
            logger.exception(f"Critical analysis error for {norm_pair}: {e}")
            final_deferred.errback(e)
            
    dl.addCallback(on_ready)
    return final_deferred