# analysis.py
import pandas as pd
import pandas_ta as ta
import numpy as np
from concurrent.futures import ThreadPoolExecutor
import threading
import time

from ctrader_open_api import Client, TcpProtocol
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import ProtoMessage
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOATrendbarPeriod as TrendbarPeriod
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAApplicationAuthReq, ProtoOAAccountAuthReq, ProtoOAErrorRes,
    ProtoOAGetTrendbarsReq, ProtoOAGetTrendbarsRes,
    ProtoOASymbolsListReq, ProtoOASymbolsListRes,
    ProtoOASymbolByIdReq, ProtoOASymbolByIdRes
)

from db import add_signal_to_history
from config import (
    logger, MARKET_DATA_CACHE, SYMBOL_DATA_CACHE, CACHE_LOCK,
    ANALYSIS_TIMEFRAMES, CT_CLIENT_ID, CT_CLIENT_SECRET, DEMO_ACCOUNT_ID
)
from ctrader_api import get_valid_access_token

_executor = None

def get_executor():
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=4)
    return _executor

def get_asset_type(pair: str) -> str:
    if '/' in pair:
        return 'crypto' if 'USDT' in pair else 'forex'
    return 'stocks'

def _connect_and_run(user_id, requests_to_send, on_message_handler, timeout=20):
    """Утиліта для підключення, виконання запитів та обробки відповідей."""
    access_token = get_valid_access_token(user_id)
    if not access_token:
        logger.error(f"Не вдалося виконати запит: невалідний токен для user_id: {user_id}")
        return False

    response_received = threading.Event()
    error_message = None

    def on_error(client_instance, error):
        nonlocal error_message
        error_message = f"Помилка від cTrader API: {error}"
        logger.error(error_message)
        if not response_received.is_set():
            response_received.set()

    def on_message_wrapper(client_instance, message: ProtoMessage):
        if message.payloadType == ProtoOAErrorRes.payload_type:
            error_res = ProtoOAErrorRes()
            error_res.ParseFromString(message.payload)
            # Викликаємо основний обробник помилок, щоб уніфікувати логіку
            on_error(client_instance, f"Код: {error_res.errorCode}, Опис: {error_res.description}")
        else:
            on_message_handler(message, response_received)

    # --- ВИПРАВЛЕННЯ: Передаємо обробники в конструктор ---
    client = Client("demo.ctraderapi.com", 5035, TcpProtocol, on_message=on_message_wrapper, on_error=on_error)
    # ----------------------------------------------------
    
    client_thread = threading.Thread(target=client.start, daemon=True)
    client_thread.start()
    
    if not client.wait_for_connect(timeout=15):
        logger.error("Не вдалося підключитися до cTrader API (таймаут).")
        client.stop()
        client_thread.join(timeout=5)
        return False

    try:
        auth_req = ProtoOAApplicationAuthReq(clientId=CT_CLIENT_ID, clientSecret=CT_CLIENT_SECRET)
        if not client.send(auth_req).wait(timeout=15):
            raise Exception("Авторизація додатку не вдалася.")
        
        acc_auth_req = ProtoOAAccountAuthReq(ctidTraderAccountId=DEMO_ACCOUNT_ID, accessToken=access_token)
        if not client.send(acc_auth_req).wait(timeout=15):
            raise Exception("Авторизація акаунту не вдалася.")

        for request in requests_to_send:
            response_received.clear()
            client.send(request)
            if not response_received.wait(timeout=timeout):
                raise Exception(f"Таймаут очікування відповіді для запиту {type(request).__name__}")
            if error_message:
                raise Exception(error_message)
    except Exception as e:
        logger.error(f"Помилка під час взаємодії з cTrader: {e}", exc_info=True)
        return False
    finally:
        client.stop()
        client_thread.join(timeout=5)
    return True

def update_symbols_cache(user_id):
    """Отримує всі символи, їх ID та digits, і кешує їх."""
    all_symbol_ids = []
    
    def on_symbols_list_message(message: ProtoMessage, event: threading.Event):
        nonlocal all_symbol_ids
        if message.payloadType == ProtoOASymbolsListRes.payload_type:
            response = ProtoOASymbolsListRes()
            response.ParseFromString(message.payload)
            all_symbol_ids.extend([s.symbolId for s in response.symbol])
            event.set()

    logger.info("Отримую список ID всіх символів...")
    list_req = ProtoOASymbolsListReq(ctidTraderAccountId=DEMO_ACCOUNT_ID)
    if not _connect_and_run(user_id, [list_req], on_symbols_list_message):
        logger.error("Не вдалося отримати список ID символів.")
        return
    logger.info(f"Отримано {len(all_symbol_ids)} ID символів. Завантажую деталі...")

    def on_symbol_details_message(message: ProtoMessage, event: threading.Event):
        if message.payloadType == ProtoOASymbolByIdRes.payload_type:
            response = ProtoOASymbolByIdRes()
            response.ParseFromString(message.payload)
            with CACHE_LOCK:
                for symbol in response.symbol:
                    SYMBOL_DATA_CACHE[symbol.symbolName] = {'symbolId': symbol.symbolId, 'digits': symbol.digits}
            logger.info(f"Закешовано деталі для {len(response.symbol)} символів.")
            event.set()

    chunk_size = 70
    detail_requests = []
    for i in range(0, len(all_symbol_ids), chunk_size):
        chunk = all_symbol_ids[i:i + chunk_size]
        detail_requests.append(ProtoOASymbolByIdReq(ctidTraderAccountId=DEMO_ACCOUNT_ID, symbolId=chunk))

    if not _connect_and_run(user_id, detail_requests, on_symbol_details_message):
        logger.error("Не вдалося отримати деталі символів.")

def get_market_data(pair, tf, asset, limit=300, force_refresh=False, user_id=None):
    key = f"{pair}_{tf}_{limit}"
    
    with CACHE_LOCK:
        if not force_refresh and key in MARKET_DATA_CACHE:
            return MARKET_DATA_CACHE[key]

    if asset != 'forex':
        return pd.DataFrame()

    if not user_id:
        logger.warning("user_id не надано для запиту Forex.")
        return pd.DataFrame()

    with CACHE_LOCK:
        symbol_details = SYMBOL_DATA_CACHE.get(pair)
    
    if not symbol_details:
        logger.error(f"Деталі для символу {pair} не знайдено в кеші. Можливо, кеш ще не завантажено.")
        return pd.DataFrame()

    tf_map = {"1m": TrendbarPeriod.M1, "15min": TrendbarPeriod.M15, "1h": TrendbarPeriod.H1, "4h": TrendbarPeriod.H4, "1day": TrendbarPeriod.D1}
    if tf not in tf_map:
        return pd.DataFrame()

    result_df = pd.DataFrame()

    def on_trendbars_message(message: ProtoMessage, event: threading.Event):
        nonlocal result_df
        if message.payloadType == ProtoOAGetTrendbarsRes.payload_type:
            response = ProtoOAGetTrendbarsRes()
            response.ParseFromString(message.payload)
            
            divisor = 10**symbol_details['digits']
            bars = [{'ts': pd.to_datetime(bar.utcTimestampInMinutes * 60, unit='s', utc=True),
                     'open': (bar.low + bar.deltaOpen) / divisor,
                     'high': (bar.low + bar.deltaHigh) / divisor,
                     'low': bar.low / divisor,
                     'close': (bar.low + bar.deltaClose) / divisor,
                     'volume': bar.volume} for bar in response.trendbar]
            
            result_df = pd.DataFrame(bars)
            event.set()

    trendbars_req = ProtoOAGetTrendbarsReq(
        ctidTraderAccountId=DEMO_ACCOUNT_ID,
        symbolId=symbol_details['symbolId'],
        period=tf_map[tf],
        count=limit
    )
    
    if not _connect_and_run(user_id, [trendbars_req], on_trendbars_message):
        return pd.DataFrame()

    if result_df.empty:
        return pd.DataFrame()

    df = result_df
    df.columns = [str(col).lower() for col in df.columns]
    df = df.sort_values(by='ts').reset_index(drop=True)
    
    with CACHE_LOCK:
        MARKET_DATA_CACHE[key] = df
    return df

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