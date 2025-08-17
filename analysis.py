import pandas as pd
import pandas_ta as ta
import numpy as np
import time
from config import MARKET_DATA_CACHE, SYMBOL_DATA_CACHE, CACHE_LOCK, ANALYSIS_TIMEFRAMES
from db import add_signal_to_history

# --- Для прикладу: get_api_detailed_signal_data & get_api_mta_data ---
def get_api_detailed_signal_data(ctrader_service, pair, user_id=None):
    # Тут можна вставити логіку Twisted + cTrader API
    # Поки приклад без WebSocket, просто повертає рандомні дані
    price = np.random.rand() * 100
    score = np.random.randint(30, 70)
    reasons = ["Ціна вище KAMA", "RSI нейтральний"]
    result = {
        "pair": pair, "price": price, "verdict_text": "↗️ Помірний сигнал: КУПУВАТИ",
        "verdict_level": "moderate_buy", "reasons": reasons,
        "support": price*0.98, "resistance": price*1.02,
        "history": {}
    }
    if user_id:
        add_signal_to_history({'user_id': user_id, 'pair': pair, 'price': price, 'bull_percentage': score})
    return result, result

def get_api_mta_data(ctrader_service, pair):
    return [{"tf": tf, "signal": "BUY" if np.random.rand()>0.5 else "SELL"} for tf in ANALYSIS_TIMEFRAMES]
