# analysis.py
import logging
import time
import json
from typing import Tuple, List, Optional, Dict, Any

import pandas as pd
import numpy as np
import talib

from twisted.internet.defer import Deferred, DeferredList
from twisted.internet import reactor, error as terror

from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAGetTrendbarsReq, ProtoOAGetTrendbarsRes
)
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOATrendbarPeriod as TrendbarPeriod

from db import add_signal_to_history
import state
from config import ANALYSIS_CONFIG

logger = logging.getLogger("analysis")
logger.setLevel(logging.INFO)

PERIOD_MAP = {
    "1m": TrendbarPeriod.M1, "5m": TrendbarPeriod.M5, "15m": TrendbarPeriod.M15,
    "1h": TrendbarPeriod.H1, "4h": TrendbarPeriod.H4, "1day": TrendbarPeriod.D1
}

# --- Data Fetching ---
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
    request = ProtoOAGetTrendbarsReq(ctidTraderAccountId=client._client.account_id, symbolId=symbol_details.symbolId, period=tf_proto, fromTimestamp=from_ts, toTimestamp=now)
    logger.info(f"Requesting candles for {norm_pair} ({period})...")
    deferred = client.send(request, timeout=60)
    def process_response(message):
        try:
            response = ProtoOAGetTrendbarsRes(); response.ParseFromString(message.payload)
            logger.info(f"✅ Received {len(response.trendbar)} candles for {norm_pair} ({period}).")
            if not response.trendbar: d.callback(pd.DataFrame()); return
            divisor = 10**5
            bars = [{'ts': pd.to_datetime(bar.utcTimestampInMinutes * 60, unit='s', utc=True), 'Open': (bar.low + bar.deltaOpen) / divisor, 'High': (bar.low + bar.deltaHigh) / divisor, 'Low': bar.low / divisor, 'Close': (bar.low + bar.deltaClose) / divisor, 'Volume': bar.volume} for bar in response.trendbar]
            df = pd.DataFrame(bars)
            d.callback(df.sort_values(by='ts').reset_index(drop=True))
        except Exception as e: d.errback(e)
    def on_error(failure): d.errback(failure)
    deferred.addCallbacks(process_response, on_error)
    return d

# --- Analysis Sub-functions (Refactored) ---
def _validate_data(df: pd.DataFrame, df_name: str) -> Optional[str]:
    if df.empty or len(df) < ANALYSIS_CONFIG["min_bars_for_analysis"]:
        return f"Недостатньо даних для аналізу ({df_name})"
    if df[['Open', 'High', 'Low', 'Close']].isna().any().any():
        return f"Історичні дані містять помилки ({df_name}, NaN)"
    last_bar_time = df.iloc[-1]['ts']
    if (pd.Timestamp.now(tz='UTC') - last_bar_time).total_seconds() > ANALYSIS_CONFIG["max_candle_staleness_seconds"]:
        logger.warning(f"Дані для {df_name} застарілі (остання свічка: {last_bar_time})")
    return None

def _get_technical_indicators(df: pd.DataFrame, trend_df: pd.DataFrame, current_price: float) -> Dict[str, Any]:
    cfg = ANALYSIS_CONFIG
    ema_trend = talib.EMA(trend_df['Close'].values, timeperiod=cfg["ema_daily_period"])
    rsi = talib.RSI(df['Close'].values, timeperiod=cfg["rsi_period"])
    macd, macdsignal, macdhist = talib.MACD(df['Close'].values, fastperiod=cfg["macd_fast"], slowperiod=cfg["macd_slow"], signalperiod=cfg["macd_signal"])
    
    return {
        "last_rsi": float(rsi[-1]) if len(rsi) > 0 else 50,
        "last_macd_hist": float(macdhist[-1]) if len(macdhist) > 0 else 0,
        "is_trend_up": (current_price > ema_trend[-1]) if len(ema_trend) > 0 else None,
        "candle_pattern": analyze_candle_patterns(df),
        "volume_info": analyze_volume(df)
    }

def _collect_signal_factors(indicators: Dict[str, Any]) -> Tuple[int, int, List[str]]:
    cfg = ANALYSIS_CONFIG; reasons, bullish, bearish = [], 0, 0
    if indicators["last_macd_hist"] > 0: bullish += 1; reasons.append("MACD росте")
    else: bearish += 1; reasons.append("MACD падає")
    if indicators["candle_pattern"]:
        p_type, p_name = indicators["candle_pattern"].get('type'), indicators["candle_pattern"].get('name')
        if p_type == 'bullish': bullish += 1; reasons.append(f"Бичачий патерн: {p_name}")
        elif p_type == 'bearish': bearish += 1; reasons.append(f"Ведмежий патерн: {p_name}")
    if indicators["last_rsi"] < cfg["rsi_oversold"]: bullish += 1; reasons.append(f"Ознаки перепроданості (RSI < {cfg['rsi_oversold']})")
    elif indicators["last_rsi"] > cfg["rsi_overbought"]: bearish += 1; reasons.append(f"Ознаки перекупленості (RSI > {cfg['rsi_overbought']})")
    return bullish, bearish, reasons

def _calculate_verdict_and_score(bullish: int, bearish: int, is_trend_up: Optional[bool], reasons: List[str]) -> Dict[str, Any]:
    verdict, score, warning = "🟡 НЕЙТРАЛЬНО", 50, None
    if is_trend_up is True:
        reasons.append("📈 Глобальний тренд: Бичачий (H4)")
        if bullish >= 2: score, verdict = 85, "⬆️ Сильна ПОКУПКА"
        elif bullish == 1: score, verdict = 65, "↗️ Помірна ПОКУПКА"
        if bearish >= 1: warning = "❗️ Сигнал на продаж проти сильного тренду (H4)"; reasons.append(warning)
    elif is_trend_up is False:
        reasons.append("📉 Глобальний тренд: Ведмежий (H4)")
        if bearish >= 2: score, verdict = 15, "⬇️ Сильний ПРОДАЖ"
        elif bearish == 1: score, verdict = 35, "↘️ Помірний ПРОДАЖ"
        if bullish >= 1: warning = "❗️ Сигнал на покупку проти сильного тренду (H4)"; reasons.append(warning)
    else:
        reasons.append("↔️ Глобальний тренд: Боковий/Невизначений (H4)")
        if bullish >= 2: score, verdict = 75, "↗️ Помірна ПОКУПКА"
        elif bearish >= 2: score, verdict = 25, "↘️ Помірний ПРОДАЖ"
    return {"verdict": verdict, "score": score, "warning": warning, "reasons": reasons}

def calculate_pivot_points(daily_df: pd.DataFrame) -> Optional[Dict[str, float]]:
    if daily_df is None or len(daily_df) < 2: return None
    try:
        prev_day = daily_df.iloc[-2]; high, low, close = prev_day['High'], prev_day['Low'], prev_day['Close']
        pivot = (high + low + close) / 3
        return {'P': pivot, 'R1': (2 * pivot) - low, 'S1': (2 * pivot) - high, 'R2': pivot + (high - low), 'S2': pivot - (high - low), 'R3': high + 2 * (pivot - low), 'S3': low - 2 * (pivot - high)}
    except (IndexError, Exception): return None

def _apply_pivot_conflict_override(verdict: str, score: int, current_price: float, pivots: Dict, reasons: List[str]) -> Dict[str, Any]:
    if not pivots: return {"verdict": verdict, "score": score, "support": None, "resistance": None}
    support_levels = sorted([pivots[k] for k in ['S1', 'S2', 'S3'] if k in pivots], reverse=True)
    resistance_levels = sorted([pivots[k] for k in ['R1', 'R2', 'R3'] if k in pivots])
    support = next((s for s in support_levels if s < current_price), None)
    resistance = next((r for r in resistance_levels if r > current_price), None)
    prox_cfg = ANALYSIS_CONFIG["pivot_proximity_percent"]
    for r_level in resistance_levels:
        if r_level and current_price < r_level and (r_level - current_price) / current_price < prox_cfg:
            if score > 60: verdict, score = "⚠️ Ризикована ПОКУПКА", 60; reasons.append(f"❗️ Ціна впритул до Pivot опору ({r_level:.5f})")
            break
    for s_level in support_levels:
        if s_level and current_price > s_level and (current_price - s_level) / current_price < prox_cfg:
            if score < 40: verdict, score = "⚠️ Ризикований ПРОДАЖ", 40; reasons.append(f"❗️ Ціна впритул до Pivot підтримки ({s_level:.5f})")
            break
    return {"verdict": verdict, "score": score, "support": support, "resistance": resistance}

def _calculate_core_signal(df: pd.DataFrame, daily_df: pd.DataFrame, h4_df: pd.DataFrame, current_price: float) -> Dict[str, Any]:
    for frame, name in [(df, "5m"), (daily_df, "D1"), (h4_df, "H4")]:
        validation_error = _validate_data(frame, name)
        if validation_error: return {"score": 50, "reasons": [validation_error], "verdict_text": "🟡 НЕЙТРАЛЬНО"}
    try:
        indicators = _get_technical_indicators(df, h4_df, current_price)
    except Exception as e:
        logger.exception("Indicator calculation failed")
        return {"score": 50, "reasons": ["Помилка розрахунку індикаторів"], "verdict_text": "🟡 НЕЙТРАЛЬНО"}
    bullish, bearish, reasons = _collect_signal_factors(indicators)
    result = _calculate_verdict_and_score(bullish, bearish, indicators["is_trend_up"], reasons)
    pivots = calculate_pivot_points(daily_df)
    pivot_result = _apply_pivot_conflict_override(result["verdict"], result["score"], current_price, pivots, result["reasons"])
    return {
        "score": int(np.clip(pivot_result["score"], 0, 100)),
        "reasons": pivot_result.get("reasons", result["reasons"]),
        "support": pivot_result["support"], "resistance": pivot_result["resistance"],
        "candle_pattern": indicators["candle_pattern"], "volume_info": indicators["volume_info"],
        "critical_warning": result["warning"], "verdict_text": pivot_result["verdict"]
    }

# --- Public API Function ---
def get_api_detailed_signal_data(client, symbol_cache, norm_pair: str, user_id: int, period: str = "15m", count: int = 500) -> Deferred:
    final_deferred = Deferred()
    d_5m = get_market_data(client, symbol_cache, norm_pair, period, count)
    d_d1 = get_market_data(client, symbol_cache, norm_pair, "1day", max(ANALYSIS_CONFIG["min_bars_for_analysis"], count))
    d_h4 = get_market_data(client, symbol_cache, norm_pair, "4h", max(ANALYSIS_CONFIG["min_bars_for_analysis"], count))
    dl = DeferredList([d_5m, d_d1, d_h4], consumeErrors=True)

    def on_ready(results):
        try:
            success_5m, df_5m = results[0]
            success_d1, df_d1 = results[1]
            success_h4, df_h4 = results[2]

            if not all([success_5m, success_d1, success_h4]):
                final_deferred.callback({"error": "Не вдалося завантажити всі необхідні ринкові дані"}); return

            current_price = None
            live_price_data = state.live_prices.get(norm_pair)
            if live_price_data and live_price_data.get("mid") and (time.time() - live_price_data.get("ts", 0)) < 30:
                current_price = float(live_price_data["mid"])
            if current_price is None and not df_5m.empty:
                current_price = float(df_5m.iloc[-1]['Close'])
            if current_price is None:
                final_deferred.callback({"error": "Не вдалося визначити поточну ціну"}); return
            
            analysis = _calculate_core_signal(df_5m, df_d1, df_h4, current_price)
            
            score = analysis.get("score", 50)
            response_data = {"pair": norm_pair, "price": current_price, "verdict_text": analysis.get("verdict_text"), "reasons": analysis.get("reasons", []), "support": analysis.get("support"), "resistance": analysis.get("resistance"), "bull_percentage": int(score), "bear_percentage": 100 - int(score), "candle_pattern": analysis.get("candle_pattern"), "volume_info": analysis.get("volume_info"), "special_warning": analysis.get("critical_warning")}
            
            if user_id != 0: add_signal_to_history({'user_id': user_id, 'pair': norm_pair, 'price': current_price, 'bull_percentage': int(score)})
            
            final_deferred.callback(response_data)
        except Exception as e:
            logger.exception(f"Critical analysis error for {norm_pair}: {e}")
            final_deferred.errback(e)
            
    dl.addCallback(on_ready)
    return final_deferred

# --- Helper functions that are unchanged ---
def analyze_candle_patterns(df: pd.DataFrame):
    try:
        if df.empty or len(df) < 5: return None
        open_v, high_v, low_v, close_v = df['Open'].values, df['High'].values, df['Low'].values, df['Close'].values
        hammer = talib.CDLHAMMER(open_v, high_v, low_v, close_v)[-1]
        engulfing = talib.CDLENGULFING(open_v, high_v, low_v, close_v)[-1]
        doji = talib.CDLDOJI(open_v, high_v, low_v, close_v)[-1]
        if hammer != 0: ptype = 'bullish' if hammer > 0 else 'bearish'; return {'name': 'HAMMER', 'type': ptype, 'text': f"{'⬆️' if ptype == 'bullish' else '⬇️'} HAMMER"}
        if engulfing != 0: ptype = 'bullish' if engulfing > 0 else 'bearish'; return {'name': 'ENGULFING', 'type': ptype, 'text': f"{'⬆️' if ptype == 'bullish' else '⬇️'} ENGULFING"}
        if doji != 0: return {'name': 'DOJI', 'type': 'neutral', 'text': '⚪ DOJI'}
        return None
    except Exception: return None

def analyze_volume(df: pd.DataFrame):
    if df.empty or 'Volume' not in df.columns or len(df) < 21: return "Недостатньо даних"
    try:
        cfg = ANALYSIS_CONFIG
        df['Volume_MA20'] = df['Volume'].rolling(window=20).mean()
        last_vol, last_ma = df.iloc[-1]['Volume'], df.iloc[-1]['Volume_MA20']
        if pd.isna(last_ma): return "Недостатньо даних"
        if last_vol > last_ma * cfg["volume_spike_multiplier"]: return "🟢 Підвищений об'єм"
        if last_vol < last_ma * cfg["volume_low_multiplier"]: return "🧊 Аномально низький об'єм"
        return "Об'єм нейтральний"
    except Exception: return "Помилка аналізу об'єму"