# analysis.py
import logging
import json
from twisted.internet.defer import Deferred
from twisted.internet import threads

# --- ПОЧАТОК ЗМІН: Видалено багато невикористовуваних імпортів ---
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOATrendbarPeriod as TrendbarPeriod
from redis_client import get_redis
# --- КІНЕЦЬ ЗМІН ---

logger = logging.getLogger("analysis")

# Мапа залишається для валідації вхідних параметрів
PERIOD_MAP = {
    "1m": TrendbarPeriod.M1,
    "5m": TrendbarPeriod.M5,
    "15m": TrendbarPeriod.M15,
    "1h": TrendbarPeriod.H1,
    "4h": TrendbarPeriod.H4,
    "1day": TrendbarPeriod.D1
}

# --- ПОЧАТОК ЗМІН: Повністю нова, спрощена логіка ---

def get_analysis_from_redis(symbol: str, timeframe: str) -> Deferred:
    """
    Асинхронно читає готовий результат аналізу з Redis.
    Повертає Deferred, який поверне dict або None.
    """
    def _fetch():
        try:
            r = get_redis()
            # Ключ має точно відповідати тому, що генерує indicator_processor
            result_key = f"analysis:result:{symbol}:{timeframe}"
            raw_data = r.get(result_key)
            if raw_data:
                return json.loads(raw_data)
            return None
        except Exception:
            logger.exception(f"get_analysis_from_redis failed for {symbol}:{timeframe}")
            return None

    return threads.deferToThread(_fetch)


def get_api_detailed_signal_data(client, symbol_cache, symbol: str, user_id: int, timeframe: str = "15m") -> Deferred:
    """
    Основна точка входу для API. Швидко отримує готовий аналіз з Redis.
    """
    final_deferred = Deferred()

    # Перевірка, чи підтримується таймфрейм для аналізу
    # Наш processor наразі не обробляє 1m та 1day
    supported_tf_for_analysis = ["5m", "15m", "1h", "4h"]
    if timeframe not in supported_tf_for_analysis:
        err_msg = {"error": f"Timeframe '{timeframe}' is not supported for detailed analysis."}
        final_deferred.callback(err_msg)
        return final_deferred

    def on_data_ready(result):
        if result:
            final_deferred.callback(result)
        else:
            # Якщо даних немає, повертаємо повідомлення про очікування
            final_deferred.callback({
                "error": f"Аналіз для {symbol} на таймфреймі {timeframe} ще не готовий. Будь ласка, зачекайте кілька хвилин."
            })

    def on_error(failure):
        logger.error(f"Error fetching analysis from Redis for {symbol}:{timeframe}: {failure}")
        final_deferred.errback(failure)

    d = get_analysis_from_redis(symbol, timeframe)
    d.addCallbacks(on_data_ready, on_error)

    return final_deferred

# --- КІНЕЦЬ ЗМІН: Вся стара логіка розрахунків видалена ---