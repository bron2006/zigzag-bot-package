import logging
import pandas as pd
import pandas_ta as ta
import numpy as np
import time
from twisted.internet.defer import Deferred, DeferredList
from twisted.internet import reactor, error as terror

from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAGetTrendbarsReq, ProtoOAGetTrendbarsRes,
    ProtoOASubscribeSpotsReq, ProtoOAUnsubscribeSpotsReq
)
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOATrendbarPeriod as TrendbarPeriod
from db import add_signal_to_history
from economic_calendar import check_for_imminent_news

logger = logging.getLogger(__name__)

PERIOD_MAP = {
    "1m": TrendbarPeriod.M1, "5m": TrendbarPeriod.M5, "15m": TrendbarPeriod.M15,
    "1h": TrendbarPeriod.H1, "4h": TrendbarPeriod.H4, "1day": TrendbarPeriod.D1
}

def _send_with_retry(client, request, timeout=60, retries=1):
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

def get_live_price(client, symbol_cache, norm_pair: str) -> Deferred:
    d = Deferred()
    symbol_details = symbol_cache.get(norm_pair)
    if not symbol_details:
        reactor.callLater(0, d.errback, Exception(f"Символ '{norm_pair}' не знайдено для live price."))
        return d
    symbol_id = symbol_details.symbolId
    account_id = client._client.account_id
    event_name = f"spot_event_{symbol_id}"
    timeout_call = None
    def cleanup():
        unsubscribe_req = ProtoOAUnsubscribeSpotsReq(ctidTraderAccountId=account_id, symbolId=[symbol_id])
        client.send(unsubscribe_req)
        client.remove_listener(event_name, on_spot_event)
        if timeout_call and not timeout_call.called:
            timeout_call.cancel()
    def on_spot_event(spot_event):
        logger.info(f"Live price received for {norm_pair}. Unsubscribing...")
        cleanup()
        if spot_event.HasField('bid') and spot_event.HasField('ask'):
            price = (spot_event.bid + spot_event.ask) / 2
            if not d.called: d.callback(price / (10**5))
        else:
            if not d.called: d.callback(None)
    def on_timeout():
        logger.warning(f"Live price request for {norm_pair} timed out. Market might be closed.")
        cleanup()
        if not d.called: d.callback(None)
    client.on(event_name, on_spot_event)
    timeout_call = reactor.callLater(10, on_timeout)
    logger.info(f"Subscribing to live price for {norm_pair} (symbolId: {symbol_id})")
    subscribe_req = ProtoOASubscribeSpotsReq(ctidTraderAccountId=account_id, symbolId=[symbol_id])
    client.send(subscribe_req)
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
        period=tf_proto,
        fromTimestamp=from_ts,
        toTimestamp=now
    )
    logger.info(f"Requesting candles for {norm_pair} ({period})...")
    deferred = _send_with_retry(client, request, timeout=60, retries=1)
    def process_response(message):
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
    def on_error(failure):
        err = failure.getErrorMessage() if hasattr(failure, 'getErrorMessage') else str(failure)
        logger.error(f"❌ Data request failed for {norm_pair} ({period}): {err}")
        d.errback(failure)
    deferred.addCallbacks(process_response, on_error)
    return d

def group_close_values(values, threshold=0.01):
    if not len(values): return []
    s = pd.Series(sorted(values)).dropna()
    if s.empty: return []
    group_starts = s.pct_change() > threshold
    group_ids = group_starts.cumsum()
    return s.groupby(group_ids).mean().tolist()

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
        if abs(signal_strength) < 100: return None
        pattern_name = found_patterns.index[0].replace("CDL_", "")
        pattern_type = 'bullish' if signal_strength > 0 else 'bearish'
        arrow = '⬆️' if pattern_type == 'bullish' else '⬇️'
        text = f'{arrow} {pattern_name}'
        return {'name': pattern_name, 'type': pattern_type, 'text': text}
    except Exception as e:
        logger.error(f"Помилка в analyze_candle_patterns: {e}")
        return None

def analyze_volume(df):
    if df.empty or 'Volume' not in df.columns or len(df) < 21: return "Недостатньо даних"
    try:
        df['Volume_MA'] = df['Volume'].rolling(window=20).mean()
        last = df.iloc[-1]
        if pd.isna(last['Volume_MA']): return "Недостатньо даних"
        if last['Volume'] > last['Volume_MA'] * 1.5: return "🟢 Підвищений об'єм"
        elif last['Volume'] < last['Volume_MA'] * 0.5: return "🧊 Аномально низький об'єм"
        return "Об'єм нейтральний"
    except Exception: return "Помилка аналізу об'єму"

def _calculate_core_signal(df, daily_df, current_price):
    try:
        df.ta.rsi(length=14, append=True)
        df.ta.kama(length=14, append=True, col_names=('KAMA',))
        df.ta.bbands(length=20, std=2, append=True)
        df.ta.ichimoku(append=True)
        df.ta.macd(append=True)
        df.ta.adx(append=True)
        df.ta.atr(length=14, append=True)
        daily_df.ta.kama(length=14, append=True, col_names=('KAMA_14',))
    except Exception as e:
        logger.error(f"Критична помилка при розрахунку індикаторів: {e}")
        return { "score": 50, "reasons": ["Помилка розрахунку індикаторів"] }

    last = df.iloc[-1]
    last_daily = daily_df.iloc[-1]
    
    score = 50
    reasons = []
    critical_warning = None
    
    long_term_support, long_term_resistance = identify_support_resistance_levels(daily_df)
    candle_pattern = analyze_candle_patterns(df)
    
    is_daily_uptrend = None
    if pd.notna(last_daily.get('KAMA_14')):
        is_daily_uptrend = last_daily['Close'] > last_daily['KAMA_14']
    
    if pd.notna(last.get('MACDh_12_26_9')):
        if last['MACDh_12_26_9'] > 0: score += 15; reasons.append("MACD росте")
        else: score -= 15; reasons.append("MACD падає")

    if pd.notna(last.get('ISA_9')) and pd.notna(last.get('ISB_26')):
         if current_price > max(last['ISA_9'], last['ISB_26']):
             score += 15; reasons.append("Тренд: Ціна над Хмарою")
         else:
             score -= 15; reasons.append("Тренд: Ціна під Хмарою")
    
    neutral_patterns = ["SPINNINGTOP", "DOJI", "DOJISTAR"]
    if candle_pattern:
        if candle_pattern['name'] in neutral_patterns:
            reasons.append(f"Нейтральний патерн: {candle_pattern['name']}")
        elif candle_pattern['type'] == 'bullish':
            score += 20; reasons.append(f"Бичачий патерн: {candle_pattern['name']}")
        else:
            score -= 20; reasons.append(f"Ведмежий патерн: {candle_pattern['name']}")

    rsi = last.get('RSI_14')
    if pd.notna(rsi):
        if rsi < 30: score += 10; reasons.append("Ознаки перепроданості (RSI)")
        elif rsi > 70: score -= 10; reasons.append("Ознаки перекупленості (RSI)")

    last_atr = last.get('ATRr_14')
    if last_atr and pd.notna(last_atr):
        atr_threshold = last_atr * 0.5
        resistance_candidates = [r for r in long_term_resistance if r > current_price]
        if resistance_candidates and (min(resistance_candidates) - current_price) < atr_threshold:
            score -= 20; reasons.append("⚠️ Ціна біля сильного денного опору")
        support_candidates = [s for s in long_term_support if s < current_price]
        if support_candidates and (current_price - max(support_candidates)) < atr_threshold:
            score += 20; reasons.append("⚠️ Ціна біля сильної денної підтримки")

    if is_daily_uptrend is not None:
        if not is_daily_uptrend and score > 65:
            score = 65
            critical_warning = "❗️ Сигнал обмежений через денний даунтренд"
        elif is_daily_uptrend and score < 35:
            score = 35
            critical_warning = "❗️ Сигнал обмежений через денний аптренд"
                
    score = int(np.clip(score, 0, 100))
    
    support_candidates = [s for s in long_term_support if s < current_price]
    support = max(support_candidates) if support_candidates else None
    resistance_candidates = [r for r in long_term_resistance if r > current_price]
    resistance = min(resistance_candidates) if resistance_candidates else None
    
    # --- ДОДАНО: перевірка на конфлікт ---
    if candle_pattern:
        if candle_pattern['type'] == 'bullish':
            if "MACD падає" in reasons or "Тренд: Ціна під Хмарою" in reasons:
                score = 50
                critical_warning = "❗️ Конфлікт сигналів: бичачий патерн суперечить тренду/індикаторам"
        elif candle_pattern['type'] == 'bearish':
            if "MACD росте" in reasons or "Тренд: Ціна над Хмарою" in reasons:
                score = 50
                critical_warning = "❗️ Конфлікт сигналів: ведмежий патерн суперечить тренду/індикаторам"
    
    return {
        "score": score, "reasons": reasons, "support": support, "resistance": resistance,
        "candle_pattern": candle_pattern, "volume_info": analyze_volume(df),
        "critical_warning": critical_warning
    }

def _generate_verdict(score):
    if score > 80: return "⬆️ Strong BUY"
    if score > 65: return "↗️ Moderate BUY"
    if score < 20: return "⬇️ Strong SELL"
    if score < 35: return "↘️ Moderate SELL"
    return "🟡 NEUTRAL"

def get_api_detailed_signal_data(client, symbol_cache, symbol: str, user_id: int, timeframe: str = "15m") -> Deferred:
    def on_data_ready(results):
        try:
            success1, df = results[0]
            success2, daily_df = results[1]
            success3, live_price = results[2]

            if not (success1 and success2) or df.empty or len(df) < 50 or daily_df.empty:
                return {"error": f"Not enough historical data for {timeframe} analysis."}

            current_price = live_price if success3 and live_price is not None else df.iloc[-1]['Close']
            
            has_news, news_text = check_for_imminent_news(symbol)
            
            analysis = _calculate_core_signal(df, daily_df, current_price)

            final_warning = None
            if has_news:
                analysis['score'] = 50
                analysis['reasons'] = [f"❗️ {news_text}"]
                final_warning = news_text
            else:
                final_warning = analysis.get("critical_warning")
            
            verdict = _generate_verdict(analysis['score'])

            add_signal_to_history({
                'user_id': user_id, 'pair': symbol, 
                'price': current_price, 'bull_percentage': analysis['score']
            })
            
            response_data = {
                "pair": symbol, "price": current_price, "verdict_text": verdict, 
                "reasons": analysis['reasons'], "support": analysis['support'], 
                "resistance": analysis['resistance'], "bull_percentage": analysis['score'],
                "bear_percentage": 100 - analysis['score'], "candle_pattern": analysis.get('candle_pattern'),
                "volume_info": analysis.get('volume_info'),
                "special_warning": final_warning
            }
            return response_data
            
        except Exception as e:
            logger.exception(f"Critical analysis error for {symbol}: {e}")
            return {"error": "Internal data processing error."}

    d1 = get_market_data(client, symbol_cache, symbol, timeframe, 200)
    d2 = get_market_data(client, symbol_cache, symbol, '1day', 100)
    d3 = get_live_price(client, symbol_cache, symbol)
    
    d_list = DeferredList([d1, d2, d3], consumeErrors=True)
    d_list.addCallback(on_data_ready)
    return d_list