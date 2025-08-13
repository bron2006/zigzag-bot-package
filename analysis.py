# analysis.py
import pandas as pd
import pandas_ta as ta
import numpy as np
from concurrent.futures import ThreadPoolExecutor

# --- ПОВНІСТЮ ВИПРАВЛЕНИЙ БЛОК ІМПОРТІВ ---
from ctrader_open_api.client import Client
from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAGetTrendbarsReq, ProtoOAGetTrendbarsRes, ProtoOAApplicationAuthReq, ProtoOAAccountAuthReq
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOATrendbarPeriod as TrendbarPeriod

from db import add_signal_to_history
from config import logger, MARKET_DATA_CACHE, ANALYSIS_TIMEFRAMES, CT_CLIENT_ID, CT_CLIENT_SECRET
from ctrader_api import get_valid_access_token

_executor = None
def get_executor():
    global _executor
    if _executor is None: _executor = ThreadPoolExecutor(max_workers=4)
    return _executor

def get_asset_type(pair: str) -> str:
    if '/' in pair: return 'crypto' if 'USDT' in pair else 'forex'
    return 'stocks'

def get_market_data(pair, tf, asset, limit=300, force_refresh=False, user_id=None):
    key = f"{pair}_{tf}_{limit}"
    if not force_refresh and key in MARKET_DATA_CACHE:
        return MARKET_DATA_CACHE[key]
    
    try:
        df = pd.DataFrame()
        if asset == 'crypto':
            logger.info("Крипто-модуль вимкнено, пропускаємо запит.")
            return pd.DataFrame()
        
        elif asset == 'forex':
            if not user_id: 
                logger.warning("user_id не надано для запиту Forex.")
                return pd.DataFrame()

            DEMO_ACCOUNT_ID = 9541520
            access_token = get_valid_access_token(user_id)
            if not access_token:
                logger.error(f"Не вдалося отримати валідний access_token для user_id: {user_id}")
                return pd.DataFrame()
            
            # --- ВИПРАВЛЕНО ІНІЦІАЛІЗАЦІЮ КЛІЄНТА ---
            client = Client("demo.ctraderapi.com", 5035, ssl=True)

            tf_map = {
                "1m": TrendbarPeriod.M1, "15min": TrendbarPeriod.M15,
                "1h": TrendbarPeriod.H1, "4h": TrendbarPeriod.H4, "1day": TrendbarPeriod.D1
            }
            if tf not in tf_map:
                logger.error(f"Непідтримуваний таймфрейм для cTrader: {tf}")
                return pd.DataFrame()

            def send_request(request):
                response_event = client.send(request)
                if response_event.wait(timeout=20): # Збільшено таймаут
                    return response_event.message
                logger.error(f"Запит {type(request).__name__} не отримав відповіді (таймаут).")
                return None

            with client:
                app_auth_res = send_request(ProtoOAApplicationAuthReq(clientId=CT_CLIENT_ID, clientSecret=CT_CLIENT_SECRET))
                if app_auth_res is None:
                    logger.error("Помилка авторизації додатку.")
                    return pd.DataFrame()
                    
                acc_auth_res = send_request(ProtoOAAccountAuthReq(ctidTraderAccountId=DEMO_ACCOUNT_ID, accessToken=access_token))
                if acc_auth_res is None:
                    logger.error("Помилка авторизації акаунту.")
                    return pd.DataFrame()
                
                request = ProtoOAGetTrendbarsReq(
                    ctidTraderAccountId=DEMO_ACCOUNT_ID,
                    symbolName=pair,
                    period=tf_map[tf],
                    count=limit
                )
                response = send_request(request)

                if isinstance(response, ProtoOAGetTrendbarsRes):
                    logger.info(f"✅ УСПІХ! Отримано {len(response.trendbar)} свічок для {pair} з cTrader.")
                    bars = [{'ts': pd.to_datetime(bar.utcTimestampInMinutes * 60, unit='s', utc=True),
                             'open': bar.open / 100000.0, 'high': bar.high / 100000.0,
                             'low': bar.low / 100000.0, 'close': bar.close / 100000.0,
                             'volume': bar.volume} for bar in response.trendbar]
                    df = pd.DataFrame(bars)
                else:
                    logger.error(f"❌ Помилка або невірна відповідь від API cTrader: {response}")
            
        elif asset == 'stocks':
            logger.warning(f"Модуль аналізу акцій вимкнено. Пропускаю запит для {pair}.")
            return pd.DataFrame()

        if df.empty: return pd.DataFrame()
        df.columns = [str(col).lower() for col in df.columns]
        if not df.empty:
            df = df.sort_values(by='ts').reset_index(drop=True)
        MARKET_DATA_CACHE[key] = df
        return df
    except Exception as e:
        logger.error(f"Помилка отримання даних для {pair} ({asset}, {tf}): {e}", exc_info=True)
        return pd.DataFrame()

# ... решта файлу `analysis.py` залишається без змін ...
def get_signal_strength_verdict(pair, display_name, asset, user_id=None, force_refresh=False):
    df = get_market_data(pair, '1m', asset, limit=100, force_refresh=force_refresh, user_id=user_id)
    if df.empty or len(df) < 25:
        return f"⚠️ Недостатньо даних для аналізу *{display_name}*.", None
    try:
        daily_df = get_market_data(pair, '1day', asset, limit=100, force_refresh=force_refresh, user_id=user_id)
        analysis = _calculate_core_signal(df, daily_df)
        add_signal_to_history({'user_id': user_id, 'pair': pair, 'price': analysis['price'], 'bull_percentage': analysis['score']})
        
        verdict_text, _ = _generate_verdict(analysis)
        formatted_price = f"{analysis['price']:.5f}"
        final_message = (f"**{verdict_text}**\n\n"
                         f"*{display_name}* | *Ціна:* `{formatted_price}`\n\n"
                         f"_Це не фінансова порада. Для деталей натисніть кнопки нижче._")
        return final_message, analysis
    except Exception as e:
        logger.error(f"Помилка розрахунку індексу для {pair}: {e}")
        return f"⚠️ Помилка аналізу *{display_name}*.", None

def get_full_mta_verdict(pair, display_name, asset, force_refresh=False, user_id=None):
    def worker(tf):
        df = get_market_data(pair, tf, asset, limit=200, force_refresh=force_refresh, user_id=user_id)
        if df.empty or len(df) < 55: return (tf, None)
        df.ta.ema(close=df['close'], length=21, append=True, col_names=('EMA_fast',))
        df.ta.ema(close=df['close'], length=55, append=True, col_names=('EMA_slow',))
        sig = "✅ BUY" if df.iloc[-1]['EMA_fast'] > df.iloc[-1]['EMA_slow'] else "❌ SELL"
        return (tf, sig)
    results = [worker(tf) for tf in ANALYSIS_TIMEFRAMES]
    rows_data = [r for r in results if r[1] is not None]
    if not rows_data:
        return f"**📊 Детальний огляд тренду:** *{display_name}*\n\nНе вдалося згенерувати жодного сигналу."
    report = "\n".join([f"• *{tf}:* {sig}" for tf, sig in rows_data])
    return f"**📊 Детальний огляд тренду:** *{display_name}*\n\n{report}"

def get_api_detailed_signal_data(pair, user_id=None):
    asset = get_asset_type(pair)
    df = get_market_data(pair, '15min', asset, limit=100, user_id=user_id)
    if df.empty or len(df) < 25: return {"error": "Недостатньо даних для аналізу."}
    try:
        daily_df = get_market_data(pair, '1day', asset, limit=100, user_id=user_id)
        analysis = _calculate_core_signal(df, daily_df)
        verdict_text, verdict_level = _generate_verdict(analysis)
        
        date_col = 'ts'
        history_df = df.tail(50)
        history = { "dates": history_df[date_col].dt.strftime('%Y-%m-%d %H:%M:%S').tolist(), "open": history_df['open'].tolist(), "high": history_df['high'].tolist(), "low": history_df['low'].tolist(), "close": history_df['close'].tolist() }
        
        return { "pair": pair, "price": analysis['price'], "verdict_text": verdict_text, "verdict_level": verdict_level, "reasons": analysis['reasons'], "support": analysis['support'], "resistance": analysis['resistance'], "history": history }
    except Exception as e: return {"error": str(e)}

def get_api_mta_data(pair, asset, user_id=None):
    def worker(tf):
        df = get_market_data(pair, tf, asset, limit=200, user_id=user_id)
        if df.empty or len(df) < 55: return None
        df.ta.ema(close=df['close'], length=21, append=True, col_names=('EMA_fast',))
        df.ta.ema(close=df['close'], length=55, append=True, col_names=('EMA_slow',))
        signal = "BUY" if df.iloc[-1]['EMA_fast'] > df.iloc[-1]['EMA_slow'] else "SELL"
        return {"tf": tf, "signal": signal}
    results = [worker(tf) for tf in ANALYSIS_TIMEFRAMES]
    return [r for r in results if r is not None]

def rank_assets_for_api(pairs, asset_type, user_id=None):
    if not pairs:
        return []
    def fetch_score(pair):
        df = get_market_data(pair, '1h', asset_type, limit=50, user_id=user_id)
        if df.empty or len(df) < 30: return {'ticker': pair, 'score': -1}
        rsi = df.ta.rsi(close=df['close'], length=14).iloc[-1]
        return {'ticker': pair, 'score': -1 if pd.isna(rsi) else abs(rsi - 50)}
    results = list(get_executor().map(fetch_score, pairs))
    active = sorted([r for r in results if r['score'] != -1], key=lambda x: x['score'], reverse=True)
    return active + [r for r in results if r['score'] == -1]

def _calculate_core_signal(df, daily_df):
    df.ta.rsi(close=df['close'], length=14, append=True, col_names=('RSI',))
    df.ta.kama(close=df['close'], length=14, append=True, col_names=('KAMA',))
    last = df.iloc[-1]
    if pd.isna(last['RSI']) or pd.isna(last['KAMA']): raise ValueError("Помилка розрахунку індикаторів")
    
    current_price = float(last['close'])
    support, resistance = _find_sr_levels(daily_df, current_price)
    
    score, reasons = 50, []
    if current_price > last['KAMA']: score += 15; reasons.append("Ціна вище лінії KAMA(14)")
    else: score -= 15; reasons.append("Ціна нижче лінії KAMA(14)")
    if last['RSI'] < 30: score += 20; reasons.append("RSI в зоні перепроданості (<30)")
    elif last['RSI'] > 70: score -= 20; reasons.append("RSI в зоні перекупленості (>70)")
    
    score = int(np.clip(score, 0, 100))
    return { "score": score, "reasons": reasons, "support": support, "resistance": resistance, "price": current_price }

def _find_sr_levels(df, current_price):
    if df.empty or len(df) < 10: return None, None
    lows = df['low'].tail(30)
    highs = df['high'].tail(30)
    support = lows[lows < current_price].max()
    resistance = highs[highs > current_price].min()
    return support if pd.notna(support) else None, resistance if pd.notna(resistance) else None

def _generate_verdict(analysis):
    score = analysis['score']
    if score > 65:
        return "⬆️ Сильний сигнал: КУПУВАТИ", "strong_buy"
    if score > 55:
        return "↗️ Помірний сигнал: КУПУВАТИ", "moderate_buy"
    if score < 35:
        return "⬇️ Сильний сигнал: ПРОДАВАТИ", "strong_sell"
    if score < 45:
        return "↘️ Помірний сигнал: ПРОДАВАТИ", "moderate_sell"
    return "🟡 НЕЙТРАЛЬНА СИТУАЦІЯ", "neutral"