# analysis.py
import logging
from twisted.internet.defer import Deferred
from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAGetTrendbarsReq, ProtoOAGetTrendbarsRes
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOATrendbarPeriod

# Видаляємо 'import state', щоб розірвати порочне коло
# import state 

logger = logging.getLogger(__name__)

# --- Функції для отримання та обробки ринкових даних ---

PERIOD_MAP = {
    '1min': ProtoOATrendbarPeriod.M1, '5min': ProtoOATrendbarPeriod.M5,
    '15min': ProtoOATrendbarPeriod.M15, '1hour': ProtoOATrendbarPeriod.H1,
    '4hour': ProtoOATrendbarPeriod.H4, '1day': ProtoOATrendbarPeriod.D1
}

def get_market_data(client, symbol_cache, norm_pair: str, period: str, count: int) -> Deferred:
    """Запитує історичні дані (свічки) для вказаної пари."""
    d = Deferred()
    symbol_details = symbol_cache.get(norm_pair)

    if not symbol_details:
        # Якщо символ не знайдено, одразу повертаємо помилку
        err_msg = f"Деталі для символу {norm_pair} не знайдено в кеші."
        logger.error(err_msg)
        d.errback(Exception(err_msg))
        return d

    trendbar_period = PERIOD_MAP.get(period)
    if not trendbar_period:
        err_msg = f"Невідомий період: {period}"
        logger.error(err_msg)
        d.errback(Exception(err_msg))
        return d
    
    request = ProtoOAGetTrendbarsReq(
        ctidTraderAccountId=client._client.account_id,
        symbolId=symbol_details.symbolId,
        period=trendbar_period,
        count=count
    )

    logger.info(f"Роблю запит на отримання {count} свічок для {norm_pair} (період: {period})...")
    deferred = client.send(request)
    
    def on_success(message):
        response = ProtoOAGetTrendbarsRes()
        response.ParseFromString(message.payload)
        logger.info(f"Отримано {len(response.trendbar)} свічок для {norm_pair}.")
        d.callback(response.trendbar)

    def on_error(failure):
        logger.error(f"Помилка отримання свічок для {norm_pair}: {failure.getErrorMessage()}")
        d.errback(failure)
        
    deferred.addCallbacks(on_success, on_error)
    return d


def get_api_detailed_signal_data(client, symbol_cache, symbol: str, user_id: int) -> Deferred:
    """
    Головна функція аналізу. Отримує дані та генерує сигнал.
    Тепер приймає 'symbol_cache' як аргумент.
    """
    d = Deferred()
    
    # Викликаємо get_market_data, передаючи symbol_cache далі
    deferred_bars = get_market_data(client, symbol_cache, symbol, '15min', 100)

    def on_bars_received(bars):
        try:
            if not bars:
                raise Exception("Отримано порожній список свічок.")

            # Проста логіка для прикладу: аналізуємо останню свічку
            last_bar = bars[-1]
            price_close = last_bar.close / (10**symbol_cache[symbol].digits)
            price_open = last_bar.open / (10**symbol_cache[symbol].digits)
            
            verdict = "🟢 Рекомендовано Купувати" if price_close > price_open else "🔴 Рекомендовано Продавати"
            
            result = {
                "pair": symbol,
                "price": price_close,
                "verdict_text": verdict,
                "support": (last_bar.low / (10**symbol_cache[symbol].digits)),
                "resistance": (last_bar.high / (10**symbol_cache[symbol].digits)),
                "reasons": [f"Аналіз останньої свічки на періоді M15."]
            }
            d.callback(result)
        except Exception as e:
            logger.error(f"Помилка під час аналізу свічок для {symbol}: {e}")
            d.errback(e)

    def on_bars_error(failure):
        # Передаємо помилку далі
        d.errback(failure)

    deferred_bars.addCallbacks(on_bars_received, on_bars_error)
    return d