# analysis.py
import logging
import time
import json
from typing import Tuple, List

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
from redis_client import get_redis

logger = logging.getLogger("analysis")

PERIOD_MAP = {
    "1m": TrendbarPeriod.M1,
    "5m": TrendbarPeriod.M5,
    "15m": TrendbarPeriod.M15,
    "1h": TrendbarPeriod.H1,
    "4h": TrendbarPeriod.H4,
    "1day": TrendbarPeriod.D1
}

# ----------------- low-level helpers -----------------
def _send_with_retry(client, request, timeout=60, retries=1) -> Deferred:
    d = Deferred()
    def _attempt(remaining):
        inner = client.send(request, timeout=timeout)
        def ok(msg):
            if not d.called:
                d.callback(msg)
        def err(f):
            # retry on timeout
            if f.check(terror.TimeoutError) and remaining > 0:
                logger.warning(f"Request {type(request).__name__} timed out, retrying ({remaining} left)...")
                reactor.callLater(0.2, _attempt, remaining - 1)
            else:
                if not d.called:
                    d.errback(f)
        inner.addCallbacks(ok, err)
    _attempt(retries)
    return d

def get_market_data(client, symbol_cache, norm_pair: str, period: str, count: int) -> Deferred:
    """
    Запит барів до cTrader через Open API, повертає Deferred -> pandas.DataFrame
    DataFrame колонки: ['ts','Open','High','Low','Close','Volume']
    """
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
        period=tf_proto,
        fromTimestamp=from_ts,
        toTimestamp=now
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
            bars = [{
                'ts': pd.to_datetime(bar.utcTimestampInMinutes * 60, unit='s', utc=True),
                'Open': (bar.low + bar.deltaOpen) / divisor,
                'High': (bar.low + bar.deltaHigh) / divisor,
                'Low': bar.low / divisor,
                'Close': (bar.low + bar.deltaClose) / divisor,
                'Volume': bar.volume
            } for bar in response.trendbar]
            df = pd.DataFrame(bars)
            d.callback(df.sort_values(by='ts').reset_index(drop=True))
        except Exception as e:
            logger.exception(f"Error processing trendbars for {norm_pair}: {e}")
            d.errback(e)

    def on_error(failure):
        err = failure.getErrorMessage() if hasattr(failure, 'getErrorMessage') else str(failure)
        logger.error(f"❌ Data request failed for {norm_pair} ({period}): {err}")
        d.errback(failure)

    deferred.addCallbacks(process_response, on_error)
    return d

def get_price_from_redis(norm_pair: str, stale_sec: int = 15) -> Deferred:
    """
    Читає останній тік з Redis: key = tick:<SYMBOL>.
    Повертає Deferred, що дасть float (mid) або None.
    Запускається у threadpool щоб не блокувати reactor.
    """
    def _fetch():
        try:
            r = get_redis()
            raw = r.get(f"tick:{norm_pair}")
            if not raw:
                return None
            data = json.loads(raw)
            ts_ms = data.get("ts_ms")
            if ts_ms and (time.time() * 1000 - ts_ms) > stale_sec * 1000:
                return None
            bid = data.get("bid")
            ask = data.get("ask")
            mid = data.get("mid")
            if mid is not None:
                return float(mid)
            if bid is not None and ask is not None:
                return (float(bid) + float(ask)) / 2.0
            return None
        except Exception as e:
            logger.exception(f"get_price_from_redis error for {norm_pair}: {e}")
            return None
    return threads.deferToThread(_fetch)

# ----------------- analysis helpers -----------------
def group_close_values(values: List[float], threshold=0.01) -> List[float]:
    if not len(values):
        return []
    s = pd.Series(sorted(values)).dropna()
    if s.empty:
        return []
    group_starts = s.pct_change() > threshold
    group_ids = group_starts.cumsum()
    return s.groupby(group_ids).mean().tolist()

def identify_support_resistance_levels(df: pd.DataFrame, window=20, threshold=0.01) -> Tuple[List[float], List[float]]:
    """
    Простий пошук локальних екстремумів на daily DF.
    Повертає (supports, resistances).
    """
    try:
        lows = df['Low'].rolling(window=window, center=True, min_periods=3).min()
        highs = df['High'].rolling(window=window, center=True, min_periods=3).max()
        support_levels = group_close_values(df.loc[df['Low'] == lows, 'Low'].tolist(), threshold)
        resistance_levels = group_close_values(df.loc[df['High'] == highs, 'High'].tolist(), threshold)
        return sorted(support_levels), sorted(resistance_levels, reverse=True)
    except Exception as e:
        logger.exception(f"identify_support_resistance_levels error: {e}")
        return [], []

def analyze_candle_patterns(df: pd.DataFrame):
    """
    Повертає словник з полями 'name','type','text' або None.
    Використовує TA-Lib для HAMMER та DOJI та ENGULF.
    """
    try:
        last = df.iloc[-1]
        open_v = df['Open'].values
        high_v = df['High'].values
        low_v = df['Low'].values
        close_v = df['Close'].values

        hammer_arr = talib.CDLHAMMER(open_v, high_v, low_v, close_v)
        doji_arr = talib.CDLDOJI(open_v, high_v, low_v, close_v)
        engulfing = talib.CDLENGULFING(open_v, high_v, low_v, close_v)

        last_hammer = int(hammer_arr[-1]) if len(hammer_arr) else 0
        last_doji = int(doji_arr[-1]) if len(doji_arr) else 0
        last_engulf = int(engulfing[-1]) if len(engulfing) else 0

        if last_hammer != 0:
            pattern_type = 'bullish' if last_hammer > 0 else 'bearish'
            arrow = '⬆️' if pattern_type == 'bullish' else '⬇️'
            return {'name': 'HAMMER', 'type': pattern_type, 'text': f"{arrow} HAMMER"}
        if last_engulf != 0:
            pattern_type = 'bullish' if last_engulf > 0 else 'bearish'
            arrow = '⬆️' if pattern_type == 'bullish' else '⬇️'
            return {'name': 'ENGULFING', 'type': pattern_type, 'text': f"{arrow} ENGULFING"}
        if last_doji != 0:
            return {'name': 'DOJI', 'type': 'neutral', 'text': '⚪ DOJI'}
        return None
    except Exception as e:
        logger.exception(f"analyze_candle_patterns error: {e}")
        return None

def analyze_volume(df: pd.DataFrame):
    if df.empty or 'Volume' not in df.columns or len(df) < 21:
        return "Недостатньо даних"
    try:
        df = df.copy()
        df['Volume_MA20'] = df['Volume'].rolling(window=20).mean()
        last = df.iloc[-1]
        if pd.isna(last['Volume_MA20']):
            return "Недостатньо даних"
        if last['Volume'] > last['Volume_MA20'] * 1.5:
            return "🟢 Підвищений об'єм"
        elif last['Volume'] < last['Volume_MA20'] * 0.5:
            return "🧊 Аномально низький об'єм"
        return "Об'єм нейтральний"
    except Exception as e:
        logger.exception(f"analyze_volume error: {e}")
        return "Помилка аналізу об'єму"

def _calculate_core_signal(df: pd.DataFrame, daily_df: pd.DataFrame, current_price: float):
    """
    Основна логіка сигналу.
    Повертає dict з ключами:
    score (0..100), reasons(list), support, resistance, candle_pattern, volume_info, critical_warning
    """
    try:
        # Перевірки вхідних даних
        if df.empty or daily_df.empty or len(df) < 50:
            return {"score": 50, "reasons": ["Недостатньо даних для аналізу"]}

        # Підготовка series
        close = df['Close'].values
        high = df['High'].values
        low = df['Low'].values
        open_v = df['Open'].values
        vol = df['Volume'].values

        close_daily = daily_df['Close'].values
        high_daily = daily_df['High'].values
        low_daily = daily_df['Low'].values

        # Індикатори (на останніх значеннях)
        ema50 = talib.EMA(close, timeperiod=50)
        ema200 = talib.EMA(close, timeperiod=200)
        ema200_daily = talib.EMA(close_daily, timeperiod=200)

        rsi = talib.RSI(close, timeperiod=14)
        rsi_last = float(rsi[-1]) if len(rsi) else np.nan

        macd, macdsignal, macdhist = talib.MACD(close, fastperiod=12, slowperiod=26, signalperiod=9)
        macd_last = float(macd[-1]) if len(macd) else np.nan
        macd_sig_last = float(macdsignal[-1]) if len(macdsignal) else np.nan
        macd_hist_last = float(macdhist[-1]) if len(macdhist) else np.nan

        atr = talib.ATR(high, low, close, timeperiod=14)
        atr_last = float(atr[-1]) if len(atr) else np.nan

        adx = talib.ADX(high, low, close, timeperiod=14)
        adx_last = float(adx[-1]) if len(adx) else np.nan

        candle_pattern = analyze_candle_patterns(df)
        volume_info = analyze_volume(df)

    except Exception as e:
        logger.exception(f"Indicator calculation failed: {e}")
        return {"score": 50, "reasons": ["Помилка розрахунку індикаторів"]}

    reasons = []
    critical_warning = None
    score = 50

    # Global trend by daily EMA200
    try:
        ema200_daily_last = float(ema200_daily[-1]) if len(ema200_daily) else None
        is_daily_uptrend = None
        if ema200_daily_last is not None:
            is_daily_uptrend = current_price > ema200_daily_last
    except Exception:
        is_daily_uptrend = None

    # Factors
    bullish_factors = 0
    bearish_factors = 0

    # MACD
    if not np.isnan(macd_hist_last):
        if macd_hist_last > 0:
            bullish_factors += 1
            reasons.append("MACD росте")
        else:
            bearish_factors += 1
            reasons.append("MACD падає")

    # Candle pattern
    if candle_pattern:
        pname = candle_pattern.get('name', '').upper()
        if candle_pattern.get('type') == 'bullish':
            bullish_factors += 1
            reasons.append(f"Бичачий патерн: {pname}")
        elif candle_pattern.get('type') == 'bearish':
            bearish_factors += 1
            reasons.append(f"Ведмежий патерн: {pname}")
        else:
            reasons.append(f"Нейтральний патерн: {pname}")

    # RSI
    if not np.isnan(rsi_last):
        if rsi_last < 30:
            bullish_factors += 1
            reasons.append("Ознаки перепроданості (RSI)")
        elif rsi_last > 70:
            bearish_factors += 1
            reasons.append("Ознаки перекупленості (RSI)")

    # ADX strength
    if not np.isnan(adx_last):
        if adx_last > 25:
            reasons.append("Сильний тренд (ADX>25)")

    # Volume signal
    if volume_info == "🟢 Підвищений об'єм":
        bullish_factors += 1
        reasons.append("Підвищений об'єм підтверджує рух")
    elif volume_info == "🧊 Аномально низький об'єм":
        reasons.append("Мало об'єму")

    # Support/resistance (daily)
    long_term_support, long_term_resistance = identify_support_resistance_levels(daily_df)
    support = max([s for s in long_term_support if s < current_price], default=None) if long_term_support else None
    resistance = min([r for r in long_term_resistance if r > current_price], default=None) if long_term_resistance else None

    # Decision rules: require at least two confirming factors for a strong signal,
    # and respect daily EMA200 as primary trend filter.

    # If daily trend bullish
    if is_daily_uptrend is True:
        if bullish_factors >= 2:
            score = 90
            verdict = "⬆️ Сильна ПОКУПКА"
        elif bullish_factors == 1:
            score = 65
            verdict = "↗️ Помірна ПОКУПКА"
        elif bearish_factors >= 2:
            score = 25
            verdict = "↘️ Помірний ПРОДАЖ"
        else:
            score = 50
            verdict = "🟡 НЕЙТРАЛЬНО"

    # If daily trend bearish
    elif is_daily_uptrend is False:
        # do not allow single hammer to make a strong buy
        if bullish_factors >= 2:
            # bullish signs but against daily trend -> weaker
            score = 60
            verdict = "↗️ Помірна ПОКУПКА (проти денного тренду)"
            critical_warning = "❗️ Сигнал проти денного даунтренду"
        elif bullish_factors == 1 and "Бичачий патерн: HAMMER" in reasons:
            score = 55
            verdict = "⚠️ Можливий відскок (HAMMER), але денний тренд ведмежий"
            critical_warning = "❗️ HAMMER без підтвердження від індикаторів"
        elif bearish_factors >= 2:
            score = 10
            verdict = "⬇️ Сильний ПРОДАЖ"
        else:
            score = 50
            verdict = "🟡 НЕЙТРАЛЬНО"

    # If daily trend unknown
    else:
        if bullish_factors >= 2:
            score = 75
            verdict = "↗️ Помірна ПОКУПКА"
        elif bearish_factors >= 2:
            score = 25
            verdict = "↘️ Помірний ПРОДАЖ"
        else:
            score = 50
            verdict = "🟡 НЕЙТРАЛЬНО"

    # Final safety checks
    # If RSI extreme cancels strong signal
    try:
        if score >= 80 and not np.isnan(rsi_last) and rsi_last > 75:
            score = 50
            critical_warning = "❗️ Сигнал скасовано: сильна перекупленість (RSI>75)"
            reasons.append(critical_warning)
        if score <= 20 and not np.isnan(rsi_last) and rsi_last < 25:
            score = 50
            critical_warning = "❗️ Сигнал скасовано: сильна перепроданість (RSI<25)"
            reasons.append(critical_warning)
    except Exception:
        pass

    score = int(np.clip(score, 0, 100))

    return {
        "score": score,
        "reasons": reasons,
        "support": support,
        "resistance": resistance,
        "candle_pattern": candle_pattern,
        "volume_info": volume_info,
        "critical_warning": critical_warning,
        "verdict_text": verdict
    }

# ----------------- public API -----------------
def get_api_detailed_signal_data(client, symbol_cache, symbol: str, user_id: int, timeframe: str = "15m") -> Deferred:
    """
    Основна точка входу. Повертає Deferred, який callback дасть dict у форматі:
    {
      "pair": symbol,
      "price": current_price,
      "verdict_text": "...",
      "reasons": [...],
      "support": ...,
      "resistance": ...,
      "bull_percentage": int,
      "bear_percentage": int,
      "candle_pattern": {...},
      "volume_info": "...",
      "special_warning": "..."  # optional
    }
    """
    final_deferred = Deferred()

    def on_data_ready(results):
        try:
            success1, df = results[0]
            success2, daily_df = results[1]
            success3, live_price = results[2]

            if not (success1 and success2) or df.empty or len(df) < 50 or daily_df.empty:
                if not final_deferred.called:
                    final_deferred.callback({"error": f"Not enough historical data for {timeframe} analysis."})
                return

            current_price = live_price if success3 and live_price is not None else float(df.iloc[-1]['Close'])

            analysis = _calculate_core_signal(df, daily_df, current_price)
            special_warning = analysis.get("critical_warning")

            verdict = analysis.get("verdict_text", _generate_verdict(analysis.get("score", 50)))
            score = analysis.get("score", 50)

            # persist minimal history
            try:
                add_signal_to_history({
                    'user_id': user_id, 'pair': symbol,
                    'price': current_price, 'bull_percentage': score
                })
            except Exception:
                logger.exception("Failed to add signal to history")

            response_data = {
                "pair": symbol,
                "price": current_price,
                "verdict_text": verdict,
                "reasons": analysis.get("reasons", []),
                "support": analysis.get("support"),
                "resistance": analysis.get("resistance"),
                "bull_percentage": score,
                "bear_percentage": 100 - score,
                "candle_pattern": analysis.get("candle_pattern"),
                "volume_info": analysis.get("volume_info"),
                "special_warning": special_warning
            }

            if not final_deferred.called:
                final_deferred.callback(response_data)

        except Exception as e:
            logger.exception(f"Critical analysis error for {symbol}: {e}")
            if not final_deferred.called:
                final_deferred.errback(e)

    # Start async requests
    d1 = get_market_data(client, symbol_cache, symbol, timeframe, 200)
    d2 = get_market_data(client, symbol_cache, symbol, '1day', 100)
    d3 = get_price_from_redis(symbol)

    dl = DeferredList([d1, d2, d3], consumeErrors=True)
    dl.addCallback(on_data_ready)
    return final_deferred

def _generate_verdict(score: int) -> str:
    if score > 80: return "⬆️ Сильна ПОКУПКА"
    if score > 65: return "↗️ Помірна ПОКУПКА"
    if score < 20: return "⬇️ Сильний ПРОДАЖ"
    if score < 35: return "↘️ Помірний ПРОДАЖ"
    return "🟡 НЕЙТРАЛЬНО"
